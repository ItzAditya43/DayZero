import type { Scenario } from "../api";

export function Slider({
  label,
  value,
  min,
  max,
  step = 1,
  suffix = "",
  hint,
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step?: number;
  suffix?: string;
  hint?: string;
  onChange: (v: number) => void;
}) {
  return (
    <div className="mb-3.5">
      <div className="flex items-baseline justify-between mb-1.5">
        <span className="label">{label}</span>
        <span className="mono text-[11px] text-teal-300">
          {value.toFixed(step < 1 ? 1 : 0)}
          {suffix}
        </span>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(parseFloat(e.target.value))}
      />
      {hint && <div className="mt-1 text-[10px] text-slate-500 leading-snug">{hint}</div>}
    </div>
  );
}

export function ScenarioPicker({
  scenarios,
  active,
  onPick,
}: {
  scenarios: Scenario[];
  active: string;
  onPick: (s: Scenario) => void;
}) {
  return (
    <div className="grid grid-cols-2 gap-1.5 mb-4">
      {scenarios.map((s) => (
        <button
          key={s.key}
          onClick={() => onPick(s)}
          title={s.description}
          className={`px-2 py-2 rounded-md text-[11px] text-left border transition ${
            active === s.key
              ? "border-teal-400/70 bg-teal-400/10 text-teal-200"
              : "border-slate-700/70 text-slate-400 hover:border-slate-500 hover:text-slate-200"
          }`}
        >
          <div className="font-medium">{s.name}</div>
          <div className="mono text-[9px] opacity-60 mt-0.5">
            P{s.rain_percentile} · +{s.temp_anomaly_c}°C
          </div>
        </button>
      ))}
    </div>
  );
}

export function Stat({
  label,
  value,
  sub,
  tone = "normal",
}: {
  label: string;
  value: string;
  sub?: string;
  tone?: "normal" | "alarm" | "good" | "warn";
}) {
  const color =
    tone === "alarm"
      ? "text-rose-400"
      : tone === "good"
        ? "text-teal-300"
        : tone === "warn"
          ? "text-amber-300"
          : "text-slate-100";
  return (
    <div>
      <div className="label mb-1">{label}</div>
      <div className={`mono text-lg leading-none ${color}`}>{value}</div>
      {sub && <div className="text-[10px] text-slate-500 mt-1">{sub}</div>}
    </div>
  );
}

export function Bar({ pct, tone = "water" }: { pct: number; tone?: "water" | "alarm" | "warn" }) {
  const bg = tone === "alarm" ? "bg-rose-500" : tone === "warn" ? "bg-amber-400" : "bg-teal-400";
  return (
    <div className="h-1.5 w-full rounded-full bg-slate-800 overflow-hidden">
      <div
        className={`h-full ${bg} transition-all duration-700`}
        style={{ width: `${Math.max(0, Math.min(100, pct))}%` }}
      />
    </div>
  );
}

export function Button({
  children,
  onClick,
  busy,
  variant = "primary",
  disabled,
}: {
  children: React.ReactNode;
  onClick: () => void;
  busy?: boolean;
  variant?: "primary" | "danger" | "ghost";
  disabled?: boolean;
}) {
  const base =
    "w-full px-3 py-2.5 rounded-md text-[11px] tracking-[0.14em] uppercase font-medium transition disabled:opacity-40 disabled:cursor-not-allowed";
  const styles =
    variant === "primary"
      ? "bg-teal-400 text-slate-950 hover:bg-teal-300"
      : variant === "danger"
        ? "border border-rose-500/60 text-rose-300 hover:bg-rose-500/10"
        : "border border-slate-700 text-slate-300 hover:border-slate-500";
  return (
    <button className={`${base} ${styles}`} onClick={onClick} disabled={busy || disabled}>
      {busy ? <span className="pulsing">Working…</span> : children}
    </button>
  );
}
