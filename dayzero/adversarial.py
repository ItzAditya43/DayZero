"""Adversarial stress testing: find the worst *plausible* scenario.

Instead of asking the user to guess a scenario, search the space for the one
that breaks this location soonest. The search is bounded by the location's own
observed record -- it cannot invent a drought drier than anything ERA5 has seen
there since 1991 -- which keeps the result a stress test rather than a fantasy.

Coarse grid first, then a local refinement around the winner. The objective
surface is noisy (rainfall jitter is stochastic), so the seed is held fixed
across evaluations to keep comparisons fair.
"""
from __future__ import annotations

import numpy as np

from . import config as C
from .climate import Scenario, build_forcing, plausible_bounds
from .hydrology import simulate
from .interventions import Plan
from .world import Region


def _evaluate(region: Region, rain_pct: float, temp: float, growth: float,
              plan: Plan | None, months: int) -> tuple[float, dict]:
    sc = Scenario("adv", "Adversarial", "", rain_pct, temp, growth)
    forcing = build_forcing(region.climate, sc, months, seed=11)
    res = simulate(region, forcing, plan, growth, months)
    # Lower is worse. Tie-break on how badly service degrades.
    objective = res.resilience_months + float(res.served_fraction.mean())
    return objective, {"scenario": sc, "result": res}


def find_breaking_point(
    region: Region,
    plan: Plan | None = None,
    months: int = C.SIM_MONTHS,
    coarse: int = 4,
) -> dict:
    b = plausible_bounds(region.climate)
    rain_lo, rain_hi = b["rain_percentile"]
    temp_lo, temp_hi = b["temp_anomaly_c"]
    grow_lo, grow_hi = b["demand_growth_pct"]

    best_obj = float("inf")
    best: dict | None = None
    evaluated = 0

    grid = (
        np.linspace(rain_lo, rain_hi, coarse),
        np.linspace(temp_lo, temp_hi, coarse),
        np.linspace(grow_lo, grow_hi, coarse),
    )
    for r in grid[0]:
        for t in grid[1]:
            for g in grid[2]:
                obj, info = _evaluate(region, float(r), float(t), float(g), plan, months)
                evaluated += 1
                if obj < best_obj:
                    best_obj, best = obj, info

    # Refine around the coarse winner with a shrinking neighbourhood.
    assert best is not None
    sc = best["scenario"]
    span = [(rain_hi - rain_lo) / coarse, (temp_hi - temp_lo) / coarse, (grow_hi - grow_lo) / coarse]
    for _ in range(2):
        span = [s / 2.0 for s in span]
        for dr in (-span[0], 0.0, span[0]):
            for dt in (-span[1], 0.0, span[1]):
                for dg in (-span[2], 0.0, span[2]):
                    r = float(np.clip(sc.rain_percentile + dr, rain_lo, rain_hi))
                    t = float(np.clip(sc.temp_anomaly_c + dt, temp_lo, temp_hi))
                    g = float(np.clip(sc.demand_growth_pct + dg, grow_lo, grow_hi))
                    obj, info = _evaluate(region, r, t, g, plan, months)
                    evaluated += 1
                    if obj < best_obj:
                        best_obj, best = obj, info
        sc = best["scenario"]

    result = best["result"]
    return {
        "scenario": {
            **best["scenario"].to_dict(),
            "name": "Worst plausible",
            "description": (
                f"Searched {evaluated} scenarios bounded by observed conditions at this "
                f"location since {region.climate.years[0]}."
            ),
        },
        "bounds": b,
        "scenarios_searched": evaluated,
        "result": result.to_dict(),
        "bottleneck": diagnose(result),
    }


def diagnose(result) -> dict:
    """Which subsystem gives out first, and how hard each one is pressed.

    Each pressure is a 0-1 reading taken from the simulated series, so the
    answer varies by place rather than being a restatement of the inputs. An
    earlier version scored "insufficient storage" as one minus the harvested
    fraction, which is trivially 1.0 whenever no harvesting has been funded --
    it named the same bottleneck for every city on Earth.
    """
    import numpy as _np

    demand = float(result.demand_l.sum()) or 1.0
    unmet = float(result.unmet_l.sum())

    # Duration, not depth. Every one of these systems touches its low point at
    # some stage of a dry season, so "how empty did it get" saturates at 1.0
    # everywhere and names the same bottleneck for every city. How *long* each
    # store spent critically low is what actually distinguishes them.
    months = max(result.months, 1)
    reservoir_low = float(
        _np.count_nonzero(result.reservoir_l < 0.10 * result.reservoir_capacity_l)
    ) / months
    aquifer_low = float(
        _np.count_nonzero(result.aquifer_l < 0.25 * result.aquifer_capacity_l)
    ) / months

    # Months where the region was short of water *and* already pumping: the
    # aquifer had stock left but could not be drawn fast enough.
    short = result.unmet_l > 0
    pumping = result.groundwater_l > 0
    rate_bound = float(_np.count_nonzero(short & pumping)) / months

    # How much of the shortfall local storage would have had to absorb.
    deficit = unmet / demand

    pressures = {
        "Surface reservoir depletion": reservoir_low,
        "Groundwater depletion": aquifer_low,
        "Aquifer extraction rate limit": rate_bound,
        "Chronic supply deficit": min(deficit * 3.0, 1.0),
    }
    order = sorted(pressures.items(), key=lambda kv: kv[1], reverse=True)
    return {
        "primary": order[0][0],
        "secondary": order[1][0],
        "pressures": {k: round(min(max(v, 0.0), 1.0), 3) for k, v in order},
        "aquifer_min_pct": round(100 * float(result.aquifer_l.min()) / result.aquifer_capacity_l, 1),
        "reservoir_min_pct": round(
            100 * float(result.reservoir_l.min()) / result.reservoir_capacity_l, 1
        ),
        "unmet_share_pct": round(100 * deficit, 1),
    }
