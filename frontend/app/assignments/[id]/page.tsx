"use client";

import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { useAuth } from "@/components/AuthProvider";
import { api } from "@/lib/api";
import { DynamicMetricForm } from "@/components/DynamicMetricForm";
import { GovernanceStepper } from "@/components/GovernanceStepper";
import {
  AssignmentDetail,
  getAssignment,
  saveValue,
  STATUS_COLORS,
  ValueRow,
} from "@/features/collection/collection";
import {
  deleteEvidence,
  downloadEvidence,
  EvidenceRow,
  listEvidence,
  uploadEvidence,
} from "@/features/evidence/evidence";

interface AISuggestion {
  id: string;
  evidence_id: string;
  candidate_value: number | null;
  candidate_unit: string | null;
  confidence: number | null;
  provider: string;
  status: string;
}

const EDITABLE = new Set(["NOT_STARTED", "IN_PROGRESS", "NEEDS_CORRECTION", "REJECTED"]);

export default function AssignmentDetailPage() {
  const params = useParams<{ id: string }>();
  const { user } = useAuth();
  const [detail, setDetail] = useState<AssignmentDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [evidence, setEvidence] = useState<EvidenceRow[]>([]);
  const [evidenceError, setEvidenceError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [suggestions, setSuggestions] = useState<AISuggestion[]>([]);
  const [aiBusy, setAiBusy] = useState(false);

  const reloadEvidence = useCallback(() => {
    const valueId = detail?.values[0]?.id;
    if (!valueId) {
      setEvidence([]);
      return Promise.resolve();
    }
    return listEvidence(valueId)
      .then(setEvidence)
      .catch((e) => setEvidenceError(e instanceof Error ? e.message : "Failed to load evidence"));
  }, [detail]);

  const reloadSuggestions = useCallback(() => {
    api<AISuggestion[]>("/api/v1/ai-suggestions?pending_only=true")
      .then(setSuggestions)
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    if (detail) reloadSuggestions();
  }, [detail, reloadSuggestions]);

  async function onExtract(evidenceId: string) {
    setAiBusy(true);
    setEvidenceError(null);
    try {
      await api(`/api/v1/ai-suggestions/extract/${evidenceId}`, { method: "POST" });
      reloadSuggestions();
    } catch (err) {
      setEvidenceError(err instanceof Error ? err.message : "Extraction failed");
    } finally {
      setAiBusy(false);
    }
  }

  async function onAcceptSuggestion(id: string, value: number | null, unit: string | null) {
    setAiBusy(true);
    try {
      await api(`/api/v1/ai-suggestions/${id}/accept`, {
        method: "POST",
        body: JSON.stringify({ value, unit }),
      });
      reloadSuggestions();
      await reload();
    } catch (err) {
      setEvidenceError(err instanceof Error ? err.message : "Accept failed");
    } finally {
      setAiBusy(false);
    }
  }

  async function onRejectSuggestion(id: string) {
    setAiBusy(true);
    try {
      await api(`/api/v1/ai-suggestions/${id}/reject`, { method: "POST" });
      reloadSuggestions();
    } catch (err) {
      setEvidenceError(err instanceof Error ? err.message : "Reject failed");
    } finally {
      setAiBusy(false);
    }
  }

  useEffect(() => {
    if (detail) reloadEvidence();
  }, [detail, reloadEvidence]);

  async function onUploadFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file || !detail?.values[0]) return;
    setUploading(true);
    setEvidenceError(null);
    try {
      await uploadEvidence(detail.values[0].id, file);
      await reloadEvidence();
    } catch (err) {
      setEvidenceError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setUploading(false);
      e.target.value = "";
    }
  }

  async function onDownload(id: string) {
    try {
      const { url } = await downloadEvidence(id);
      window.open(url, "_blank");
    } catch (err) {
      setEvidenceError(err instanceof Error ? err.message : "Download failed");
    }
  }

  async function onDeleteEvidence(id: string) {
    try {
      await deleteEvidence(id);
      await reloadEvidence();
    } catch (err) {
      setEvidenceError(err instanceof Error ? err.message : "Delete failed");
    }
  }

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
      <div className="detail-header rise">
        <h1>{metric.label}</h1>
        <span
          className="status-badge"
          style={{ borderColor: STATUS_COLORS[assignment.status], color: STATUS_COLORS[assignment.status] }}
        >
          {assignment.status.replace("_", " ")}
        </span>
      </div>
      <p className="hint rise rise-d1">
        {detail.entity_name} · {detail.period_label} · <span className="mono">{metric.metric_code}</span>
      </p>
      <GovernanceStepper status={assignment.status} />

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
        <h2>Evidence</h2>
        {evidenceError && <div className="auth-error">{evidenceError}</div>}
        {detail.values.length > 0 && user?.role === "DATA_OWNER" && editable && (
          <label className="uploadbtn">
            {uploading ? "Uploading…" : "Upload evidence (PDF / CSV / XLSX / PNG / JPG)"}
            <input type="file" accept=".pdf,.csv,.xlsx,.png,.jpg,.jpeg" onChange={onUploadFile} />
          </label>
        )}
        {detail.values.length === 0 ? (
          <p className="state">Save a value first, then attach evidence.</p>
        ) : evidence.length === 0 ? (
          <p className="state">
            No evidence attached{metric.evidence_required ? " — this BRSR Core metric REQUIRES evidence" : ""}.
          </p>
        ) : (
          <table className="data-table">
            <thead>
              <tr><th>File</th><th>Type</th><th>Size</th><th>SHA-256</th><th></th></tr>
            </thead>
            <tbody>
              {evidence.map((ev) => (
                <tr key={ev.id}>
                  <td>{ev.original_filename}</td>
                  <td>{ev.mime_type}</td>
                  <td>{(ev.size_bytes / 1024).toFixed(1)} KB</td>
                  <td className="mono">{ev.sha256_hash.slice(0, 16)}…</td>
                  <td>
                    <button className="ghostbtn" onClick={() => onDownload(ev.id)}>Download</button>{" "}
                    {user?.role === "DATA_OWNER" && (
                      <>
                        <button className="ghostbtn" disabled={aiBusy} onClick={() => onExtract(ev.id)}>
                          🤖 Extract
                        </button>{" "}
                        <button className="ghostbtn danger" onClick={() => onDeleteEvidence(ev.id)}>Delete</button>
                      </>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      {suggestions.filter(s => detail.values.some(v => {
        const ev = evidence.find(e => e.id === s.evidence_id);
        return ev && ev.metric_value_id === detail.values[0]?.id;
      })).length > 0 && (
        <section className="history">
          <h2>AI suggestions — UNVERIFIED</h2>
          <p className="hint" style={{ fontSize: ".8rem" }}>
            Accepting creates an <strong>owner-authored draft</strong> (IN_PROGRESS) that you still
            review and submit — a suggestion can never directly enter the approved record.
          </p>
          {suggestions
            .filter((s) => s.status === "PENDING" && evidence.some(
              (e) => e.id === s.evidence_id && e.metric_value_id === detail.values[0]?.id))
            .map((s) => (
              <div key={s.id} className="glass-card" style={{ padding: "1rem 1.2rem", margin: ".6rem 0" }}>
                <div style={{ display: "flex", alignItems: "center", gap: ".8rem", flexWrap: "wrap" }}>
                  <span className="badge warn">AI SUGGESTION — UNVERIFIED</span>
                  <span style={{ fontSize: "1.15rem", fontWeight: 800 }}>
                    {s.candidate_value?.toLocaleString()} {s.candidate_unit}
                  </span>
                  <span className="badge required">
                    confidence {s.confidence ? Math.round(s.confidence * 100) : "?"}%
                  </span>
                  {s.provider === "local_demo" && <span className="badge evidence">demo extraction</span>}
                  <span style={{ marginLeft: "auto" }}>
                    <button className="primarybtn" disabled={aiBusy}
                      onClick={() => onAcceptSuggestion(s.id, s.candidate_value, s.candidate_unit)}>
                      Accept
                    </button>{" "}
                    <button className="ghostbtn" disabled={aiBusy} onClick={() => onRejectSuggestion(s.id)}>
                      Reject
                    </button>
                  </span>
                </div>
              </div>
            ))}
        </section>
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
