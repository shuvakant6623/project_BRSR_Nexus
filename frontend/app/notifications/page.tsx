"use client";

import { useCallback, useEffect, useState } from "react";

import { api } from "@/lib/api";

interface NotificationRow {
  id: string;
  type: string;
  payload: { message?: string; metric_code?: string };
  read_at: string | null;
  created_at: string;
}

const TYPE_ICONS: Record<string, string> = {
  DUE_SOON: "⏳", DUE_TOMORROW: "⚠️", OVERDUE: "🔥",
  RETURNED_FOR_CORRECTION: "↩️", APPROVED: "✅", VALIDATION_EXCEPTION: "🚩",
  AI_SUGGESTION_READY: "🤖", PERIOD_LOCKED: "🔒",
};

export default function NotificationsPage() {
  const [rows, setRows] = useState<NotificationRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(() => {
    api<NotificationRow[]>("/api/v1/notifications")
      .then(setRows)
      .catch((e) => setError(e instanceof Error ? e.message : "Failed to load notifications"));
  }, []);

  useEffect(() => { reload(); }, [reload]);

  async function markRead(id: string) {
    await api(`/api/v1/notifications/${id}/read`, { method: "POST" }).catch(() => undefined);
    reload();
  }

  if (error) return <main className="page"><div className="state error">{error}</div></main>;
  if (rows === null) return <main className="page"><div className="state">Loading notifications…</div></main>;

  return (
    <main className="page">
      <h1 className="rise">Notifications</h1>
      <p className="hint rise rise-d1">Reminders, review outcomes and period events.</p>
      {rows.length === 0 ? (
        <div className="state">Nothing yet — reminders appear as deadlines approach.</div>
      ) : (
        rows.map((n) => (
          <div key={n.id}
            className={`glass-card rise ${n.read_at ? "" : "notif-unread"}`}
            style={{ padding: ".9rem 1.2rem", margin: ".6rem 0", display: "flex", gap: "1rem", alignItems: "center" }}>
            <span style={{ fontSize: "1.3rem" }}>{TYPE_ICONS[n.type] ?? "🔔"}</span>
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: ".9rem", fontWeight: n.read_at ? 500 : 700 }}>
                {n.payload?.message ?? n.type.replace(/_/g, " ")}
              </div>
              <div className="hint" style={{ fontSize: ".74rem" }}>
                {new Date(n.created_at).toLocaleString()}
              </div>
            </div>
            {!n.read_at && (
              <button className="ghostbtn" onClick={() => markRead(n.id)}>Mark read</button>
            )}
          </div>
        ))
      )}
    </main>
  );
}
