"""The coupled water-balance simulation.

One month per step. The state that carries forward is storage: rooftop tanks,
community storage, and the aquifer. Everything else is a flow computed from the
forcing and the current state.

    rainfall -> roof runoff -> tanks -> household supply
             -> pervious ground -> aquifer recharge
             -> catchment runoff -> reservoir stock -> municipal supply

    demand = population x lpcd x days, uplifted by heat
    shortfall after municipal + tanks is pumped from the aquifer
    when the aquifer cannot cover it, service drops -- that is the failure

Municipal supply is a reservoir *stock*, not a fixed fraction. Catchment
inflow scales with rainfall raised to STREAMFLOW_ELASTICITY, so a moderate
rainfall deficit produces a much larger runoff deficit -- the mechanism behind
every real day-zero event. The reservoir buffers a bad year and collapses in a
bad run of years, which a fraction-based model can never reproduce.

The failure criterion is service falling below SURVIVAL_FRACTION of demand,
not the aquifer hitting zero. A region can limp along on rationing for a while;
what matters is when it can no longer meet basic need.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from . import config as C
from .interventions import Plan, catalogue
from .world import Region


@dataclass
class SimResult:
    months: int
    served_fraction: np.ndarray
    demand_l: np.ndarray
    municipal_l: np.ndarray
    harvest_l: np.ndarray
    groundwater_l: np.ndarray
    aquifer_l: np.ndarray
    reservoir_l: np.ndarray
    reservoir_capacity_l: float
    tank_l: np.ndarray
    unmet_l: np.ndarray
    aquifer_capacity_l: float
    failure_month: int | None
    stress_month: int | None
    people: float
    _meta: dict = field(default_factory=dict)

    @property
    def resilience_months(self) -> int:
        """Months survived before basic need goes unmet. Capped at the horizon."""
        return self.failure_month if self.failure_month is not None else self.months

    def to_dict(self) -> dict:
        return {
            "months": self.months,
            "failure_month": self.failure_month,
            "stress_month": self.stress_month,
            "resilience_months": self.resilience_months,
            "survived": self.failure_month is None,
            "people_affected": round(self.people) if self.failure_month is not None else 0,
            "aquifer_end_pct": round(100 * float(self.aquifer_l[-1]) / self.aquifer_capacity_l, 1),
            "reservoir_min_pct": round(100 * float(self.reservoir_l.min()) / self.reservoir_capacity_l, 1),
            "reservoir_end_pct": round(100 * float(self.reservoir_l[-1]) / self.reservoir_capacity_l, 1),
            "aquifer_min_pct": round(100 * float(self.aquifer_l.min()) / self.aquifer_capacity_l, 1),
            "mean_served_pct": round(100 * float(self.served_fraction.mean()), 1),
            "min_served_pct": round(100 * float(self.served_fraction.min()), 1),
            "total_unmet_l": round(float(self.unmet_l.sum())),
            "total_harvest_l": round(float(self.harvest_l.sum())),
            "series": {
                "served_pct": [round(100 * float(v), 1) for v in self.served_fraction],
                "aquifer_pct": [
                    round(100 * float(v) / self.aquifer_capacity_l, 1) for v in self.aquifer_l
                ],
                "demand_ml": [round(float(v) / 1e6, 2) for v in self.demand_l],
                "municipal_ml": [round(float(v) / 1e6, 2) for v in self.municipal_l],
                "harvest_ml": [round(float(v) / 1e6, 2) for v in self.harvest_l],
                "groundwater_ml": [round(float(v) / 1e6, 2) for v in self.groundwater_l],
                "tank_ml": [round(float(v) / 1e6, 2) for v in self.tank_l],
                "reservoir_pct": [
                    round(100 * float(v) / self.reservoir_capacity_l, 1) for v in self.reservoir_l
                ],
            },
        }


def simulate(
    region: Region,
    forcing: dict[str, np.ndarray],
    plan: Plan | None = None,
    demand_growth_pct: float = 0.0,
    months: int = C.SIM_MONTHS,
) -> SimResult:
    plan = plan or Plan()
    rain = forcing["rain_mm"][:months]
    temp = forcing["temp_c"][:months]
    n = len(rain)

    cat = catalogue(region.population)
    fx = plan.effects(cat)
    equipped_ids = plan.building_ids
    equipped_area = sum(b.area_m2 for b in region.buildings if b.id in equipped_ids)
    unequipped_area = max(region.roof_area_m2 - equipped_area, 0.0)

    tank_capacity = equipped_area * C.TANK_LITRES_PER_M2
    aquifer_cap = region.aquifer_capacity_l
    pervious = region.pervious_area_m2

    # Area measures take time to build. Before deploy_month they do nothing --
    # a plan that only pays off in year three is a real risk the model shows.
    ready = plan.deploy_month(cat)

    base_pop = max(region.population, 1.0)
    mean_temp = region.climate.mean_annual_temp
    baseline_demand_month = base_pop * C.LPCD * C.DAYS_IN_MONTH

    # --- upstream reservoir sizing -----------------------------------------
    # Gross abstraction needed to deliver the design fraction after losses.
    gross_month = baseline_demand_month * C.MUNICIPAL_DESIGN_FRACTION / (
        1.0 - C.DISTRIBUTION_LOSS_FRACTION
    )
    reservoir_cap = gross_month * C.RESERVOIR_MONTHS_OF_SUPPLY
    reservoir = reservoir_cap * C.RESERVOIR_INITIAL_FRACTION

    # Calibrate catchment yield so that a median year delivers the design
    # abstraction plus a small surplus. Because inflow is a power law in
    # rainfall, the normalisation must be computed over the actual seasonal
    # profile rather than assumed -- otherwise Jensen's inequality inflates it.
    normal = np.maximum(region.climate.normal_rain, 1e-6)
    normal_mean = float(normal.mean()) or 1.0
    shape = (normal / normal_mean) ** C.STREAMFLOW_ELASTICITY
    shape_sum = float(shape.sum()) or 1.0
    yield_per_unit = gross_month * 12.0 * C.RESERVOIR_MEDIAN_YEAR_SURPLUS / shape_sum

    tank = 0.0
    aquifer = aquifer_cap * C.AQUIFER_INITIAL_FRACTION

    served_f = np.zeros(n)
    demand_a = np.zeros(n)
    muni_a = np.zeros(n)
    harv_a = np.zeros(n)
    gw_a = np.zeros(n)
    aq_a = np.zeros(n)
    res_a = np.zeros(n)
    tank_a = np.zeros(n)
    unmet_a = np.zeros(n)

    failure_month: int | None = None
    stress_month: int | None = None

    for t in range(n):
        active = t >= ready
        demand_cut = fx["demand_reduction"] if active else 0.0
        leak_cut = fx["leak_reduction"] if active else 0.0
        greywater = fx["greywater_reuse"] if active else 0.0
        recharge_boost = fx["recharge_boost"] if active else 0.0
        extra_storage = fx["storage_bonus_l"] if active else 0.0

        # --- demand ---------------------------------------------------------
        pop = base_pop * (1.0 + demand_growth_pct / 100.0 * (t / 12.0))
        heat = max(0.0, float(temp[t]) - mean_temp)
        lpcd = (C.LPCD + C.DEMAND_TEMP_SENSITIVITY * heat) * (1.0 - demand_cut)
        demand = pop * lpcd * C.DAYS_IN_MONTH

        # --- upstream reservoir --------------------------------------------
        # Catchment runoff is a power law in rainfall, then the utility draws
        # what it needs from whatever is stored. When the stock runs out the
        # city is left with that month's inflow and nothing more: day zero.
        # max(0) guards the fractional exponent: a negative base would go complex.
        inflow_res = yield_per_unit * (max(float(rain[t]), 0.0) / normal_mean) ** C.STREAMFLOW_ELASTICITY
        reservoir = min(reservoir + inflow_res, reservoir_cap)

        # Leak repair cuts abstraction as well as loss -- less is pumped to
        # deliver the same water, which is why it protects the reservoir.
        loss = C.DISTRIBUTION_LOSS_FRACTION * (1.0 - leak_cut)
        want_gross = demand / max(1.0 - loss, 0.05)
        abstract = min(reservoir, want_gross)
        reservoir -= abstract
        municipal = abstract * (1.0 - loss)

        # --- rooftop harvest ------------------------------------------------
        # 1 mm of rain on 1 m2 is exactly 1 litre.
        inflow = equipped_area * float(rain[t]) * C.RUNOFF_COEFFICIENT
        capacity = tank_capacity + extra_storage
        tank = min(tank + inflow, capacity)
        overflow = max(inflow - (capacity - min(tank, capacity)), 0.0)

        # --- meet demand in merit order: municipal, then tank, then aquifer --
        served = min(municipal, demand)
        remaining = demand - served

        from_tank = min(tank, remaining)
        tank -= from_tank
        served += from_tank
        remaining -= from_tank

        # Greywater is recycled from what has already been delivered.
        reuse = min(served * greywater, remaining)
        served += reuse
        remaining -= reuse

        pumpable = aquifer * C.MAX_MONTHLY_EXTRACTION_FRACTION
        from_gw = min(pumpable, remaining)
        aquifer -= from_gw
        served += from_gw
        remaining -= from_gw

        # --- recharge -------------------------------------------------------
        recharge = pervious * float(rain[t]) * C.NATURAL_RECHARGE_FRACTION
        # Roofs without harvesting shed to the storm drain; a little infiltrates.
        recharge += unequipped_area * float(rain[t]) * 0.05
        # Recharge wells capture tank overflow and street runoff.
        recharge *= 1.0 + recharge_boost
        recharge += overflow * 0.35 * recharge_boost
        aquifer = min(aquifer + recharge, aquifer_cap)

        # --- record ---------------------------------------------------------
        frac = served / demand if demand > 0 else 1.0
        served_f[t] = min(frac, 1.0)
        demand_a[t] = demand
        muni_a[t] = municipal
        harv_a[t] = inflow - overflow
        gw_a[t] = from_gw
        aq_a[t] = aquifer
        res_a[t] = reservoir
        tank_a[t] = tank
        unmet_a[t] = max(remaining, 0.0)

        if stress_month is None and frac < 0.75:
            stress_month = t + 1
        if failure_month is None and frac < C.SURVIVAL_FRACTION:
            failure_month = t + 1

    return SimResult(
        months=n,
        served_fraction=served_f,
        demand_l=demand_a,
        municipal_l=muni_a,
        harvest_l=harv_a,
        groundwater_l=gw_a,
        aquifer_l=aq_a,
        reservoir_l=res_a,
        reservoir_capacity_l=reservoir_cap,
        tank_l=tank_a,
        unmet_l=unmet_a,
        aquifer_capacity_l=aquifer_cap,
        failure_month=failure_month,
        stress_month=stress_month,
        people=base_pop,
        _meta={"equipped_area_m2": equipped_area, "deploy_month": ready},
    )


def score(result: SimResult) -> float:
    """Scalar objective the optimiser maximises.

    Months survived dominates; average service quality breaks ties between
    plans that survive the whole horizon.
    """
    return result.resilience_months * 1000.0 + float(result.served_fraction.mean()) * 100.0
