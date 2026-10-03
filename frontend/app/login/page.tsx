"use client";

import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";

import { useAuth } from "@/components/AuthProvider";
import { login } from "@/lib/api";

const PIPELINE = [
  "Collection", "Normalization", "Validation", "Calculation",
  "Consolidation", "Review", "Evidence", "Audit", "Lineage",
  "Assurance", "Locked snapshot", "BRSR report",
];

export default function LoginPage() {
  const router = useRouter();
  const { refresh } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await login(email, password);
      await refresh();
      router.push("/");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="auth-main">
      <section className="auth-hero">
        <h1 className="rise">
          Every number has an <span className="grad">owner, a unit, evidence and a trail</span> —
          before it reaches the report.
        </h1>
        <p className="rise rise-d1">
          A controlled BRSR data-management platform: collect, validate, consolidate and report
          with full lineage and auditability on every figure.
        </p>
        <div className="auth-pipeline rise rise-d2">
          {PIPELINE.map((step, i) => (
            <span key={step}>{i + 1}. {step}</span>
          ))}
        </div>
      </section>
      <section className="auth-card-panel">
        <form className="auth-card glass-card" onSubmit={onSubmit}>
          <div className="brand" style={{ marginBottom: ".4rem" }}>
            <span className="brand-mark">BR</span> BRSR Reporting Portal
          </div>
          <p className="hint" style={{ margin: 0 }}>Sign in to continue</p>
          <label>
            Email
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              autoComplete="username"
            />
          </label>
          <label>
            Password
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              autoComplete="current-password"
            />
          </label>
          {error && <div className="auth-error">{error}</div>}
          <button type="submit" className="primarybtn" disabled={busy}>
            {busy ? "Signing in…" : "Sign in"}
          </button>
        </form>
      </section>
    </main>
  );
}
