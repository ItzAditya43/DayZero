"""Tests for the parts that would silently produce wrong numbers.

The priority here is not coverage, it is the class of bug that a simulation
can hide: an area computed in the wrong units, a plan that quietly exceeds its
budget, an "optimal" answer worse than the heuristic it is supposed to beat.
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from dayzero import config as C
from dayzero.climate import PRESETS, build_forcing, plausible_bounds
from dayzero.data.openmeteo import ClimateHistory, Place
from dayzero.geometry import (
    bbox_area_m2,
    bbox_around,
    polygon_area_m2,
    projector,
    utm_crs,
)
from dayzero.hydrology import simulate
from dayzero.interventions import Plan, catalogue, rwh_cost
from dayzero.optimize import knapsack_roofs, optimize
from dayzero.world import Building, Region

# --------------------------------------------------------------------------
# Geometry -- the unit bug that would silently wreck every downstream number.
# --------------------------------------------------------------------------

def test_utm_zone_selection():
    assert utm_crs(12.97, 77.59).to_epsg() == 32643   # Bengaluru, north
    assert utm_crs(-33.92, 18.42).to_epsg() == 32734  # Cape Town, south


def test_polygon_area_is_metres_not_degrees():
    """A 100 m square must measure ~10,000 m2, not ~8e-9 square degrees."""
    lat, lon = 12.9716, 77.5946
    d_lat = 100.0 / 111_320.0
    d_lon = 100.0 / (111_320.0 * math.cos(math.radians(lat)))
    ring = [
        (lon, lat),
        (lon + d_lon, lat),
        (lon + d_lon, lat + d_lat),
        (lon, lat + d_lat),
    ]
    area = polygon_area_m2(ring, projector(lat, lon))
    assert 9_500 < area < 10_500, area


def test_degenerate_polygons_are_zero_not_crash():
    tf = projector(12.97, 77.59)
    assert polygon_area_m2([], tf) == 0.0
    assert polygon_area_m2([(77.59, 12.97), (77.60, 12.97)], tf) == 0.0


def test_bbox_area_matches_requested_radius():
    area = bbox_area_m2(bbox_around(12.9716, 77.5946, 900.0))
    assert 0.9 * (1800**2) < area < 1.1 * (1800**2)


# --------------------------------------------------------------------------
# Fixtures: a synthetic region, so tests never touch the network.
# --------------------------------------------------------------------------

def _history(annual_mm: float = 900.0, n_years: int = 30) -> ClimateHistory:
    rng = np.random.default_rng(0)
    # A monsoon-shaped year: most rain in four months.
    shape = np.array([0.01, 0.01, 0.02, 0.05, 0.09, 0.14, 0.18, 0.17, 0.15, 0.11, 0.05, 0.02])
    years = list(range(1991, 1991 + n_years))
    totals = annual_mm * rng.uniform(0.62, 1.35, n_years)
    rain = totals[:, None] * shape[None, :]
    temp = np.tile(np.array([21, 23, 26, 28, 27, 24, 23, 23, 23, 23, 21, 20.5]), (n_years, 1))
    et0 = np.tile(np.full(12, 120.0), (n_years, 1))
    return ClimateHistory(12.97, 77.59, years, rain, temp, et0)


def _region(n_buildings: int = 1900) -> Region:
    """A synthetic study area at roughly real inner-city density.

    Density matters: a sparse suburb genuinely survives scenarios that break a
    dense one, so a thin fixture would pass the failure tests for the wrong
    reason. 1900 buildings over 3 km2 gives ~37k residents, which is close to
    what central Bengaluru actually measures.
    """
    rng = np.random.default_rng(3)
    ground = 3.0e6
    buildings = []
    for i in range(n_buildings):
        area = float(rng.uniform(45, 900))
        buildings.append(
            Building(
                id=i,
                lon=77.59,
                lat=12.97,
                area_m2=area,
                floors=2.0,
                kind="residential",
                people=area * 2.0 * C.PEOPLE_PER_M2_PER_FLOOR,
                ring=[],
            )
        )
    return Region(
        place=Place("Test", "", "", 12.97, 77.59),
        bbox=bbox_around(12.97, 77.59, 866.0),
        ground_area_m2=ground,
        buildings=buildings,
        climate=_history(),
    )


@pytest.fixture(scope="module")
def region() -> Region:
    return _region()


# --------------------------------------------------------------------------
# Climate scenarios
# --------------------------------------------------------------------------

def test_drier_scenarios_produce_less_rain(region):
    totals = []
    for key in ("baseline", "dry", "drought", "extreme"):
        sc = next(s for s in PRESETS if s.key == key)
        totals.append(build_forcing(region.climate, sc, 60)["rain_mm"].sum())
    assert totals == sorted(totals, reverse=True), totals


def test_rainfall_is_never_negative(region):
    for sc in PRESETS:
        rain = build_forcing(region.climate, sc, 60)["rain_mm"]
        assert (rain >= 0).all()


def test_adversarial_bounds_respect_the_observed_record(region):
    b = plausible_bounds(region.climate)
    assert b["driest_observed_mm"] == pytest.approx(
        float(region.climate.annual_rain.min()), rel=1e-3
    )
    assert b["rain_percentile"][0] >= 1.0


# --------------------------------------------------------------------------
# Hydrology
# --------------------------------------------------------------------------

def test_baseline_survives_and_extreme_does_not(region):
    def months(key: str) -> int:
        sc = next(s for s in PRESETS if s.key == key)
        f = build_forcing(region.climate, sc, 60)
        return simulate(region, f, Plan(), sc.demand_growth_pct, 60).resilience_months

    assert months("baseline") == 60, "a median year must not break the region"
    assert months("extreme") < 60, "the extreme scenario must actually stress it"


def test_service_fraction_stays_in_range(region):
    sc = next(s for s in PRESETS if s.key == "extreme")
    res = simulate(region, build_forcing(region.climate, sc, 60), Plan(), 10.0, 60)
    assert (res.served_fraction >= 0).all() and (res.served_fraction <= 1.0).all()


def test_storages_never_exceed_capacity_or_go_negative(region):
    sc = next(s for s in PRESETS if s.key == "drought")
    res = simulate(region, build_forcing(region.climate, sc, 60), Plan(), 5.0, 60)
    assert (res.aquifer_l >= -1e-6).all()
    assert (res.aquifer_l <= res.aquifer_capacity_l + 1e-6).all()
    assert (res.reservoir_l >= -1e-6).all()
    assert (res.reservoir_l <= res.reservoir_capacity_l + 1e-6).all()


def test_intervening_never_makes_things_worse_than_nothing(region):
    """Not a tautology: interventions have deployment lags and side effects."""
    sc = next(s for s in PRESETS if s.key == "extreme")
    f = build_forcing(region.climate, sc, 60)
    bare = simulate(region, f, Plan(), sc.demand_growth_pct, 60)
    funded = simulate(
        region,
        f,
        Plan({b.id for b in region.buildings}, {"fixtures", "restrictions", "leak_repair"}),
        sc.demand_growth_pct,
        60,
    )
    assert funded.resilience_months >= bare.resilience_months


# --------------------------------------------------------------------------
# Optimiser -- the budget guarantee and the greedy floor.
# --------------------------------------------------------------------------

@pytest.mark.parametrize("budget", [5e6, 2e7, 5e7, 1.5e8])
def test_optimal_plan_never_exceeds_budget(region, budget):
    sc = next(s for s in PRESETS if s.key == "extreme")
    f = build_forcing(region.climate, sc, 60)
    out = optimize(region, f, budget, sc.demand_growth_pct, 60)
    for key in ("greedy", "optimal"):
        spent = out[key]["plan"]["total_cost"]
        assert spent <= budget + 1.0, f"{key} spent {spent} of {budget}"


@pytest.mark.parametrize("budget", [5e6, 2e7, 5e7, 1.5e8])
def test_optimal_is_never_worse_than_greedy(region, budget):
    sc = next(s for s in PRESETS if s.key == "extreme")
    f = build_forcing(region.climate, sc, 60)
    out = optimize(region, f, budget, sc.demand_growth_pct, 60)
    assert out["improvement"]["months_vs_greedy"] >= 0


def test_knapsack_respects_budget(region):
    for budget in (0.0, 1e5, 1e6, 1e7, 1e8):
        picked = knapsack_roofs(region, budget)
        areas = {b.id: b.area_m2 for b in region.buildings}
        assert sum(rwh_cost(areas[i]) for i in picked) <= budget + 1.0


def test_more_budget_never_hurts_the_optimiser(region):
    """The exact search must be monotone in budget; greedy famously is not."""
    sc = next(s for s in PRESETS if s.key == "extreme")
    f = build_forcing(region.climate, sc, 60)
    prev = -1
    for budget in (1e7, 3e7, 6e7, 1.2e8):
        got = optimize(region, f, budget, sc.demand_growth_pct, 60)["optimal"]["result"][
            "resilience_months"
        ]
        assert got >= prev
        prev = got


# --------------------------------------------------------------------------
# Intervention costing
# --------------------------------------------------------------------------

def test_area_measure_costs_scale_with_population():
    small = catalogue(1_000)["leak_repair"].cost
    big = catalogue(100_000)["leak_repair"].cost
    assert big == pytest.approx(small * 100, rel=0.02)


def test_stacked_reductions_compound_rather_than_sum():
    plan = Plan(set(), {"fixtures", "restrictions"})
    cat = catalogue(10_000)
    combined = plan.effects(cat)["demand_reduction"]
    a = cat["fixtures"].demand_reduction
    b = cat["restrictions"].demand_reduction
    assert combined == pytest.approx(1 - (1 - a) * (1 - b))
    assert combined < a + b


def test_deploy_month_is_the_slowest_measure():
    cat = catalogue(10_000)
    plan = Plan(set(), {"restrictions", "greywater"})
    assert plan.deploy_month(cat) == cat["greywater"].months_to_deploy
