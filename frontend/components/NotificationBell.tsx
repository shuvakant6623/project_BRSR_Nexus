"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { api } from "@/lib/api";

interface NotificationRow {
  id: string;
  type: string;
  payload: { message?: string };
  read_at: string | null;
  created_at: string;
}

export function NotificationBell() {
  const [count, setCount] = useState(0);
  const [open, setOpen] = useState(false);
  const [rows, setRows] = useState<NotificationRow[]>([]);
  const ref = useRef<HTMLDivElement | null>(null);

  const reload = () =>
    api<NotificationRow[]>("/api/v1/notifications")
      .then((rs) => {
        setRows(rs);
        setCount(rs.filter((r) => !r.read_at).length);
      })
      .catch(() => undefined);

  useEffect(() => {
    reload();
    const t = setInterval(reload, 20000);
    return () => clearInterval(t);
  }, []);

  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, [open]);

  return (
    <div ref={ref} style={{ position: "relative" }}>
      <button
        className="ghostbtn"
        style={{ position: "relative", padding: ".42rem .6rem" }}
        aria-label="Notifications"
        onClick={() => { setOpen(!open); if (!open) reload(); }}
      >
        🔔
        {count > 0 && (
          <span style={{
            position: "absolute", top: -5, right: -5,
            background: "var(--red)", color: "white", borderRadius: 999,
            fontSize: ".62rem", fontWeight: 800, padding: "1px 5px",
          }}>{count}</span>
        )}
      </button>
      {open && (
        <div className="styled-select-pop" style={{ right: 0, left: "auto", width: "22rem", maxHeight: "24rem" }}>
          <div style={{ padding: ".4rem .6rem", display: "flex", justifyContent: "space-between" }}>
            <strong style={{ fontSize: ".8rem" }}>Notifications</strong>
            <Link href="/notifications" className="linkbtn" style={{ fontSize: ".74rem" }}>View all</Link>
          </div>
          {rows.length === 0 && (
            <div className="styled-select-empty">Nothing yet.</div>
          )}
          {rows.slice(0, 8).map((n) => (
            <div key={n.id} className="styled-select-item" style={{ alignItems: "flex-start" }}>
              <span style={{ fontSize: ".8rem" }}>
                {n.payload?.message ?? n.type.replace(/_/g, " ")}
                <br />
                <span style={{ color: "var(--muted)", fontSize: ".7rem" }}>
                  {new Date(n.created_at).toLocaleString()}
                </span>
              </span>
              {!n.read_at && <span className="badge ok">new</span>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
