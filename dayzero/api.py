"""HTTP surface for DayZero.

The React build is served from the same origin as the API, so there is exactly
one deployment, one URL, and no CORS in production. The CORS middleware below
exists only so `npm run dev` on :5173 can talk to :8000 during development.
"""
from __future__ import annotations

import os
from functools import lru_cache

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import adversarial, world
from . import config as C
from .brief import llm
from .climate import PRESETS, Scenario, build_forcing, plausible_bounds
from .data import openmeteo
from .hydrology import simulate
from .interventions import Plan, catalogue
from .optimize import optimize

app = FastAPI(title="DayZero", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

DIST = C.ROOT / "frontend" / "dist"
PRESET_BY_KEY = {s.key: s for s in PRESETS}


# --------------------------------------------------------------------------
# Region cache. Rebuilding a region reprojects thousands of polygons, so the
# assembled object is memoised per (lat, lon, radius).
# --------------------------------------------------------------------------

@lru_cache(maxsize=16)
def _region(lat: float, lon: float, radius: float, label: str, pop: float) -> world.Region:
    place = openmeteo.Place(name=label or "Study area", country="", admin="", lat=lat, lon=lon)
    return world.build_region(place, radius_m=radius, population_override=pop or None)


def get_region(req: AreaRequest) -> world.Region:
    try:
        return _region(
            round(req.lat, 5),
            round(req.lon, 5),
            float(req.radius_m),
            req.label or "",
            float(req.population or 0.0),
        )
    except Exception as exc:
        raise HTTPException(502, f"could not assemble study area: {exc}") from exc


def resolve_scenario(req: ScenarioSpec | None) -> Scenario:
    if req is None:
        return PRESET_BY_KEY["drought"]
    if req.key and req.key in PRESET_BY_KEY and req.rain_percentile is None:
        return PRESET_BY_KEY[req.key]
    base = PRESET_BY_KEY.get(req.key or "drought", PRESETS[2])
    return Scenario(
        key="custom",
        name="Custom scenario",
        description="User-defined stress test.",
        rain_percentile=float(req.rain_percentile if req.rain_percentile is not None else base.rain_percentile),
        temp_anomaly_c=float(req.temp_anomaly_c if req.temp_anomaly_c is not None else base.temp_anomaly_c),
        demand_growth_pct=float(req.demand_growth_pct if req.demand_growth_pct is not None else base.demand_growth_pct),
    )


# --------------------------------------------------------------------------
# Schemas
# --------------------------------------------------------------------------

class AreaRequest(BaseModel):
    lat: float
    lon: float
    radius_m: float = Field(default=C.DEFAULT_RADIUS_M, ge=200, le=3000)
    label: str = ""
    # Occupancy inferred from footprints is the model's weakest assumption.
    # Supply the real figure here to replace it.
    population: float | None = Field(default=None, ge=0, le=5_000_000)


class ScenarioSpec(BaseModel):
    key: str | None = None
    rain_percentile: float | None = Field(default=None, ge=1, le=99)
    temp_anomaly_c: float | None = Field(default=None, ge=-1, le=6)
    demand_growth_pct: float | None = Field(default=None, ge=-5, le=40)


class SimRequest(AreaRequest):
    scenario: ScenarioSpec | None = None
    months: int = Field(default=C.SIM_MONTHS, ge=12, le=120)
    building_ids: list[int] = []
    measures: list[str] = []


class OptimizeRequest(SimRequest):
    budget: float = Field(default=50_000_000, gt=0)
    explain: bool = True


class AdversarialRequest(AreaRequest):
    months: int = Field(default=C.SIM_MONTHS, ge=12, le=120)
    budget: float | None = None


# --------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------

@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "version": app.version, "llm": llm.status(), "frontend_built": DIST.exists()}


