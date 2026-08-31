"""Assemble a study area: real footprints + real climate -> a simulatable Region."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from . import config as C
from .data import openmeteo, overpass
from .data.openmeteo import ClimateHistory
from .geometry import bbox_area_m2, bbox_around, polygon_area_m2, projector

# Rough floor counts by OSM building tag, used when building:levels is absent.
_FLOORS_BY_TAG = {
    "apartments": 4.0, "residential": 2.0, "house": 1.5, "detached": 2.0,
    "terrace": 2.0, "dormitory": 4.0, "hotel": 5.0, "commercial": 3.0,
    "retail": 2.0, "office": 5.0, "industrial": 1.5, "warehouse": 1.0,
    "school": 2.0, "university": 3.0, "hospital": 4.0, "church": 1.0,
    "temple": 1.0, "mosque": 1.0, "garage": 1.0, "shed": 1.0, "hut": 1.0,
}
# Buildings people do not live in still have roofs worth harvesting, but they
# should not inflate the population estimate.
_NON_RESIDENTIAL = {
    "industrial", "warehouse", "garage", "shed", "hut", "roof", "carport",
    "church", "temple", "mosque", "retail", "commercial", "office",
}


@dataclass
class Building:
    id: int
    lon: float
    lat: float
    area_m2: float
    floors: float
    kind: str
    people: float
    ring: list[tuple[float, float]] = field(default_factory=list)

    @property
    def is_residential(self) -> bool:
        return self.kind not in _NON_RESIDENTIAL


@dataclass
class Region:
    place: openmeteo.Place
    bbox: tuple[float, float, float, float]
    ground_area_m2: float
    buildings: list[Building]
    climate: ClimateHistory
    current: dict = field(default_factory=dict)
    population_estimated: bool = True

    @property
    def population(self) -> float:
        return sum(b.people for b in self.buildings)

    @property
    def roof_area_m2(self) -> float:
        return sum(b.area_m2 for b in self.buildings)

    @property
    def aquifer_capacity_l(self) -> float:
        return self.ground_area_m2 * C.AQUIFER_LITRES_PER_M2

    @property
    def pervious_area_m2(self) -> float:
        """Open ground that can recharge the aquifer.

        Not everything without a roof is pervious -- roads and paved yards shed
        water straight to the storm drain -- so the unbuilt area is discounted.
        """
        built = min(self.roof_area_m2, self.ground_area_m2 * 0.85)
        unbuilt = max(self.ground_area_m2 - built, self.ground_area_m2 * 0.05)
        return unbuilt * C.PERVIOUS_AREA_FRACTION

    def summary(self) -> dict:
        rain = self.climate.annual_rain
        harvestable = self.roof_area_m2 * float(np.median(rain)) * C.RUNOFF_COEFFICIENT
        return {
            "place": self.place.label,
            "lat": self.place.lat,
            "lon": self.place.lon,
            "bbox": list(self.bbox),
            "ground_area_km2": round(self.ground_area_m2 / 1e6, 3),
            "buildings": len(self.buildings),
            "roof_area_m2": round(self.roof_area_m2),
            "roof_coverage_pct": round(100 * self.roof_area_m2 / self.ground_area_m2, 1),
            "population": round(self.population),
            "population_per_km2": round(self.population / max(self.ground_area_m2 / 1e6, 1e-9)),
            "population_is_estimated": self.population_estimated,
            "mean_annual_rain_mm": round(float(rain.mean()), 1),
            "annual_demand_l": round(self.population * C.LPCD * 365.0),
            "harvestable_l_per_year": round(harvestable),
            "current": self.current,
        }


def build_region(
    place: openmeteo.Place,
    radius_m: float = C.DEFAULT_RADIUS_M,
    with_forecast: bool = True,
    population_override: float | None = None,
) -> Region:
    """Assemble a study area.

    `population_override` replaces the footprint-derived estimate. Occupancy is
    the weakest assumption in the whole model -- OSM rarely records what a
    building is for, so a commercial district and a housing block look alike --
    and a user who knows the real figure should be able to say so.
    """
    bbox = bbox_around(place.lat, place.lon, radius_m)
    elements = overpass.buildings(bbox)
    tf = projector(place.lat, place.lon)

    out: list[Building] = []
    for el in elements:
        tags = el.get("tags") or {}
        kind = tags.get("building", "yes")
        for ring in overpass.rings(el):
            area = polygon_area_m2(ring, tf)
            if area < C.MIN_BUILDING_AREA_M2:
                continue
            floors = _floors(tags, kind)
            people = _occupancy(area, floors, kind)
            lons = [p[0] for p in ring]
            lats = [p[1] for p in ring]
            out.append(
                Building(
                    id=int(el["id"]),
                    lon=sum(lons) / len(lons),
                    lat=sum(lats) / len(lats),
                    area_m2=area,
                    floors=floors,
                    kind=kind,
                    people=people,
                    ring=[(round(x, 6), round(y, 6)) for x, y in ring],
                )
            )

    out.sort(key=lambda b: b.area_m2, reverse=True)
    out = out[: C.MAX_BUILDINGS]

    ground_km2 = bbox_area_m2(bbox) / 1e6
    total = sum(b.people for b in out)

    if population_override and total > 0:
        # Redistribute the stated population across buildings in proportion to
        # the floor area already estimated, so per-building detail survives.
        factor = population_override / total
        for b in out:
            b.people *= factor
    else:
        # Sanity bound on density. If the tags produced something impossible,
        # scale every building down proportionally rather than trusting it.
        ceiling = C.MAX_PEOPLE_PER_KM2 * ground_km2
        if total > ceiling > 0:
            factor = ceiling / total
            for b in out:
                b.people *= factor

    return Region(
        place=place,
        bbox=bbox,
        ground_area_m2=bbox_area_m2(bbox),
        buildings=out,
        climate=openmeteo.climate_history(place.lat, place.lon),
        current=openmeteo.current_conditions(place.lat, place.lon) if with_forecast else {},
        population_estimated=population_override is None,
    )


# Tags that positively identify housing, as opposed to `building=yes`.
_RESIDENTIAL = {
    "apartments", "residential", "house", "detached", "terrace", "semidetached_house",
    "dormitory", "bungalow", "static_caravan", "hut", "farm",
}


def _occupancy(area_m2: float, floors: float, kind: str) -> float:
    """Estimated residents of one building.

    OSM rarely says what a building is for, so this leans on two robust
    signals: the tag when there is one, and the footprint size when there is
    not. Getting this wrong in the optimistic direction inflates demand and
    makes every region look doomed, so the defaults are deliberately cautious.
    """
    if kind in _NON_RESIDENTIAL:
        return 0.0
    share = 1.0 if kind in _RESIDENTIAL else C.UNTAGGED_RESIDENTIAL_SHARE
    if area_m2 > C.LARGE_FOOTPRINT_M2:
        share *= C.LARGE_FOOTPRINT_OCCUPANCY_FACTOR
    return area_m2 * floors * C.PEOPLE_PER_M2_PER_FLOOR * share


def _floors(tags: dict, kind: str) -> float:
    for key in ("building:levels", "levels"):
        raw = tags.get(key)
        if raw:
            try:
                return max(1.0, min(float(str(raw).split(";")[0]), 60.0))
            except ValueError:
                pass
    return _FLOORS_BY_TAG.get(kind, C.DEFAULT_FLOORS)


def geojson(region: Region, selected: set[int] | None = None) -> dict:
    """Footprints as GeoJSON for MapLibre. Rings are closed here, not client-side."""
    selected = selected or set()
    feats = []
    for b in region.buildings:
        ring = list(b.ring)
        if ring[0] != ring[-1]:
            ring.append(ring[0])
        feats.append(
            {
                "type": "Feature",
                "id": b.id,
                "properties": {
                    "id": b.id,
                    "area": round(b.area_m2),
                    "kind": b.kind,
                    "people": round(b.people, 1),
                    "selected": 1 if b.id in selected else 0,
                },
                "geometry": {"type": "Polygon", "coordinates": [ring]},
            }
        )
    return {"type": "FeatureCollection", "features": feats}
