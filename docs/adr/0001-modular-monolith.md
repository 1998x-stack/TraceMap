# ADR 0001 — Modular monolith; AI never holds a write credential

**Status:** Accepted for prototype (2026-11-09).

- Build a single FastAPI domain service and a React Flow workspace; postpone microservices.
- Use immutable paragraphs with exact Unicode-codepoint quote anchors.
- Store one project-wide monotonically increasing revision, enforce `If-Match` and scoped idempotency.
- Generation and Patch remain read-only proposals; only the authenticated user can commit them.
- Until real authentication and isolated workers exist, the service explicitly refuses `TRACEMAP_ENV=production`.
- Temporary architecture compromise: SQLite and synchronous demo tasks instead of PostgreSQL and durable jobs. Replace these before real external users.

**Security rationale:** a model-generated suggestion may be invalid, malicious or wrong. No model output is trusted without server-side structural and citation checks. Provenance is not the same as truth.
