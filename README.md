# DayZero

### Find your Day Zero. Then buy it back.

In 2018 Cape Town counted down to **Day Zero** — the date the taps would be
shut off. Every city has one. Most have never calculated it.

Pick any point on Earth. DayZero pulls the real building footprints and 34
years of real climate history for that spot, simulates the water balance
forward month by month, and tells you which month the taps run dry. Then it
searches the intervention space for the cheapest plan that pushes that month
further away.

It is not a dashboard and not a forecast. It answers one question:

> *When does this place run out of water, and what is the cheapest way to buy
> those months back?*

Built for **NextStep Hacks 2026** · *Earth Forward*.

---

## Why this is not another climate dashboard

Most climate hackathon projects visualise data. This one **simulates a system
and then optimises against it**, and every number traces back to something real:

| | |
|---|---|
| **Real geometry** | Building footprints from OpenStreetMap, areas measured in a local UTM projection — never in degrees |
| **Real climate** | ERA5 reanalysis, 1991–2024, daily rainfall / temperature / evapotranspiration for the exact coordinate |
| **Real mechanism** | A coupled reservoir–aquifer–demand model, not a weighted score |
| **Real optimisation** | An exact search over the intervention space, benchmarked against the greedy heuristic it beats |

Scenarios are drawn from the location's own record. "Severe drought" in
Bengaluru means *the 10th-percentile monsoon that actually occurred there*, not
an arbitrary −35% slider. That makes every scenario defensible and specific to
the place — a severe drought in Cape Town has a completely different shape.

---

## The model

### Water balance

One month per timestep. Storage carries forward; everything else is a flow.

```
rainfall ──┬─> roof runoff ──> rooftop tanks ──┐
           │                                   │
           ├─> pervious ground ──> aquifer ────┼──> household supply
           │                                   │
           └─> catchment runoff ──> reservoir ─┘

demand = population × lpcd × days,  uplifted by heat
```

The critical design choice: **municipal supply is a reservoir stock, not a
fixed fraction.** A fraction can only scale down smoothly. A reservoir can
*empty* — and emptying is what "day zero" actually is.

Catchment inflow scales with rainfall raised to an elasticity of 2.5, because
streamflow responds strongly non-linearly to rainfall deficit: dry soil absorbs
the first rain and yields almost no runoff. Published elasticities for
semi-arid catchments run 2–3. This is the mechanism behind every real day-zero
event, and a linear model cannot reproduce it.

Failure is defined as **service falling below 45% of demand** — basic need —
not the aquifer hitting zero. A region can ration for a while; what matters is
when it can no longer meet basic need.

### The optimiser

Three stages, layered so the demo can show what each one buys:

1. **Greedy** — rank every roof and every measure by estimated litres-per-rupee
   and buy down the list. This is what a spreadsheet would do. It is the
   baseline we beat.
2. **Exact** — enumerate all 2⁶ subsets of area-wide measures; for each, solve
   the remaining rooftop budget with a bounded-knapsack DP over roof-size bins,
   sweeping the roof/measure budget split.
3. **Rank** — score every candidate with the *full hydrological simulation*,
   not the surrogate. All reported numbers come from this stage.

The gap between stages 1 and 3 is where the interesting behaviour lives, and it
is genuinely emergent rather than contrived:

- Measures with long deployment times contribute nothing in year one. The
  cost-effectiveness ranking cannot see that.
- Equipping a roof for harvesting **stops that roof shedding runoff to the
  ground**, so past a point harvesting starves the aquifer it is meant to
  protect. Spending the entire budget on roofs is not optimal.
- Stacked demand reductions compound rather than sum — two 30% cuts give 51%,
  not 60%.

The headline result on the demo location (Bengaluru, extreme scenario):

| Budget available | Greedy | DayZero |
|---:|---:|---:|
| ₹1.5 cr | 49 months | 49 months |
| **₹2.0 cr** | **38 months** (spends ₹2.00 cr) | **49 months** (spends ₹1.27 cr) |
| ₹2.5 cr | 49 months | 49 months |

At ₹2 cr DayZero buys **11 more months for 37% less money**, and hands back
₹73 lakh of the budget.

**Greedy gets worse when given more money.** At ₹1.5 cr its ranking buys
managed aquifer recharge (10 months to deploy). At ₹2.0 cr the extra budget
lets it afford greywater recycling, which scores higher on litres-per-rupee, so
it swaps — but greywater takes 14 months to build and contributes nothing
before the failure point. Eleven months of resilience are lost by spending more.

The exact search holds 49 at every budget, because it scores candidates with
the simulation, which knows about deployment lag. Cape Town shows the same
pathology independently (52 → 60, a 8-month gap at ₹2 cr).

### Adversarial stress testing

Rather than asking the user to guess a scenario, DayZero searches for the one
that breaks this location soonest — coarse grid, then local refinement, ~118
evaluations in under a second.

The search is **bounded by the location's own observed record**. It cannot
invent a drought drier than anything ERA5 has measured there since 1991. That
keeps it a stress test rather than a fantasy.

---

## Running it

```bash
uv sync                              # Python deps (uv installs 3.12 itself)
cd frontend && npm install && npm run build && cd ..
uv run uvicorn dayzero.api:app --reload --port 8000
```

Open <http://localhost:8000>. FastAPI serves the built React app from the same
origin, so there is one process, one URL and no CORS.

For frontend development with hot reload, run the API on `:8000` and
`npm run dev` in `frontend/` on `:5173` — Vite proxies `/api` across.

### Docker

