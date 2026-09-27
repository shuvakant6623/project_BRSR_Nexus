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

  if (error) return <main className="page"><div className="state error">Error: {error}</div></main>;
  if (!versions) return <main className="page"><div className="state">Loading framework…</div></main>;

  return (
    <main className="page">
      <h1>BRSR Framework</h1>
      <p className="hint">
        Forms, validation and consolidation are driven by this metadata — adding a metric here
        changes the product without a code change.
      </p>
      <div className="version-picker">
        {versions.map((v) => (
          <button
            key={v.id}
            className={`pill ${selected === v.id ? "active" : ""}`}
            onClick={() => setSelected(v.id)}
          >
            {v.version_code} · {v.metric_count} metrics {v.is_active ? "· active" : ""}
          </button>
        ))}
      </div>

      <div className="tabs">
        {(["metrics", "rules", "formulas"] as const).map((t) => (
          <button key={t} className={`tab ${tab === t ? "active" : ""}`} onClick={() => setTab(t)}>
            {t === "metrics" ? `Metrics (${metrics.length})` : t === "rules" ? `Validation Rules (${rules.length})` : `Formulas (${formulas.length})`}
          </button>
        ))}
      </div>

      {loading && <div className="state">Loading…</div>}

      {!loading && tab === "metrics" && (
        <>
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
        <table className="data-table">
          <thead>
            <tr>
              <th>Code</th><th>Class</th><th>Target</th><th>Severity</th><th>Applies on</th><th>Message</th>
            </tr>
          </thead>
          <tbody>
            {rules.map((r) => (
              <tr key={r.rule_code}>
                <td>{r.rule_code}</td>
                <td>{r.rule_class}</td>
                <td>{r.target_metric_code ?? "—"}</td>
                <td><span className={`sev ${r.severity.toLowerCase()}`}>{r.severity}</span></td>
                <td>{r.applies_on}</td>
                <td>{r.message_template}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {!loading && tab === "formulas" && (
        <table className="data-table">
          <thead>
            <tr><th>Code</th><th>Name</th><th>Version</th><th>Expression</th><th>Constants</th></tr>
          </thead>
          <tbody>
            {formulas.map((f) =>
              f.versions.map((fv) => (
                <tr key={`${f.code}-${fv.version}`}>
                  <td>{f.code}</td>
                  <td>{f.name}</td>
                  <td>v{fv.version}</td>
                  <td className="mono">{fv.expression}</td>
                  <td className="mono">{JSON.stringify(fv.constants)}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      )}
    </main>
  );
}

function MetricTable({ title, metrics }: { title: string; metrics: MetricMeta[] }) {
  return (
    <section className="metric-group">
      <h2>{title}</h2>
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
    </section>
  );
}