@app.get("/api/assumptions")
def assumptions() -> dict:
    """Every model parameter, exposed. The honesty is the feature."""
    return {
        "water": {
            "litres_per_capita_per_day": C.LPCD,
            "survival_fraction_of_demand": C.SURVIVAL_FRACTION,
            "demand_rise_per_degree_c_lpcd": C.DEMAND_TEMP_SENSITIVITY,
        },
        "occupancy": {
            "people_per_m2_per_floor": C.PEOPLE_PER_M2_PER_FLOOR,
            "default_floors": C.DEFAULT_FLOORS,
            "min_building_area_m2": C.MIN_BUILDING_AREA_M2,
            "untagged_residential_share": C.UNTAGGED_RESIDENTIAL_SHARE,
            "large_footprint_m2": C.LARGE_FOOTPRINT_M2,
            "large_footprint_occupancy_factor": C.LARGE_FOOTPRINT_OCCUPANCY_FACTOR,
            "note": (
                "OSM rarely records what a building is for, so occupancy is the "
                "weakest assumption in the model. Pass `population` on any request "
                "to replace the estimate with a known figure."
            ),
        },
        "harvesting": {
            "runoff_coefficient": C.RUNOFF_COEFFICIENT,
            "tank_litres_per_m2_roof": C.TANK_LITRES_PER_M2,
        },
        "aquifer": {
            "natural_recharge_fraction": C.NATURAL_RECHARGE_FRACTION,
            "pervious_area_fraction": C.PERVIOUS_AREA_FRACTION,
            "usable_storage_litres_per_m2": C.AQUIFER_LITRES_PER_M2,
            "initial_fill_fraction": C.AQUIFER_INITIAL_FRACTION,
            "max_monthly_extraction_fraction": C.MAX_MONTHLY_EXTRACTION_FRACTION,
        },
        "municipal": {
            "supply_fraction_of_demand": C.MUNICIPAL_SUPPLY_FRACTION,
            "rainfall_elasticity": C.MUNICIPAL_RAINFALL_ELASTICITY,
            "lag_months": C.MUNICIPAL_LAG_MONTHS,
            "distribution_loss_fraction": C.DISTRIBUTION_LOSS_FRACTION,
        },
        "data_sources": {
            "climate": "ERA5 reanalysis via Open-Meteo Archive API (1991-2024, daily)",
            "buildings": "OpenStreetMap building footprints via Overpass API",
            "geometry": "Footprint areas projected to local UTM before measurement",
        },
        "disclaimer": (
            "DayZero produces scenario projections under stated assumptions. "
            "These are stress tests, not forecasts."
        ),
    }


@app.get("/api/search")
def search(q: str) -> dict:
    if not q.strip():
        return {"results": []}
    try:
        places = openmeteo.geocode(q)
    except Exception as exc:
        raise HTTPException(502, f"geocoding unavailable: {exc}") from exc
    return {
        "results": [
            {"label": p.label, "name": p.name, "lat": p.lat, "lon": p.lon} for p in places
        ]
    }


@app.get("/api/interventions")
def interventions(population: float = 10_000) -> dict:
    """Area-measure costs scale with the population served, so the catalogue is
    only meaningful once you say how many people it has to cover."""
    cat = catalogue(population)
    return {
        "population": population,
        "area_measures": [m.to_dict() for m in cat.values()],
        "currency": "INR",
    }


@app.get("/api/scenarios")
def scenarios() -> dict:
    return {"presets": [s.to_dict() for s in PRESETS]}


@app.post("/api/region")
def region_endpoint(req: AreaRequest) -> dict:
    r = get_region(req)
    if not r.buildings:
        raise HTTPException(
            404,
            "No mapped buildings here. Try a denser urban area or a larger radius.",
        )
    return {
        "region": r.summary(),
        "climate": r.climate.to_dict(),
        "buildings": world.geojson(r),
        "bounds": plausible_bounds(r.climate),
        "scenarios": [s.to_dict() for s in PRESETS],
    }


