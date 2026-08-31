"""OpenStreetMap building footprints via the Overpass API.

Overpass is free and keyless but slow and rate-limited, so every response is
cached by bounding box. The demo neighbourhood ships pre-cached in the repo.
"""
from __future__ import annotations

import httpx

from .. import cache
from ..config import MAX_BUILDINGS

MIRRORS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass.osm.ch/api/interpreter",
]
TIMEOUT = httpx.Timeout(180.0, connect=15.0)

# Overpass front-ends return 406 to clients with a default library User-Agent.
# Identifying the app properly is also just good manners toward a free service.
HEADERS = {
    "User-Agent": "DayZero/0.1 (climate resilience research; contact via project repo)",
    "Accept": "application/json",
}


def _query(bbox: tuple[float, float, float, float]) -> str:
    s, w, n, e = bbox
    box = f"{s:.6f},{w:.6f},{n:.6f},{e:.6f}"
    return f"""
[out:json][timeout:120];
(
  way["building"]({box});
  relation["building"]["type"="multipolygon"]({box});
);
out geom {MAX_BUILDINGS};
""".strip()


def buildings(bbox: tuple[float, float, float, float]) -> list[dict]:
    """Raw Overpass elements for buildings inside the bbox."""
    s, w, n, e = bbox
    key = f"overpass:{s:.5f},{w:.5f},{n:.5f},{e:.5f}"
    payload = cache.get(key)
    if payload is None or not payload.get("elements"):
        payload = _fetch(_query(bbox))
        # Never cache an empty answer. Overpass returns 0 elements under load
        # for areas that demonstrably have thousands of buildings, and caching
        # that would permanently convince the app the place is unmapped.
        if payload.get("elements"):
            cache.put(key, payload)
    return payload.get("elements", [])


def _fetch(query: str) -> dict:
    """Try each mirror until one returns actual data.

    A mirror can answer 200 with an empty element list when its database is
    stale or still importing, which would otherwise be cached as "there are no
    buildings here". An empty result is therefore treated as a failure and the
    next mirror is tried; only if every mirror agrees is the emptiness real.
    """
    last: Exception | str | None = None
    empty: dict | None = None
    for url in MIRRORS:
        try:
            r = httpx.post(url, data={"data": query}, headers=HEADERS, timeout=TIMEOUT)
            r.raise_for_status()
            payload = r.json()
            if payload.get("elements"):
                return payload
            empty = payload
            last = f"{url} returned 0 elements"
        except Exception as exc:  # try the next mirror
            last = exc
    if empty is not None:
        return empty
    raise RuntimeError(f"all Overpass mirrors failed: {last}")


def rings(element: dict) -> list[list[tuple[float, float]]]:
    """Outer ring(s) of an element as lon/lat coordinate lists."""
    if element.get("type") == "way":
        geom = element.get("geometry") or []
        if len(geom) >= 3:
            return [[(p["lon"], p["lat"]) for p in geom]]
        return []
    out = []
    for member in element.get("members") or []:
        if member.get("role") != "outer":
            continue
        geom = member.get("geometry") or []
        if len(geom) >= 3:
            out.append([(p["lon"], p["lat"]) for p in geom])
    return out
