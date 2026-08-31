// Typed client for the DayZero API. Same-origin in production, proxied in dev.

export type Place = { label: string; name: string; lat: number; lon: number };

export type RegionSummary = {
  place: string;
  lat: number;
  lon: number;
  bbox: number[];
  ground_area_km2: number;
  buildings: number;
  roof_area_m2: number;
  roof_coverage_pct: number;
  population: number;
  population_per_km2: number;
  population_is_estimated: boolean;
  mean_annual_rain_mm: number;
  annual_demand_l: number;
  harvestable_l_per_year: number;
  current: {
    temperature_c?: number;
    humidity_pct?: number;
    rain_last_30d_mm?: number;
  };
};

export type Climate = {
  years: number[];
  elevation: number;
  annual_rain_mm: number[];
  normal_monthly_rain_mm: number[];
  normal_monthly_temp_c: number[];
  mean_annual_rain_mm: number;
  driest_year: number;
  driest_year_rain_mm: number;
  wettest_year: number;
};

export type Scenario = {
  key: string;
  name: string;
  description: string;
  rain_percentile: number;
  temp_anomaly_c: number;
  demand_growth_pct: number;
};

export type SimSeries = {
  served_pct: number[];
  aquifer_pct: number[];
  reservoir_pct: number[];
  demand_ml: number[];
  municipal_ml: number[];
  harvest_ml: number[];
  groundwater_ml: number[];
  tank_ml: number[];
};

export type SimResult = {
  months: number;
  failure_month: number | null;
  stress_month: number | null;
  resilience_months: number;
  survived: boolean;
  people_affected: number;
  aquifer_end_pct: number;
  aquifer_min_pct: number;
  reservoir_min_pct: number;
  mean_served_pct: number;
  min_served_pct: number;
  total_unmet_l: number;
  total_harvest_l: number;
  series: SimSeries;
};

export type Measure = {
  key: string;
  name: string;
  description: string;
  cost: number;
  months_to_deploy: number;
  effects: Record<string, number>;
};

export type PlanDto = {
  building_ids: number[];
  n_buildings: number;
  roof_area_m2: number;
  rwh_cost: number;
  measures: Measure[];
  total_cost: number;
  currency: string;
};

export type Bottleneck = {
  primary: string;
  secondary: string;
  pressures: Record<string, number>;
  aquifer_min_pct: number;
};

export type Optimization = {
  budget: number;
  candidates_evaluated: number;
  baseline: { plan: PlanDto; result: SimResult };
  greedy: { plan: PlanDto; result: SimResult };
  optimal: { plan: PlanDto; result: SimResult };
  improvement: {
    months_vs_baseline: number;
    months_vs_greedy: number;
    budget_used_pct: number;
    greedy_budget_used_pct: number;
  };
};

export type Brief = {
  headline: string;
  situation: string;
  recommendation: string[];
  reasoning: string;
  tradeoffs: string;
  source: string;
  fallback_reason?: string;
};

export type RegionResponse = {
  region: RegionSummary;
  climate: Climate;
  buildings: GeoJSON.FeatureCollection;
  bounds: {
    rain_percentile: [number, number];
    temp_anomaly_c: [number, number];
    demand_growth_pct: [number, number];
    driest_observed_mm: number;
    median_observed_mm: number;
  };
  scenarios: Scenario[];
};

export type OptimizeResponse = {
  region: RegionSummary;
  scenario: Scenario;
  optimization: Optimization;
  bottleneck: Bottleneck;
  selected_buildings: number[];
  brief: Brief | null;
};

export type AdversarialResponse = {
  scenario: Scenario;
  bounds: RegionResponse["bounds"];
  scenarios_searched: number;
  result: SimResult;
  bottleneck: Bottleneck;
  survival_plan?: Optimization;
};

async function post<T>(path: string, body: unknown): Promise<T> {
  const r = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) {
    const detail = await r.json().catch(() => ({}));
    throw new Error(detail.detail || `${r.status} ${r.statusText}`);
  }
  return r.json();
}

export type AreaSpec = {
  lat: number;
  lon: number;
  radius_m: number;
  label?: string;
  population?: number | null;
};
export type ScenarioSpec = {
  key?: string;
  rain_percentile?: number;
  temp_anomaly_c?: number;
  demand_growth_pct?: number;
};

export const api = {
  search: async (q: string): Promise<Place[]> => {
    const r = await fetch(`/api/search?q=${encodeURIComponent(q)}`);
    if (!r.ok) throw new Error("Search failed");
    return (await r.json()).results;
  },
  region: (a: AreaSpec) => post<RegionResponse>("/api/region", a),
  simulate: (a: AreaSpec, scenario: ScenarioSpec, months = 60) =>
    post<{ scenario: Scenario; result: SimResult; bottleneck: Bottleneck }>(
      "/api/simulate",
      { ...a, scenario, months },
    ),
  optimize: (a: AreaSpec, scenario: ScenarioSpec, budget: number, months = 60) =>
    post<OptimizeResponse>("/api/optimize", { ...a, scenario, budget, months }),
  adversarial: (a: AreaSpec, budget?: number, months = 60) =>
    post<AdversarialResponse>("/api/adversarial", { ...a, budget, months }),
  assumptions: async () => (await fetch("/api/assumptions")).json(),
};

// --- formatting helpers ----------------------------------------------------

export function rupees(v: number): string {
  if (v >= 1e7) return `₹${(v / 1e7).toFixed(2)} cr`;
  // Spelled out: "L" next to volumes on a water app reads as litres.
  if (v >= 1e5) return `₹${(v / 1e5).toFixed(2)} lakh`;
  return `₹${Math.round(v).toLocaleString("en-IN")}`;
}

export function litres(v: number): string {
  if (v >= 1e9) return `${(v / 1e9).toFixed(2)} GL`;
  if (v >= 1e6) return `${(v / 1e6).toFixed(0)} ML`;
  if (v >= 1e3) return `${(v / 1e3).toFixed(0)} kL`;
  return `${Math.round(v)} L`;
}

export function months(m: number, survived: boolean, horizon: number): string {
  if (survived) return `> ${horizon} mo`;
  return `${m} mo`;
}
