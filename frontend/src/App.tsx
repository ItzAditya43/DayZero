import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import MapView from "./components/MapView";
import { RainfallChart, ServiceChart, StorageChart } from "./components/Charts";
import { Bar, Button, ScenarioPicker, Slider, Stat } from "./components/Controls";
import {
  api,
  litres,
  rupees,
  type AdversarialResponse,
  type AreaSpec,
  type Bottleneck,
  type OptimizeResponse,
  type Place,
  type RegionResponse,
  type Scenario,
  type SimResult,
} from "./api";

const DEFAULTS: AreaSpec = { lat: 12.9716, lon: 77.5946, radius_m: 900, label: "Bengaluru, India" };
const HORIZON = 60;

export default function App() {
  const [area, setArea] = useState<AreaSpec>(DEFAULTS);
  const [region, setRegion] = useState<RegionResponse | null>(null);
  const [scenario, setScenario] = useState<Scenario | null>(null);
  const [custom, setCustom] = useState(false);
  // Defaults chosen so the first run lands on the result that shows why the
  // optimiser exists: at this budget the greedy ranking loses 11 months.
  const [budgetCr, setBudgetCr] = useState(2);

  const [sim, setSim] = useState<{ result: SimResult; bottleneck: Bottleneck } | null>(null);
  const [opt, setOpt] = useState<OptimizeResponse | null>(null);
  const [adv, setAdv] = useState<AdversarialResponse | null>(null);

  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<Place[]>([]);

  // ---- load a study area -------------------------------------------------
  const load = useCallback(async (spec: AreaSpec) => {
    setBusy("region");
    setError(null);
    setRegion(null);
    setSim(null);
    setOpt(null);
    setAdv(null);
    try {
      const r = await api.region(spec);
      setRegion(r);
      setScenario(r.scenarios.find((s) => s.key === "extreme") ?? r.scenarios[0]);
      setCustom(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  }, []);

  useEffect(() => {
    load(DEFAULTS);
  }, [load]);

  // ---- search ------------------------------------------------------------
  const timer = useRef<number | undefined>(undefined);
  useEffect(() => {
    window.clearTimeout(timer.current);
    if (query.trim().length < 2) {
      setHits([]);
      return;
    }
    timer.current = window.setTimeout(async () => {
      try {
        setHits(await api.search(query));
      } catch {
        setHits([]);
      }
    }, 300);
    return () => window.clearTimeout(timer.current);
  }, [query]);

  const spec = useMemo<AreaSpec>(() => area, [area]);
  const scenarioSpec = useMemo(
    () =>
      scenario
        ? custom
          ? {
              rain_percentile: scenario.rain_percentile,
              temp_anomaly_c: scenario.temp_anomaly_c,
              demand_growth_pct: scenario.demand_growth_pct,
            }
          : { key: scenario.key }
        : {},
    [scenario, custom],
  );

  // ---- actions -----------------------------------------------------------
  const run = async (kind: "sim" | "opt" | "adv") => {
    if (!region || !scenario) return;
    setBusy(kind);
    setError(null);
    try {
      if (kind === "sim") {
        setOpt(null);
        setAdv(null);
        setSim(await api.simulate(spec, scenarioSpec, HORIZON));
      } else if (kind === "opt") {
        setAdv(null);
        const r = await api.optimize(spec, scenarioSpec, budgetCr * 1e7, HORIZON);
        setOpt(r);
        setSim({ result: r.optimization.baseline.result, bottleneck: r.bottleneck });
      } else {
        setOpt(null);
        const r = await api.adversarial(spec, budgetCr * 1e7, HORIZON);
        setAdv(r);
        setSim({ result: r.result, bottleneck: r.bottleneck });
        setScenario({ ...r.scenario, key: "custom", name: "Worst plausible" });
        setCustom(true);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };

  const patch = (p: Partial<Scenario>) => {
    if (!scenario) return;
    setScenario({ ...scenario, ...p, key: "custom", name: "Custom scenario" });
    setCustom(true);
  };

  const selected = opt?.selected_buildings ?? adv?.survival_plan?.optimal.plan.building_ids ?? [];
  const plannedResult =
    opt?.optimization.optimal.result ?? adv?.survival_plan?.optimal.result ?? null;
  const optimization = opt?.optimization ?? adv?.survival_plan ?? null;

  return (
    <div className="h-full flex flex-col bg-[var(--ink)]">
      <Header
        query={query}
        setQuery={setQuery}
        hits={hits}
        onPick={(p) => {
          setQuery("");
          setHits([]);
          const next = { ...area, lat: p.lat, lon: p.lon, label: p.label };
          setArea(next);
          load(next);
        }}
        region={region}
      />

      {error && (
        <div className="px-4 py-2 bg-rose-950/60 border-y border-rose-800/60 text-rose-200 text-xs">
          {error}
        </div>
      )}

      <div
        className="flex-1 min-h-0 grid grid-cols-1 auto-rows-auto
                   lg:grid-cols-[340px_1fr_400px] lg:grid-rows-[minmax(0,1fr)]"
      >
        {/* ---------------- left: scenario controls ---------------- */}
        <aside className="border-r border-[var(--line)] overflow-y-auto min-h-0 p-4 space-y-4 order-2 lg:order-1">
          <RegionCard
            region={region}
            busy={busy === "region"}
            onPopulation={(v) => {
              const next = { ...area, population: v };
              setArea(next);
              load(next);
            }}
          />

          <section className="panel p-3.5">
            <div className="label mb-2.5">Climate scenario</div>
            {region && scenario && (
              <>
                <ScenarioPicker
                  scenarios={region.scenarios}
                  active={custom ? "custom" : scenario.key}
                  onPick={(s) => {
                    setScenario(s);
                    setCustom(false);
                  }}
                />
                <Slider
                  label="Rainfall percentile"
                  value={scenario.rain_percentile}
                  min={region.bounds.rain_percentile[0]}
                  max={95}
                  suffix="th"
                  hint={`P50 = ${region.bounds.median_observed_mm} mm/yr · driest observed = ${region.bounds.driest_observed_mm} mm`}
                  onChange={(v) => patch({ rain_percentile: v })}
                />
                <Slider
                  label="Temperature anomaly"
                  value={scenario.temp_anomaly_c}
                  min={0}
                  max={4}
                  step={0.1}
                  suffix=" °C"
                  hint="Raises evapotranspiration and per-capita demand."
                  onChange={(v) => patch({ temp_anomaly_c: v })}
                />
                <Slider
                  label="Demand growth"
                  value={scenario.demand_growth_pct}
                  min={0}
                  max={30}
                  suffix=" %/yr"
                  onChange={(v) => patch({ demand_growth_pct: v })}
                />
              </>
            )}
          </section>

          <section className="panel p-3.5">
            <div className="label mb-2.5">Adaptation budget</div>
            <Slider
              label="Available funding"
              value={budgetCr}
              min={0.5}
              max={40}
              step={0.5}
              suffix=" cr"
              hint={`${rupees(budgetCr * 1e7)} to spend on interventions.`}
              onChange={setBudgetCr}
            />
          </section>

          <div className="space-y-2">
            <Button onClick={() => run("sim")} busy={busy === "sim"} disabled={!region}>
              Run stress test
            </Button>
            <Button onClick={() => run("opt")} busy={busy === "opt"} disabled={!region}>
              Generate adaptation plan
            </Button>
            <Button
              variant="danger"
              onClick={() => run("adv")}
              busy={busy === "adv"}
              disabled={!region}
            >
              Find my breaking point
            </Button>
          </div>

          {region && (
            <section className="panel p-3.5">
              <div className="label mb-1">Observed rainfall · ERA5</div>
              <div className="text-[10px] text-slate-500 mb-2">
                {region.climate.years[0]}–{region.climate.years.at(-1)} · driest{" "}
                {region.climate.driest_year} at {region.climate.driest_year_rain_mm} mm
              </div>
              <RainfallChart
                years={region.climate.years}
                annual={region.climate.annual_rain_mm}
                median={region.bounds.median_observed_mm}
              />
            </section>
          )}

          <p className="text-[10px] leading-relaxed text-slate-600">
            DayZero produces scenario projections under stated assumptions. These are stress
            tests, not forecasts. Climate from ERA5 reanalysis; footprints from OpenStreetMap.
          </p>
        </aside>

        {/* ---------------- centre: map ---------------- */}
        {/* The map fills its grid cell, which needs a definite height: the
            canvas is absolutely positioned and contributes none of its own. */}
        <main className="relative order-1 lg:order-2 h-[46vh] lg:h-full lg:min-h-0">
          <MapView
            buildings={region?.buildings ?? null}
            selected={selected}
            center={region ? [region.region.lon, region.region.lat] : null}
            bbox={region?.region.bbox ?? null}
            onPick={(lat, lon) => {
              const next = { ...area, lat, lon, label: "Custom point" };
              setArea(next);
              load(next);
            }}
          />
          <MapLegend selectedCount={selected.length} />
          {busy === "region" && (
            <div className="absolute inset-0 grid place-items-center bg-[var(--ink)]/70 backdrop-blur-sm">
              <div className="mono text-xs text-teal-300 pulsing">
                Fetching footprints and 34 years of climate…
              </div>
            </div>
          )}
        </main>

        {/* ---------------- right: results ---------------- */}
        <aside className="border-l border-[var(--line)] overflow-y-auto min-h-0 p-4 space-y-4 order-3">
          {!sim && !busy && <EmptyState />}
          {sim && (
            <Verdict
              result={plannedResult ?? sim.result}
              baseline={sim.result}
              bottleneck={sim.bottleneck}
              improved={!!plannedResult}
            />
          )}
          {sim && (
            <section className="panel p-3.5">
              <div className="label mb-2">Water service delivered</div>
              <ServiceChart baseline={sim.result} planned={plannedResult} />
            </section>
          )}
          {sim && (
            <section className="panel p-3.5">
              <div className="label mb-2">Storage · reservoir and aquifer</div>
              <StorageChart result={plannedResult ?? sim.result} />
            </section>
          )}
          {adv && <AdversarialCard adv={adv} />}
          {optimization && <PlanCard opt={optimization} />}
          {opt?.brief && <BriefCard brief={opt.brief} />}
        </aside>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------

function Header({
  query,
  setQuery,
  hits,
  onPick,
  region,
}: {
  query: string;
  setQuery: (v: string) => void;
  hits: Place[];
  onPick: (p: Place) => void;
  region: RegionResponse | null;
}) {
  const cur = region?.region.current;
  return (
    <header className="border-b border-[var(--line)] px-4 py-2.5 flex items-center gap-4 flex-wrap">
      <div className="flex items-baseline gap-2.5">
        <span className="mono text-sm tracking-[0.2em] text-teal-300">DAYZERO</span>
        <span className="label hidden sm:block">Find your Day Zero. Then buy it back.</span>
      </div>

      <div className="relative flex-1 min-w-[180px] max-w-md">
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search a city, or click anywhere on the map…"
          className="w-full bg-[var(--panel-2)] border border-[var(--line)] rounded-md px-3 py-1.5 text-xs
                     placeholder:text-slate-600 focus:outline-none focus:border-teal-500/60"
        />
        {hits.length > 0 && (
          <ul className="absolute z-20 mt-1 w-full panel overflow-hidden">
            {hits.map((p, i) => (
              <li key={i}>
                <button
                  onClick={() => onPick(p)}
                  className="w-full text-left px-3 py-2 text-xs hover:bg-teal-400/10 hover:text-teal-200"
                >
                  {p.label}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      {cur?.temperature_c != null && (
        <div className="mono text-[10px] text-slate-500 flex gap-3">
          <span>{cur.temperature_c}°C now</span>
          {cur.rain_last_30d_mm != null && <span>{cur.rain_last_30d_mm} mm / 30d</span>}
        </div>
      )}
    </header>
  );
}

function RegionCard({
  region,
  busy,
  onPopulation,
}: {
  region: RegionResponse | null;
  busy: boolean;
  onPopulation: (v: number | null) => void;
}) {
  if (!region) {
    return (
      <section className="panel p-3.5 h-28 grid place-items-center">
        <span className={`mono text-[11px] text-slate-600 ${busy ? "pulsing" : ""}`}>
          {busy ? "Assembling study area…" : "No area loaded"}
        </span>
      </section>
    );
  }
  const r = region.region;
  const coverPct = Math.round((r.harvestable_l_per_year / r.annual_demand_l) * 100);
  return (
    <section className="panel p-3.5">
      <div className="text-sm text-slate-100 mb-0.5">{r.place}</div>
      <div className="mono text-[10px] text-slate-500 mb-3">
        {r.lat.toFixed(4)}, {r.lon.toFixed(4)} · {r.ground_area_km2} km²
      </div>
      <div className="grid grid-cols-2 gap-3 mb-3">
        <Stat label="Buildings" value={r.buildings.toLocaleString()} sub={`${r.roof_coverage_pct}% roof cover`} />
        <Stat
          label="Population"
          value={r.population.toLocaleString()}
          sub={`${r.population_per_km2.toLocaleString()}/km² · ${
            r.population_is_estimated ? "estimated" : "you set this"
          }`}
        />
        <Stat label="Roof area" value={`${(r.roof_area_m2 / 1e4).toFixed(1)} ha`} />
        <Stat label="Rainfall" value={`${r.mean_annual_rain_mm} mm`} sub="mean annual, ERA5" />
      </div>
      <div className="pt-3 border-t border-[var(--line)]">
        <div className="flex justify-between items-baseline mb-1.5">
          <span className="label">Rooftop yield vs demand</span>
          <span className="mono text-[11px] text-teal-300">{coverPct}%</span>
        </div>
        <Bar pct={coverPct} />
        <div className="text-[10px] text-slate-500 mt-1.5">
          {litres(r.harvestable_l_per_year)}/yr harvestable against {litres(r.annual_demand_l)}/yr
          demand.
        </div>
      </div>
      <PopulationOverride current={r.population} onSet={onPopulation} />
    </section>
  );
}

/** Occupancy inferred from footprints is the model's weakest assumption, so
 *  the UI says so and lets anyone who knows the real number supply it. */
function PopulationOverride({
  current,
  onSet,
}: {
  current: number;
  onSet: (v: number | null) => void;
}) {
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState("");
  if (!open) {
    return (
      <button
        onClick={() => {
          setDraft(String(current));
          setOpen(true);
        }}
        className="mt-3 text-[10px] text-slate-600 hover:text-teal-400 underline underline-offset-2"
      >
        Population is inferred from footprints — set the real figure
      </button>
    );
  }
  const commit = () => {
    const v = parseFloat(draft.replace(/[^0-9.]/g, ""));
    onSet(Number.isFinite(v) && v > 0 ? v : null);
    setOpen(false);
  };
  return (
    <div className="mt-3 flex gap-1.5">
      <input
        autoFocus
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => e.key === "Enter" && commit()}
        className="flex-1 min-w-0 bg-[var(--panel-2)] border border-[var(--line)] rounded px-2 py-1
                   mono text-[11px] focus:outline-none focus:border-teal-500/60"
      />
      <button
        onClick={commit}
        className="px-2 rounded border border-teal-500/50 text-teal-300 text-[10px] hover:bg-teal-400/10"
      >
        Set
      </button>
      <button
        onClick={() => {
          onSet(null);
          setOpen(false);
        }}
        className="px-2 rounded border border-slate-700 text-slate-400 text-[10px] hover:border-slate-500"
      >
        Auto
      </button>
    </div>
  );
}

function Verdict({
  result,
  baseline,
  bottleneck,
  improved,
}: {
  result: SimResult;
  baseline: SimResult;
  bottleneck: Bottleneck;
  improved: boolean;
}) {
  const failed = !result.survived;
  return (
    <section
      className={`panel p-3.5 border-l-2 ${failed ? "border-l-rose-500" : "border-l-teal-400"}`}
    >
      <div className="label mb-2">{failed ? "Day Zero projected" : "No Day Zero in range"}</div>
      <div className={`mono text-3xl mb-1 ${failed ? "text-rose-400" : "text-teal-300"}`}>
        {failed ? `Month ${result.failure_month}` : `> ${result.months} months`}
      </div>
      <div className="text-[11px] text-slate-400 mb-3">
        {failed
          ? `Service falls below basic need. ${result.people_affected.toLocaleString()} people affected.`
          : "Basic need is met across the whole projection horizon."}
      </div>

      {improved && (
        <div className="mb-3 px-2.5 py-2 rounded bg-teal-400/10 border border-teal-400/25">
          <span className="mono text-[11px] text-teal-200">
            {baseline.resilience_months} → {result.resilience_months} months
          </span>
          <span className="text-[10px] text-teal-400/70 ml-2">
            +{result.resilience_months - baseline.resilience_months} with the funded plan
          </span>
        </div>
      )}

      <div className="grid grid-cols-3 gap-3 pt-3 border-t border-[var(--line)]">
        <Stat
          label="Mean service"
          value={`${result.mean_served_pct}%`}
          tone={result.mean_served_pct < 70 ? "alarm" : "good"}
        />
        <Stat
          label="Aquifer low"
          value={`${result.aquifer_min_pct}%`}
          tone={result.aquifer_min_pct < 25 ? "alarm" : "normal"}
        />
        <Stat
          label="Reservoir low"
          value={`${result.reservoir_min_pct}%`}
          tone={result.reservoir_min_pct < 15 ? "alarm" : "normal"}
        />
      </div>

      <div className="mt-3 pt-3 border-t border-[var(--line)]">
        <div className="label mb-1.5">Bottleneck</div>
        <div className="text-xs text-amber-300">{bottleneck.primary}</div>
        <div className="text-[10px] text-slate-500 mt-0.5">then {bottleneck.secondary}</div>
      </div>
    </section>
  );
}

function AdversarialCard({ adv }: { adv: AdversarialResponse }) {
  const s = adv.scenario;
  return (
    <section className="panel p-3.5 border-l-2 border-l-rose-500">
      <div className="label mb-2">Adversarial search</div>
      <div className="text-[11px] text-slate-400 mb-3">
        Searched {adv.scenarios_searched} scenarios bounded by what has actually occurred here.
        The worst plausible combination:
      </div>
      <div className="grid grid-cols-3 gap-3">
        <Stat label="Rainfall" value={`P${s.rain_percentile.toFixed(0)}`} />
        <Stat label="Temp" value={`+${s.temp_anomaly_c.toFixed(1)}°C`} />
        <Stat label="Growth" value={`${s.demand_growth_pct.toFixed(0)}%`} />
      </div>
      <div className="text-[10px] text-slate-600 mt-2.5">
        Bounded below by the driest year on record here ({adv.bounds.driest_observed_mm} mm).
      </div>
    </section>
  );
}

function PlanCard({ opt }: { opt: NonNullable<OptimizeResponse["optimization"]> }) {
  const { optimal, greedy, baseline, improvement } = opt;
  const gap = improvement.months_vs_greedy;
  return (
    <section className="panel p-3.5">
      <div className="flex justify-between items-baseline mb-3">
        <span className="label">Optimal adaptation plan</span>
        <span className="mono text-[10px] text-slate-500">
          {opt.candidates_evaluated} plans evaluated
        </span>
      </div>

      <ol className="space-y-2 mb-3">
        {optimal.plan.n_buildings > 0 && (
          <li className="flex justify-between gap-3 text-[11px]">
            <span className="text-slate-300">
              Rooftop harvesting · {optimal.plan.n_buildings.toLocaleString()} buildings
              <span className="block text-[10px] text-slate-600">
                {optimal.plan.roof_area_m2.toLocaleString()} m² equipped
              </span>
            </span>
            <span className="mono text-teal-300 whitespace-nowrap">
              {rupees(optimal.plan.rwh_cost)}
            </span>
          </li>
        )}
        {optimal.plan.measures.map((m) => (
          <li key={m.key} className="flex justify-between gap-3 text-[11px]">
            <span className="text-slate-300">
              {m.name}
              <span className="block text-[10px] text-slate-600">
                {m.months_to_deploy} months to deploy
              </span>
            </span>
            <span className="mono text-teal-300 whitespace-nowrap">{rupees(m.cost)}</span>
          </li>
        ))}
      </ol>

      <div className="flex justify-between text-[11px] pt-2.5 border-t border-[var(--line)] mb-3">
        <span className="label">Total committed</span>
        <span className="mono text-slate-100">
          {rupees(optimal.plan.total_cost)}{" "}
          <span className="text-slate-600">of {rupees(opt.budget)}</span>
        </span>
      </div>

      <table className="w-full text-[11px]">
        <thead>
          <tr className="label">
            <th className="text-left font-normal pb-1.5"> </th>
            <th className="text-right font-normal pb-1.5">No action</th>
            <th className="text-right font-normal pb-1.5">Greedy</th>
            <th className="text-right font-normal pb-1.5 text-teal-400">DayZero</th>
          </tr>
        </thead>
        <tbody className="mono">
          <Row
            label="Months survived"
            a={baseline.result.resilience_months}
            b={greedy.result.resilience_months}
            c={optimal.result.resilience_months}
          />
          <Row
            label="Mean service"
            a={`${baseline.result.mean_served_pct}%`}
            b={`${greedy.result.mean_served_pct}%`}
            c={`${optimal.result.mean_served_pct}%`}
          />
          <Row
            label="Aquifer low"
            a={`${baseline.result.aquifer_min_pct}%`}
            b={`${greedy.result.aquifer_min_pct}%`}
            c={`${optimal.result.aquifer_min_pct}%`}
          />
          <Row
            label="Spent"
            a={rupees(baseline.plan.total_cost)}
            b={rupees(greedy.plan.total_cost)}
            c={rupees(optimal.plan.total_cost)}
          />
        </tbody>
      </table>

      {gap > 0 && (
        <div className="mt-3 px-2.5 py-2 rounded bg-amber-400/10 border border-amber-400/25 text-[11px] text-amber-200">
          The exact search beats ranking by cost-effectiveness by{" "}
          <span className="mono">{gap} months</span> at the same budget.
        </div>
      )}
    </section>
  );
}

function Row({
  label,
  a,
  b,
  c,
}: {
  label: string;
  a: string | number;
  b: string | number;
  c: string | number;
}) {
  return (
    <tr className="border-t border-[var(--line)]">
      <td className="py-1.5 text-slate-500 text-[10px] uppercase tracking-wider">{label}</td>
      <td className="py-1.5 text-right text-slate-500">{a}</td>
      <td className="py-1.5 text-right text-slate-400">{b}</td>
      <td className="py-1.5 text-right text-teal-300">{c}</td>
    </tr>
  );
}

function BriefCard({ brief }: { brief: NonNullable<OptimizeResponse["brief"]> }) {
  return (
    <section className="panel p-3.5">
      <div className="flex justify-between items-baseline mb-2.5">
        <span className="label">Decision brief</span>
        <span className="mono text-[9px] text-slate-600 uppercase">{brief.source}</span>
      </div>
      <p className="text-xs text-slate-100 leading-relaxed mb-3">{brief.headline}</p>
      <p className="text-[11px] text-slate-400 leading-relaxed mb-3">{brief.situation}</p>
      <div className="label mb-1.5">Why this plan</div>
      <p className="text-[11px] text-slate-400 leading-relaxed mb-3">{brief.reasoning}</p>
      <div className="label mb-1.5">Trade-offs</div>
      <p className="text-[11px] text-slate-400 leading-relaxed">{brief.tradeoffs}</p>
    </section>
  );
}

function MapLegend({ selectedCount }: { selectedCount: number }) {
  return (
    <div className="absolute top-3 left-3 panel px-3 py-2 text-[10px] space-y-1.5 pointer-events-none">
      <div className="flex items-center gap-2">
        <span className="w-2.5 h-2.5 rounded-sm bg-[#38506b]" />
        <span className="text-slate-400">Mapped building</span>
      </div>
      <div className="flex items-center gap-2">
        <span className="w-2.5 h-2.5 rounded-sm bg-teal-400" />
        <span className="text-slate-300">
          Funded for harvesting{selectedCount ? ` · ${selectedCount.toLocaleString()}` : ""}
        </span>
      </div>
    </div>
  );
}

function EmptyState() {
  return (
    <div className="h-full grid place-items-center text-center px-6">
      <div>
        <div className="mono text-xs text-slate-600 mb-2">NO STRESS TEST RUN</div>
        <p className="text-[11px] text-slate-500 leading-relaxed max-w-[240px]">
          Pick a scenario and run a stress test, or let DayZero search for the worst plausible
          conditions this location has the record to justify.
        </p>
      </div>
    </div>
  );
}
