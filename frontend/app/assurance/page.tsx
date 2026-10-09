"use client";

import { useEffect, useState } from "react";

import { StyledSelect } from "@/components/StyledSelect";
import { api } from "@/lib/api";
import {
  AssuranceReadiness,
  exportAssuranceReadinessCsv,
  getAssuranceReadiness,
} from "@/features/assurance/assurance";

export default function AssurancePage() {
  const [periods, setPeriods] = useState<{ id: string; label: string }[]>([]);
  const [periodId, setPeriodId] = useState<string>("");
  const [brsrCoreOnly, setBrsrCoreOnly] = useState<boolean>(false);
  const [readiness, setReadiness] = useState<AssuranceReadiness | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [exporting, setExporting] = useState<boolean>(false);

  useEffect(() => {
    api<{ id: string; label: string }[]>("/api/v1/reporting-periods")
      .then((res) => {
        setPeriods(res);
        if (res.length > 0) {
          const fy25 = res.find((p) => p.label === "FY2025-26") ?? res[0];
          setPeriodId(fy25.id);
        }
      })
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    if (!periodId) return;
    setLoading(true);
    setError(null);
    getAssuranceReadiness(periodId, brsrCoreOnly)
      .then(setReadiness)
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load assurance readiness"))
      .finally(() => setLoading(false));
  }, [periodId, brsrCoreOnly]);

  async function handleExport() {
    if (!periodId) return;
    setExporting(true);
    try {
      await exportAssuranceReadinessCsv(periodId, brsrCoreOnly);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Export failed");
    } finally {
      setExporting(false);
    }
  }

  return (
    <main className="page">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", flexWrap: "wrap", gap: "1rem" }}>
        <div>
          <h1 className="rise">Assurance Readiness</h1>
          <p className="hint rise rise-d1">
            Independent assessment of disclosure completion, evidence backing, validation exceptions,
            and consolidation integrity for BRSR Core and Comprehensive disclosures.
          </p>
        </div>
        <button
          className="ghostbtn"
          onClick={handleExport}
          disabled={exporting || loading || !readiness}
          style={{ alignSelf: "center" }}
        >
          {exporting ? "Exporting…" : "Export Readiness CSV"}
        </button>
      </div>

      <div className="filter-row rise rise-d2" style={{ marginTop: "1rem", display: "flex", alignItems: "center", gap: "1rem", flexWrap: "wrap" }}>
        <StyledSelect
          ariaLabel="Reporting period"
          value={periodId}
          options={periods.map((p) => ({ value: p.id, label: p.label }))}
          onChange={setPeriodId}
          placeholder="Reporting period"
        />

        <label style={{ display: "inline-flex", alignItems: "center", gap: "0.5rem", cursor: "pointer", fontSize: "0.9rem" }}>
          <input
            type="checkbox"
            checked={brsrCoreOnly}
            onChange={(e) => setBrsrCoreOnly(e.target.checked)}
          />
          <strong>BRSR Core Only</strong> (Mandatory Assurance Indicators)
        </label>
      </div>

      {error && <div className="auth-error" style={{ margin: "1rem 0" }}>{error}</div>}

      {loading && <p className="hint" style={{ margin: "2rem 0" }}>Evaluating assurance readiness…</p>}

      {!loading && readiness && (
        <div className="rise rise-d3" style={{ marginTop: "1.5rem" }}>
          {/* Provisional Banner */}
          {!readiness.is_locked && (
            <div
              className="glass-card"
              style={{
                padding: "0.85rem 1.25rem",
                marginBottom: "1.5rem",
                borderLeft: "4px solid var(--accent-warn, #f59e0b)",
                background: "rgba(245, 158, 11, 0.08)",
              }}
            >
              <div style={{ fontWeight: 600, color: "var(--accent-warn, #f59e0b)", marginBottom: "0.25rem" }}>
                ⚠ Provisional Readiness State
              </div>
              <div style={{ fontSize: "0.85rem", opacity: 0.9 }}>
                Reporting period <strong>{readiness.period_label}</strong> is currently unlocked.
                Readiness scores and gap analyses are provisional and subject to live data modifications until locked by ESG Management.
              </div>
            </div>
          )}

          {/* Overview Cards */}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: "1rem", marginBottom: "1.5rem" }}>
            <div className="glass-card" style={{ padding: "1.2rem" }}>
              <div style={{ fontSize: "0.8rem", textTransform: "uppercase", letterSpacing: "0.05em", opacity: 0.7 }}>
                Readiness Status
              </div>
              <div style={{ margin: "0.6rem 0", display: "flex", alignItems: "baseline", gap: "0.75rem" }}>
                <span
                  className={`badge ${
                    readiness.readiness_status === "READY"
                      ? "ok"
                      : readiness.readiness_status === "PROVISIONAL"
                      ? "warn"
                      : "error"
                  }`}
                  style={{ fontSize: "1rem", padding: "0.3rem 0.75rem" }}
                >
                  {readiness.readiness_status}
                </span>
                <span style={{ fontSize: "1.5rem", fontWeight: 700 }}>
                  {readiness.readiness_score_pct}%
                </span>
              </div>
              <div style={{ fontSize: "0.75rem", opacity: 0.8 }}>{readiness.score_explanation}</div>
            </div>

            <div className="glass-card" style={{ padding: "1.2rem" }}>
              <div style={{ fontSize: "0.8rem", textTransform: "uppercase", letterSpacing: "0.05em", opacity: 0.7 }}>
                Indicators Ready
              </div>
              <div style={{ fontSize: "1.8rem", fontWeight: 700, margin: "0.5rem 0" }}>
                {readiness.ready_indicators} <span style={{ fontSize: "1rem", fontWeight: 400, opacity: 0.6 }}>/ {readiness.total_indicators}</span>
              </div>
              <div style={{ fontSize: "0.75rem", opacity: 0.8 }}>
                {readiness.approved_indicators} indicators fully approved
              </div>
            </div>

            <div className="glass-card" style={{ padding: "1.2rem" }}>
              <div style={{ fontSize: "0.8rem", textTransform: "uppercase", letterSpacing: "0.05em", opacity: 0.7 }}>
                Assurance Blockers
              </div>
              <div style={{ fontSize: "1.8rem", fontWeight: 700, margin: "0.5rem 0", color: readiness.missing_evidence_count > 0 || readiness.blocking_exception_count > 0 ? "var(--accent-warn, #f59e0b)" : "inherit" }}>
                {readiness.missing_evidence_count + readiness.blocking_exception_count}
              </div>
              <div style={{ fontSize: "0.75rem", opacity: 0.8 }}>
                {readiness.missing_evidence_count} missing evidence • {readiness.blocking_exception_count} blocking exceptions
              </div>
            </div>

            <div className="glass-card" style={{ padding: "1.2rem" }}>
              <div style={{ fontSize: "0.8rem", textTransform: "uppercase", letterSpacing: "0.05em", opacity: 0.7 }}>
                Consolidation Integrity
              </div>
              <div style={{ fontSize: "1.8rem", fontWeight: 700, margin: "0.5rem 0", color: readiness.incomplete_consolidation_count > 0 ? "var(--accent-warn, #f59e0b)" : "inherit" }}>
                {readiness.incomplete_consolidation_count === 0 ? "100%" : `${readiness.incomplete_consolidation_count} Incomplete`}
              </div>
              <div style={{ fontSize: "0.75rem", opacity: 0.8 }}>
                {readiness.incomplete_consolidation_count === 0 ? "All group & child nodes consolidated" : "Unconsolidated ancestor metrics"}
              </div>
            </div>
          </div>

          {/* Entity Readiness Breakdown */}
          {readiness.entity_summaries.length > 0 && (
            <div className="glass-card" style={{ padding: "1.25rem", marginBottom: "1.5rem" }}>
              <h3 style={{ margin: "0 0 1rem 0", fontSize: "1.1rem" }}>Entity Assurance Readiness</h3>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))", gap: "1rem" }}>
                {readiness.entity_summaries.map((es) => (
                  <div
                    key={es.entity_id}
                    style={{
                      padding: "0.9rem",
                      borderRadius: "6px",
                      background: "rgba(255, 255, 255, 0.04)",
                      border: "1px solid rgba(255, 255, 255, 0.08)",
                    }}
                  >
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.5rem" }}>
                      <strong>{es.entity_name}</strong>
                      <span className={`badge ${es.is_ready ? "ok" : "warn"}`} style={{ fontSize: "0.75rem" }}>
                        {es.is_ready ? "READY" : "INCOMPLETE"}
                      </span>
                    </div>
                    <div style={{ fontSize: "0.8rem", opacity: 0.8 }}>
                      Approved: {es.approved_indicators} / {es.total_indicators}
                    </div>
                    {(!es.is_ready) && (
                      <div style={{ fontSize: "0.75rem", color: "var(--accent-warn, #f59e0b)", marginTop: "0.4rem" }}>
                        {es.has_missing_evidence && "• Evidence missing "}
                        {es.has_blocking_exceptions && "• Unresolved exceptions"}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Indicators Detailed Table */}
          <div className="glass-card" style={{ padding: "1.25rem" }}>
            <h3 style={{ margin: "0 0 1rem 0", fontSize: "1.1rem" }}>
              Disclosure Checklist ({readiness.indicators.length} {brsrCoreOnly ? "BRSR Core" : "Total"} Indicators)
            </h3>
            <div style={{ overflowX: "auto" }}>
              <table className="table" style={{ width: "100%", fontSize: "0.85rem" }}>
                <thead>
                  <tr>
                    <th>Metric</th>
                    <th>Label</th>
                    <th>Section / Principle</th>
                    <th>Approval</th>
                    <th>Evidence</th>
                    <th>Consolidated</th>
                    <th>Status</th>
                    <th>Defects / Gaps</th>
                  </tr>
                </thead>
                <tbody>
                  {readiness.indicators.map((ind) => (
                    <tr key={ind.metric_code}>
                      <td>
                        <code>{ind.metric_code}</code>
                        {ind.brsr_core && (
                          <span className="badge ok" style={{ marginLeft: "0.4rem", fontSize: "0.65rem" }}>
                            CORE
                          </span>
                        )}
                      </td>
                      <td>{ind.label}</td>
                      <td>
                        Sec {ind.section} {ind.principle ? `• ${ind.principle}` : ""}
                      </td>
                      <td>
                        <span className={`badge ${ind.is_approved ? "ok" : "pending"}`}>
                          {ind.is_approved ? "Approved" : "Pending"}
                        </span>
                      </td>
                      <td>
                        <span className={`badge ${ind.has_evidence ? "ok" : "warn"}`}>
                          {ind.has_evidence ? "Attached" : "Missing"}
                        </span>
                      </td>
                      <td>
                        <span className={`badge ${ind.is_consolidated ? "ok" : "warn"}`}>
                          {ind.is_consolidated ? "Yes" : "Pending"}
                        </span>
                      </td>
                      <td>
                        <span className={`badge ${ind.is_ready ? "ok" : "error"}`}>
                          {ind.is_ready ? "READY" : "NOT READY"}
                        </span>
                      </td>
                      <td>
                        {ind.defects.length === 0 ? (
                          <span style={{ color: "var(--accent-ok, #10b981)", fontSize: "0.8rem" }}>✓ Complete</span>
                        ) : (
                          <ul style={{ margin: 0, paddingLeft: "1.1rem", color: "var(--accent-warn, #f59e0b)", fontSize: "0.75rem" }}>
                            {ind.defects.map((d, i) => (
                              <li key={i}>{d}</li>
                            ))}
                          </ul>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}
    </main>
  );
}
