import { HealthBadge } from "@/components/HealthBadge";

export default function Home() {
  return (
    <main className="landing">
      <header className="topbar">
        <span className="brand">BRSR Reporting Portal</span>
        <HealthBadge />
      </header>
      <section className="hero">
        <h1>Controlled BRSR data management &amp; reporting</h1>
        <p>
          Every reported number carries an owner, a unit, a validation state, evidence, a review
          state and a full audit trail — before it reaches the final BRSR report.
        </p>
        <p className="hint">
          Sign in is introduced in the Auth phase. Backend API docs are available at{" "}
          <a href="http://localhost:8000/docs" target="_blank" rel="noreferrer">
            /docs
          </a>
          .
        </p>
      </section>
    </main>
  );
}
