"use client";

import { useEffect, useMemo, useState } from "react";

import {
  FormulaMeta,
  FrameworkVersion,
  listFormulas,
  listMetrics,
  listRules,
  listVersions,
  MetricMeta,
  ValidationRuleMeta,
} from "@/features/framework/framework";

const SECTIONS = [
  { key: "A", label: "Section A — General Disclosures" },
  { key: "B", label: "Section B — Management & Process" },
  { key: "C", label: "Section C — Principle-wise Performance" },
];

const PRINCIPLES: Record<string, string> = {
  P1: "P1 Ethics & Transparency",
  P2: "P2 Sustainable Goods",
  P3: "P3 Employee Wellbeing",
  P4: "P4 Stakeholders",
  P5: "P5 Human Rights",
  P6: "P6 Environment",
  P7: "P7 Policy Advocacy",
  P8: "P8 Inclusive Growth",
  P9: "P9 Consumer Value",
};

export default function FrameworkPage() {
  const [versions, setVersions] = useState<FrameworkVersion[] | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [metrics, setMetrics] = useState<MetricMeta[]>([]);
  const [rules, setRules] = useState<ValidationRuleMeta[]>([]);
  const [formulas, setFormulas] = useState<FormulaMeta[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<"metrics" | "rules" | "formulas">("metrics");

  useEffect(() => {
    listVersions()
      .then((vs) => {
        setVersions(vs);
        const active = vs.find((v) => v.is_active) ?? vs[0];
        if (active) setSelected(active.id);
      })
      .catch((e) => setError(e instanceof Error ? e.message : "Failed to load framework versions"));
  }, []);

  useEffect(() => {
    if (!selected) return;
    setLoading(true);
    Promise.all([listMetrics(selected), listRules(selected), listFormulas(selected)])
      .then(([m, r, f]) => {
        setMetrics(m);
        setRules(r);
        setFormulas(f);
      })
      .catch((e) => setError(e instanceof Error ? e.message : "Failed to load framework"))
      .finally(() => setLoading(false));
  }, [selected]);

  const grouped = useMemo(() => {
    const out: Record<string, MetricMeta[]> = { A: [], B: [] };
    for (const m of metrics) {
      if (m.section === "C") {
        const key = m.principle ?? "C?";
        (out[key] ??= []).push(m);
      } else {
        out[m.section].push(m);
      }
    }
    for (const key of Object.keys(out)) {
      out[key].sort((a, b) => (a.display_order ?? 0) - (b.display_order ?? 0));
    }
    return out;
  }, [metrics]);

  const metricStats = useMemo(() => {
    const core = metrics.filter((m) => m.brsr_core).length;
    const required = metrics.filter((m) => m.required).length;
    const evidence = metrics.filter((m) => m.evidence_required).length;
    const numeric = metrics.filter((m) => m.data_type === "numeric").length;
    return { core, required, evidence, numeric, qualitative: metrics.length - numeric };
  }, [metrics]);

  const ruleStats = useMemo(() => {
    const blocking = rules.filter((r) => r.severity === "BLOCKING").length;
    const warning = rules.filter((r) => r.severity === "WARNING").length;
    const info = rules.filter((r) => r.severity === "INFO").length;
    return { blocking, warning, info };
  }, [rules]);

  if (error) return <main className="page"><div className="state error">Error: {error}</div></main>;
  if (!versions) return <main className="page"><div className="state">Loading framework…</div></main>;

  return (
    <main className="page">
      <h1 className="rise">BRSR Framework</h1>
      <p className="hint rise rise-d1">
        Forms, validation and consolidation are driven by this metadata — adding a metric here
        changes the product without a code change.
      </p>
      <div className="version-picker rise rise-d1">
        {versions.map((v) => (
          <button
            key={v.id}
            className={`pill ${selected === v.id ? "active" : ""}`}
            onClick={() => setSelected(v.id)}
          >
            {v.version_code} · {v.metric_count} metrics {v.is_active ? "· ✓ active" : ""}
          </button>
        ))}
      </div>

      <div className="tabs rise rise-d2">
        {(["metrics", "rules", "formulas"] as const).map((t) => (
          <button key={t} className={`tab ${tab === t ? "active" : ""}`} onClick={() => setTab(t)}>
            {t === "metrics" ? `Metrics (${metrics.length})` : t === "rules" ? `Validation Rules (${rules.length})` : `Formulas (${formulas.length})`}
          </button>
        ))}
      </div>

      {loading && <div className="state">Loading…</div>}

      {!loading && tab === "metrics" && (
        <>
          <div className="stat-row rise rise-d2">
            <div className="stat-card">
              <div className="stat-value">{metrics.length}</div>
              <div className="stat-label">Total Metrics</div>
            </div>
            <div className="stat-card">
              <div className="stat-value">{metricStats.core}</div>
              <div className="stat-label">BRSR Core</div>
            </div>
            <div className="stat-card">
              <div className="stat-value">{metricStats.required}</div>
              <div className="stat-label">Required</div>
            </div>
            <div className="stat-card">
              <div className="stat-value">{metricStats.evidence}</div>
              <div className="stat-label">Evidence Needed</div>
            </div>
            <div className="stat-card">
              <div className="stat-value">{metricStats.numeric}</div>
              <div className="stat-label">Numeric</div>
            </div>
            <div className="stat-card">
              <div className="stat-value">{metricStats.qualitative}</div>
              <div className="stat-label">Qualitative</div>
            </div>
          </div>
          {SECTIONS.map((s) =>
            grouped[s.key]?.length ? (
              <MetricTable key={s.key} title={s.label} metrics={grouped[s.key]} />
            ) : null
          )}
          {Object.keys(PRINCIPLES).map((p) =>
            grouped[p]?.length ? (
              <MetricTable key={p} title={PRINCIPLES[p]} metrics={grouped[p]} />
            ) : null
          )}
        </>
      )}

      {!loading && tab === "rules" && (
        <>
          <div className="stat-row rise rise-d2">
            <div className="stat-card">
              <div className="stat-value">{rules.length}</div>
              <div className="stat-label">Total Rules</div>
            </div>
            <div className="stat-card">
              <div className="stat-value" style={{ color: "#f87171" }}>{ruleStats.blocking}</div>
              <div className="stat-label">Blocking</div>
            </div>
            <div className="stat-card">
              <div className="stat-value" style={{ color: "#fbbf24" }}>{ruleStats.warning}</div>
              <div className="stat-label">Warnings</div>
            </div>
            <div className="stat-card">
              <div className="stat-value" style={{ color: "#38bdf8" }}>{ruleStats.info}</div>
              <div className="stat-label">Info</div>
            </div>
          </div>
          <div className="table-wrap rise rise-d2">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Code</th><th>Class</th><th>Target</th><th>Severity</th><th>Applies on</th><th>Message</th>
                </tr>
              </thead>
              <tbody>
                {rules.map((r) => (
                  <tr key={r.rule_code}>
                    <td className="mono">{r.rule_code}</td>
                    <td>{r.rule_class}</td>
                    <td className="mono">{r.target_metric_code ?? "—"}</td>
                    <td><span className={`sev ${r.severity.toLowerCase()}`}>{r.severity}</span></td>
                    <td>{r.applies_on}</td>
                    <td>{r.message_template}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      {!loading && tab === "formulas" && (
        <>
          <div className="stat-row rise rise-d2">
            <div className="stat-card">
              <div className="stat-value">{formulas.length}</div>
              <div className="stat-label">Formula Definitions</div>
            </div>
            <div className="stat-card">
              <div className="stat-value">{formulas.reduce((acc, f) => acc + f.versions.length, 0)}</div>
              <div className="stat-label">Total Versions</div>
            </div>
          </div>
          <div className="table-wrap rise rise-d2">
            <table className="data-table">
              <thead>
                <tr><th>Code</th><th>Name</th><th>Version</th><th>Expression</th><th>Constants</th></tr>
              </thead>
              <tbody>
                {formulas.map((f) =>
                  f.versions.map((fv) => (
                    <tr key={`${f.code}-${fv.version}`}>
                      <td className="mono">{f.code}</td>
                      <td>{f.name}</td>
                      <td>v{fv.version}</td>
                      <td className="mono">{fv.expression}</td>
                      <td className="mono">{JSON.stringify(fv.constants)}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </>
      )}
    </main>
  );
}

function MetricTable({ title, metrics }: { title: string; metrics: MetricMeta[] }) {
  const [collapsed, setCollapsed] = useState(false);
  return (
    <section className="section-card rise rise-d2">
      <h2
        onClick={() => setCollapsed(!collapsed)}
        style={{ cursor: "pointer", display: "flex", alignItems: "center", gap: "0.6rem" }}
      >
        <span style={{ color: "var(--muted)", fontSize: "0.78rem", transition: "transform 0.2s", transform: collapsed ? "rotate(-90deg)" : "rotate(0)" }}>▾</span>
        {title}
        <span style={{ fontSize: "0.78rem", color: "var(--muted)", fontWeight: 400 }}>
          ({metrics.length} metric{metrics.length !== 1 ? "s" : ""})
        </span>
      </h2>
      {!collapsed && (
        <table className="data-table">
          <thead>
            <tr>
              <th>Code</th><th>Label</th><th>Type</th><th>Unit</th><th>Aggregation</th><th>Flags</th>
            </tr>
          </thead>
          <tbody>
            {metrics.map((m) => (
              <tr key={m.metric_code}>
                <td className="mono">{m.metric_code}</td>
                <td>{m.label}</td>
                <td>{m.data_type}</td>
                <td>{m.canonical_unit ?? "—"}</td>
                <td>{m.aggregation_semantics === "RATIO_RECALCULATION"
                  ? `Σ${m.ratio_numerator_code} / Σ${m.ratio_denominator_code}`
                  : m.aggregation_semantics}</td>
                <td>
                  {m.brsr_core && <span className="badge core">Core</span>}{" "}
                  {m.evidence_required && <span className="badge evidence">Evidence</span>}{" "}
                  {m.required && <span className="badge required">Required</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