@app.post("/api/simulate")
def simulate_endpoint(req: SimRequest) -> dict:
    r = get_region(req)
    sc = resolve_scenario(req.scenario)
    forcing = build_forcing(r.climate, sc, req.months)
    plan = Plan(set(req.building_ids), set(req.measures))
    res = simulate(r, forcing, plan, sc.demand_growth_pct, req.months)
    return {
        "scenario": sc.to_dict(),
        "result": res.to_dict(),
        "bottleneck": adversarial.diagnose(res),
    }


@lru_cache(maxsize=32)
def _optimized(
    lat: float, lon: float, radius: float, label: str, pop: float,
    rain_pct: float, temp: float, growth: float, budget: float, months: int,
) -> dict:
    """Everything except the brief, memoised on the exact request.

    The brief is fetched separately, and re-deriving a 300-candidate search to
    write two paragraphs about it would double the wait on a small instance.
    Keyed on primitives so it is hashable.
    """
    r = _region(lat, lon, radius, label, pop)
    sc = Scenario("custom", "Custom scenario", "", rain_pct, temp, growth)
    forcing = build_forcing(r.climate, sc, months)
    opt = optimize(r, forcing, budget, growth, months)
    return {
        "region": r.summary(),
        "scenario": sc.to_dict(),
        "optimization": opt,
        "bottleneck": adversarial.diagnose(simulate(r, forcing, Plan(), growth, months)),
        "selected_buildings": opt["optimal"]["plan"]["building_ids"],
    }


def _optimize_payload(req: "OptimizeRequest") -> dict:
    sc = resolve_scenario(req.scenario)
    try:
        payload = _optimized(
            round(req.lat, 5), round(req.lon, 5), float(req.radius_m),
            req.label or "", float(req.population or 0.0),
            sc.rain_percentile, sc.temp_anomaly_c, sc.demand_growth_pct,
            float(req.budget), int(req.months),
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(502, f"could not run the optimiser: {exc}") from exc
    # Preserve the preset's own name and blurb, which the cache key drops.
    return {**payload, "scenario": {**payload["scenario"], **sc.to_dict()}}


@app.post("/api/optimize")
def optimize_endpoint(req: OptimizeRequest) -> dict:
    """The plan and the comparison. Ask /api/brief for the prose."""
    payload = _optimize_payload(req)
    payload["brief"] = llm.generate(payload) if req.explain else None
    return payload


@app.post("/api/brief")
def brief_endpoint(req: OptimizeRequest) -> dict:
    """The written brief for a plan already computed by /api/optimize.

    Split out because the optimiser is fast and the language model is not.
    Fetching them together makes the whole page wait on the slowest part; the
    memoised search above means asking twice costs nothing.
    """
    return {"brief": llm.generate(_optimize_payload(req))}


@app.post("/api/adversarial")
def adversarial_endpoint(req: AdversarialRequest) -> dict:
    r = get_region(req)
    found = adversarial.find_breaking_point(r, months=req.months)

    if req.budget:
        sc_dict = found["scenario"]
        sc = Scenario(
            "adversarial", "Worst plausible", sc_dict["description"],
            sc_dict["rain_percentile"], sc_dict["temp_anomaly_c"], sc_dict["demand_growth_pct"],
        )
        forcing = build_forcing(r.climate, sc, req.months, seed=11)
        found["survival_plan"] = optimize(
            r, forcing, req.budget, sc.demand_growth_pct, req.months
        )
    return found


# --------------------------------------------------------------------------
# Static frontend -- mounted last so /api/* always wins.
# --------------------------------------------------------------------------

if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        candidate = DIST / path
        if path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(DIST / "index.html")
else:
    @app.get("/")
    def no_build() -> dict:
        return {
            "message": "DayZero API is running. The frontend has not been built.",
            "build": "cd frontend && npm install && npm run build",
            "docs": "/docs",
        }


def main() -> None:
    import uvicorn

    uvicorn.run(
        "dayzero.api:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "7860")),
        reload=bool(os.getenv("DAYZERO_RELOAD")),
    )


if __name__ == "__main__":
    main()
