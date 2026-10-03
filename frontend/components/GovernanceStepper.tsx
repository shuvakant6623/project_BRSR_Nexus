"use client";

const STEPS = [
  { key: "IN_PROGRESS", label: "Draft" },
  { key: "SUBMITTED", label: "Submitted" },
  { key: "UNDER_REVIEW", label: "Review" },
  { key: "APPROVED", label: "Approved" },
  { key: "LOCKED", label: "Locked" },
];

const ALIASES: Record<string, number> = {
  NOT_STARTED: 0,
  IN_PROGRESS: 0,
  NEEDS_CORRECTION: 0,
  REJECTED: 0,
  SUBMITTED: 1,
  UNDER_REVIEW: 2,
  APPROVED: 3,
  LOCKED: 4,
};

export function GovernanceStepper({ status }: { status: string }) {
  const currentIndex = ALIASES[status] ?? 0;
  return (
    <div className="stepper rise rise-d1">
      {STEPS.map((step, i) => {
        const cls = i < currentIndex ? "done" : i === currentIndex ? "current" : "";
        return (
          <span key={step.key} style={{ display: "flex", alignItems: "center" }}>
            {i > 0 && <span className={`step-line ${i <= currentIndex ? "done" : ""}`} />}
            <span className={`step ${cls}`}>
              <span className="step-dot">{i < currentIndex ? "✓" : i + 1}</span>
              <span className="step-label">{step.label}</span>
            </span>
          </span>
        );
      })}
      {(status === "NEEDS_CORRECTION" || status === "REJECTED") && (
        <span className="badge error" style={{ marginLeft: ".8rem" }}>
          {status === "REJECTED" ? "Rejected — resubmit required" : "Returned — corrections requested"}
        </span>
      )}
    </div>
  );
}
