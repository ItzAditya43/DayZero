"""Finding the cheapest plan that survives.

Three stages, deliberately layered so the demo can show what each one buys:

  1. GREEDY -- rank every item (each roof, each area measure) by estimated
     litres-per-rupee and buy down the list until the budget runs out. This is
     what a spreadsheet would do, and it is the baseline we beat.

  2. EXACT -- enumerate all 2^k subsets of area measures (k is small), and for
     each subset solve the remaining rooftop budget with a bounded-knapsack DP
     over roof-size bundles. The DP is exact on the surrogate objective.

  3. RANK -- score every candidate from stage 2 with the *full* hydrological
     simulation, not the surrogate, and keep the best. This is where the gap
     opens: the surrogate cannot see deployment lag, tank overflow, or the fact
     that recharge wells are worth less once the roofs upstream are harvested.

The reported numbers always come from stage 3, never from the surrogate.
"""
from __future__ import annotations

import itertools
import math
from dataclasses import dataclass

import numpy as np

from . import config as C
from .hydrology import SimResult, score, simulate
from .interventions import MEASURE_KEYS, AreaMeasure, Plan, catalogue, rwh_cost
from .world import Region

# Budget is discretised for the DP. 600 buckets keeps it exact enough to be
# meaningful while staying instant.
DP_BUCKETS = 600


@dataclass
class Candidate:
    plan: Plan
    result: SimResult
    label: str

    @property
    def score(self) -> float:
        return score(self.result)


# --------------------------------------------------------------------------
# Surrogate values: estimated litres per year, used only for ranking/DP.
# --------------------------------------------------------------------------

def _annual_rain(region: Region) -> float:
    return float(np.median(region.climate.annual_rain))


def roof_value(area_m2: float, annual_rain_mm: float) -> float:
    """Litres a roof could yield in a median year, before storage limits."""
    return area_m2 * annual_rain_mm * C.RUNOFF_COEFFICIENT


def measure_value(m: AreaMeasure, region: Region, annual_rain_mm: float) -> float:
    demand = region.population * C.LPCD * 365.0
    municipal = demand * C.MUNICIPAL_SUPPLY_FRACTION
    v = 0.0
    v += demand * m.demand_reduction
    v += municipal * C.DISTRIBUTION_LOSS_FRACTION * m.leak_reduction
    v += demand * m.greywater_reuse * 0.8
    v += region.pervious_area_m2 * annual_rain_mm * C.NATURAL_RECHARGE_FRACTION * m.recharge_boost
    v += m.storage_bonus_l * 4.0  # a tank turns over a few times a year
    return v


# --------------------------------------------------------------------------
# Stage 1: greedy
# --------------------------------------------------------------------------

def greedy_plan(region: Region, budget: float, cat: dict[str, AreaMeasure]) -> Plan:
    rain = _annual_rain(region)
    items: list[tuple[float, str, object, float]] = []
    for b in region.buildings:
        cost = rwh_cost(b.area_m2)
        items.append((roof_value(b.area_m2, rain) / cost, "roof", b.id, cost))
    for m in cat.values():
        if m.cost > 0:
            items.append((measure_value(m, region, rain) / m.cost, "measure", m.key, m.cost))
    items.sort(key=lambda x: x[0], reverse=True)

    plan = Plan()
    spent = 0.0
    for _ratio, kind, ref, cost in items:
        if spent + cost > budget:
            continue
        spent += cost
        (plan.building_ids if kind == "roof" else plan.measures).add(ref)
    return plan


# --------------------------------------------------------------------------
# Stage 2: bounded-knapsack DP over roof-size bundles
# --------------------------------------------------------------------------

def _bundles(region: Region, n_bins: int = 12) -> list[tuple[float, float, int, list[int]]]:
    """Group roofs into size bins -> (cost, value, count, ids sorted big-first).

    Thousands of individual roofs would make the DP slow for no benefit: two
    roofs of the same size are interchangeable. Binning collapses the item set
    to a dozen while keeping the cost/value structure intact.
    """
    rain = _annual_rain(region)
    areas = np.array([b.area_m2 for b in region.buildings])
    if len(areas) == 0:
        return []
    edges = np.unique(np.quantile(areas, np.linspace(0, 1, n_bins + 1)))
    idx = np.clip(np.digitize(areas, edges[1:-1]), 0, len(edges) - 2)

    out = []
    for b in range(int(idx.max()) + 1):
        members = [region.buildings[i] for i in np.flatnonzero(idx == b)]
        if not members:
            continue
        members.sort(key=lambda x: x.area_m2, reverse=True)
        mean_area = float(np.mean([m.area_m2 for m in members]))
        out.append(
            (
                rwh_cost(mean_area),
                roof_value(mean_area, rain),
                len(members),
                [m.id for m in members],
            )
        )
    return out


