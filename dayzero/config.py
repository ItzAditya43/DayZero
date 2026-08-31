"""Tunable parameters for the DayZero model.

Every number here is an assumption. They are exposed in the API so the UI can
show them and the user can override them -- that honesty is the point. Sources
are noted where a published figure exists.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE_DB = ROOT / "cache" / "dayzero.sqlite"

# --- Water demand -----------------------------------------------------------
# Litres per capita per day. CPHEEO (India) norm for metro water supply is
# 135 lpcd; WHO puts basic need far lower. 135 is a reasonable urban default.
LPCD = 135.0

# Fraction of demand that is non-negotiable (drinking, cooking, sanitation).
# Below this the simulation reports a failure regardless of storage.
SURVIVAL_FRACTION = 0.45

# Demand rises in hot months. Extra litres/person/day per degree C of monthly
# mean temperature above the local annual mean.
DEMAND_TEMP_SENSITIVITY = 2.5

# --- Occupancy --------------------------------------------------------------
# People per square metre of building footprint, per floor. ~0.02 p/m2/floor is
# a common urban residential density (i.e. ~50 m2 of floor area per person).
PEOPLE_PER_M2_PER_FLOOR = 0.02
DEFAULT_FLOORS = 2.5
# Footprints below this are sheds/garages -- ignored.
MIN_BUILDING_AREA_M2 = 20.0

# Most OSM buildings carry only `building=yes`, with no clue what they are.
# Treating all of them as housing badly over-counts commercial districts: it
# put downtown Phoenix at 21,000 people/km2 against an actual ~1,500. This is
# the share of an untagged building assumed to be residential.
UNTAGGED_RESIDENTIAL_SHARE = 0.70

# Large floorplates skew commercial, institutional or industrial almost
# everywhere, so occupancy per square metre is discounted above this size.
LARGE_FOOTPRINT_M2 = 1500.0
LARGE_FOOTPRINT_OCCUPANCY_FACTOR = 0.45

# A final sanity bound. No neighbourhood on Earth sustains more than roughly
# 100k residents per km2 (Dharavi, Manila's slums), so anything above this is
# the tag data lying rather than a real place.
MAX_PEOPLE_PER_KM2 = 100_000.0

# --- Rainwater harvesting ---------------------------------------------------
# Fraction of rain landing on a roof that reaches the tank. Accounts for
# first-flush diversion, evaporation, gutter losses. 0.80 is the standard
# design figure for a hard roof.
RUNOFF_COEFFICIENT = 0.80

# Storage tank sized as litres per m2 of roof. A 100 m2 roof gets 5000 L.
TANK_LITRES_PER_M2 = 50.0

# --- Aquifer ----------------------------------------------------------------
# Fraction of rainfall over pervious ground that reaches the aquifer.
NATURAL_RECHARGE_FRACTION = 0.12
# Fraction of the study area that is not built over (parks, soil, verges).
PERVIOUS_AREA_FRACTION = 0.35
# Usable aquifer storage under the study area, litres per m2 of ground.
# Hard-rock aquifers like Bengaluru's have a large saturated thickness but a
# low specific yield: ~40 m at 2% yield gives ~800 L per m2 of ground.
AQUIFER_LITRES_PER_M2 = 800.0
# How full the aquifer is when the simulation starts.
AQUIFER_INITIAL_FRACTION = 0.55
# Hard cap on how fast the aquifer can be pumped, as a fraction of its
# remaining stock per month. Wells cannot drain an aquifer instantly.
MAX_MONTHLY_EXTRACTION_FRACTION = 0.045

# --- Municipal supply -------------------------------------------------------
# Municipal water is modelled as an upstream reservoir stock, not a fixed
# fraction. That matters: a fraction can only ever scale down smoothly, but a
# reservoir can empty, and emptying is what "day zero" actually is.

# Net delivery the system is designed to provide, as a fraction of baseline
# demand. 1.0 means the utility aims to meet demand in full in a normal year.
MUNICIPAL_DESIGN_FRACTION = 1.0

# Distribution losses (non-revenue water). India urban average is ~35%, so the
# utility must abstract more than it delivers.
DISTRIBUTION_LOSS_FRACTION = 0.32

# Live storage in the upstream reservoir system, in months of gross abstraction.
RESERVOIR_MONTHS_OF_SUPPLY = 11.0
RESERVOIR_INITIAL_FRACTION = 0.70

# In a median year the catchment yields slightly more than the city abstracts.
RESERVOIR_MEDIAN_YEAR_SURPLUS = 1.05

# Elasticity of catchment runoff to rainfall. Streamflow responds strongly
# non-linearly to rainfall deficit -- dry soil absorbs the first rain and yields
# little runoff -- so a 25% rainfall deficit typically produces a 45-55%
# streamflow deficit. Published elasticities for semi-arid catchments run 2-3.
STREAMFLOW_ELASTICITY = 2.5

# Convenience: gross abstraction as a multiple of demand, used by the optimiser
# surrogate to value leak repair.
MUNICIPAL_SUPPLY_FRACTION = MUNICIPAL_DESIGN_FRACTION / (1.0 - DISTRIBUTION_LOSS_FRACTION)

# --- Simulation -------------------------------------------------------------
SIM_MONTHS = 60
DAYS_IN_MONTH = 30.44

# --- Climate history --------------------------------------------------------
ERA5_START = "1991-01-01"
ERA5_END = "2024-12-31"

# --- Study area -------------------------------------------------------------
# Half-width of the bounding box fetched around the chosen point, in metres.
DEFAULT_RADIUS_M = 900.0
# Overpass will happily return tens of thousands of buildings. Cap it.
MAX_BUILDINGS = 4000
