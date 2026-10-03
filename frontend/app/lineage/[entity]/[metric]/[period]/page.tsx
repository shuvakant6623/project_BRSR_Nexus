"use client";

import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { api } from "@/lib/api";

interface EvidenceNode {
  id: string; filename: string; mime_type: string; size_bytes: number;
  sha256: string; uploaded_by: string; uploaded_at: string;
}
interface AuditNode { action: string; actor: string; at: string; reason: string | null; }
interface ChainNode {
  entity_name: string; entity_type: string; value_id: string; version: number;
  raw_value: number | null; raw_unit: string | null;
  normalized_value: number | null; normalized_unit: string | null;
  is_calculated: boolean; status: string; uploader: string | null;
  submitted_at: string | null; approved_at: string | null;
  evidence: EvidenceNode[]; audit: AuditNode[];
}
interface Lineage {
  entity_name: string; metric_code: string; metric_label: string; unit: string | null;
  period_label: string; kind: string; value: number | null;
  aggregation_semantics: string | null; is_stale: boolean; stale_reason: string | null;
  formula: {
    code: string; name: string; version: number; expression: string;
    input_metric_codes: string[]; constants: Record<string, number>;
    resolved_inputs: Record<string, string>;
  } | null;
  chain: ChainNode[]; audit_count: number;
}

const TYPE_COLORS: Record<string, string> = {
  GROUP: "#10b981", SUBSIDIARY: "#38bdf8", BUSINESS_UNIT: "#a78bfa",
  PLANT: "#f59e0b", PROJECT: "#f472b6", DEPARTMENT: "#94a3b8",
};

