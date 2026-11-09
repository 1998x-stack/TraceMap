# TraceMap — Linux local deployment guide

This document is written so a fresh engineer/agent with **no prior context** can
reproduce the local TraceMap research workbench on a Linux host. It was executed
end to end on the reference host below; every command is copy-pasteable.

> **Scope: local development only.** This deployment uses a fake
> `Authorization: Bearer dev-<name>` identity, SQLite, synchronous parsing and a
> rule-based (non-LLM) generation demo. It must run on `127.0.0.1` only. See
> [§11 Security](#11-security--what-this-deployment-is-not) before sharing it.
> Known pitfalls live in [`gotchas.md`](gotchas.md) — read it first when
> something fails.

---

## 1. Supported environment & verified baseline

| Item | Reference host (verified) |
| --- | --- |
| OS | Ubuntu 24.04.3 LTS (noble), x86_64 |
| Kernel | `7.0.0-38-generic` |
| CPU / RAM / disk | 12 vCPU / 31 GiB / `/dev/sda3` ext4, 610 GiB free |
| Python | **3.12.3** (system); venv built with `uv 0.13.5` |
| Node / npm | **v22.23.3** / **10.9.9** |
| Git / OpenSSL | 2.43.0 / 3.0.13 |
| Browser test | Playwright **1.65.0**, Chromium build **1254** (Chrome for Testing 158.0.8127.18) |
| User | non-root `ubuntu` (uid 1000); `sudo` requires a password |
| Firewall | not modified; nothing bound to a public interface |

Backend libraries resolved into the venv: FastAPI 0.162.2, Starlette 1.10.0,
Pydantic 2.14.3, SQLAlchemy 2.1.8, Uvicorn 0.54.0, pypdf 6.21.4, pytest 9.2.0,
httpx 0.28.1, python-multipart 0.0.33. Frontend (pinned by lockfile): Vite
5.4.21, React 18.3.1, `@xyflow/react` 12.12.1, TypeScript 5.9.3.

Minimum: a 64-bit Linux, Python ≥ 3.12, Node ≥ 22, ~2 GiB free disk. Chromium
system libraries are needed only for browser tests (`libnss3`, `libatk*`,
`libgbm1`, `libasound2t64`, `libcups2t64`, `libatspi2.0-0t64`, fonts, …). They
were **already present** on the reference host, so `playwright install
--with-deps` (which needs `sudo`) was **not** required; plain
`npx playwright install chromium` sufficed.

## 2. One-time setup (no `sudo`)

The reference host has **no system `pip`/`ensurepip`** ([GT-0006](gotchas.md#gt-0006--system-python-has-no-pip-or-venv-on-ubuntu-2404)),
so the venv is created with `uv`. If your host has `python3-venv`, the
`python -m venv` + `pip` path from the README works identically.

```bash
# 0. get the code
git clone git@github.com:1998x-stack/TraceMap.git
cd TraceMap

# 1. backend virtualenv (isolated; never install into system Python)
cd apps/api
uv venv --python 3.12 .venv                          # or: python3 -m venv .venv
uv pip install --python .venv/bin/python -e '.[test]' # or: source .venv/bin/activate && pip install -e '.[test]'

# 2. frontend dependencies (lockfile is committed)
cd ../web
npm ci

# 3. Chromium for browser tests (add --with-deps only if you have sudo and the
#    system libraries are genuinely missing)
npx playwright install chromium
```

Runtime state (PID files, logs, SQLite) is kept **outside** the repo by default,
under `$TRACEMAP_RUNTIME_DIR` (`~/tracemap-runtime`), so checkouts and
`git clean` cannot destroy research data. Lifecycle scripts use `umask 077`
and restrict existing runtime subdirectories to mode 0700. This is a deliberate
access-control change for any older, shared runtime folder; review such folders
before upgrading.

## 3. Start, status, stop, restart

```bash
scripts/dev-start.sh     # idempotent: checks prereqs/ports, waits for health
scripts/dev-status.sh    # PIDs, listeners, /health, /docs, recent logs
scripts/dev-stop.sh      # refuses to kill a PID that is not TraceMap
scripts/dev-start.sh     # (restart = stop then start)
```

`dev-start.sh` will refuse to start a duplicate, and `dev-stop.sh` will refuse
to kill an unrelated PID (it verifies the command line). Both work from any
current directory.

The two-terminal README flow is still valid if you prefer foreground processes:

```bash
# Terminal A
cd apps/api && source .venv/bin/activate
TRACEMAP_ENV=development TRACEMAP_DATABASE_URL="sqlite:///$HOME/tracemap-runtime/data/tracemap-dev.db" \
  uvicorn tracemap.main:app --host 127.0.0.1 --port 8000
# Terminal B
cd apps/web && TRACEMAP_PROXY_TARGET=http://127.0.0.1:8000 npm run dev
```

> Always pass an **absolute** `TRACEMAP_DATABASE_URL`. The in-code default
> `sqlite:///./tracemap-dev.db` is relative to the process CWD ([GT-0002](gotchas.md#gt-0002--default-sqlite-path-is-cwd-relative--import-side-effect-creates-a-stray-db)).

### Optional: run as a systemd **user** service

A reviewable template (never installed automatically) is in
[`scripts/systemd/`](../scripts/systemd/README.md). Do not create a system-wide
unit, and do not enable it for other users.

## 4. Access it from your laptop (SSH tunnel — do not open ports)

The API and Vite bind to loopback only. Forward them over SSH:

```bash
ssh -N -L 5173:127.0.0.1:5173 -L 8000:127.0.0.1:8000 ubuntu@<server-ip>
```

Then on your laptop:

- Workbench UI: <http://127.0.0.1:5173>
- API docs: <http://127.0.0.1:8000/docs> (Swagger assets load from a CDN —
  [GT-0009](gotchas.md#gt-0009--swagger-ui-at-docs-loads-assets-from-a-cdn))
- OpenAPI JSON: <http://127.0.0.1:8000/openapi.json>
- Health: <http://127.0.0.1:8000/health>

No firewall change, reverse proxy, or `0.0.0.0` binding is required or allowed.

## 5. Environment variables & data paths

| Variable | Default | Meaning |
| --- | --- | --- |
| `TRACEMAP_ENV` | `development` | Must be `development`; any other value makes the API refuse to start. |
| `TRACEMAP_DATABASE_URL` | `sqlite:///./tracemap-dev.db` | SQLAlchemy URL. **Set it to an absolute path** in any scripted use. |
| `TRACEMAP_API_HOST` / `TRACEMAP_API_PORT` | `127.0.0.1` / `8000` | API bind address/port. |
| `TRACEMAP_WEB_HOST` / `TRACEMAP_WEB_PORT` | `127.0.0.1` / `5173` | Vite bind address/port. |
| `TRACEMAP_RUNTIME_DIR` | `~/tracemap-runtime` | Root for `pids/`, `logs/`, `data/`. |
| `TRACEMAP_PROXY_TARGET` | `http://127.0.0.1:8000` | Vite dev-proxy target for `/api` and `/health`. |
| `TRACEMAP_API_PYTHON` | `apps/api/.venv/bin/python` if present else `python3` | Interpreter for the Playwright backend. |
| `TRACEMAP_E2E_API_PORT` / `TRACEMAP_E2E_WEB_PORT` | `8010` / `5273` | Isolated E2E ports. |
| `TRACEMAP_E2E_DATABASE_URL` | unique temp file | Isolated E2E database. |

Default data paths on the reference host:

```text
~/tracemap-runtime/
├── data/tracemap-dev.db      # the real dev database
├── logs/api.log              # uvicorn stdout/stderr
├── logs/web.log              # vite output
└── pids/api.pid, web.pid
```

## 6. Logs & basic troubleshooting

```bash
scripts/dev-status.sh                 # one-stop status
tail -f ~/tracemap-runtime/logs/api.log
tail -f ~/tracemap-runtime/logs/web.log
ss -tlnp | grep -E ':8000|:5173'      # confirm loopback-only listeners

curl -fsS http://127.0.0.1:8000/health
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/docs
```

Logs contain timestamps and error levels from Uvicorn/Vite. They do **not**
contain request bodies, tokens or user documents. If the API exits immediately,
the top of `api.log` shows why (usually `TRACEMAP_ENV` or the port).

## 7. Tests & browser tests

```bash
# backend contract + unit/integration (30 tests)
source apps/api/.venv/bin/activate
python -m compileall -q apps/api/tracemap
python -m pytest -q apps/api/tests
python scripts/export_openapi.py --check     # stable route-signature contract
python scripts/benchmark_domain.py           # synthetic lexical microbenchmark

# frontend
cd apps/web
npm run build                                # strict TS + Vite bundle
npm run test:e2e                             # Playwright starts its OWN api+vite
cd ../..                                     # required for scripts/ paths

# deployment smoke tests (see §8 for isolated writes)
scripts/smoke-test.sh                        # live checks + throwaway-db workflow
scripts/smoke-test.sh --restart              # start->health->stop->start->persist->stop
```

The Playwright harness does **not** reuse your dev servers and does **not**
touch your dev database: it uses ports `8010`/`5273` and a unique temp SQLite
file (see [GT-0001](gotchas.md#gt-0001--playwright-web-server-assumed-a-global-uvicornpython)
and [GT-0004](gotchas.md#gt-0004--e2e-reused-dev-servers-and-a-shared-database-file)).
Clean stale browser-test files with `rm -f /tmp/tracemap-e2e-*.db`.

## 8. SQLite backup, restore, and cleanup

All writes in `scripts/smoke-test.sh` go to a **throwaway** database, and
`--restart` uses an isolated `TRACEMAP_RUNTIME_DIR`. Your dev database is only
touched by normal use of the workbench.

**Backup (online-safe copy):**

```bash
RUNTIME=${TRACEMAP_RUNTIME_DIR:-$HOME/tracemap-runtime}
mkdir -p "$RUNTIME/backups"
sqlite3 "$RUNTIME/data/tracemap-dev.db" ".backup '$RUNTIME/backups/tracemap-$(date +%Y%m%d-%H%M%S).db'"
```

**Restore-verification procedure (do this on a copy, not in place):**

```bash
RUNTIME=${TRACEMAP_RUNTIME_DIR:-$HOME/tracemap-runtime}
cp "$RUNTIME/backups/<file>.db" /tmp/restore-check.db
TRACEMAP_RUNTIME_DIR=/tmp/restore-runtime \
TRACEMAP_API_PORT=8040 TRACEMAP_WEB_PORT=5193 \
TRACEMAP_DATABASE_URL="sqlite:////tmp/restore-check.db" \
  scripts/dev-start.sh
curl -fsS http://127.0.0.1:8040/api/v1/projects \
  -H 'Authorization: Bearer dev-alice' | head -c 300
TRACEMAP_RUNTIME_DIR=/tmp/restore-runtime scripts/dev-stop.sh
```

**Clean up test environments without deleting real data:**

```bash
rm -f /tmp/tracemap-e2e-*.db /tmp/tracemap-smoke-*.db /tmp/restore-check.db
rm -rf /tmp/tracemap-restart.* /tmp/restore-runtime
# Only if you deliberately want to reset local dev data (this DOES remove it):
#   scripts/dev-stop.sh && rm -rf "${TRACEMAP_RUNTIME_DIR:-$HOME/tracemap-runtime}"
```

Never delete `~/tracemap-runtime/data/tracemap-dev.db` to "make tests pass".

## 9. Verified results (reference host)

| Check | Command | Result |
| --- | --- | --- |
| Python syntax | `python -m compileall -q apps/api/tracemap` | OK |
| Backend tests | `python -m pytest -q apps/api/tests` | **30 passed** (1 deprecation warning, GT-0008) |
| OpenAPI contract | `python scripts/export_openapi.py --check` | **22 operations / 19 paths OK** |
| Benchmark | `python scripts/benchmark_domain.py` | median **3.1 ms**, p95 **3.3 ms**, 21 nodes |
| Frontend build | `npm run build` | **passed** |
| Browser E2E | `npm run test:e2e` | **3 passed** |
| Smoke (live + workflow) | `scripts/smoke-test.sh` | **31 passed, 0 failed** |
| Restart/persistence | `scripts/smoke-test.sh --restart` | **8 passed** |
| Prod guard | `TRACEMAP_ENV=production ... create_app()` | raises `RuntimeError` |
| Loopback only | `ss -tlnp` | `127.0.0.1:8000`, `127.0.0.1:5173` |
| Dev-data persistence | create → `dev-stop` → `dev-start` → read | project readable |

Baseline commit `58497c2` (27 tests, 3 E2E) → hardened head `ea14213`
(30 tests, 3 E2E, scripts). Browser screenshots are written to
`apps/web/test-results/ui-desktop.png` and `ui-mobile.png`.

## 10. FAQ

- **`uvicorn: command not found` in `npm run test:e2e`** → fixed; update to a
  commit ≥ `f0402e2`, or set `TRACEMAP_API_PYTHON=/abs/path/to/.venv/bin/python`.
- **`ensurepip is not available`** → use `uv venv` (GT-0006).
- **Data vanished after restart** → you used a relative DB URL; set an absolute
  `TRACEMAP_DATABASE_URL` (GT-0002).
- **Port already in use** → `scripts/dev-status.sh` shows the owner; do not
  blindly `kill -9`.
- **`/docs` blank offline** → CDN assets (GT-0009); use `/openapi.json`.
- **Everything else** → [`gotchas.md`](gotchas.md).

## 11. Security — what this deployment is NOT

- **Not production.** No external authentication, no sessions, no multi-tenancy.
  Anyone who can reach the API holds a `dev-*` identity.
- The API refuses any `TRACEMAP_ENV` other than `development`, and rejects
  non-loopback clients — but a same-host reverse proxy would bypass that
  middleware, so **never** put this behind Nginx/Caddy or publish the port.
- Do not upload real or sensitive documents: PDF parsing is synchronous and
  unisolated (no CPU/RAM/time limits, no malware scanning).
- Source deletion does not guarantee erasure of quotes already copied into maps,
  drafts, or history snapshots.
- Do not treat the SQLite file or logs as safe for secrets.

Implementation gaps and rollout blockers: [`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md),
[`BACKEND_OPTIMIZATION_V0.3.md`](BACKEND_OPTIMIZATION_V0.3.md).
