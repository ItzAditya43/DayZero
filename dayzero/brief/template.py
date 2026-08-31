"""Deterministic decision brief -- no API, no key, no network.

This is the floor the product never falls below. If every LLM backend is
unreachable or out of quota, the app still produces a complete, readable brief
from the numbers the optimiser already computed. Judges clicking the live link
at 2am get a working demo either way.
"""
from __future__ import annotations


def fmt_money(v: float, currency: str = "INR") -> str:
    if currency == "INR":
        if v >= 1e7:
            return f"Rs {v / 1e7:.2f} crore"
        if v >= 1e5:
            return f"Rs {v / 1e5:.2f} lakh"
        return f"Rs {v:,.0f}"
    return f"{v:,.0f}"


def fmt_litres(v: float) -> str:
    if v >= 1e9:
        return f"{v / 1e9:,.2f} GL"
    if v >= 1e6:
        return f"{v / 1e6:,.0f} ML"
    if v >= 1e3:
        return f"{v / 1e3:,.0f} kL"
    return f"{v:,.0f} L"


def fmt_months(m: int, survived: bool, horizon: int) -> str:
    if survived:
        return f"beyond the {horizon}-month horizon"
    years, rem = divmod(m, 12)
    if years and rem:
        return f"month {m} ({years}y {rem}m)"
    if years:
        return f"month {m} ({years} years)"
    return f"month {m}"


def generate(payload: dict) -> dict:
    region = payload["region"]
    opt = payload["optimization"]
    base = opt["baseline"]["result"]
    good = opt["optimal"]["result"]
    plan = opt["optimal"]["plan"]
    greedy = opt["greedy"]["result"]
    scen = payload.get("scenario", {})
    horizon = base["months"]
    cur = plan.get("currency", "INR")

    base_when = fmt_months(base["resilience_months"], base["survived"], horizon)
    good_when = fmt_months(good["resilience_months"], good["survived"], horizon)

    headline = (
        f"{region['place']} holds out until {base_when} under "
        f"{scen.get('name', 'this scenario').lower()}; the recommended plan pushes that to {good_when}."
    )

    situation = (
        f"The study area covers {region['ground_area_km2']} km2 with {region['buildings']:,} "
        f"mapped buildings, {region['roof_area_m2']:,} m2 of roof, and an estimated "
        f"{region['population']:,} residents. Median rainfall here is "
        f"{region['mean_annual_rain_mm']:.0f} mm/year, which means those roofs shed roughly "
        f"{region['harvestable_l_per_year'] / 1e6:.0f} million litres annually -- against a "
        f"domestic demand of about {region['annual_demand_l'] / 1e6:.0f} million litres. "
        f"Under this scenario, service falls below the survival threshold at {base_when}, "
        f"with the aquifer bottoming out at {base['aquifer_min_pct']}% of usable storage."
    )

    steps = []
    if plan["n_buildings"]:
        steps.append(
            f"Install rooftop harvesting on {plan['n_buildings']:,} buildings "
            f"({plan['roof_area_m2']:,} m2 of roof) -- {fmt_money(plan['rwh_cost'], cur)}."
        )
    for m in plan["measures"]:
        steps.append(
            f"{m['name']} -- {fmt_money(m['cost'], cur)}, "
            f"{m['months_to_deploy']} months to deploy."
        )
    if not steps:
        steps.append("No intervention clears the budget threshold at this scenario.")

    gap = opt["improvement"]["months_vs_greedy"]
    if gap > 0:
        reasoning = (
            f"Ranking interventions by litres-per-rupee -- the obvious approach -- buys "
            f"{greedy['resilience_months']} months. The optimiser finds {good['resilience_months']}, "
            f"a {gap}-month gain for the same budget. The naive ranking overvalues measures "
            f"that take a year to build and undervalues the ones that compound: it cannot see "
            f"that harvesting roofs upstream reduces what recharge wells have left to capture."
        )
    else:
        reasoning = (
            f"At this budget the greedy ranking and the exact search converge on comparable "
            f"outcomes ({greedy['resilience_months']} vs {good['resilience_months']} months). "
            f"The constraint here is the budget itself, not the allocation of it."
        )

    tradeoff = (
        f"The plan commits {fmt_money(plan['total_cost'], cur)} of a "
        f"{fmt_money(opt['budget'], cur)} budget "
        f"({opt['improvement']['budget_used_pct']}%). Average service rises from "
        f"{base['mean_served_pct']}% to {good['mean_served_pct']}% of demand, and the aquifer's "
        f"low point improves from {base['aquifer_min_pct']}% to {good['aquifer_min_pct']}%. "
        f"Measures with long deployment times contribute nothing in the first year, which is "
        f"why the model still shows early stress even under the funded plan."
    )

    return {
        "headline": headline,
        "situation": situation,
        "recommendation": steps,
        "reasoning": reasoning,
        "tradeoffs": tradeoff,
        "source": "template",
    }
