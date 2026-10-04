# API

Base: `/api/v1` · JWT Bearer auth · RFC 7807 errors · pagination `?page&page_size`
Live OpenAPI: http://localhost:8000/docs

| Domain | Endpoints |
|---|---|
| Auth | POST /auth/login · POST /auth/refresh · POST /auth/logout · GET /auth/me |
| Users | GET/POST /users (admin) · POST /users/{id}/scopes |
| Entities | GET/POST /entities · GET/PATCH /entities/{id} |
| Framework | GET /framework/versions · GET/POST /framework/versions/{id}/metrics · GET .../rules · GET .../formulas |
| Periods | GET /reporting-periods · POST /reporting-periods/{id}/lock |
| Assignments | GET/POST /assignments · GET /assignments/{id} · POST /assignments/{id}/value (SAVE_DRAFT/SUBMIT) · POST /assignments/{id}/review (START_REVIEW/APPROVE/NEEDS_CORRECTION/REJECT) |
| Validation | POST /validation/run · GET /validation/exceptions · POST /validation/exceptions/{id}/explain · POST .../resolve |
| Calculations | POST /calculations/run |
| Consolidation | GET /consolidation/{entity}/{metric}/{period} · POST /consolidation/recompute |
| Lineage | GET /lineage/{entity}/{metric}/{period} |
| Evidence | POST /evidence · GET /evidence/{id} · GET /evidence/{id}/download · DELETE /evidence/{id} · GET /evidence/by-value/{id} |
| Reports | POST /reports/{period}/generate · GET /reports/{period} · GET /reports/{period}/preview · GET /reports/{period}/download |
| Dashboard | GET /dashboard/summary |
| Trends | GET /trends/{metric_code} |
| Audit | GET /audit · GET /audit/metric-value/{id}/history |
| Bulk import | GET /bulk-import/template · POST /bulk-import · GET /bulk-import/{job} |
| Notifications | GET /notifications · GET /notifications/unread-count · POST /notifications/{id}/read |
| AI | POST /ai-suggestions/extract/{evidence} · GET /ai-suggestions · POST /ai-suggestions/{id}/accept · POST .../reject |
| Ops | GET /healthz · GET /readyz |