def knapsack_roofs(region: Region, budget: float) -> set[int]:
    """Exact bounded knapsack on binned roofs, solved by binary splitting.

    "Up to N copies of bin i" becomes O(log N) 0/1 items of size 1, 2, 4, ...
    so a standard 0/1 knapsack DP solves it. Costs are discretised onto a
    bucket grid; the DP is exact with respect to that grid.
    """
    bundles = _bundles(region)
    if not bundles or budget <= 0:
        return set()

    step = max(budget / DP_BUCKETS, 1.0)
    cap = int(budget / step)
    if cap <= 0:
        return set()

    # (cost_in_buckets, value, bundle_index, copies_represented)
    # Costs round UP. Rounding to nearest would let a few hundred small
    # roundings compound into a plan that quietly exceeds the budget, which is
    # the one thing a budget-constrained optimiser must never do.
    items: list[tuple[int, float, int, int]] = []
    for bi, (cost, value, count, _ids) in enumerate(bundles):
        unit = math.ceil(cost / step)
        if unit <= 0 or unit > cap:
            continue
        k, left = 1, count
        while left > 0:
            take = min(k, left)
            if unit * take <= cap:
                items.append((unit * take, value * take, bi, take))
            left -= take
            k *= 2

    if not items:
        return set()

    dp = np.zeros(cap + 1)
    taken: list[np.ndarray] = []
    for cost_b, value, _bi, _copies in items:
        shifted = np.full(cap + 1, -np.inf)
        shifted[cost_b:] = dp[: cap + 1 - cost_b] + value
        take = shifted > dp
        dp = np.where(take, shifted, dp)
        taken.append(take)

    # Walk the decisions backwards to recover how many of each bin were bought.
    counts = [0] * len(bundles)
    b = int(np.argmax(dp))
    for i in range(len(items) - 1, -1, -1):
        cost_b, _value, bi, copies = items[i]
        if b >= cost_b and taken[i][b]:
            counts[bi] += copies
            b -= cost_b

    picked: set[int] = set()
    for bi, n in enumerate(counts):
        if n > 0:
            ids = bundles[bi][3]
            picked.update(ids[: min(n, len(ids))])

    # The DP works on binned mean costs, so the realised cost of the specific
    # roofs chosen can still drift over budget. Trim the worst value-per-rupee
    # roofs until it fits. This is a guarantee, not an optimisation.
    area_by_id = {b.id: b.area_m2 for b in region.buildings}
    total = sum(rwh_cost(area_by_id[i]) for i in picked)
    if total > budget:
        by_ratio = sorted(picked, key=lambda i: area_by_id[i])
        for bid in by_ratio:
            if total <= budget:
                break
            total -= rwh_cost(area_by_id[bid])
            picked.discard(bid)
    return picked


# --------------------------------------------------------------------------
# Stage 3: rank candidates with the real simulator
# --------------------------------------------------------------------------

def optimize(
    region: Region,
    forcing: dict[str, np.ndarray],
    budget: float,
    demand_growth_pct: float = 0.0,
    months: int = C.SIM_MONTHS,
) -> dict:
    area_by_id = {b.id: b.area_m2 for b in region.buildings}
    cat = catalogue(region.population)

    def run(plan: Plan) -> SimResult:
        return simulate(region, forcing, plan, demand_growth_pct, months)

    baseline = run(Plan())
    greedy = greedy_plan(region, budget, cat)
    greedy_result = run(greedy)

    best: Candidate | None = None
    evaluated = 0

    def consider(plan: Plan, label: str) -> None:
        nonlocal best, evaluated
        evaluated += 1
        cand = Candidate(plan, run(plan), label)
        if best is None or cand.score > best.score:
            best = cand

    # The greedy plan is always in the candidate set. The exact search should
    # dominate it, but making that a guarantee rather than an expectation means
    # the reported "optimal" can never be worse than the baseline heuristic.
    consider(greedy, "greedy")

    keys = MEASURE_KEYS
    for r in range(len(keys) + 1):
        for subset in itertools.combinations(keys, r):
            fixed = sum(cat[k].cost for k in subset)
            if fixed > budget:
                continue
            leftover = budget - fixed
            # Spending the whole remainder on roofs is not always best. Every
            # equipped roof stops shedding runoff to the ground, so past a
            # point harvesting starves the aquifer it is meant to protect.
            # Sweeping the roof budget lets the search find that turning point.
            for frac in (0.0, 0.25, 0.5, 0.75, 1.0):
                roofs = knapsack_roofs(region, leftover * frac) if frac else set()
                consider(
                    Plan(roofs, set(subset)),
                    f"{'+'.join(subset) or 'none'} @ {int(frac * 100)}% roofs",
                )

    assert best is not None
    return {
        "budget": budget,
        "currency": "INR",
        "candidates_evaluated": evaluated,
        "baseline": {"plan": Plan().to_dict(area_by_id, cat), "result": baseline.to_dict()},
        "greedy": {"plan": greedy.to_dict(area_by_id, cat), "result": greedy_result.to_dict()},
        "optimal": {"plan": best.plan.to_dict(area_by_id, cat), "result": best.result.to_dict()},
        "improvement": {
            "months_vs_baseline": best.result.resilience_months - baseline.resilience_months,
            "months_vs_greedy": best.result.resilience_months - greedy_result.resilience_months,
            "budget_used_pct": round(100 * best.plan.cost(area_by_id, cat) / budget, 1) if budget else 0,
            "greedy_budget_used_pct": round(100 * greedy.cost(area_by_id, cat) / budget, 1) if budget else 0,
        },
    }
