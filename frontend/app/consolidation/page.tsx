"use client";

import { useEffect, useState } from "react";

import { useAuth } from "@/components/AuthProvider";
import { api } from "@/lib/api";
import { EntityNode, listEntities } from "@/features/entities/entities";
import {
  getTrace,
  recomputeConsolidation,
  RecomputeResult,
  TraceOut,
} from "@/features/consolidation/consolidation";

const METRICS = [
  { code: "C-P6-TOTAL-ENERGY", label: "Total Energy (MWh)" },
  { code: "C-P6-TOTAL-GHG", label: "Total GHG (tCO2e)" },
  { code: "C-P6-GHG-INTENSITY", label: "GHG Intensity (tCO2e/crore)" },
  { code: "C-P6-ENERGY-INTENSITY", label: "Energy Intensity (MWh/crore)" },
  { code: "C-P6-WATER-INTENSITY", label: "Water Intensity (kL/crore)" },
  { code: "C-P6-WASTE-RECYCLED-PCT", label: "Waste Recycled %" },
  { code: "C-P3-ATTRITION", label: "Attrition %" },
  { code: "A-REVENUE", label: "Revenue (INR crore)" },
];

export default function ConsolidationPage() {
  const { user } = useAuth();
  const [entities, setEntities] = useState<EntityNode[]>([]);
  const [periods, setPeriods] = useState<{ id: string; label: string }[]>([]);
  const [entityId, setEntityId] = useState<string>("");
  const [metricCode, setMetricCode] = useState(METRICS[0].code);
  const [periodId, setPeriodId] = useState<string>("");
  const [trace, setTrace] = useState<TraceOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    listEntities().then(setEntities).catch(() => undefined);
    api<{ id: string; label: string }[]>("/api/v1/reporting-periods")
      .then(setPeriods)
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    if (periods.length && !periodId) {
      const fy25 = periods.find((p) => p.label === "FY2025-26") ?? periods[0];
      setPeriodId(fy25.id);
    }
  }, [periods, periodId]);

  async function load() {
    if (!entityId || !metricCode || !periodId) return;
    setTrace(null);
    setError(null);
    try {
      setTrace(await getTrace(entityId, metricCode, periodId));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load consolidation trace");
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [entityId, metricCode, periodId]);

  async function onRecompute() {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const result: RecomputeResult = await recomputeConsolidation(periodId, metricCode);
      setNotice(
        `Consolidated ${result.consolidated} entity/metric pairs` +
          (result.failures.length ? ` — ${result.failures.length} reported failures (e.g. zero denominators / missing approvals)` : "")
      );
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Recompute failed");
    } finally {
      setBusy(false);
    }
  }

  const canRecompute = user?.role === "ADMIN" || user?.role === "ESG_MANAGER";

  return (
    <main className="page">
      <h1>Consolidation</h1>
      <p className="hint">
        Group ratios are computed as Σnumerator / Σdenominator across the hierarchy — child
        percentages are never averaged.
      </p>
      <div className="filter-row">
        <select value={periodId} onChange={(e) => setPeriodId(e.target.value)}>
          {periods.map((p) => (
            <option key={p.id} value={p.id}>{p.label}</option>
          ))}
        </select>
        <select value={metricCode} onChange={(e) => setMetricCode(e.target.value)}>
          {METRICS.map((m) => (
            <option key={m.code} value={m.code}>{m.label}</option>
          ))}
        </select>
        <select value={entityId} onChange={(e) => setEntityId(e.target.value)}>
          <option value="">— select entity —</option>
          {entities.map((e) => (
            <option key={e.id} value={e.id}>{e.name}</option>
          ))}
        </select>
        {canRecompute && (
          <button className="primarybtn" disabled={busy || !periodId} onClick={onRecompute}>
            {busy ? "Recomputing…" : "Recompute"}
          </button>
        )}
      </div>

      {error && <div className="auth-error">{error}</div>}
      {notice && <div className="form-success">{notice}</div>}

      {trace && (
        <div className="metric-form">
          <div className="metric-form-header">
            <h2>
              {trace.entity_name} · {trace.metric_code} · {trace.period_label}
            </h2>
            {trace.is_stale && <span className="badge error">STALE — recomputation required</span>}
          </div>
          <div className="kpi-row">
            <div className="kpi">
              <div className="kpi-value">
                {trace.computed_value?.toLocaleString(undefined, { maximumFractionDigits: 4 })}
                <span className="kpi-unit"> {trace.unit}</span>
              </div>
              <div className="kpi-label">{trace.aggregation_semantics}</div>
            </div>
            <div className="kpi">
              <div className="kpi-value">{trace.contributing_value_count}</div>
              <div className="kpi-label">contributing values</div>
            </div>
          </div>
          {trace.contributions.length > 0 && (
            <table className="data-table">
              <thead>
                <tr><th>Contributing entity</th><th>Value</th><th>Unit</th><th>Component</th></tr>
              </thead>
              <tbody>
                {trace.contributions.map((c, i) => (
                  <tr key={i}>
                    <td>{c.entity_name}</td>
                    <td className="mono">{c.value.toLocaleString()}</td>
                    <td>{c.unit}</td>
                    <td>{c.component ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </main>
  );
}