export default function LineagePage() {
  const params = useParams<{ entity: string; metric: string; period: string }>();
  const [data, setData] = useState<Lineage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);

  useEffect(() => {
    api<Lineage>(
      `/api/v1/lineage/${params.entity}/${params.metric}/${params.period}`
    )
      .then((d) => {
        setData(d);
        if (d.chain.length) setExpanded(d.chain[0].value_id);
      })
      .catch((e) => setError(e instanceof Error ? e.message : "Failed to load lineage"));
  }, [params]);

  if (error)
    return (
      <main className="page">
        <div className="state error">{error}</div>
        <p className="hint" style={{ marginTop: ".8rem" }}>
          Run consolidation first (Consolidation screen → Recompute), then revisit.
        </p>
      </main>
    );
  if (!data)
    return <main className="page"><div className="state">Tracing lineage…</div></main>;

  return (
    <main className="page">
      <a className="linkbtn" href="/consolidation">← Back to consolidation</a>
      <div className="detail-header rise" style={{ marginTop: ".8rem" }}>
        <h1>Where did this number come from?</h1>
        {data.is_stale && <span className="badge error">STALE — recomputation required</span>}
      </div>
      <p className="hint rise rise-d1">
        {data.entity_name} · {data.metric_label} · {data.period_label}
      </p>

      {/* result node */}
      <div className="glass-card rise rise-d2" style={{ padding: "1.3rem 1.5rem", margin: "1.1rem 0" }}>
        <div style={{ display: "flex", alignItems: "baseline", gap: "1rem", flexWrap: "wrap" }}>
          <span style={{ fontSize: "2.1rem", fontWeight: 800, letterSpacing: "-.03em" }}>
            {data.value?.toLocaleString()}
            <span className="kpi-unit"> {data.unit}</span>
          </span>
          <span className="badge core">{data.kind === "consolidated" ? "CONSOLIDATED" : "REPORTED VALUE"}</span>
          {data.aggregation_semantics === "RATIO_RECALCULATION" && (
            <span className="badge ok">Σnum / Σden recomputed</span>
          )}
        </div>
        <p className="hint" style={{ margin: ".5rem 0 0", fontSize: ".82rem" }}>
          Assembled from {data.chain.length} governed value
          {data.chain.length === 1 ? "" : "s"} · {data.audit_count} audit events · uploader,
          evidence, review and approval verifiable below.
        </p>
      </div>

      {data.formula && (
        <div className="glass-card rise rise-d2" style={{ padding: "1.1rem 1.4rem", margin: "0 0 1.1rem" }}>
          <h3 style={{ margin: "0 0 .3rem", fontSize: ".95rem" }}>
            Formula <span className="mono">{data.formula.code}</span> v{data.formula.version}
          </h3>
          <div className="mono" style={{ color: "var(--sky)", fontSize: ".84rem" }}>
            {data.formula.expression}
          </div>
          <div className="hint" style={{ fontSize: ".78rem", marginTop: ".45rem" }}>
            Resolved inputs:{" "}
            {Object.entries(data.formula.resolved_inputs).map(([k, v]) => (
              <span key={k} className="mono" style={{ marginRight: ".8rem" }}>
                {k} = {v}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* contributor chain */}
      <div className="lineage-chain">
        {data.chain.map((n, i) => {
          const open = expanded === n.value_id;
          return (
            <div key={n.value_id} className="rise" style={{ animationDelay: `${i * 0.05}s` }}>
              {i > 0 && <div className="lineage-connector" />}
              <div className="glass-card lineage-node" onClick={() => setExpanded(open ? null : n.value_id)}>
                <div className="lineage-node-head">
                  <span className="entity-dot" style={{ background: TYPE_COLORS[n.entity_type] ?? "#94a3b8" }} />
                  <strong>{n.entity_name}</strong>
                  <span className="mono" style={{ color: "var(--muted)" }}>
                    v{n.version} · {n.normalized_value?.toLocaleString()} {n.normalized_unit}
                  </span>
                  {n.is_calculated && <span className="badge core">calculated</span>}
                  <span className="status-badge" style={{ marginLeft: "auto" }}>{n.status}</span>
                  <span className="lineage-caret">{open ? "▾" : "▸"}</span>
                </div>
                {open && (
                  <div className="lineage-detail">
                    <div className="lineage-grid">
                      <div>
                        <div className="kpi-label">Raw entry</div>
                        <div className="mono">
                          {n.raw_value?.toLocaleString() ?? "—"} {n.raw_unit ?? ""}
                        </div>
                      </div>
                      <div>
                        <div className="kpi-label">Uploader</div>
                        <div style={{ fontSize: ".84rem" }}>{n.uploader ?? "—"}</div>
                      </div>
                      <div>
                        <div className="kpi-label">Submitted</div>
                        <div style={{ fontSize: ".84rem" }}>
                          {n.submitted_at ? new Date(n.submitted_at).toLocaleString() : "—"}
                        </div>
                      </div>
                      <div>
                        <div className="kpi-label">Approved</div>
                        <div style={{ fontSize: ".84rem" }}>
                          {n.approved_at ? new Date(n.approved_at).toLocaleString() : "pending review"}
                        </div>
                      </div>
                    </div>

                    <div style={{ marginTop: ".8rem" }}>
                      <div className="kpi-label">Evidence ({n.evidence.length})</div>
                      {n.evidence.length === 0 ? (
                        <p className="hint" style={{ fontSize: ".78rem", margin: ".25rem 0 0" }}>
                          No evidence attached to this value.
                        </p>
                      ) : (
                        n.evidence.map((ev) => (
                          <div key={ev.id} className="evidence-chip">
                            📄 {ev.filename} · {(ev.size_bytes / 1024).toFixed(1)} KB · sha256{" "}
                            <span className="mono">{ev.sha256.slice(0, 16)}…</span>
                          </div>
                        ))
                      )}
                    </div>

                    <div style={{ marginTop: ".8rem" }}>
                      <div className="kpi-label">Audit trail ({n.audit.length})</div>
                      <div className="audit-mini">
                        {n.audit.length === 0 ? (
                          <p className="hint" style={{ fontSize: ".78rem", margin: ".25rem 0 0" }}>
                            No audit events recorded for this value.
                          </p>
                        ) : (
                          n.audit.map((a, j) => (
                            <div key={j} className="audit-row">
                              <span className="badge ok">{a.action}</span>
                              <span>{a.actor}</span>
                              <span style={{ color: "var(--muted)", marginLeft: "auto" }}>
                                {new Date(a.at).toLocaleString()}
                              </span>
                            </div>
                          ))
                        )}
                      </div>
                    </div>
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </main>
  );
}
