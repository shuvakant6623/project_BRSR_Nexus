"use client";

import { CartesianGrid, Bar, BarChart, Cell, Pie, PieChart, ResponsiveContainer,
  Tooltip, XAxis, YAxis } from "recharts";
import { useEffect, useMemo, useRef, useState } from "react";

import { useAuth } from "@/components/AuthProvider";
import { api } from "@/lib/api";
import { getTrace, TraceOut } from "@/features/consolidation/consolidation";
import { Assignment, listAssignments } from "@/features/collection/collection";
import { EntityNode, listEntities } from "@/features/entities/entities";
import { ValidationException, listExceptions } from "@/features/validation/validation";

/* ---------------- animated counter ---------------- */
function useCountUp(target: number | null, duration = 900): string {
  const [value, setValue] = useState(0);
  const raf = useRef<number | null>(null);
  useEffect(() => {
    if (target === null) return;
    const start = performance.now();
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / duration);
      const eased = 1 - Math.pow(1 - t, 3);
      setValue(target * eased);
      if (t < 1) raf.current = requestAnimationFrame(tick);
    };
    raf.current = requestAnimationFrame(tick);
    return () => { if (raf.current) cancelAnimationFrame(raf.current); };
  }, [target, duration]);
  if (target === null) return "—";
  const rounded = Math.abs(target) >= 100 ? Math.round(value) : Math.round(value * 100) / 100;
  return rounded.toLocaleString();
}

const STATUS_COLORS: Record<string, string> = {
  NOT_STARTED: "#64748b",
  IN_PROGRESS: "#38bdf8",
  SUBMITTED: "#a78bfa",
  UNDER_REVIEW: "#fbbf24",
  APPROVED: "#10b981",
  LOCKED: "#34d399",
  NEEDS_CORRECTION: "#fb923c",
  REJECTED: "#f87171",
};

