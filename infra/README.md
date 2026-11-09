# Infrastructure (planned)

Placeholder for PostgreSQL migrations, private object storage, isolated parsing workers, deployment and observability.

The development API deliberately uses SQLite + `create_all()` and runs parsing inline. No production deployment should happen before authentication, data retention, upload isolation and queue leases are implemented. See `docs/IMPLEMENTATION_PLAN.md`.
