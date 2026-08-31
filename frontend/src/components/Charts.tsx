import {
  Area,
  AreaChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { SimResult } from "../api";

const AXIS = { stroke: "#7c8ea6", fontSize: 10 };
const GRID = "#1e2a3a";

function tooltipStyle() {
  return {
    contentStyle: {
      background: "#0c1118",
      border: "1px solid #1e2a3a",
      borderRadius: 8,
      fontSize: 11,
    },
    labelStyle: { color: "#7c8ea6" },
  };
}

/** Water service over time, with the failure threshold drawn in. */
export function ServiceChart({
  baseline,
  planned,
  survivalPct = 45,
}: {
  baseline: SimResult;
  planned?: SimResult | null;
  survivalPct?: number;
}) {
  const data = baseline.series.served_pct.map((v, i) => ({
    month: i + 1,
    baseline: v,
    planned: planned?.series.served_pct[i],
  }));
  return (
    <ResponsiveContainer width="100%" height={190}>
      <AreaChart data={data} margin={{ top: 6, right: 8, left: -22, bottom: 0 }}>
        <defs>
          <linearGradient id="gBase" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#f43f5e" stopOpacity={0.45} />
            <stop offset="100%" stopColor="#f43f5e" stopOpacity={0.02} />
          </linearGradient>
          <linearGradient id="gPlan" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#2dd4bf" stopOpacity={0.4} />
            <stop offset="100%" stopColor="#2dd4bf" stopOpacity={0.02} />
          </linearGradient>
        </defs>
        <CartesianGrid stroke={GRID} strokeDasharray="2 4" vertical={false} />
        <XAxis dataKey="month" {...AXIS} tickLine={false} axisLine={false} />
        <YAxis domain={[0, 100]} {...AXIS} tickLine={false} axisLine={false} unit="%" />
        <Tooltip {...tooltipStyle()} formatter={(v) => `${v}%`} />
        <ReferenceLine
          y={survivalPct}
          stroke="#fbbf24"
          strokeDasharray="4 3"
          label={{ value: "survival threshold", fill: "#fbbf24", fontSize: 9, position: "insideTopRight" }}
        />
        {baseline.failure_month && (
          // Dashed, so it reads as an annotation rather than a data spike.
          <ReferenceLine
            x={baseline.failure_month}
            stroke="#f43f5e"
            strokeDasharray="3 3"
            strokeWidth={1}
            label={{
              value: `fails m${baseline.failure_month}`,
              fill: "#f43f5e",
              fontSize: 9,
              position: "insideBottomLeft",
            }}
          />
        )}
        <Area
          type="monotone"
          dataKey="baseline"
          name="No action"
          stroke="#f43f5e"
          strokeWidth={1.6}
          fill="url(#gBase)"
        />
        {planned && (
          <Area
            type="monotone"
            dataKey="planned"
            name="With plan"
            stroke="#2dd4bf"
            strokeWidth={1.8}
            fill="url(#gPlan)"
          />
        )}
        <Legend wrapperStyle={{ fontSize: 10, color: "#7c8ea6" }} />
      </AreaChart>
    </ResponsiveContainer>
  );
}

/** The two storages that actually drive failure. */
export function StorageChart({ result }: { result: SimResult }) {
  const data = result.series.aquifer_pct.map((v, i) => ({
    month: i + 1,
    aquifer: v,
    reservoir: result.series.reservoir_pct[i],
  }));
  return (
    <ResponsiveContainer width="100%" height={170}>
      <LineChart data={data} margin={{ top: 6, right: 8, left: -22, bottom: 0 }}>
        <CartesianGrid stroke={GRID} strokeDasharray="2 4" vertical={false} />
        <XAxis dataKey="month" {...AXIS} tickLine={false} axisLine={false} />
        <YAxis domain={[0, 100]} {...AXIS} tickLine={false} axisLine={false} unit="%" />
        <Tooltip {...tooltipStyle()} formatter={(v) => `${v}%`} />
        <Line
          type="monotone"
          dataKey="reservoir"
          name="Reservoir"
          stroke="#60a5fa"
          strokeWidth={1.7}
          dot={false}
        />
        <Line
          type="monotone"
          dataKey="aquifer"
          name="Aquifer"
          stroke="#a78bfa"
          strokeWidth={1.7}
          dot={false}
        />
        <Legend wrapperStyle={{ fontSize: 10, color: "#7c8ea6" }} />
      </LineChart>
    </ResponsiveContainer>
  );
}

/** The observed rainfall record the scenarios are drawn from. */
export function RainfallChart({
  years,
  annual,
  median,
}: {
  years: number[];
  annual: number[];
  median: number;
}) {
  const data = years.map((y, i) => ({ year: y, rain: annual[i] }));
  return (
    <ResponsiveContainer width="100%" height={130}>
      <AreaChart data={data} margin={{ top: 6, right: 8, left: -18, bottom: 0 }}>
        <defs>
          <linearGradient id="gRain" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#38bdf8" stopOpacity={0.5} />
            <stop offset="100%" stopColor="#38bdf8" stopOpacity={0.03} />
          </linearGradient>
        </defs>
        <CartesianGrid stroke={GRID} strokeDasharray="2 4" vertical={false} />
        <XAxis dataKey="year" {...AXIS} tickLine={false} axisLine={false} minTickGap={26} />
        <YAxis {...AXIS} tickLine={false} axisLine={false} width={40} />
        <Tooltip {...tooltipStyle()} formatter={(v) => `${v} mm`} />
        <ReferenceLine y={median} stroke="#7c8ea6" strokeDasharray="3 3" />
        <Area type="monotone" dataKey="rain" name="Annual rainfall" stroke="#38bdf8" fill="url(#gRain)" />
      </AreaChart>
    </ResponsiveContainer>
  );
}