```bash
docker build -t dayzero .
docker run -p 7860:7860 dayzero
```

### Tests

```bash
uv run pytest
```

24 tests covering the failure modes that matter: area measured in metres rather
than degrees, storages that never exceed capacity or go negative, plans that
never exceed their budget, and the guarantee that the exact search is never
worse than greedy and never non-monotone in budget.

---

## Deployment

Every option below is free and none needs a credit card. The whole app is one
Docker image serving one URL, so anything that runs a container works.

### Show it to someone right now — no account anywhere

```bash
./scripts/share.sh
```

Builds the frontend, starts the app, and opens a Cloudflare quick tunnel. You
get a public `https://…trycloudflare.com` link in about a minute. The link lives
only while the script runs — ideal for recording the demo video or a mentor
session, not for the submission link.

### Render — one click from GitHub

`render.yaml` is committed, so: **New → Blueprint → connect this repo**. Render
reads the Dockerfile and the health check and deploys. Free instances sleep
after 15 minutes and take ~50s to wake, so during judging keep it warm with a
free [cron-job.org](https://cron-job.org) ping to `/api/health` every 10 minutes.

### Hugging Face Spaces

```bash
pip install -U "huggingface_hub[cli]" && hf auth login
./scripts/deploy_hf.sh <your-hf-username>
```

### Anywhere else

```bash
docker build -t dayzero .
docker run -p 7860:7860 dayzero
```

**The demo cache is committed on purpose.** `cache/dayzero.sqlite` holds
pre-fetched Overpass and ERA5 responses for the demo cities, so the app runs
with no network at all. Overpass rate-limits aggressively and intermittently
returns zero results under load; you do not want to discover that while a judge
has your link open.

Add a location to the cache with:

```bash
uv run python scripts/warm_cache.py "Jaipur, India" 26.9124 75.7873
```

---

## The decision brief

The LLM writes the brief and nothing else. **The numbers come from the
optimiser; the model only explains them.** Every figure is pre-formatted before
it reaches the model, so it can quote "Rs 19.97 lakh" but cannot print
`1997000.0`.

### It works with zero configuration

If Ollama is running on your machine, DayZero finds it, lists what you have
installed, and picks the best model available. Nothing is downloaded and no key
is needed.

Run `ollama signin` once (free account) and it will also reach Ollama's **cloud
models** — a 31B model answers in about 4 seconds, versus several minutes for a
4B model on a laptop CPU. Reasoning models are deliberately ranked last and
`think` is disabled: a chain of thought before a two-paragraph brief is pure
latency.

| Backend | Cost | Use for |
|---|---|---|
| `ollama` (cloud models) | free tier, ollama.com account | **the default** — fast and good |
| `ollama` (local models) | free, fully offline | no account, no network |
| `groq` | free tier, no card | if you prefer a hosted key |
| `openrouter` | free tier | fallback |
| `anthropic` | paid | if hackathon credits appear |

A deployed server has no local Ollama. Give it a key from
[ollama.com/settings/keys](https://ollama.com/settings/keys) as `OLLAMA_API_KEY`
and it reaches the same cloud models.

### It also works with no LLM at all

If every backend is unreachable or out of quota, a **deterministic template
brief** is generated instead — complete, readable, and built from the same
numbers. The app never surfaces an LLM error to a visitor. Candidate models are
tried in order, so a model that has been retired upstream or moved behind a
paid plan is skipped rather than failing the request.

---

## Honest limitations

These are stated because a model whose assumptions are visible is more useful
than one that hides them. Every parameter below is exposed at `/api/assumptions`.

- **Occupancy is the weakest assumption.** OSM rarely records what a building
  is for, so a commercial district and a housing block look alike. The estimate
  uses tags where present and discounts large floorplates, landing dense urban
  cores at 7,000–9,000 people/km². Pass `population` on any request — or click
  the link in the UI — to replace it with a known figure.
- **Aquifer and reservoir volumes are parameterised, not measured.** No free
  API publishes them per coordinate. They are derived from published
  specific-yield and storage-ratio figures and scaled by study-area size.
- **Intervention costs are per-capita rates** calibrated to Indian rupees, so
  they scale to any study area but are not procurement quotes.
- **These are scenario projections under stated assumptions, not predictions.**
  The app says so in its own footer.

---

## Layout

```
dayzero/
├── config.py          every model parameter, in one place
├── cache.py           SQLite response cache
├── geometry.py        UTM projection and area measurement
├── data/
│   ├── openmeteo.py   ERA5 history, forecast, geocoding
│   └── overpass.py    OSM building footprints
├── world.py           footprints + climate -> a simulatable Region
├── climate.py         percentile-based scenarios from the real record
├── hydrology.py       the coupled water-balance simulation
├── interventions.py   the catalogue and the Plan object
├── optimize.py        greedy vs exact search
├── adversarial.py     worst-plausible-scenario search + bottleneck diagnosis
├── brief/             pluggable LLM + deterministic template
└── api.py             FastAPI, serves the built frontend

frontend/              React + Vite + Tailwind + MapLibre + Recharts
tests/                 pytest
scripts/               cache warming, HF deployment
```

## Data credits

- Climate: [ERA5](https://www.ecmwf.int/en/forecasts/dataset/ecmwf-reanalysis-v5)
  reanalysis via the [Open-Meteo](https://open-meteo.com/) Archive API
- Buildings and basemap: © [OpenStreetMap](https://www.openstreetmap.org/copyright)
  contributors, via [Overpass](https://overpass-api.de/) (ODbL)
