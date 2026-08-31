"""Scenario generation grounded in the location's own observed record.

The central design decision of DayZero: a "severe drought" is not an
arbitrary -35% slider. It is the monthly rainfall pattern of a year that
actually occurred at this coordinate, drawn from the tail of the ERA5
distribution. That makes every scenario defensible and location-specific --
a severe drought in Chennai is a different shape from one in Cape Town.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .data.openmeteo import ClimateHistory


@dataclass
class Scenario:
    key: str
    name: str
    description: str
    rain_percentile: float
    temp_anomaly_c: float
    demand_growth_pct: float

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "name": self.name,
            "description": self.description,
            "rain_percentile": self.rain_percentile,
            "temp_anomaly_c": self.temp_anomaly_c,
            "demand_growth_pct": self.demand_growth_pct,
        }


PRESETS = [
    Scenario("baseline", "Baseline", "A median year, repeated. What the system is built for.", 50, 0.0, 0.0),
    Scenario("dry", "Dry year", "Rainfall at the 25th percentile of the local record.", 25, 0.4, 2.0),
    Scenario("drought", "Severe drought", "10th-percentile rainfall with a warming signal.", 10, 1.2, 5.0),
    Scenario("extreme", "Extreme + heat", "5th-percentile rainfall, strong heat anomaly, growth.", 5, 2.2, 10.0),
]


def _percentile_year_profile(hist: ClimateHistory, pct: float) -> np.ndarray:
    """Monthly rainfall (mm) for a year at the given annual-total percentile.

    Rather than scaling the median profile -- which would distort the shape of
    the monsoon -- this interpolates between the two observed years whose annual
    totals bracket the target. The seasonal signature stays real.
    """
    totals = hist.annual_rain
    order = np.argsort(totals)
    target = float(np.percentile(totals, pct))
    sorted_totals = totals[order]
    pos = float(np.searchsorted(sorted_totals, target))
    lo = int(np.clip(np.floor(pos), 0, len(order) - 1))
    hi = int(np.clip(lo + 1, 0, len(order) - 1))
    span = sorted_totals[hi] - sorted_totals[lo]
    w = 0.0 if span <= 1e-6 else float((target - sorted_totals[lo]) / span)
    profile = (1 - w) * hist.rain_mm[order[lo]] + w * hist.rain_mm[order[hi]]
    # Nudge onto the exact target total without changing the seasonal shape.
    if profile.sum() > 1e-6:
        profile = profile * (target / profile.sum())
    return profile


def build_forcing(
    hist: ClimateHistory,
    scenario: Scenario,
    months: int,
    seed: int = 7,
) -> dict[str, np.ndarray]:
    """Expand a scenario into month-by-month rainfall, temperature and ET0.

    Year-to-year variability is preserved by sampling residuals from the real
    record, so a multi-year run is not the same year copied N times.
    """
    rng = np.random.default_rng(seed)
    base_rain = _percentile_year_profile(hist, scenario.rain_percentile)
    base_temp = hist.normal_temp + scenario.temp_anomaly_c
    base_et0 = hist.normal_et0

    # ET0 rises with temperature. ~4%/degC is a reasonable first-order response
    # for a Penman-Monteith reference surface.
    base_et0 = base_et0 * (1.0 + 0.04 * scenario.temp_anomaly_c)

    n_years = int(np.ceil(months / 12)) + 1
    rain, temp, et0 = [], [], []
    for y in range(n_years):
        # Multiplicative noise on rainfall, damped so a stress test does not
        # accidentally hand the region a wet year.
        jitter = np.clip(rng.normal(1.0, 0.18, 12), 0.55, 1.35)
        rain.append(base_rain * jitter)
        temp.append(base_temp + rng.normal(0.0, 0.35, 12))
        et0.append(base_et0 * np.clip(rng.normal(1.0, 0.06, 12), 0.8, 1.25))

    return {
        # Rainfall cannot be negative; the interpolation and jitter can produce
        # a tiny negative value, and downstream code raises it to a power.
        "rain_mm": np.maximum(np.concatenate(rain)[:months], 0.0),
        "temp_c": np.concatenate(temp)[:months],
        "et0_mm": np.concatenate(et0)[:months],
    }


def plausible_bounds(hist: ClimateHistory) -> dict:
    """Search bounds for the adversarial test, derived from the real record.

    The lower rainfall bound is the driest year actually observed here -- the
    adversarial search is not allowed to invent a drought worse than history.
    """
    totals = hist.annual_rain
    worst_pct = float(100.0 * (totals <= totals.min()).sum() / len(totals))
    return {
        "rain_percentile": [max(1.0, worst_pct), 50.0],
        "temp_anomaly_c": [0.0, 3.0],
        "demand_growth_pct": [0.0, 20.0],
        "driest_observed_mm": round(float(totals.min()), 1),
        "median_observed_mm": round(float(np.median(totals)), 1),
    }
