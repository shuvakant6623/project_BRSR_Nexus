# Security decisions

- **Auth**: bcrypt password hashing; JWT access (60 min) + refresh (7 d)
  with rotation — the old refresh token is revoked in Redis on every refresh;
  logout denylists the token; login rate-limited (10 failures → 429 per
  IP+email, 15 min window).
- **Authorization**: server-side only. Every endpoint resolves the user's
  role AND entity-subtree scope (recursive CTE); frontend hiding is treated
  as cosmetic. Negative paths are integration-tested (owner→foreign entity
  403, management write 403, assessor/owner admin actions 403, reviewer
  framework writes 403).
- **Audit**: append-only audit_event; UPDATE/DELETE rejected by a database
  trigger — even a compromised admin account cannot rewrite history.
- **Injection**: SQLAlchemy parameterized queries only; the formula evaluator
  is a hand-written recursive-descent parser over an allow-listed grammar —
  no eval/exec, injection attempts are unit-tested.
- **Files**: private S3-compatible bucket (RustFS) (anonymous access disabled at init);
  presigned, time-limited download URLs with browser-reachable host
  rewriting; MIME + extension + size validation; SHA-256 integrity on every
  evidence object.
- **AI**: document text treated as untrusted data, never instructions
  (prompt-injection mitigation §9.3); extraction is draft-only with per-field
  confidence; acceptance is an explicit logged human action. Suggestions are
  ownership-scoped: only the assignment's data owner (or an admin) may
  trigger extraction, accept or reject a suggestion, and suggestion listings
  are filtered to the caller's own assignments or entity scope.
- **Report rendering**: snapshot-sourced strings (labels, codes, emails,
  units) are HTML-escaped before the report preview is served, so stored
  values can never be interpreted as markup in the browser.
- **Config**: all secrets via environment variables; dev secrets are clearly
  labelled demo-only.
