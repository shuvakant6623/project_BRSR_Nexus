"use client";

import { useEffect, useState } from "react";

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

export default function AuditPage() {
  const [rows, setRows] = useState<AuditRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [actionFilter, setActionFilter] = useState("");

  useEffect(() => {
    const qs = actionFilter ? `?action=${actionFilter}` : "";
    api<AuditRow[]>(`/api/v1/audit${qs}`)
      .then(setRows)
      .catch((e) => setError(e instanceof Error ? e.message : "Failed to load audit trail"));
  }, [actionFilter]);

  if (error) return <main className="page"><div className="state error">{error}</div></main>;
  if (rows === null) return <main className="page"><div className="state">Loading audit trail…</div></main>;

  return (
    <main className="page">
      <h1 className="rise">Audit trail</h1>
      <p className="hint rise rise-d1">
        Append-only record of every state change. Rows are immutable — even a compromised admin
        account cannot rewrite what happened (enforced by a database trigger).
      </p>
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
        <span className="userchip">{rows.length} events</span>
      </div>
      {rows.length === 0 ? (
        <div className="state">No audit events match the filter.</div>
      ) : (
        <div className="table-wrap rise rise-d2">
          <table className="data-table">
            <thead>
              <tr><th>Action</th><th>Actor</th><th>Object</th><th>Change</th><th>When</th></tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id}>
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
              ))}
            </tbody>
          </table>
        </div>
      )}
    </main>
  );
}
