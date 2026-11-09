# AGENTS.md

Guidance for any coding agent working in the **TraceMap** repository. Keep this
file short; the detailed fault knowledge lives in
[`docs/gotchas.md`](docs/gotchas.md).

## 1. What this project is (and is not)

TraceMap is an *evidence-first research-map* workbench: import text/Markdown/
text-layer PDF → grouped notes → deterministic "extractive" demo draft → human
review → manual edits → Markdown/JSON export.

This is an **engineering prototype / local development tool**, not a product:

- Authentication is a fake `Authorization: Bearer dev-<name>` identity.
- Generation is the deterministic lexical demo by default (`generationMode:
  extractive_demo`, offline, no key). An **optional real LLM provider** exists but
  is **off by default**; enable it with `TRACEMAP_GENERATION_MODE=llm` in `.env`
  (see [`docs/LLM_PROVIDER.md`](docs/LLM_PROVIDER.md)). Its output is a grounded
  *candidate* draft that a human must commit; it never sets `verified_by_user`.
- Storage is SQLite; parsing is synchronous; there is no isolated worker,
  no PostgreSQL, no object storage.
- The API **refuses to start** unless `TRACEMAP_ENV=development` and also
  rejects non-loopback clients (defence in depth, *not* real auth).
- Source deletion is **not** a full data-erasure guarantee (quotes copied into
  maps/drafts/history remain). See
  [`docs/BACKEND_OPTIMIZATION_V0.3.md`](docs/BACKEND_OPTIMIZATION_V0.3.md).

Never claim a production feature is done. Tracked gaps: G1–G5 in
[`docs/IMPLEMENTATION_PLAN.md`](docs/IMPLEMENTATION_PLAN.md).

## 2. Start here

1. **Read [`docs/gotchas.md`](docs/gotchas.md) first** — search your error text
   or a `GT-####` id before changing anything.
2. Architecture & contracts: [`README.md`](README.md) → `apps/`,
   `packages/contracts/`, [`docs/`](docs/).
3. Full deployment: [`docs/DEPLOYMENT_LINUX.md`](docs/DEPLOYMENT_LINUX.md).

## 3. Before you change code

- Check the working tree: `git status` / `git log --oneline -5`. Do not
  overwrite others' work or `main`; use a `chore/…`/`fix/…` branch.
- Look for an existing `GT` entry for the fault. If one exists, follow its fix;
  if it re-occurs, **update that entry** instead of duplicating it.
- Reproduce first (smallest command), then fix, then add a regression test.

## 4. Run tests after any change

```bash
source apps/api/.venv/bin/activate          # created with `uv venv` (see GT-0006)
python -m compileall -q apps/api/tracemap
python -m pytest -q apps/api/tests          # must be fully green
python scripts/export_openapi.py --check    # route-signature contract
python scripts/benchmark_domain.py          # synthetic, informational timing
cd apps/web && npm run build && npm run test:e2e
cd ../..                                    # return to repo root
scripts/smoke-test.sh && scripts/smoke-test.sh --restart
```

Contract rule: **any route/method/parameter/response change must be followed by
`python scripts/export_openapi.py`** to refresh
`packages/contracts/openapi.generated.json`, or CI fails.

## 5. When you find a problem

Add/update an entry in [`docs/gotchas.md`](docs/gotchas.md) using the existing
format (`GT-000N`, Status, Class, Severity, Symptoms, Minimal reproduction,
Expected/Actual, Root cause, Fix, Files, Related tests, Verification,
Prevention, Links). Keep resolved entries forever; mark unverified guesses
`HYPOTHESIS`; never paste tokens, passwords or raw user data.

## 6. Destructive / forbidden actions — do not run without explicit approval

- `sudo` / `apt` / firewall changes / binding to `0.0.0.0` / reverse proxies.
- Committing `.env` (real secrets) or any file under `.env.*` except
  `.env.example`; pasting keys into code, docs or logs.
- Deleting or overwriting an existing `*.db` (including `tracemap-dev.db`) or
  anything under `$TRACEMAP_RUNTIME_DIR`.
- `git push --force`, rewriting history, or committing to `main` directly.
- Disabling the production guard, the loopback middleware, or any test/assert.
- Setting TRACEMAP_API_HOST / TRACEMAP_WEB_HOST to any non-loopback host,
  reusing E2E databases, or treating skipped health checks as passed.
- Installing a **system-wide** service. (A reviewable *user*-unit template
  exists in [`scripts/systemd/`](scripts/systemd/README.md); never install it
  without approval.)

## 7. Which features are NOT implemented (do not imply otherwise)

Rich AI Patch operations (only a rule-based demo exists); external auth / sessions
/ multi-tenant security; PostgreSQL + migrations; isolated async job worker;
private object storage; full deletion governance; native Xmind import/export; any
production deployment. The optional LLM provider is prototype-grade: no cost cap,
synchronous, no durable jobs, no accuracy evaluation (see `docs/LLM_PROVIDER.md`).

## 8. Shortest path from zero

```bash
# 1. backend
cd apps/api && uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -e '.[test]'
# 2. frontend
cd ../web && npm ci && npx playwright install chromium
# 3. run (any cwd) — loopback only
cd ../.. && scripts/dev-start.sh
# 4. verify
scripts/smoke-test.sh && scripts/dev-status.sh
# 5. stop
scripts/dev-stop.sh
```

If something breaks, in order: `scripts/dev-status.sh` → `scripts/dev-start.sh`
→ tail `$TRACEMAP_RUNTIME_DIR/logs/api.log` → `docs/gotchas.md`.
