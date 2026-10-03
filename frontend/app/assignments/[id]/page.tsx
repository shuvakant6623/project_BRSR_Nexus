"use client";

import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { DynamicMetricForm } from "@/components/DynamicMetricForm";
import {
  AssignmentDetail,
  getAssignment,
  saveValue,
  STATUS_COLORS,
  ValueRow,
} from "@/features/collection/collection";

const EDITABLE = new Set(["NOT_STARTED", "IN_PROGRESS", "NEEDS_CORRECTION", "REJECTED"]);

export default function AssignmentDetailPage() {
  const params = useParams<{ id: string }>();
  const [detail, setDetail] = useState<AssignmentDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(() => {
    return getAssignment(params.id)
      .then(setDetail)
      .catch((e) => setError(e instanceof Error ? e.message : "Failed to load assignment"));
  }, [params.id]);

  useEffect(() => {
    reload();
  }, [reload]);

  if (error) return <main className="page"><div className="state error">Error: {error}</div></main>;
  if (detail === null) return <main className="page"><div className="state">Loading assignment…</div></main>;

  const { metric, values, assignment } = detail;
  const editable = EDITABLE.has(assignment.status);
  const latest = values[0];

  async function handleSave(
    value: { raw_value: number | null; raw_unit: string | null; qualitative_value: string | null },
    action: "SAVE_DRAFT" | "SUBMIT",
    expectedLastVersion: number | null,
  ) {
    await saveValue(params.id, {
      action,
      raw_value: value.raw_value,
      raw_unit: value.raw_unit,
      qualitative_value: value.qualitative_value,
      expected_last_version: expectedLastVersion,
    });
    await reload();
  }

  return (
    <main className="page">
      <a className="linkbtn" href="/assignments">← Back to assignments</a>
      <div className="detail-header">
        <h1>{metric.label}</h1>
        <span
          className="status-badge"
          style={{ borderColor: STATUS_COLORS[assignment.status], color: STATUS_COLORS[assignment.status] }}
        >
          {assignment.status.replace("_", " ")}
        </span>
      </div>
      <p className="hint">
        {detail.entity_name} · {detail.period_label} · <span className="mono">{metric.metric_code}</span>
      </p>

      <DynamicMetricForm
        metric={metric}
        initialValue={{
          raw_value: latest?.raw_value ?? null,
          raw_unit: latest?.raw_unit ?? (metric.allowed_units?.[0] ?? metric.canonical_unit ?? null),
          qualitative_value: latest?.qualitative_value ?? null,
        }}
        initialVersion={detail.latest_version}
        disabled={!editable}
        onSave={handleSave}
      />

      {!editable && (
        <div className="state">
          This assignment is <strong>{assignment.status.replace("_", " ")}</strong> and cannot be
          edited. Values in review or approved states are read-only for data owners.
        </div>
      )}

      <section className="history">
        <h2>Value history</h2>
        {values.length === 0 ? (
          <p className="state">No values saved yet.</p>
        ) : (
          <table className="data-table">
            <thead>
              <tr><th>Version</th><th>Raw value</th><th>Unit</th><th>Normalized</th><th>Status</th><th>Submitted</th></tr>
            </thead>
            <tbody>
              {values.map((v: ValueRow) => (
                <tr key={v.id}>
                  <td>v{v.version}{v.is_calculated && <span className="badge core"> calc</span>}</td>
                  <td className="mono">{v.raw_value ?? v.qualitative_value ?? "—"}</td>
                  <td>{v.raw_unit ?? "—"}</td>
                  <td className="mono">{v.normalized_value != null ? `${v.normalized_value} ${v.normalized_unit ?? ""}` : "—"}</td>
                  <td>{v.status}</td>
                  <td>{v.submitted_at ? new Date(v.submitted_at).toLocaleString() : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </main>
  );
}
