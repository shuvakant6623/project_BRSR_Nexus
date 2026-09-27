"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

import { useAuth } from "@/components/AuthProvider";
import { HealthBadge } from "@/components/HealthBadge";

export default function Home() {
  const router = useRouter();
  const { user, loading, logout } = useAuth();

  useEffect(() => {
    if (!loading && !user) router.push("/login");
  }, [loading, user, router]);

  if (loading) {
    return <main className="landing"><p className="hint">Loading session…</p></main>;
  }
  if (!user) return null;

  return (
    <main className="landing">
      <header className="topbar">
        <span className="brand">BRSR Reporting Portal</span>
        <span className="userchip">
          {user.full_name} · {user.role.replace("_", " ")}
        </span>
        <button className="ghostbtn" onClick={() => logout().then(() => router.push("/login"))}>
          Sign out
        </button>
        <HealthBadge />
      </header>
      <section className="hero">
        <h1>Welcome, {user.full_name}</h1>
        <p>
          You are signed in as <strong>{user.email}</strong> with role{" "}
          <strong>{user.role.replace("_", " ")}</strong>. Your data scope covers{" "}
          {user.entity_scope_ids.length} entit{user.entity_scope_ids.length === 1 ? "y" : "ies"}.
        </p>
        <p className="hint">
          Role-specific screens (assignments, review queue, consolidation, reports) appear as those
          modules land in subsequent phases.
        </p>
      </section>
    </main>
  );
}
