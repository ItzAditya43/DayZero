"""Projection and area helpers.

The single most important thing in this file: roof areas are computed in a
local UTM projection, never in degrees. At Bengaluru's latitude a degree of
longitude is ~102 km while a degree of latitude is ~110 km, so treating
lat/lon as a flat cartesian plane under-reports area by roughly a third.
"""
from __future__ import annotations

import math

from pyproj import CRS, Transformer
from shapely.geometry import Polygon
from shapely.ops import transform as shapely_transform

_WGS84 = CRS.from_epsg(4326)


def utm_crs(lat: float, lon: float) -> CRS:
    """The UTM zone containing this point, as a metre-based CRS."""
    zone = int(math.floor((lon + 180.0) / 6.0) % 60) + 1
    epsg = (32600 if lat >= 0 else 32700) + zone
    return CRS.from_epsg(epsg)


def projector(lat: float, lon: float) -> Transformer:
    return Transformer.from_crs(_WGS84, utm_crs(lat, lon), always_xy=True)


def polygon_area_m2(coords: list[tuple[float, float]], tf: Transformer) -> float:
    """Area in square metres of a lon/lat ring, projected first."""
    if len(coords) < 3:
        return 0.0
    try:
        ring = Polygon(coords)
        if not ring.is_valid:
            ring = ring.buffer(0)
        return float(shapely_transform(tf.transform, ring).area)
    except Exception:
        return 0.0


def bbox_around(lat: float, lon: float, radius_m: float) -> tuple[float, float, float, float]:
    """(south, west, north, east) for a square box of the given half-width."""
    dlat = radius_m / 111_320.0
    dlon = radius_m / (111_320.0 * max(math.cos(math.radians(lat)), 0.01))
    return (lat - dlat, lon - dlon, lat + dlat, lon + dlon)


def bbox_area_m2(bbox: tuple[float, float, float, float]) -> float:
    south, west, north, east = bbox
    mid = (south + north) / 2.0
    height = (north - south) * 111_320.0
    width = (east - west) * 111_320.0 * math.cos(math.radians(mid))
    return abs(height * width)
