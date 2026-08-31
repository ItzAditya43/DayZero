"""The intervention catalogue and the Plan object the optimiser searches over.

Two kinds of lever:

  * Rooftop harvesting, decided per building. Cost scales with roof area, so
    big roofs are cheap per litre and small ones are not -- this is what makes
    the selection problem interesting rather than uniform.
  * Area-wide measures, decided once for the whole study area. These interact
    with harvesting (recharge wells are worth less once roofs are harvested,
    because there is less runoff left to infiltrate), which is precisely the
    non-additivity that breaks greedy selection.

Area-measure costs are stored per capita and materialised against the actual
population of the study area, so the catalogue is meaningful for a village and
for a city centre without retuning. Costs are in Indian rupees.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace

from . import config as C

CURRENCY = "INR"

# Rooftop rainwater harvesting: a fixed plumbing/first-flush cost per building
# plus a tank cost that scales with roof area.
RWH_FIXED_COST = 18_000.0
RWH_COST_PER_M2 = 320.0


def rwh_cost(area_m2: float) -> float:
    return RWH_FIXED_COST + RWH_COST_PER_M2 * area_m2


@dataclass(frozen=True)
class AreaMeasure:
    key: str
    name: str
    description: str
    cost_per_capita: float
    months_to_deploy: int
    # Effects, all fractional unless the name says otherwise.
    demand_reduction: float = 0.0        # cuts litres/capita/day
    leak_reduction: float = 0.0          # cuts distribution losses
    greywater_reuse: float = 0.0         # fraction of served water returned
    recharge_boost: float = 0.0          # multiplies natural recharge
    storage_l_per_capita: float = 0.0    # extra community storage
    # Filled in by for_population().
    cost: float = 0.0
    storage_bonus_l: float = 0.0

    def for_population(self, population: float) -> AreaMeasure:
        pop = max(population, 1.0)
        return replace(
            self,
            cost=round(self.cost_per_capita * pop, -3),
            storage_bonus_l=self.storage_l_per_capita * pop,
        )

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "name": self.name,
            "description": self.description,
            "cost": self.cost,
            "cost_per_capita": self.cost_per_capita,
            "months_to_deploy": self.months_to_deploy,
            "effects": {
                k: v
                for k, v in (
                    ("demand_reduction", self.demand_reduction),
                    ("leak_reduction", self.leak_reduction),
                    ("greywater_reuse", self.greywater_reuse),
                    ("recharge_boost", self.recharge_boost),
                    ("storage_bonus_l", round(self.storage_bonus_l)),
                )
                if v
            },
        }


# Two weeks of survival-level demand, used to size the community reservoir.
_FORTNIGHT_SURVIVAL_L = C.LPCD * C.SURVIVAL_FRACTION * 14

TEMPLATES: list[AreaMeasure] = [
    AreaMeasure(
        "leak_repair", "Distribution leak repair",
        "Pressure management and mains replacement on the worst-performing lines.",
        cost_per_capita=250, months_to_deploy=8, leak_reduction=0.40,
    ),
    AreaMeasure(
        "fixtures", "Low-flow fixture retrofit",
        "Subsidised aerators, dual-flush cisterns and shower restrictors.",
        cost_per_capita=85, months_to_deploy=4, demand_reduction=0.12,
    ),
    AreaMeasure(
        "greywater", "Decentralised greywater recycling",
        "Cluster-scale treatment returning wash water for flushing and gardens.",
        cost_per_capita=370, months_to_deploy=14, greywater_reuse=0.22,
    ),
    AreaMeasure(
        "recharge_wells", "Managed aquifer recharge wells",
        "Injection wells and percolation pits that route storm runoff underground.",
        cost_per_capita=180, months_to_deploy=10, recharge_boost=0.85,
    ),
    AreaMeasure(
        "community_tank", "Community storage reservoir",
        "A shared buffer tank sized for roughly two weeks of survival demand.",
        cost_per_capita=290, months_to_deploy=12,
        storage_l_per_capita=_FORTNIGHT_SURVIVAL_L,
    ),
    AreaMeasure(
        "restrictions", "Demand restrictions and tariff reform",
        "Rising block tariffs plus a ban on non-essential outdoor use.",
        cost_per_capita=24, months_to_deploy=2, demand_reduction=0.09,
    ),
]

MEASURE_KEYS = [m.key for m in TEMPLATES]


def catalogue(population: float) -> dict[str, AreaMeasure]:
    """Concrete, costed measures for a study area of this size."""
    return {m.key: m.for_population(population) for m in TEMPLATES}


@dataclass
class Plan:
    """A concrete adaptation plan: which roofs, and which area-wide measures."""

    building_ids: set[int] = field(default_factory=set)
    measures: set[str] = field(default_factory=set)

    def _measures(self, cat: dict[str, AreaMeasure]) -> list[AreaMeasure]:
        return [cat[k] for k in sorted(self.measures) if k in cat]

    def cost(self, area_by_id: dict[int, float], cat: dict[str, AreaMeasure]) -> float:
        total = sum(rwh_cost(area_by_id[i]) for i in self.building_ids if i in area_by_id)
        return total + sum(m.cost for m in self._measures(cat))

    def effects(self, cat: dict[str, AreaMeasure]) -> dict[str, float]:
        """Combine area measures. Reductions compound rather than sum, so two
        30% cuts give 51%, not 60% -- stacking measures has diminishing returns."""
        out = {
            "demand_reduction": 0.0, "leak_reduction": 0.0,
            "greywater_reuse": 0.0, "recharge_boost": 0.0, "storage_bonus_l": 0.0,
        }
        for m in self._measures(cat):
            for name in ("demand_reduction", "leak_reduction", "greywater_reuse"):
                out[name] = 1.0 - (1.0 - out[name]) * (1.0 - getattr(m, name))
            out["recharge_boost"] += m.recharge_boost
            out["storage_bonus_l"] += m.storage_bonus_l
        return out

    def deploy_month(self, cat: dict[str, AreaMeasure]) -> int:
        ms = self._measures(cat)
        return max((m.months_to_deploy for m in ms), default=0)

    def to_dict(self, area_by_id: dict[int, float], cat: dict[str, AreaMeasure]) -> dict:
        roofs = sorted(self.building_ids)
        return {
            "building_ids": roofs,
            "n_buildings": len(roofs),
            "roof_area_m2": round(sum(area_by_id.get(i, 0.0) for i in roofs)),
            "rwh_cost": round(sum(rwh_cost(area_by_id[i]) for i in roofs if i in area_by_id)),
            "measures": [m.to_dict() for m in self._measures(cat)],
            "total_cost": round(self.cost(area_by_id, cat)),
            "currency": CURRENCY,
        }
