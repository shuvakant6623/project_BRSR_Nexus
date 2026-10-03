"use client";

import { useEffect, useState } from "react";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export function HealthDot() {
  const [ok, setOk] = useState<boolean | null>(null);
  useEffect(() => {
    const check = () =>
      fetch(`${API_URL}/readyz`)
        .then((r) => r.json())
        .then((d) => setOk(d.status === "ready"))
        .catch(() => setOk(false));
    check();
    const t = setInterval(check, 15000);
    return () => clearInterval(t);
  }, []);
  const color = ok === null ? "#64748b" : ok ? "#10b981" : "#f87171";
  return (
    <span
      title={ok === null ? "Checking backend…" : ok ? "All systems ready" : "Backend degraded"}
      style={{
        width: 9,
        height: 9,
        borderRadius: 999,
        background: color,
        boxShadow: ok ? "0 0 10px rgba(16,185,129,.7)" : "none",
        animation: ok === null ? "pulseDot 2s infinite" : "none",
        flexShrink: 0,
      }}
    />
  );
}
