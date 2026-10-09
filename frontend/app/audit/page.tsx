"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { StyledSelect } from "@/components/StyledSelect";
import { api } from "@/lib/api";

interface AuditRow {
  id: string;
  action: string;
  actor: string;
  entity_id: string | null;
  metric_code: string | null;
  object_type: string;
  object_id: string | null;
  old_value: Record<string, unknown> | null;
  new_value: Record<string, unknown> | null;
  reason: string | null;
  request_id: string | null;
  created_at: string;
}

const ACTION_COLORS: Record<string, string> = {
  CREATED: "#38bdf8", UPDATED: "#94a3b8", SUBMITTED: "#a78bfa",
  APPROVED: "#10b981", REJECTED: "#f87171", LOCKED: "#34d399",
  EXCEPTION_RAISED: "#f87171", EXPLANATION_ADDED: "#fbbf24", REVIEWED: "#fbbf24",
  VALIDATED: "#38bdf8",
};

const PAGE_SIZE = 50;

export default function AuditPage() {
  const [rows, setRows] = useState<AuditRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [actionFilter, setActionFilter] = useState("");
  const [objectTypeFilter, setObjectTypeFilter] = useState("");
  const [page, setPage] = useState(1);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const fetchAudit = useCallback(() => {
    const params = new URLSearchParams();
    if (actionFilter) params.set("action", actionFilter);
    if (objectTypeFilter) params.set("object_type", objectTypeFilter);
    params.set("page", String(page));
    params.set("page_size", String(PAGE_SIZE));
    const qs = params.toString() ? `?${params}` : "";
    api<AuditRow[]>(`/api/v1/audit${qs}`)
      .then(setRows)
      .catch((e) => setError(e instanceof Error ? e.message : "Failed to load audit trail"));
  }, [actionFilter, objectTypeFilter, page]);

  useEffect(() => {
    setPage(1); // reset page when filters change
  }, [actionFilter, objectTypeFilter]);

  useEffect(() => {
    fetchAudit();
  }, [fetchAudit]);

  const stats = useMemo(() => {
    if (!rows) return null;
    const actionCounts: Record<string, number> = {};
    const objectTypes = new Set<string>();
    for (const r of rows) {
      actionCounts[r.action] = (actionCounts[r.action] ?? 0) + 1;
      objectTypes.add(r.object_type);
    }
    return { actionCounts, objectTypes: Array.from(objectTypes).sort() };
  }, [rows]);

  if (error) return <main className="page"><div className="state error">{error}</div></main>;
  if (rows === null) return <main className="page"><div className="state">Loading audit trail…</div></main>;

  const hasNext = rows.length === PAGE_SIZE;
  const hasPrev = page > 1;

  return (
    <main className="page">
      <h1 className="rise">Audit Trail</h1>
      <p className="hint rise rise-d1">
        Append-only record of every state change. Rows are immutable — even a compromised admin
        account cannot rewrite what happened (enforced by a database trigger).
      </p>

      <div className="stat-row rise rise-d1">
        <div className="stat-card">
          <div className="stat-value">{rows.length}</div>
          <div className="stat-label">Events (this page)</div>
        </div>
        {stats && Object.entries(stats.actionCounts).slice(0, 4).map(([action, count]) => (
          <div className="stat-card" key={action}>
            <div className="stat-value" style={{ color: ACTION_COLORS[action] ?? "var(--muted)" }}>{count}</div>
            <div className="stat-label">{action.replace(/_/g, " ")}</div>
          </div>
        ))}
      </div>

      <div className="filter-row rise rise-d2">
        <StyledSelect
          ariaLabel="Action filter"
          value={actionFilter}
          options={[
            { value: "", label: "All actions" },
            ...Object.keys(ACTION_COLORS).map((a) => ({ value: a, label: a.replace(/_/g, " ") })),
          ]}
          onChange={setActionFilter}
          placeholder="All actions"
        />
        <StyledSelect
          ariaLabel="Object type filter"
          value={objectTypeFilter}
          options={[
            { value: "", label: "All object types" },
            ...(stats?.objectTypes ?? []).map((t) => ({ value: t, label: t })),
          ]}
          onChange={setObjectTypeFilter}
          placeholder="All object types"
        />
        <span className="userchip">{rows.length} events · page {page}</span>
      </div>

      {rows.length === 0 ? (
        <div className="state rise rise-d2">No audit events match the filter.</div>
      ) : (
        <div className="table-wrap rise rise-d2">
          <table className="data-table">
            <thead>
              <tr><th>Action</th><th>Actor</th><th>Object</th><th>Change</th><th>When</th></tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <>
                  <tr
                    key={r.id}
                    onClick={() => setExpandedId(expandedId === r.id ? null : r.id)}
                    style={{ cursor: "pointer" }}
                  >
                    <td>
                      <span className="badge" style={{
                        color: ACTION_COLORS[r.action] ?? "var(--muted)",
                        border: `1px solid ${ACTION_COLORS[r.action] ?? "var(--border)"}55`,
                      }}>{r.action.replace(/_/g, " ")}</span>
                    </td>
                    <td style={{ fontSize: ".82rem" }}>{r.actor}</td>
                    <td>
                      <span className="mono">{r.object_type}</span>
                      {r.metric_code && <span className="mono" style={{ color: "var(--muted)" }}> · {r.metric_code}</span>}
                    </td>
                    <td style={{ maxWidth: "24rem", fontSize: ".78rem" }}>
                      {r.new_value ? (
                        <span className="mono" style={{ color: "var(--muted)" }}>
                          {JSON.stringify(r.new_value).slice(0, 90)}
                          {JSON.stringify(r.new_value).length > 90 ? "…" : ""}
                        </span>
                      ) : "—"}
                      {r.reason && <div className="explanation">{r.reason}</div>}
                    </td>
                    <td style={{ fontSize: ".78rem", whiteSpace: "nowrap" }}>
                      {new Date(r.created_at).toLocaleString()}
                    </td>
                  </tr>
                  {expandedId === r.id && (
                    <tr key={`${r.id}-detail`}>
                      <td colSpan={5} style={{ background: "rgba(13, 22, 41, 0.5)", padding: "0.8rem 1rem" }}>
                        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0.6rem", fontSize: "0.8rem" }}>
                          <div>
                            <strong style={{ color: "var(--muted)" }}>Event ID:</strong>{" "}
                            <span className="mono">{r.id}</span>
                          </div>
                          <div>
                            <strong style={{ color: "var(--muted)" }}>Object ID:</strong>{" "}
                            <span className="mono">{r.object_id ?? "—"}</span>
                          </div>
                          <div>
                            <strong style={{ color: "var(--muted)" }}>Entity ID:</strong>{" "}
                            <span className="mono">{r.entity_id ?? "—"}</span>
                          </div>
                          <div>
                            <strong style={{ color: "var(--muted)" }}>Request ID:</strong>{" "}
                            <span className="mono">{r.request_id ?? "—"}</span>
                          </div>
                          {r.old_value && (
                            <div style={{ gridColumn: "1 / -1" }}>
                              <strong style={{ color: "var(--muted)" }}>Old value:</strong>
                              <pre style={{ margin: "0.3rem 0 0", color: "#f87171", fontSize: "0.76rem", whiteSpace: "pre-wrap", wordBreak: "break-all" }}>{JSON.stringify(r.old_value, null, 2)}</pre>
                            </div>
                          )}
                          {r.new_value && (
                            <div style={{ gridColumn: "1 / -1" }}>
                              <strong style={{ color: "var(--muted)" }}>New value:</strong>
                              <pre style={{ margin: "0.3rem 0 0", color: "#10b981", fontSize: "0.76rem", whiteSpace: "pre-wrap", wordBreak: "break-all" }}>{JSON.stringify(r.new_value, null, 2)}</pre>
                            </div>
                          )}
                        </div>
                      </td>
                    </tr>
                  )}
                </>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="pagination rise rise-d2">
        <button disabled={!hasPrev} onClick={() => setPage((p) => p - 1)}>← Previous</button>
        <span className="page-info">Page {page}</span>
        <button disabled={!hasNext} onClick={() => setPage((p) => p + 1)}>Next →</button>
      </div>
    </main>
  );
}
