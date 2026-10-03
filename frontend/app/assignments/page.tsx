"use client";

import { useEffect, useState } from "react";

import { StyledSelect } from "@/components/StyledSelect";
import { Assignment, listAssignments, STATUS_COLORS } from "@/features/collection/collection";

export default function AssignmentsPage() {
  const [rows, setRows] = useState<Assignment[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<string>("");

  useEffect(() => {
    listAssignments(statusFilter ? { status: statusFilter } : {})
      .then(setRows)
      .catch((e) => setError(e instanceof Error ? e.message : "Failed to load assignments"));
  }, [statusFilter]);

  if (error) return <main className="page"><div className="state error">Error: {error}</div></main>;
  if (rows === null) return <main className="page"><div className="state">Loading assignments…</div></main>;
  if (rows.length === 0)
    return <main className="page"><div className="state">No assignments match the current filter.</div></main>;

  return (
    <main className="page">
      <h1>My Assignments</h1>
      <p className="hint">{rows.length} assignments in your authorized scope.</p>
      <div className="filter-row">
        <StyledSelect
          ariaLabel="Status filter"
          value={statusFilter}
          options={[
            { value: "", label: "All statuses" },
            ...Object.keys(STATUS_COLORS).map((s) => ({ value: s, label: s.replace("_", " ") })),
          ]}
          onChange={setStatusFilter}
          placeholder="All statuses"
        />
      </div>
      <table className="data-table">
        <thead>
          <tr><th>Metric</th><th>Status</th><th>Due</th><th></th></tr>
        </thead>
        <tbody>
          {rows.map((a) => (
            <tr key={a.id}>
              <td className="mono">{a.metric_code}</td>
              <td>
                <span
                  className="status-badge"
                  style={{ borderColor: STATUS_COLORS[a.status], color: STATUS_COLORS[a.status] }}
                >
                  {a.status.replace("_", " ")}
                </span>
              </td>
              <td>{a.due_date ?? "—"}</td>
              <td><a className="linkbtn" href={`/assignments/${a.id}`}>Open</a></td>
            </tr>
          ))}
        </tbody>
      </table>
    </main>
  );
}
