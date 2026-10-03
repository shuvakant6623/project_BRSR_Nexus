"use client";

import { useCallback, useEffect, useState } from "react";

import { useAuth } from "@/components/AuthProvider";
import { StyledSelect } from "@/components/StyledSelect";
import {
  downloadReport,
  generateReport,
  listPeriods,
  listReports,
  lockPeriod,
  Period,
  ReportRow,
} from "@/features/reports/reports";

export default function ReportsPage() {
  const { user } = useAuth();
  const [periods, setPeriods] = useState<Period[]>([]);
  const [periodId, setPeriodId] = useState("");
  const [reports, setReports] = useState<ReportRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [confirmLock, setConfirmLock] = useState(false);

  const canManage = user?.role === "ADMIN" || user?.role === "ESG_MANAGER";
  const period = periods.find((p) => p.id === periodId);

  const reload = useCallback(() => {
    if (!periodId) return Promise.resolve();
    return listReports(periodId).then(setReports).catch(() => setReports([]));
  }, [periodId]);

  useEffect(() => {
    listPeriods()
      .then((ps) => {
        setPeriods(ps);
        const fy24 = ps.find((p) => p.label === "FY2024-25") ?? ps[0];
        if (fy24) setPeriodId(fy24.id);
      })
      .catch((e) => setError(e instanceof Error ? e.message : "Failed to load periods"));
  }, []);

  useEffect(() => {
    reload();
    const t = setInterval(() => {
      if (reports?.some((r) => r.status === "PENDING" || r.status === "RUNNING")) reload();
    }, 3000);
    return () => clearInterval(t);
  }, [reload, reports]);

  async function onLock() {
    setBusy(true);
    setError(null);
    try {
      await lockPeriod(periodId);
      setNotice("Period locked. Values are now immutable.");
      setConfirmLock(false);
      setPeriods(await listPeriods());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Lock failed");
    } finally {
      setBusy(false);
    }
  }

  async function onGenerate() {
    setBusy(true);
    setError(null);
    try {
      await generateReport(periodId);
      setNotice("Report generation queued — rendering from the immutable snapshot.");
      await reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Generation failed");
    } finally {
      setBusy(false);
    }
  }

  async function onDownload() {
    try {
      const { url } = await downloadReport(periodId);
      window.open(url, "_blank");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Download failed");
    }
  }

  return (
    <main className="page">
      <h1 className="rise">Reports</h1>
      <p className="hint rise rise-d1">
        Reports are generated only from <strong>locked</strong> periods, via an immutable
        checksummed snapshot — never from live mutable data.
      </p>
      <div className="filter-row rise rise-d2">
        <StyledSelect
          ariaLabel="Reporting period"
          value={periodId}
          options={periods.map((p) => ({ value: p.id, label: p.label }))}
          onChange={setPeriodId}
          placeholder="Reporting period"
        />
        {period?.locked ? (
          <span className="badge ok">LOCKED</span>
        ) : (
          <span className="badge pending">IN PROGRESS</span>
        )}
        {canManage && period && !period.locked && (
          <button className="ghostbtn" disabled={busy} onClick={() => setConfirmLock(true)}>
            Lock period
          </button>
        )}
        {canManage && period?.locked && (
          <button className="primarybtn" disabled={busy} onClick={onGenerate}>
            {busy ? "Working…" : "Generate report"}
          </button>
        )}
        {period?.locked && (
          <>
            <a className="linkbtn" href={`/api/v1/reports/${periodId}/preview`} target="_blank" rel="noreferrer">
              Preview HTML
            </a>
            <button className="ghostbtn" onClick={onDownload}>Download PDF</button>
          </>
        )}
      </div>

      {error && <div className="auth-error">{error}</div>}
      {notice && <div className="form-success">{notice}</div>}

      {confirmLock && (
        <div className="glass-card" style={{ padding: "1.2rem", margin: "1rem 0" }}>
          <h3 style={{ margin: "0 0 .4rem" }}>Lock {period?.label}?</h3>
          <p className="hint" style={{ margin: "0 0 .8rem" }}>
            Locking makes every value in this period immutable and requires: all in-scope
            assignments APPROVED and zero unresolved BLOCKING exceptions. This cannot be undone.
          </p>
          <button className="primarybtn" disabled={busy} onClick={onLock}>Confirm lock</button>{" "}
          <button className="ghostbtn" onClick={() => setConfirmLock(false)}>Cancel</button>
        </div>
      )}

      {reports !== null && reports.length > 0 && (
        <div className="table-wrap rise">
          <table className="data-table">
            <thead>
              <tr><th>Report</th><th>Status</th><th>Snapshot checksum</th><th>Completed</th></tr>
            </thead>
            <tbody>
              {reports.map((r) => (
                <tr key={r.id}>
                  <td className="mono">{r.id.slice(0, 8)}…</td>
                  <td>
                    <span className={`badge ${r.status === "SUCCESS" ? "ok" : r.status === "FAILED" ? "error" : "pending"}`}>
                      {r.status}{r.status === "RUNNING" ? "…" : ""}
                    </span>
                    {r.error && <div className="explanation">{r.error}</div>}
                  </td>
                  <td className="mono">{r.checksum?.slice(0, 20)}…</td>
                  <td style={{ fontSize: ".8rem" }}>
                    {r.completed_at ? new Date(r.completed_at).toLocaleString() : "—"}
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
