"use client";

import { useEffect, useState } from "react";

type ReadyState =
  | { kind: "loading" }
  | { kind: "ok"; deps: Record<string, boolean> }
  | { kind: "degraded"; deps: Record<string, boolean> }
  | { kind: "error" };

export function HealthBadge() {
  const [state, setState] = useState<ReadyState>({ kind: "loading" });

  useEffect(() => {
    const check = () =>
      fetch(`${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/readyz`)
        .then((r) => r.json())
        .then((data) =>
          setState(
            data.status === "ready"
              ? { kind: "ok", deps: data.dependencies }
              : { kind: "degraded", deps: data.dependencies }
          )
        )
        .catch(() => setState({ kind: "error" }));
    check();
    const t = setInterval(check, 15000);
    return () => clearInterval(t);
  }, []);

  if (state.kind === "loading") return <span className="badge pending">Checking backend…</span>;
  if (state.kind === "error") return <span className="badge error">Backend unreachable</span>;
  const label = state.kind === "ok" ? "All systems ready" : "Degraded";
  return (
    <span className={`badge ${state.kind === "ok" ? "ok" : "warn"}`}>
      {label} — PG: {state.deps.postgres ? "up" : "down"}, Redis:{" "}
      {state.deps.redis ? "up" : "down"}, MinIO: {state.deps.minio ? "up" : "down"}
    </span>
  );
}
