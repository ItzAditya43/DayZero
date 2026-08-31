"""Pre-fetch and cache everything a demo location needs.

Run this once per demo city and commit cache/dayzero.sqlite. The app then
works with no network at all -- which is what you want when a judge opens the
live link and Overpass is rate-limiting.

    uv run python scripts/warm_cache.py "Bengaluru" 12.9716 77.5946
"""
from __future__ import annotations

import sys
import time

from dayzero import cache, world
from dayzero.config import DEFAULT_RADIUS_M
from dayzero.data import openmeteo

DEMOS = [
    ("Bengaluru, India", 12.9716, 77.5946),
    ("Chennai, India", 13.0827, 80.2707),
    ("Cape Town, South Africa", -33.9249, 18.4241),
    ("Phoenix, Arizona", 33.4484, -112.0740),
]


def warm(label: str, lat: float, lon: float, radius: float = DEFAULT_RADIUS_M) -> None:
    print(f"\n=== {label} ({lat}, {lon}) r={radius:.0f}m ===")
    place = openmeteo.Place(name=label, country="", admin="", lat=lat, lon=lon)
    t0 = time.time()
    try:
        region = world.build_region(place, radius_m=radius)
    except Exception as exc:
        print(f"  FAILED: {type(exc).__name__}: {exc}")
        return
    s = region.summary()
    print(f"  buildings        {s['buildings']:,}")
    print(f"  roof area        {s['roof_area_m2']:,} m2  ({s['roof_coverage_pct']}% coverage)")
    print(f"  population est.  {s['population']:,}")
    print(f"  mean rainfall    {s['mean_annual_rain_mm']} mm/yr")
    print(f"  harvestable      {s['harvestable_l_per_year'] / 1e6:,.0f} ML/yr")
    print(f"  annual demand    {s['annual_demand_l'] / 1e6:,.0f} ML/yr")
    print(f"  took             {time.time() - t0:.1f}s")


if __name__ == "__main__":
    if len(sys.argv) >= 4:
        warm(sys.argv[1], float(sys.argv[2]), float(sys.argv[3]),
             float(sys.argv[4]) if len(sys.argv) > 4 else DEFAULT_RADIUS_M)
    else:
        for d in DEMOS:
            warm(*d)
    print(f"\ncached keys: {len(cache.keys())}")
