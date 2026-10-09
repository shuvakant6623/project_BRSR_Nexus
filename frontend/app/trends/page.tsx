"use client";

import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useEffect, useState } from "react";

import { StyledSelect } from "@/components/StyledSelect";
import { api } from "@/lib/api";

interface TrendPoint {
  period_label: string;
  framework_version: string;
  value: number | null;
  unit: string | null;
  continuity: "direct" | "remapped" | "gap";
  note: string | null;
}
interface Trend {
  metric_code: string;
  label: string;
  unit: string | null;
  points: TrendPoint[];
}

const METRICS = [
  { code: "C-P6-TOTAL-ENERGY", label: "Total energy (MWh)" },
  { code: "C-P6-TOTAL-GHG", label: "Total GHG (tCO2e)" },
  { code: "C-P6-GHG-INTENSITY", label: "GHG intensity" },
  { code: "C-P6-ENERGY-INTENSITY", label: "Energy intensity" },
  { code: "C-P6-WATER-WITHDRAWAL", label: "Water withdrawal (kL)" },
  { code: "C-P3-ATTRITION", label: "Attrition %" },
  { code: "C-P8-CSR-SPEND", label: "CSR spend (INR crore)" },
  { code: "C-P3-LTIFR", label: "LTIFR" },
];

export default function TrendsPage() {
  const [metric, setMetric] = useState(METRICS[0].code);
  const [trend, setTrend] = useState<Trend | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setTrend(null);
    api<Trend>(`/api/v1/trends/${metric}`)
      .then(setTrend)
      .catch((e) => setError(e instanceof Error ? e.message : "Failed to load trend"));
  }, [metric]);

  const chartData = (trend?.points ?? []).map((p) => ({
    period: p.period_label,
    value: p.value ?? 0,
    gap: p.continuity === "gap",
  }));
  const hasGap = (trend?.points ?? []).some((p) => p.continuity === "gap");

  return (
    <main className="page">
      <h1 className="rise">Multi-year trends</h1>
      <p className="hint rise rise-d1">
        Cross-year comparisons follow <strong>metric lineage</strong> — years without a continuity
        mapping are shown as gaps, never silently compared against differently-defined metrics.
      </p>
      <div className="filter-row rise rise-d2" style={{ position: "relative", zIndex: 100 }}>
        <StyledSelect
          ariaLabel="Metric"
          value={metric}
          options={METRICS.map((m) => ({ value: m.code, label: m.label }))}
          onChange={setMetric}
        />
      </div>
      {error && <div className="state error">{error}</div>}
      {!trend && !error && <div className="skeleton" style={{ height: "20rem" }} />}
      {trend && (
        <div className="dash-card glass-card rise rise-d2" style={{ padding: "1.3rem" }}>
          <h3>{trend.label} — {trend.unit}</h3>
          <p className="sub">
            {hasGap
              ? "⚠ One or more years are a continuity GAP (no lineage mapping) — no line is drawn across them."
              : "Continuous mapping across periods via metric lineage."}
          </p>
          <div style={{ width: "100%", height: 320 }}>
            <ResponsiveContainer>
              <LineChart data={chartData} margin={{ left: 0, right: 20 }}>
                <CartesianGrid stroke="rgba(148,163,184,.12)" />
                <XAxis dataKey="period" tick={{ fill: "#8fa3bd", fontSize: 12 }} />
                <YAxis tick={{ fill: "#8fa3bd", fontSize: 11 }} />
                <Tooltip contentStyle={{ background: "#101b31", border: "1px solid rgba(94,118,153,.3)", borderRadius: 10, fontSize: 12 }} />
                <Line type="monotone" dataKey="value" stroke="#10b981" strokeWidth={3}
                  dot={{ r: 6, fill: "#10b981" }} connectNulls={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
          <table className="data-table" style={{ marginTop: "1rem" }}>
            <thead>
              <tr><th>Period</th><th>Framework</th><th>Value</th><th>Continuity</th></tr>
            </thead>
            <tbody>
              {trend.points.map((p) => (
                <tr key={p.period_label}>
                  <td>{p.period_label}</td>
                  <td className="mono">{p.framework_version}</td>
                  <td className="mono">
                    {p.value === null ? "—" : `${p.value.toLocaleString()} ${p.unit ?? ""}`}
                  </td>
                  <td>
                    <span className={`badge ${p.continuity === "gap" ? "error" : p.continuity === "remapped" ? "warn" : "ok"}`}>
                      {p.continuity.toUpperCase()}{p.note ? ` — ${p.note}` : ""}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </main>
  );
}