export default function Home() {
  const { user, loading } = useAuth();
  const [assignments, setAssignments] = useState<Assignment[] | null>(null);
  const [exceptions, setExceptions] = useState<ValidationException[] | null>(null);
  const [entities, setEntities] = useState<EntityNode[]>([]);
  const [trace, setTrace] = useState<TraceOut | null>(null);
  const [traceNote, setTraceNote] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([
      listAssignments().catch(() => []),
      listExceptions().catch(() => []),
      listEntities().catch(() => []),
    ])
      .then(async ([a, e, ents]) => {
        setAssignments(a);
        setExceptions(e);
        setEntities(ents);
        const group = ents.find((x) => x.name === "MEIL Group");
        const fy24 = await api<{ id: string; label: string }[]>("/api/v1/reporting-periods")
          .then((ps) => ps.find((p) => p.label === "FY2024-25"))
          .catch(() => null);
        if (group && fy24) {
          try {
            setTrace(await getTrace(group.id, "C-P6-TOTAL-ENERGY", fy24.id));
          } catch {
            setTraceNote("Run consolidation once from the Consolidation screen to populate group KPIs.");
          }
        }
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load dashboard"));
  }, []);

  const statusCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const a of assignments ?? []) counts[a.status] = (counts[a.status] ?? 0) + 1;
    return Object.entries(counts).map(([name, value]) => ({
      name: name.replace(/_/g, " "),
      value,
      fill: STATUS_COLORS[name] ?? "#64748b",
    }));
  }, [assignments]);

  const approvedCount = (assignments ?? []).filter(
    (a) => a.status === "APPROVED" || a.status === "LOCKED"
  ).length;
  const openBlocking = (exceptions ?? []).filter(
    (e) => e.severity === "BLOCKING" && e.status !== "RESOLVED"
  ).length;
  const openWarnings = (exceptions ?? []).filter(
    (e) => e.severity === "WARNING" && e.status !== "RESOLVED"
  ).length;
  const total = assignments?.length ?? 0;
  const incomplete = total > 0 && approvedCount < total;

  const energy = useCountUp(trace?.computed_value ?? null);
  const contributors = trace?.contributing_value_count ?? null;
  const avgPerPlant = useCountUp(
    trace?.computed_value != null && (trace?.contributing_value_count ?? 0) > 0
      ? trace.computed_value / (trace?.contributing_value_count ?? 1)
      : null
  );

  if (loading) {
    return (
      <main className="page">
        <div className="skeleton" style={{ height: "2rem", width: "18rem" }} />
        <div className="skeleton" style={{ height: "7rem", marginTop: "1rem" }} />
      </main>
    );
  }
  if (!user) return null;

  return (
    <main className="page">
      <h1 className="rise">Welcome back, {user.full_name.split(" ")[0]}</h1>
      <p className="hint rise rise-d1">
        {user.role.replace("_", " ")} · scope: {user.entity_scope_ids.length} entit
        {user.entity_scope_ids.length === 1 ? "y" : "ies"} · every figure below is live from the
        governed pipeline.
      </p>

      {error && <div className="state error" style={{ marginTop: "1rem" }}>{error}</div>}

      <section className="kpi-row">
        <div className="kpi glass-card rise rise-d1">
          <div className="kpi-value">{energy}<span className="kpi-unit">MWh</span></div>
          <div className="kpi-label">Group energy · FY2024-25</div>
        </div>
        <div className="kpi glass-card rise rise-d2">
          <div className="kpi-value">
            {trace ? avgPerPlant : "—"}
            <span className="kpi-unit">MWh/plant</span>
          </div>
          <div className="kpi-label">Avg energy per contributing plant</div>
        </div>
        <div className="kpi glass-card rise rise-d3">
          <div className="kpi-value">
            {approvedCount}<span className="kpi-unit">/ {total || "—"}</span>
          </div>
          <div className="kpi-label">Assignments approved</div>
        </div>
        <div className="kpi glass-card rise rise-d4">
          <div className="kpi-value">{openBlocking}<span className="kpi-unit">blocking</span></div>
          <div className="kpi-label">{openWarnings} warnings open</div>
        </div>
      </section>

      {incomplete && (
        <div className="auth-error rise" style={{ borderColor: "rgba(251,191,36,.5)", color: "var(--amber)", background: "rgba(251,191,36,.06)" }}>
          INCOMPLETE — {approvedCount} OF {total} ASSIGNMENTS APPROVED. Consolidated figures reflect
          approved data only.
        </div>
      )}

      <div className="rise rise-d2" style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))", gap: "1rem", marginTop: "1.2rem" }}>
        <div className="glass-card" style={{ padding: "1.2rem" }}>
          <h3 style={{ margin: "0 0 .4rem", fontSize: ".95rem" }}>Pipeline status</h3>
          <p className="hint" style={{ margin: "0 0 .6rem", fontSize: ".8rem" }}>
            Every assignment in your scope, by state.
          </p>
          <div style={{ width: "100%", height: 230 }}>
            <ResponsiveContainer>
              <PieChart>
                <Pie data={statusCounts} dataKey="value" nameKey="name" innerRadius={58}
                  outerRadius={88} paddingAngle={3} strokeWidth={0}>
                  {statusCounts.map((s) => <Cell key={s.name} fill={s.fill} />)}
                </Pie>
                <Tooltip contentStyle={{ background: "#101b31", border: "1px solid rgba(94,118,153,.3)", borderRadius: 10, fontSize: 12 }} />
              </PieChart>
            </ResponsiveContainer>
          </div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: ".5rem" }}>
            {statusCounts.map((s) => (
              <span key={s.name} style={{ fontSize: ".72rem", color: "var(--muted)" }}>
                <span style={{ color: s.fill, fontWeight: 800 }}>●</span> {s.name} ({s.value})
              </span>
            ))}
          </div>
        </div>

        <div className="glass-card" style={{ padding: "1.2rem" }}>
          <h3 style={{ margin: "0 0 .4rem", fontSize: ".95rem" }}>
            Group energy by plant — FY2024-25
          </h3>
          <p className="hint" style={{ margin: "0 0 .6rem", fontSize: ".8rem" }}>
            {contributors ?? "—"} contributing approved values · {traceNote ?? "Σ of normalized plant readings."}
          </p>
          <div style={{ width: "100%", height: 260 }}>
            {trace ? (
              <ResponsiveContainer>
                <BarChart data={trace.contributions} margin={{ left: -18 }}>
                  <CartesianGrid stroke="rgba(148,163,184,.12)" vertical={false} />
                  <XAxis dataKey="entity_name" tick={{ fill: "#8fa3bd", fontSize: 10 }} interval={0} angle={-28} textAnchor="end" height={54} />
                  <YAxis tick={{ fill: "#8fa3bd", fontSize: 10 }} />
                  <Tooltip cursor={{ fill: "rgba(56,189,248,.06)" }} contentStyle={{ background: "#101b31", border: "1px solid rgba(94,118,153,.3)", borderRadius: 10, fontSize: 12 }} />
                  <Bar dataKey="value" radius={[6, 6, 0, 0]}>
                    {trace.contributions.map((c, i) => (
                      <Cell key={i} fill={i % 2 ? "#10b981" : "#38bdf8"} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <div className="state" style={{ height: "100%", display: "flex", alignItems: "center", justifyContent: "center" }}>
                {traceNote ?? "Loading…"}
              </div>
            )}
          </div>
        </div>
      </div>
    </main>
  );
}
