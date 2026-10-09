# Judge demo sequence (~10 minutes)

0. `./run.sh` — wait for "demo ready". Open http://localhost:3000.
   Login `manager@example.local` / `Demo@12345`.

1. DASHBOARD — BRSR Core readiness ring (44%, PROVISIONAL), pipeline funnel,
   KPI cards with YoY, and the "Why ratios are recomputed" card: naive
   average 0.2873 (struck through) vs correct Σ/Σ 0.2172 — the platform
   recomputes ratios at every hierarchy level, never averages percentages.

2. EXCEPTIONS — click "Run validation": 10 rule classes + statistical
   IQR/z-score sweeps run live. Show the Beta workforce mismatch
   (252 vs 240, BLOCKING) and Plant Zeta's statistical outlier.

3. REVIEW QUEUE — open a submission; show value, unit, evidence, exceptions,
   approval actions. Try approving an assignment with unresolved BLOCKING
   exceptions → refused with the reason.

4. CONSOLIDATION — pick FY2024-25, Total Energy, MEIL Group → 936 MWh from
   8 plants. Click "Where did this number come from?".

5. LINEAGE — the full trail: consolidated 936 → per-plant calculated values
   (formula F-TOTAL-ENERGY v1 with resolved inputs) → uploader → submitted →
   audit events. Every number answers "who, what, when, backed by what".

6. DATA OWNER FLOW — sign in as owner-alpha, open "Electricity from
   non-renewable sources", submit 170,000 kWh (normalizes to 170 MWh),
   upload electricity_bill.pdf evidence.

7. VALIDATION → YoY warning "+70% year-on-year" appears automatically.

8. AI (optional) — on the evidence row click "🤖 Extract": demo extraction
   (clearly labelled) proposes a value with confidence; Accept creates an
   owner DRAFT — never an approval.

9. REPORTS — FY2024-25 is locked: click Generate report → Celery renders the
   PDF from the immutable snapshot → Preview HTML shows Sections A/B/C and
   P1–P9 with the snapshot checksum. Download PDF.

10. TRENDS — FY2024-25 vs FY2025-26 with lineage-aware continuity; metrics
    without a mapping show an explicit GAP.

Closing line: "Every number you just saw had an owner, a unit, a validation
state, evidence, a review state and an audit trail before it reached the
report."

## Automated walkthrough

`bash scripts/demo_walkthrough.sh` drives the whole flow above against the
live stack via the API: logins for every role, submit with unit
normalization, YoY warning, evidence-gated approval, exception
explain/resolve, RBAC negatives, derived calculations and FY24 group
consolidation with ratio math. Run it once on a fresh `./run.sh` state — it
mutates demo data as it goes.
