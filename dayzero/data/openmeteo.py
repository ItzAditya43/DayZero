"""Open-Meteo clients: geocoding, ERA5 reanalysis history, and forecast.

No API key. The archive endpoint gives daily precipitation, temperature and
FAO-56 reference evapotranspiration back to 1940 for any coordinate on Earth,
which is what grounds every scenario in this project in real observations.
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass, field

import httpx
import numpy as np

from .. import cache
from ..config import ERA5_END, ERA5_START

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

TIMEOUT = httpx.Timeout(60.0, connect=15.0)


@dataclass
class Place:
    name: str
    country: str
    admin: str
    lat: float
    lon: float

    @property
    def label(self) -> str:
        bits = [b for b in (self.name, self.admin, self.country) if b]
        return ", ".join(dict.fromkeys(bits))


def geocode(query: str, count: int = 5) -> list[Place]:
    key = f"geocode:{query.lower().strip()}:{count}"
    payload = cache.get(key)
    if payload is None:
        r = httpx.get(
            GEOCODE_URL,
            params={"name": query, "count": count, "language": "en", "format": "json"},
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        payload = r.json()
        cache.put(key, payload)
    return [
        Place(
            name=h.get("name", ""),
            country=h.get("country", ""),
            admin=h.get("admin1", ""),
            lat=float(h["latitude"]),
            lon=float(h["longitude"]),
        )
        for h in payload.get("results") or []
    ]


@dataclass
class ClimateHistory:
    """Monthly-aggregated ERA5 history for one point.

    Arrays are shaped (n_years, 12). Rainfall is mm/month, temperature is the
    monthly mean in degrees C, et0 is mm/month of reference evapotranspiration.
    """

    lat: float
    lon: float
    years: list[int]
    rain_mm: np.ndarray
    temp_c: np.ndarray
    et0_mm: np.ndarray
    elevation: float = 0.0
    _norm: dict = field(default_factory=dict, repr=False)

    @property
    def annual_rain(self) -> np.ndarray:
        return self.rain_mm.sum(axis=1)

    @property
    def normal_rain(self) -> np.ndarray:
        """Median monthly rainfall profile -- 'what normal looks like here'."""
        return np.median(self.rain_mm, axis=0)

    @property
    def normal_temp(self) -> np.ndarray:
        return np.median(self.temp_c, axis=0)

    @property
    def normal_et0(self) -> np.ndarray:
        return np.median(self.et0_mm, axis=0)

    @property
    def mean_annual_temp(self) -> float:
        return float(np.mean(self.temp_c))

    def to_dict(self) -> dict:
        return {
            "lat": self.lat,
            "lon": self.lon,
            "years": self.years,
            "elevation": self.elevation,
            "annual_rain_mm": [round(float(v), 1) for v in self.annual_rain],
            "normal_monthly_rain_mm": [round(float(v), 1) for v in self.normal_rain],
            "normal_monthly_temp_c": [round(float(v), 1) for v in self.normal_temp],
            "normal_monthly_et0_mm": [round(float(v), 1) for v in self.normal_et0],
            "mean_annual_rain_mm": round(float(self.annual_rain.mean()), 1),
            "driest_year": int(self.years[int(np.argmin(self.annual_rain))]),
            "driest_year_rain_mm": round(float(self.annual_rain.min()), 1),
            "wettest_year": int(self.years[int(np.argmax(self.annual_rain))]),
        }


def _monthly(dates: list[str], values: list[float | None], how: str) -> tuple[list[int], np.ndarray]:
    """Fold a daily series into a (n_years, 12) array by sum or mean."""
    years = sorted({int(d[:4]) for d in dates})
    index = {y: i for i, y in enumerate(years)}
    total = np.zeros((len(years), 12))
    count = np.zeros((len(years), 12))
    for d, v in zip(dates, values):
        if v is None:
            continue
        y, m = int(d[:4]), int(d[5:7])
        total[index[y], m - 1] += float(v)
        count[index[y], m - 1] += 1
    if how == "mean":
        with np.errstate(invalid="ignore", divide="ignore"):
            out = np.where(count > 0, total / np.maximum(count, 1), np.nan)
        # Fill any month with no observations using that month's climatology.
        col_means = np.nanmean(out, axis=0)
        idx = np.where(np.isnan(out))
        out[idx] = np.take(col_means, idx[1])
        return years, out
    # Sums: a partial month would under-report, so scale to a full month.
    days = np.array(
        [[calendar.monthrange(y, m)[1] for m in range(1, 13)] for y in years],
        dtype=float,
    )
    scale = np.where(count > 0, days / np.maximum(count, 1), 1.0)
    return years, total * scale


def climate_history(lat: float, lon: float) -> ClimateHistory:
    key = f"era5:{lat:.4f}:{lon:.4f}:{ERA5_START}:{ERA5_END}"
    payload = cache.get(key)
    if payload is None:
        r = httpx.get(
            ARCHIVE_URL,
            params={
                "latitude": lat,
                "longitude": lon,
                "start_date": ERA5_START,
                "end_date": ERA5_END,
                "daily": "precipitation_sum,temperature_2m_mean,et0_fao_evapotranspiration",
                "timezone": "UTC",
            },
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        payload = r.json()
        cache.put(key, payload)

    daily = payload["daily"]
    dates = daily["time"]
    years, rain = _monthly(dates, daily["precipitation_sum"], "sum")
    _, temp = _monthly(dates, daily["temperature_2m_mean"], "mean")
    _, et0 = _monthly(dates, daily["et0_fao_evapotranspiration"], "sum")

    # Drop a trailing partial year so percentile scenarios are not skewed.
    if len(years) > 2 and rain[-1].sum() < 0.4 * np.median(rain[:-1].sum(axis=1)):
        years, rain, temp, et0 = years[:-1], rain[:-1], temp[:-1], et0[:-1]

    return ClimateHistory(
        lat=lat,
        lon=lon,
        years=years,
        rain_mm=rain,
        temp_c=temp,
        et0_mm=et0,
        elevation=float(payload.get("elevation") or 0.0),
    )


def current_conditions(lat: float, lon: float) -> dict:
    """Live-ish snapshot used only for the header strip in the UI."""
    key = f"forecast:{lat:.3f}:{lon:.3f}"
    payload = cache.get(key)
    if payload is None:
        try:
            r = httpx.get(
                FORECAST_URL,
                params={
                    "latitude": lat,
                    "longitude": lon,
                    "current": "temperature_2m,relative_humidity_2m,precipitation",
                    "daily": "precipitation_sum",
                    "past_days": 30,
                    "forecast_days": 7,
                    "timezone": "auto",
                },
                timeout=TIMEOUT,
            )
            r.raise_for_status()
            payload = r.json()
            cache.put(key, payload)
        except Exception:
            return {}
    cur = payload.get("current") or {}
    daily = (payload.get("daily") or {}).get("precipitation_sum") or []
    past = [v for v in daily[:30] if v is not None]
    return {
        "temperature_c": cur.get("temperature_2m"),
        "humidity_pct": cur.get("relative_humidity_2m"),
        "precipitation_mm": cur.get("precipitation"),
        "rain_last_30d_mm": round(sum(past), 1) if past else None,
    }
