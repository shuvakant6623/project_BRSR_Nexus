"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { StyledSelect } from "@/components/StyledSelect";
import { api } from "@/lib/api";

interface Job {
  job_id: string;
  status: string;
  total_rows: number;
  valid_rows: number;
  invalid_rows: number;
  error: string | null;
  completed_at: string | null;
}

export default function ImportPage() {
  const [periods, setPeriods] = useState<{ id: string; label: string; locked: boolean }[]>([]);
  const [periodId, setPeriodId] = useState("");
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const fileRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    api<{ id: string; label: string; locked: boolean }[]>("/api/v1/reporting-periods")
      .then(setPeriods)
      .catch(() => undefined);
  }, []);

  const poll = useCallback((jobId: string) => {
    const t = setInterval(() => {
      api<Job>(`/api/v1/bulk-import/${jobId}`)
        .then((j) => {
          setJob(j);
          if (j.status === "SUCCESS" || j.status === "FAILED") clearInterval(t);
        })
        .catch(() => clearInterval(t));
    }, 2000);
  }, []);

  async function onUpload(file: File) {
    if (!periodId) {
      setError("Pick a reporting period first");
      return;
    }
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const form = new FormData();
      form.append("file", file);
      const res = await fetch(
        `${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/api/v1/bulk-import?period_id=${periodId}`,
        {
          method: "POST",
          body: form,
          headers: { Authorization: `Bearer ${localStorage.getItem("brsr.access_token")}` },
        }
      );
      if (!res.ok) throw new Error((await res.json()).detail || "Upload failed");
      const { job_id } = await res.json();
      setNotice("Upload accepted — processing in the background worker…");
      poll(job_id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Upload failed");
    } finally {
      setBusy(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  const locked = periods.find((p) => p.id === periodId)?.locked;

  return (
    <main className="page">
      <h1 className="rise">Bulk import</h1>
      <p className="hint rise rise-d1">
        Upload a CSV of readings — valid rows become <strong>drafts in your assignments</strong>{" "}
        (never auto-submitted); invalid rows are reported for correction.
      </p>
      <div className="filter-row rise rise-d2">
        <StyledSelect
          ariaLabel="Reporting period"
          value={periodId}
          options={periods.map((p) => ({ value: p.id, label: p.label + (p.locked ? " (locked)" : "") }))}
          onChange={setPeriodId}
          placeholder="Reporting period"
        />
        <a className="linkbtn" href="/api/v1/bulk-import/template">⬇ Download my template</a>
      </div>

      {locked && <div className="state error">This period is locked — imports are disabled.</div>}
      {error && <div className="auth-error">{error}</div>}
      {notice && <div className="form-success">{notice}</div>}

      <label className="uploadbtn rise rise-d3" style={{ display: "inline-flex" }}>
        {busy ? "Uploading…" : "📁 Choose CSV to import"}
        <input
          ref={fileRef}
          type="file"
          accept=".csv"
          disabled={busy || locked}
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) onUpload(f);
          }}
        />
      </label>

      {job && (
        <div className="glass-card" style={{ padding: "1.2rem", marginTop: "1rem" }}>
          <h3 style={{ margin: "0 0 .5rem", fontSize: ".95rem" }}>
            Job {job.job_id.slice(0, 8)}…{" "}
            <span className={`badge ${job.status === "SUCCESS" ? "ok" : job.status === "FAILED" ? "error" : "pending"}`}>
              {job.status}
            </span>
          </h3>
          {job.status === "SUCCESS" ? (
            <div className="kpi-row" style={{ margin: 0 }}>
              <div className="kpi" style={{ padding: ".7rem 1rem" }}>
                <div className="kpi-value" style={{ fontSize: "1.4rem" }}>{job.total_rows}</div>
                <div className="kpi-label">rows read</div>
              </div>
              <div className="kpi" style={{ padding: ".7rem 1rem" }}>
                <div className="kpi-value" style={{ fontSize: "1.4rem", color: "var(--accent-2)" }}>{job.valid_rows}</div>
                <div className="kpi-label">drafts created</div>
              </div>
              <div className="kpi" style={{ padding: ".7rem 1rem" }}>
                <div className="kpi-value" style={{ fontSize: "1.4rem", color: "var(--red)" }}>{job.invalid_rows}</div>
                <div className="kpi-label">invalid (see error report)</div>
              </div>
            </div>
          ) : job.status === "FAILED" ? (
            <p className="hint" style={{ color: "var(--red)" }}>{job.error}</p>
          ) : (
            <div className="skeleton" style={{ height: "1rem", width: "60%" }} />
          )}
        </div>
      )}
    </main>
  );
}
