# TraceMap — Gotchas & Fault Knowledge Base

> Engineering knowledge base for anyone (human or agent) deploying, testing or
> fixing TraceMap on Linux. **Read this before changing code or re-running a
> failing command.** Every entry is a *real* observation on the reference host
> unless it is explicitly tagged `HYPOTHESIS`.

## 1. Quick diagnosis entry points

| Symptom | Start here |
| --- | --- |
| `uvicorn: command not found` from `npm run test:e2e` | [GT-0001](#gt-0001--playwright-web-server-assumed-a-global-uvicornpython) |
| Data "disappears" after restart, or a stray `tracemap-dev.db` appears in the repo root | [GT-0002](#gt-0002--default-sqlite-path-is-cwd-relative--import-side-effect-creates-a-stray-db) |
| `npm install` pulls unexpected versions / different Chromium build | [GT-0003](#gt-0003--no-frontend-lockfile--dependency-drift) |
| E2E touches the developer database or collides on ports | [GT-0004](#gt-0004--e2e-reused-dev-servers-and-a-shared-database-file) |
| HTTP **500** from a write with a large `If-Match` | [GT-0005](#gt-0005--oversized-if-match-revision-caused-a-500-overflowerror) |
| `python3 -m venv` / `pip` fails ("ensurepip is not available") | [GT-0006](#gt-0006--system-python-has-no-pip-or-venv-on-ubuntu-2404) |
| Root node lost its title after applying a generated draft | [GT-0007](#gt-0007--committing-a-generation-draft-replaces-the-entire-map) |
| `StarletteDeprecationWarning: ... install httpx2 instead` | [GT-0008](#gt-0008--deprecated-starlette-testclient--httpx-pairing) |
| `/docs` renders blank with no internet | [GT-0009](#gt-0009--swagger-ui-at-docs-loads-assets-from-a-cdn) |
| Untracked `tsconfig.tsbuildinfo` after a build | [GT-0010](#gt-0010--tsc--b-leaves-an-untracked-tsbuildinfo) |
| Public bind override in dev-start | [GT-0012](#gt-0012--host-override-could-expose-development-services) |
| Wrong PID killed / opaque port treated as free | [GT-0013](#gt-0013--pid-reuse-and-opaque-listener-ownership) |
| Smoke script returned success when server absent | [GT-0014](#gt-0014--live-smoke-skipped-absent-services) |
| Playwright reused unknown test servers or database override | [GT-0015](#gt-0015--e2e-server-reuse-and-database-override) |
| Restart smoke could inherit user database | [GT-0016](#gt-0016--restart-test-inherited-database-url) |
| Test commands broke when run outside repository root | [GT-0017](#gt-0017--relative-commands-and-unscoped-tmp-cleanup) |
| Safety tests fail only when `TRACEMAP_*` is exported in the shell | [GT-0018](#gt-0018--safety-tests-depended-on-ambient-tracemap-variables) |
| `crypto.randomUUID is not a function` (LAN / plain-HTTP origin) | [GT-0021](#gt-0021--cryptorandomuuid-is-not-a-function-on-a-plain-http-lan-origin) |
| Explicitly empty environment value was overridden by `.env` on Linux | [GT-0026](#gt-0026--shell-dotenv-loader-overwrote-explicit-empty-environment-variables) |
| LLM output still truncated after automatic retry | [GT-0027](#gt-0027--truncation-retry-reused-the-same-token-budget) |
| LLM candidate has no valid evidence, but still appears in the map | [GT-0024](#gt-0024--model-claims-with-invalid-or-out-of-scope-anchors-survived) |
| Candidate generation takes tens of seconds with no visible explanation | [GT-0025](#gt-0025--synchronous-generation-looked-frozen) |
| `502 LLM_OUTPUT_TRUNCATED` after retry, or malformed model JSON | [GT-0022](#gt-0022--reasoning-model-truncation-broke-llm-generation-intermittently) and [GT-0027](#gt-0027--truncation-retry-reused-the-same-token-budget) |\n| Source deleted but quote remains in a map, draft or historical snapshot | [GT-0028](#gt-0028--source-delete-left-derived-evidence-in-live-records) |\n| PDF upload blocks API or consumes unbounded parser resources | [GT-0029](#gt-0029--pdf-extraction-ran-inside-the-api-process) |\n| Local API accepts forwarded headers or an external Host | [GT-0030](#gt-0030--dev-api-trusted-loopback-proxy-metadata) |
| Markdown export hides node type / notes / verification | [GT-0023](#gt-0023--markdown-export-does-not-convey-node-type-notes-or-verification) |
| `scripts/dev-start.sh: No such file or directory` after following the guide | [GT-0019](#gt-0019--deployment-guide-left-the-shell-in-appsweb) |
| HTTP **500** `Internal Server Error` (non-JSON) on a locked SQLite / after ~20 s | [GT-0020](#gt-0020--locked-sqlite-returned-an-opaque-non-json-500) |
| Test suite is slow (~40 s) | [GT-0011](#gt-0011--sqlite-ddlfsync-is-slow-on-this-host) |

## 2. Current environment and verified commits

Reference host (see `docs/DEPLOYMENT_LINUX.md` for the full baseline):

- Ubuntu 24.04.3 LTS, kernel `7.0.0-38-generic`, x86_64, 12 vCPU, 31 GiB RAM.
- Python **3.12.3** (system) installed via **`uv 0.13.5`** into `apps/api/.venv`
  — the system interpreter has **no `pip`/`ensurepip`** ([GT-0006](#gt-0006--system-python-has-no-pip-or-venv-on-ubuntu-2404)).
- Node **v22.23.3**, npm **10.9.9**; Vite 5.4.21, React 18.3.1,
  `@xyflow/react` 12.12.1, TypeScript 5.9.3, Playwright **1.65.0** (Chromium 1254).
- Backend: FastAPI 0.162.2, Starlette 1.10.0, Pydantic 2.14.3, SQLAlchemy 2.1.8,
  Uvicorn 0.54.0, pypdf 6.21.4, pytest 9.2.0, httpx 0.28.1.
- `sudo` requires a password → no `apt`, no system-wide units, no firewall edits.

Verified commits:

| Commit | Meaning |
| --- | --- |
| `58497c2` | Upstream baseline as found on `main` (27 Python tests, 3 Chromium E2E). |
| `f0402e2` | E2E harness isolation (fixes [GT-0001](#gt-0001--playwright-web-server-assumed-a-global-uvicornpython), [GT-0004](#gt-0004--e2e-reused-dev-servers-and-a-shared-database-file)). |
| `023df9a` | Lockfile + ignore rules (fixes [GT-0003](#gt-0003--no-frontend-lockfile--dependency-drift), [GT-0010](#gt-0010--tsc--b-leaves-an-untracked-tsbuildinfo)). |
| `429afac` | `If-Match` bounds (fixes [GT-0005](#gt-0005--oversized-if-match-revision-caused-a-500-overflowerror)). |
| `3e7c1fd` | Restart-persistence + lifecycle tests. |
| `ea14213` | Deployment scripts + CI script check (mitigates [GT-0002](#gt-0002--default-sqlite-path-is-cwd-relative--import-side-effect-creates-a-stray-db), [GT-0006](#gt-0006--system-python-has-no-pip-or-venv-on-ubuntu-2404)). |
| `bf31da4` | Fail-closed loopback, owned PID records, isolated smoke (GT-0012–GT-0014). |
| `7c06f87` | E2E DB-override proof + restart sentinel (GT-0015, GT-0016). |
| `784511c` | Private runtime permissions and gotchas record (verified baseline for this review). |
| `1182bc1`, `771b3f4`, `52bfd20` | Independent Linux review: hermetic safety tests, storage-error contract, PDF coverage (GT-0018–GT-0020). |
| `ebbec19` | LAN/plain-HTTP origin support: UUID fallback (GT-0021). |
| `d2ba874` | Centralize configuration in `.env` / `.env.example`. |
| `7efe4fd` | Optional grounded LLM provider (GT-0022). |
| `8c6d7aa` | UI reflects the active generation provider. |

## 3. Most common errors (index)

- `uvicorn: command not found` → GT-0001
- `Error: Process from config.webServer was not able to start. Exit code: 127` → GT-0001
- `OverflowError: Python int too large to convert to SQLite INTEGER` → GT-0005
- `The virtual environment was not created successfully because ensurepip is not available` → GT-0006
- `StarletteDeprecationWarning ... httpx2` → GT-0008
- `EADDRINUSE` / "port already in use" from `bash -n`-clean scripts → use `scripts/dev-status.sh` first
- `REVISION_CONFLICT` (409) after editing in two places → expected CAS behaviour, reload and retry
- `NO_UNDO_AVAILABLE` (409) → last change was `source_add`/`source_delete`; deletion is irreversible by design

## 4. Resolved or mitigated issues

| ID | Title | Class | Sev |
| --- | --- | --- | --- |
| GT-0001 | Playwright web server assumed a global `uvicorn`/`python` | Deployment/Test | P1 |
| GT-0002 | Default SQLite path is CWD-relative; import still creates a stray DB (**mitigated**) | Deployment/Database | P1 |
| GT-0003 | No frontend lockfile → dependency drift | Environment | P2 |
| GT-0004 | E2E reused dev servers and a shared database file | Test | P1 |
| GT-0005 | Oversized `If-Match` revision → 500 `OverflowError` | Backend/Security | P1 |
| GT-0006 | System Python has no `pip`/`venv` | Environment | P2 |
| GT-0010 | `tsc -b` leaves an untracked `tsbuildinfo` | Environment | P3 |
| GT-0018 | Safety tests depended on ambient `TRACEMAP_*` variables | Test/Reproducibility | P2 |
| GT-0019 | Deployment guide left the shell in `apps/web` | Documentation | P2 |
| GT-0020 | Locked SQLite returned an opaque non-JSON 500 | Backend/Reliability | P2 |
| GT-0021 | `crypto.randomUUID` missing on a plain-HTTP LAN origin | Frontend/Deployment | P1 |
| GT-0022 | Reasoning-model truncation broke LLM output | Backend/LLM | P2 |
| GT-0027 | Truncation retry reused the same token budget | Backend/LLM | P1 |

## 5. Open issues / roadmap

| ID | Title | Class | Sev | Why not fixed here |
| --- | --- | --- | --- | --- |
| GT-0007 | Committing a draft replaces the entire map | Backend/Algorithm | P2 | Needs a product decision (merge vs replace), out of scope for a deployment pass |
| GT-0008 | Deprecated Starlette `TestClient` + `httpx` pairing | Test | P3 | Would require `httpx2` or a version pin; not blocking now |
| GT-0009 | Swagger UI assets load from a CDN | Frontend/Docs | P3 | Cosmetic; affects offline `/docs` only |
| GT-0011 | SQLite DDL/fsync is slow on this host | Environment | P3 | Host disk characteristic; not application code |
| GT-0017 | Relative commands and unscoped /tmp cleanup | Documentation | P2 | Guide corrected; independent cold-start now performed by this review (see GT-0019) |
| GT-0023 | Markdown export hides node type, notes and verification | Export/Frontend | P3 | Needs a format decision (Xmind-clean headings vs richer labels) |

## 5.1 Deployment review follow-up (PR #6)

The following faults were identified by a **source-level safety review** of PR #6,
not by inspecting private server logs. The follow-up security and lifecycle
checks passed in [GitHub Actions #42575575595](https://github.com/1998x-stack/TraceMap/actions/runs/42575575595)
on GitHub's Ubuntu runner. This validates the repository in CI, **not**
the private Linux server, its firewall, or a full independent cold-start.
GT-0017 remains open until another agent follows the new setup guide end to end.

| ID | Severity | Symptom / root issue |
| --- | --- | --- |
| GT-0012 | P0 | Unsafe host overrides can bind development Vite/API to public interfaces |
| GT-0013 | P1 | PID reuse and `ss` hiding an owner's PID make stop/start ownership unreliable |
| GT-0014 | P1 | Missing live development services were SKIP, yet smoke exited successfully |
| GT-0015 | P1 | E2E reused local listeners and trusted an arbitrary DB URL override |
| GT-0016 | P1 | Restart smoke inherited TRACEMAP_DATABASE_URL despite isolated runtime |
| GT-0017 | P2 | Agent commands used the wrong working directory; wildcard cleanup was too broad |

## 6. Recommended troubleshooting order

1. `scripts/dev-status.sh` — are the processes up, on the right ports, on loopback?
2. `scripts/dev-start.sh` — confirm prerequisites and whether a duplicate/port conflict exists.
3. `curl -fsS http://127.0.0.1:8000/health` and check `$TRACEMAP_RUNTIME_DIR/logs/api.log`.
4. `scripts/smoke-test.sh` — protocol/workflow level; `--restart` for persistence.
5. `python -m pytest -q apps/api/tests` — domain and API invariants.
6. `cd apps/web && npm run build && npm run test:e2e` — UI and browser workflow.
7. Search this file by the error text or `GT-####` before inventing a new fix.

## 7. Command cheat-sheet

```bash
# --- one-time setup (no sudo) ---
cd apps/api && uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -e '.[test]'
cd apps/web && npm ci && npx playwright install chromium

# --- run / inspect / stop ---
scripts/dev-start.sh        # idempotent; waits for health
scripts/dev-status.sh       # pids, listeners, health, tail of logs
scripts/dev-stop.sh         # refuses to kill unrelated PIDs
scripts/smoke-test.sh       # live checks + isolated workflow
scripts/smoke-test.sh --restart   # start->health->stop->start->persist->stop

# --- tests ---
source apps/api/.venv/bin/activate
python -m compileall -q apps/api/tracemap
python -m pytest -q apps/api/tests
python scripts/export_openapi.py --check
python scripts/benchmark_domain.py
cd apps/web && npm run build && npm run test:e2e
```

## 8. See also

- [`docs/DEPLOYMENT_LINUX.md`](DEPLOYMENT_LINUX.md) — full from-scratch deployment guide.
- [`AGENTS.md`](../AGENTS.md) — how a new agent should work in this repo.
- [`docs/IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md) — gates and what is *not* implemented.
- [`docs/BACKEND_OPTIMIZATION_V0.3.md`](BACKEND_OPTIMIZATION_V0.3.md),
  [`docs/ALGORITHM_OPTIMIZATION_V0.3.md`](ALGORITHM_OPTIMIZATION_V0.3.md),
  [`docs/VERIFICATION_V0.3.md`](VERIFICATION_V0.3.md) — design and prior evidence.
- [`scripts/systemd/README.md`](../scripts/systemd/README.md) — optional user service.

---

## GT-0001 — Playwright web server assumed a global `uvicorn`/`python`

**Status:** RESOLVED
**Class:** Deployment / Test
**Severity:** P1
**First seen:** 2026-11-09
**Environment:** Ubuntu 24.04.3, Node 22.23.3, Playwright 1.65.0, commit `58497c2`.

**Symptoms:** `npm run test:e2e` printed
`[WebServer] bash: line 1: uvicorn: command not found` and
`Error: Process from config.webServer was not able to start. Exit code: 127`.

**Minimal reproduction:**
```bash
cd apps/api && uv venv .venv && uv pip install --python .venv/bin/python -e '.[test]'
cd ../web && npm ci && npm run test:e2e
```

**Expected:** Playwright starts the backend and the browser suite runs.

**Actual:** the `webServer` command ran `uvicorn ...` from a login shell whose
`PATH` does not contain the project virtualenv, so the process never started.

**Root cause:** `apps/web/playwright.config.ts` hard-coded
`bash -lc "cd ../api && ... uvicorn tracemap.main:app"`. It assumed `uvicorn`
was installed globally (true in CI after `pip install -e`, false for the
documented local venv setup) and relied on a relative `cd`.

**Fix:** resolve the interpreter from `apps/api/.venv/bin/python` (override with
`TRACEMAP_API_PYTHON`, fall back to `python3` for CI) and launch
`python -m uvicorn ...` with Playwright's `cwd`/`env` options.

**Files:** `apps/web/playwright.config.ts`

**Related tests:** `apps/web/e2e/*.spec.ts` via `npm run test:e2e`.

**Verification:** `npm run test:e2e` → `3 passed (12.4s)` at commit `f0402e2`.

**Prevention:** CI now runs `npm ci`; the harness resolves the interpreter the
same way a developer would. Prefer `cwd`/`env` over `bash -lc "cd ..."`.

**Links:** commit `f0402e2`.

---

## GT-0002 — Default SQLite path is CWD-relative + import side effect creates a stray DB

**Status:** MITIGATED — script-controlled paths are safe; import-time side effect remains
**Class:** Deployment / Database
**Severity:** P1
**First seen:** 2026-11-09
**Environment:** any, commit `58497c2`.

**Symptoms:** a `tracemap-dev.db` file appears in whatever directory imported
`tracemap.main` (it appeared in the repo root during this session); pointing the
API at a relative URL means restarting from a different directory appears to
"lose" all data.

**Minimal reproduction:**
```bash
cd /home/ubuntu/codes/TraceMap
python3 -c "import sys; sys.path.insert(0,'apps/api'); import tracemap.main"   # with TRACEMAP_ENV unset
ls -la tracemap-dev.db   # created relative to the current directory
```

**Expected:** development data persists in one predictable location.

**Actual:** `tracemap.main` defines a module-level `app = create_app()`, which
runs `Base.metadata.create_all()` against the default
`sqlite:///./tracemap-dev.db` **relative to the process CWD**, as a side effect
of *importing* the module.

**Root cause:** `apps/api/tracemap/main.py` — `create_app()` default
`database_url` is `sqlite:///./tracemap-dev.db`; module-level `app = create_app()`.
(The relative path is intentional for the README two-terminal flow, but unsafe
for scripted/CI/restart use.)

**Fix (deployment-level, minimal):** the lifecycle scripts always export an
**absolute** `TRACEMAP_DATABASE_URL` under `$TRACEMAP_RUNTIME_DIR/data/`, so
imports and restarts are location-independent. The import side effect is
documented rather than removed (changing the module bootstrap would affect the
`uvicorn tracemap.main:app` entry point).

**Files:** `scripts/dev-common.sh`, `scripts/dev-start.sh`,
`scripts/smoke-test.sh`; documented here.

**Related tests:** `apps/api/tests/test_linux_smoke.py::test_file_database_persists_across_api_restart`.

**Verification:** `scripts/smoke-test.sh --restart` → project readable after a
full stop/start (`8 passed`) at `3e7c1fd`; `scripts/dev-*` write only under
`$TRACEMAP_RUNTIME_DIR`.

**Prevention:** never rely on the relative default outside the two-terminal
README flow; always set an absolute `TRACEMAP_DATABASE_URL`. `*.db` is
git-ignored so a stray file cannot be committed.

**Links:** commit `ea14213`; `scripts/dev-common.sh`.

---

## GT-0003 — No frontend lockfile → dependency drift

**Status:** RESOLVED
**Class:** Environment / Reproducibility
**Severity:** P2
**First seen:** 2026-11-09
**Environment:** Node 22.23.3, commit `58497c2`.

**Symptoms:** `npm install` resolved different versions than CI had validated;
the pre-cached Playwright browser (Chromium build **1248**) did not match the
freshly-installed `@playwright/test` (which needs build **1254**), triggering a
200 MiB download.

**Minimal reproduction:**
```bash
cd apps/web && ls package-lock.json   # absent
npm install && npx playwright --version    # 1.65.0 although package.json says ^1.54.0
```

**Expected:** identical installs on every machine/CI run.

**Actual:** there was no `package-lock.json`, so `^` ranges floated to latest.

**Root cause:** lockfile was never generated/committed; CI used `npm install`.

**Fix:** commit the generated `apps/web/package-lock.json` and switch CI to
`npm ci` for the web-build and browser-e2e jobs.

**Files:** `apps/web/package-lock.json`, `.github/workflows/ci.yml`.

**Related tests:** CI `web-build` / `browser-e2e` jobs.

**Verification:** `npm ci` → `added 91 packages in 2s`, `npx playwright --version` → `1.65.0` (matches cached Chromium 1254).

**Prevention:** keep the lockfile updated in the same PR that changes
`package.json`; CI uses `npm ci`.

**Links:** commit `023df9a`.

---

## GT-0004 — E2E reused dev servers and a shared database file

**Status:** RESOLVED
**Class:** Test
**Severity:** P1
**First seen:** 2026-11-09
**Environment:** commit `58497c2`.

**Symptoms:** risk of browser tests writing into the real dev SQLite file, and
of two runs colliding on `127.0.0.1:8000` / `/tmp/tracemap-e2e.db`.

**Minimal reproduction:** start `scripts/dev-start.sh`, then run
`npm run test:e2e` with the old config (`reuseExistingServer: !CI`) — Playwright
adopts the developer's API on port 8000.

**Expected:** E2E uses its own backend, database and ports.

**Actual:** the old harness reused any server already on 8000/5173 and used a
fixed `/tmp/tracemap-e2e.db`.

**Root cause:** `playwright.config.ts` `reuseExistingServer: !process.env.CI`
combined with the standard dev ports and a shared DB path.

**Fix:** dedicated E2E ports (API 8010, web 5273 via `--strictPort`) and a
unique throwaway DB (`tracemap-e2e-<pid>-<time>.db`); the dev servers on
8000/5173 are never touched.

**Files:** `apps/web/playwright.config.ts`, `apps/web/vite.config.ts`.

**Related tests:** `apps/web/e2e/research-loop.spec.ts`,
`apps/web/e2e/ui-regression.spec.ts`.

**Verification:** `npm run test:e2e` starts its own uvicorn on `127.0.0.1:8010`
and passes 3/3 while `scripts/dev-start.sh` keeps running on 8000/5173.

**Prevention:** keep E2E ports/DB disjoint from dev; do not reintroduce a shared
`/tmp` database. Clean old files with `rm -f /tmp/tracemap-e2e-*.db`.

**Links:** commit `f0402e2`.

---

## GT-0005 — Oversized `If-Match` revision caused a 500 `OverflowError`

**Status:** RESOLVED
**Class:** Backend / Security
**Severity:** P1
**First seen:** 2026-11-09
**Environment:** FastAPI 0.162.2, SQLAlchemy 2.1.8, SQLite, commit `429afac` (pre-fix `58497c2`).

**Symptoms:** a write with an absurdly large revision returned HTTP 500 with
`OverflowError: Python int too large to convert to SQLite INTEGER`.

**Minimal reproduction:**
```bash
curl -s -o /dev/null -w '%{http_code}\n' -X POST \
  "http://127.0.0.1:8000/api/v1/projects/<pid>/nodes/ops" \
  -H 'Authorization: Bearer dev-<name>' -H 'Content-Type: application/json' \
  -H 'If-Match: "rev-999999999999999999999"' -H 'Idempotency-Key: bigrev-0001' \
  -d '{"operations":[]}'
# before fix: 500 ; after fix: 400
```
(Also reproducible with `python -m pytest`; see the regression test.)

**Expected:** an out-of-range revision is a client error (400/409), never 500.

**Actual:** `int()` parsed an unbounded integer; the CAS
`UPDATE projects SET revision = expected + 1 WHERE revision = expected`
overflowed the SQLite signed-64-bit column.

**Root cause:** `apps/api/tracemap/main.py::create_app.get_revision` used
`re.fullmatch(r'"rev-[0-9]+"', ...)` with no upper bound; `claim_revision`
then wrote `expected + 1`.

**Fix:** bound the parsed value (`MAX_REVISION = 2**53 - 1`, chosen to stay below
the SQLite limit *including the `+1`* and at the JavaScript safe-integer
boundary) and return `400 BAD_REQUEST` when exceeded.

**Files:** `apps/api/tracemap/main.py`.

**Related tests:** `apps/api/tests/test_hardening.py::test_oversized_if_match_revision_is_rejected_without_500`.

**Verification:** `python -m pytest -q apps/api/tests` → `30 passed` at `429afac`;
an endpoint-wide fuzz (all write endpoints, malformed JSON, weird headers) now
reports **no** 5xx.

**Prevention:** bound every client-supplied integer that is bound into SQL;
keep the regression test.

**Links:** commit `429afac`; `docs/BACKEND_OPTIMIZATION_V0.3.md §4`.

---

## GT-0006 — System Python has no `pip` or `venv` on Ubuntu 24.04

**Status:** RESOLVED
**Class:** Environment
**Severity:** P2
**First seen:** 2026-11-09
**Environment:** Ubuntu 24.04.3, Python 3.12.3, no `sudo` password.

**Symptoms:**
```
The virtual environment was not created successfully because ensurepip is not
available ... apt install python3.12-venv
```
and `python3 -m pip` → `No module named pip`.

**Minimal reproduction:**
```bash
python3 -m venv /tmp/x      # fails: ensurepip missing
python3 -m pip --version    # No module named pip
```

**Expected:** a reproducible, isolated backend environment.

**Actual:** `python3-venv`/`python3-pip` are not installed and cannot be
installed without `sudo`.

**Root cause:** minimal Ubuntu image without the venv/pip packages.

**Fix:** use the already-installed `uv` (0.13.5) to create and populate the venv
without root:
```bash
cd apps/api
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -e '.[test]'
```
This matches the README's intent (`python -m venv`/`pip` remain valid where those
packages exist). `scripts/dev-start.sh` fails fast with the exact `uv` command.

**Files:** `scripts/dev-start.sh`; documented in `docs/DEPLOYMENT_LINUX.md`.

**Related tests:** the whole `apps/api/tests` suite runs from this venv.

**Verification:** `uv pip install` → 24 packages; `python -m pytest -q apps/api/tests` → 30 passed.

**Prevention:** prerequisite check in `dev-start.sh`; if `sudo` becomes
available, `sudo apt-get install -y python3.12-venv` also works.

**Links:** `scripts/dev-start.sh`.

---

## GT-0007 — Committing a generation draft replaces the entire map

**Status:** OPEN (behaviour documented; not changed)
**Class:** Backend / Algorithm
**Severity:** P2
**First seen:** 2026-11-09
**Environment:** commit `58497c2` and later.

**Symptoms:** after `POST .../generation-drafts/{id}/commit`, the map root
title becomes the *generation goal*, and any pre-existing manual nodes are gone.

**Minimal reproduction (API level):**
1. Create a project titled `冒烟研究`.
2. Add a text source.
3. `POST /generate` with `{"goal":"可信研究", ...}`.
4. `POST /generation-drafts/{id}/commit`.
5. `GET /export?format=md` → the root heading is `可信研究`, not `冒烟研究`, and
   the map equals the draft exactly.

**Expected (arguably):** replacing the map is explicit, but users may not
realise prior manual structure is discarded.

**Actual:** `commit_draft` does `commit_map(..., d.payload["map"], ...)`, i.e. a
whole-map replacement. The UI button is labelled "确认替换地图" (confirm
**replace** map), and a stale draft is rejected with 409, so the damage is
bounded — but there is no diff/merge and no warning about dropped manual nodes.

**Root cause:** by design in this prototype; `apps/api/tracemap/main.py`
(`commit_draft`) and `core.extractive_draft` (root = `root_map(goal[:160])`).

**Fix:** none in this pass (product decision required). Options: merge-only-add
semantics, or show a removed-node diff before commit.

**Files:** `apps/api/tracemap/main.py`, `apps/web/src/App.tsx` (draft dialog).

**Related tests:** `scripts/smoke-test.sh` asserts the goal-derived heading and
references this entry; `apps/api/tests/test_api.py::test_draft_never_writes_without_commit_and_undo`.

**Verification:** N/A (open). Behaviour is asserted by the smoke test.

**Prevention / next step:** track under G4; if merge is chosen, add a draft-diff
test and update the dialog copy.

**Links:** `docs/IMPLEMENTATION_PLAN.md` (G4).

---

## GT-0008 — Deprecated Starlette `TestClient` + `httpx` pairing

**Status:** OPEN
**Class:** Test
**Severity:** P3
**First seen:** 2026-11-09
**Environment:** Starlette 1.10.0, httpx 0.28.1.

**Symptoms:** every pytest run prints
`StarletteDeprecationWarning: Using httpx with starlette.testclient is deprecated; install httpx2 instead`.

**Expected:** a warning-free suite on supported versions.

**Actual:** the installed Starlette wants `httpx2` for its `TestClient`.

**Root cause:** Starlette's deprecated httpx shim; dependency versions are
unpinned (`httpx>=0.27,<1`). **HYPOTHESIS:** a future Starlette release will
remove the httpx path.

**Fix:** none now (test-only, not blocking). Follow-up: add `httpx2` to the test
extras, or pin Starlette/httpx to a compatible pair.

**Files:** `apps/api/pyproject.toml` (test extra), `apps/api/tests/conftest.py`.

**Related tests:** all of `apps/api/tests`.

**Verification:** `python -m pytest -q apps/api/tests` → `30 passed, 1 warning`.

**Prevention:** treat the warning as a canary; address before the removal lands.

**Links:** upstream Starlette deprecation notice.

---

## GT-0009 — Swagger UI at `/docs` loads assets from a CDN

**Status:** OPEN
**Class:** Frontend / Docs
**Severity:** P3
**First seen:** 2026-11-09
**Environment:** FastAPI 0.162.2, air-gapped browser.

**Symptoms:** offline, `/docs` returns 200 but the page renders blank because
`swagger-ui-bundle.js` / `.css` come from `cdn.jsdelivr.net`.

**Minimal reproduction:** open `http://127.0.0.1:8000/docs` with no internet.

**Expected:** a usable API browser on a local-only host.

**Actual:** HTML depends on CDN assets.

**Root cause:** FastAPI default Swagger UI `swagger_js_url`/`swagger_css_url`.

**Fix:** none now. `/openapi.json` remains fully local and `curl`-friendly, so
the API is still inspectable offline.

**Files:** `apps/api/tracemap/main.py` (if a self-hosted UI is chosen later).

**Related tests:** `scripts/smoke-test.sh` asserts `/docs` returns 200 (HTML),
not that it renders offline.

**Verification:** `curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/docs` → 200.

**Prevention:** if offline docs matter, vendor the Swagger assets and point
`FastAPI(docs_url=...)` / CDN URLs at local files.

**Links:** FastAPI docs on `swagger_js_url`.

---

## GT-0010 — `tsc -b` leaves an untracked `tsbuildinfo`

**Status:** RESOLVED
**Class:** Environment
**Severity:** P3
**First seen:** 2026-11-09
**Environment:** TypeScript 5.9.3, commit `58497c2`.

**Symptoms:** after `npm run build`, `apps/web/tsconfig.tsbuildinfo` shows as
untracked and can be committed by accident.

**Minimal reproduction:**
```bash
cd apps/web && npm run build && git status --short   # ?? apps/web/tsconfig.tsbuildinfo
```

**Expected:** build cache is ignored.

**Actual:** not covered by `.gitignore`.

**Root cause:** `tsc -b` incremental cache; no ignore rule.

**Fix:** add `*.tsbuildinfo` (and `.pi/`) to `.gitignore`.

**Files:** `.gitignore`.

**Verification:** `git status --short` no longer lists it.

**Prevention:** keep build artifacts ignored.

**Links:** commit `023df9a`.

---

## GT-0011 — SQLite DDL/fsync is slow on this host

**Status:** OPEN (environment observation, not a code defect)
**Class:** Environment / Performance
**Severity:** P3
**First seen:** 2026-11-09
**Environment:** ext4 on `/dev/sda3`, busy shared host.

**Symptoms:** `python -m pytest -q apps/api/tests` takes ~40 s; the per-test
`client` fixture setup (which creates the app and its tables) is ~1.7 s.

**Minimal reproduction:**
```python
import sqlite3, time
c = sqlite3.connect("/tmp/x.db"); c.execute("PRAGMA foreign_keys=ON")
t = time.perf_counter()
for i in range(13): c.execute(f"create table if not exists t{i}(id integer primary key, v text)")
c.commit(); print(round(time.perf_counter()-t, 3))   # ~1.2 s here
```

**Expected:** milliseconds.

**Actual:** ~1.2–2.7 s for 13 trivial DDL statements on disk; `create_app` over
**in-memory** SQLite is **23 ms**.

**Root cause:** filesystem/fsync latency on this host (the box runs many other
services). Not application code. **HYPOTHESIS:** general disk contention.

**Fix:** none needed for correctness. For faster local tests one could point
test SQLite files at a tmpfs (e.g. `/dev/shm`), at the cost of persistence
fidelity.

**Files:** n/a (test/DB configuration only).

**Related tests:** all `apps/api/tests`.

**Verification:** in-memory `create_app` 0.023 s vs on-disk 1.99 s.

**Prevention:** do not treat wall-clock test time here as an application SLO.

**Links:** `docs/VERIFICATION_V0.3.md §3`.

---

*Last updated: 2026-11-09. When you resolve an entry, keep it — update the status,
add the fix, files, tests and the verifying commit SHA. Never delete a resolved
entry and never remove the failing test that guarded it.*

---

## GT-0012 — Host override could expose development services

**Status:** RESOLVED — verified by GitHub CI (not a production or private-server certification)
**Class:** Security / Deployment
**Severity:** P0
**First seen:** 2026-11-09
**Environment:** PR #6 at dcc1a13, Linux, shell scripts.

**Symptoms:** `TRACEMAP_WEB_HOST=0.0.0.0 scripts/dev-start.sh` could
launch Vite on all interfaces. The development API accepted similar host
overrides. Fake bearer tokens do not protect public endpoints.

**Minimal reproduction (safe, without starting services):**
`TRACEMAP_WEB_HOST=0.0.0.0 bash scripts/dev-start.sh`
must exit nonzero with `DEV_BIND_UNSAFE` before a service is started.

**Expected:** only 127.0.0.1 is allowed.
**Actual (before):** override values were passed directly to Uvicorn/Vite.
**Root cause:** dev-common exposed host variables without validation.
**Fix:** validate both literal hosts, ports, runtime and SQLite URL before
touching runtime files. Vite also rejects non-loopback proxy targets.
**Files:** scripts/dev-common.sh, scripts/dev-start.sh, apps/web/vite.config.ts.
**Related tests:** scripts/tests/test_dev_safety.py (host and port matrix);
GitHub deployment-lifecycle CI.
**Verification:** [CI #42575575595](https://github.com/1998x-stack/TraceMap/actions/runs/42575575595) — four jobs passed; regression and Linux lifecycle tests completed. Do not mark verified without run URL.
**Prevention:** fail-closed default and regression assertions.
**Links:** PR #6.

## GT-0013 — PID reuse and opaque listener ownership

**Status:** RESOLVED — verified by GitHub CI (not a production or private-server certification)
**Class:** Deployment / Process management
**Severity:** P1
**First seen:** 2026-11-09
**Environment:** PR #6 original scripts.

**Symptoms:** `ss -p` can hide another user's PID while still showing the
listener, incorrectly reporting a port as free. An old PID file that names a
reused process with a matching word could be signalled.

**Minimal reproduction:** mock `ss` output containing LISTEN but no
`pid=...`; `port_state` must return `other` rather than `free`. Record
a PID/starttime pair, alter the starttime, and verify `pid_owned` rejects it.

**Expected:** never reuse or kill a process without verified ownership.
**Actual (before):** listener was inferred solely from parseable PID; stop
trusted a command substring.
**Root cause:** PID-only file and process-name check; hidden listener metadata.
**Fix:** PID + `/proc/PID/stat` starttime, strict loopback listener checks,
serialized lifecycle via flock, and refusal when ownership is uncertain.
Old PID files without a starttime deliberately fail closed: review and stop
legacy services manually before upgrading.
**Files:** scripts/dev-common.sh, scripts/dev-start.sh, scripts/dev-stop.sh,
scripts/dev-status.sh.
**Related tests:** scripts/tests/test_dev_safety.py.
**Verification:** [CI #42575575595](https://github.com/1998x-stack/TraceMap/actions/runs/42575575595) — four jobs passed; regression and Linux lifecycle tests completed.
**Prevention:** preserve process-generation checks and never assume PID-less
`ss` output means a free port.
**Links:** PR #6.

## GT-0014 — Live smoke skipped absent services

**Status:** RESOLVED — verified by GitHub CI (not a production or private-server certification)
**Class:** Test / Deployment
**Severity:** P1
**First seen:** 2026-11-09
**Environment:** PR #6 original smoke-test.sh.

**Symptoms:** when API and Vite were not running, `scripts/smoke-test.sh`
could print SKIP for both and still exit successfully because the throwaway
workflow passed.

**Minimal reproduction:** with no TraceMap listeners, run
`scripts/smoke-test.sh --live-only`; it must return nonzero and report API
and web as missing.
**Expected:** a deployment health check requires a running, owned service.
**Actual (before):** missing services did not increment FAIL.
**Root cause:** SKIP was treated as acceptable for required live checks.
**Fix:** live checks fail when state/identity differs from the owned
loopback instance; a standalone `--live-only` regression path is supported.
**Files:** scripts/smoke-test.sh.
**Related tests:** scripts/tests/test_dev_safety.py and CI lifecycle job.
**Verification:** [CI #42575575595](https://github.com/1998x-stack/TraceMap/actions/runs/42575575595) — four jobs passed; regression and Linux lifecycle tests completed.
**Prevention:** exit nonzero for FAIL or required SKIP.
**Links:** PR #6.

## GT-0015 — E2E server reuse and database override

**Status:** RESOLVED — verified by GitHub CI (not a production or private-server certification)
**Class:** Test / Data isolation
**Severity:** P1
**First seen:** 2026-11-09
**Environment:** Playwright on Linux.

**Symptoms:** the original dedicated E2E ports still used
`reuseExistingServer: !process.env.CI`, so a local port collision could
silently use another developer's listener. `TRACEMAP_E2E_DATABASE_URL` could
override the disposable DB with a persistent one.

**Minimal reproduction:** inspect `apps/web/playwright.config.ts`; test that
`TRACEMAP_E2E_DATABASE_URL=sqlite:////tmp/shared.db` is rejected rather than
used, and a pre-existing E2E listener makes the run fail.
**Expected:** tests never reuse live services or writable user DB files.
**Actual (before):** reuse enabled outside CI and override trusted.
**Root cause:** incomplete isolation on local runner.
**Fix:** reuse always false; mkdtemp unique private DB; reject DB overrides;
validate distinct test ports; clean owned temp directory when runner exits.
**Files:** apps/web/playwright.config.ts.
**Related tests:** browser-e2e CI, test harness startup.
**Verification:** [CI #42575575595](https://github.com/1998x-stack/TraceMap/actions/runs/42575575595) — four jobs passed; regression and Linux lifecycle tests completed.
**Prevention:** never relax the isolation guards to make a failing test pass.
**Links:** PR #6.

## GT-0016 — Restart test inherited database URL

**Status:** RESOLVED — verified by GitHub CI (not a production or private-server certification)
**Class:** Database / Test
**Severity:** P1
**First seen:** 2026-11-09
**Environment:** PR #6 original restart smoke.

**Symptoms:** `scripts/smoke-test.sh --restart` changed
`TRACEMAP_RUNTIME_DIR`, but if the shell exported
`TRACEMAP_DATABASE_URL`, the lifecycle scripts still preferred that URL.

**Minimal reproduction:** configure a test sentinel SQLite outside a temporary
runtime, export its URL, invoke restart test. It must not change the sentinel.
**Expected:** every restart test uses only a new disposable database.
**Actual (before):** inherited DB override remained active.
**Root cause:** API_DB_URL gives precedence to TRACEMAP_DATABASE_URL.
**Fix:** explicitly unset inherited DB URL, allocate dynamic free loopback
ports, and use exit traps for cleanup.
**Files:** scripts/smoke-test.sh.
**Related tests:** CI deployment-lifecycle restart and persistence cycle.
**Verification:** [CI #42575575595](https://github.com/1998x-stack/TraceMap/actions/runs/42575575595) — 8 restart assertions passed; the inherited-db sentinel SHA-256 was unchanged.
**Prevention:** never run destructive tests with unreviewed env overrides.
**Links:** PR #6.

## GT-0017 — Relative commands and unscoped /tmp cleanup

**Status:** OPEN — commands corrected, independent clean-host walkthrough still pending
**Class:** Documentation / Agent reliability
**Severity:** P2
**First seen:** 2026-11-09
**Environment:** new-agent cold start.

**Symptoms:** `AGENTS.md` and the Linux deployment guide ran
`cd apps/web` followed by `scripts/smoke-test.sh`, which is not in the
working directory. Wildcard `rm` commands could remove concurrent test
files under /tmp.

**Minimal reproduction:** follow the old quick-reference command block from
the repo root; smoke script path cannot be resolved after `cd apps/web`.
**Expected:** copy-paste from repo root works and cleanup is owned.
**Actual (before):** path dependent and overly broad.
**Root cause:** command examples did not restore CWD; cleanup not scoped to
one test invocation.
**Fix:** restore repo root before running scripts, remove wildcard cleanup,
and link to unique temp-directory ownership.
**Files:** AGENTS.md, docs/DEPLOYMENT_LINUX.md.
**Related tests:** independent cold-start walkthrough required for final
server acceptance.
**Verification:** documentation paths were corrected; independent fresh-agent reproduction is not yet verified.
**Prevention:** run documentation blocks as scripts in CI when practical.
**Links:** PR #6.

## GT-0018 — Safety tests depended on ambient TRACEMAP variables

**Status:** RESOLVED
**Class:** Test / Reproducibility
**Severity:** P2
**First seen:** 2026-11-09
**Environment:** independent cold-start review of `784511c`, Ubuntu 24.04.3.

**Symptoms:** `python -m unittest discover -s scripts/tests` reported 1 failure
when the shell had exported the documented port variables (as the deployment
guide suggests for a second instance). The failing sub-case expected
`must differ` and instead got `api: port 8123 already in use`.

**Minimal reproduction:**
```bash
cd <repo>
TRACEMAP_API_PORT=8123 TRACEMAP_WEB_PORT=5323 \
  python3 -m unittest discover -s scripts/tests -p 'test_*.py'
# before fix: FAILED (failures=1) in test_start_fails_closed_on_unsafe_host_and_bad_ports
```

**Expected:** deployment contract tests pass (or fail) identically regardless of
the caller's environment.

**Actual:** `run()` cloned `os.environ`, so `TRACEMAP_API_PORT`/`TRACEMAP_WEB_PORT`
leaked into the child; the `{"TRACEMAP_WEB_PORT": "8000"}` matrix row assumed the
API port defaulted to `8000` and no service was listening.

**Root cause:** `scripts/tests/test_dev_safety.py::run` used
`os.environ.copy()` and the matrix relied on implicit defaults.

**Fix:** strip every inherited `TRACEMAP_*` variable before applying per-test
overrides; make the "must differ" case explicit
(`{"TRACEMAP_API_PORT": "8000", "TRACEMAP_WEB_PORT": "8000"}`); add a
hermeticity regression test.

**Files:** `scripts/tests/test_dev_safety.py`.

**Related tests:**
`DeploymentSafetyTests::test_safety_harness_ignores_ambient_tracemap_environment`.

**Verification:** 8 tests pass both without and with
`TRACEMAP_RUNTIME_DIR/API_PORT/WEB_PORT` exported.

**Prevention:** never depend on ambient environment in contract tests; assert
that the harness strips it.

**Links:** commit `1182bc1` (this review).

---

## GT-0019 — Deployment guide left the shell in `apps/web`

**Status:** RESOLVED
**Class:** Documentation / Agent reliability
**Severity:** P2
**First seen:** 2026-11-09
**Environment:** independent cold-start review of `784511c`.

**Symptoms:** following `docs/DEPLOYMENT_LINUX.md` verbatim, the last setup step
runs in `apps/web`, so the very next §3 command fails:
`scripts/dev-start.sh: No such file or directory` (exit 127).

**Minimal reproduction:**
```bash
cd <repo>/apps/web && scripts/dev-start.sh      # exit 127
```

**Expected:** every copy-paste block from the guide works in order.

**Actual:** §2 ended in `apps/web`; §3 used repository-root-relative paths.

**Root cause:** missing `cd` back to the repository root between §2 and §3.

**Fix:** add `# 4. return to the repository root` / `cd ../..` to the setup
block, state that `scripts/…` paths are repo-root relative, and add an
alternate-port example.

**Files:** `docs/DEPLOYMENT_LINUX.md`.

**Related tests:** the independent cold-start walkthrough in this review follows
the guide verbatim.

**Verification:** the corrected guide was executed end to end from a fresh clone
(see PR comment / GT-0017).

**Prevention:** keep a single documented working directory; run documentation
command blocks in CI where practical (GT-0017).

**Links:** `PR #6` documentation commit (this review).

---

## GT-0020 — Locked SQLite returned an opaque non-JSON 500

**Status:** RESOLVED
**Class:** Backend / Reliability / Security
**Severity:** P2
**First seen:** 2026-11-09
**Environment:** SQLAlchemy 2.1.8, SQLite, commit `784511c`.

**Symptoms:** while the SQLite file was write-locked by another process, a write
returned HTTP 500 with the plain-text body `Internal Server Error` after a ~20 s
stall. The response was not the unified JSON error envelope, so a client could
not tell "retry later" from a real bug; diagnosis required reading server logs.
No database internals were leaked.

**Minimal reproduction:** start the API on a file database, hold an exclusive
write lock, then:
```bash
curl -s -o body.txt -w '%{http_code}\n' -X POST \
  "http://127.0.0.1:8207/api/v1/projects/<pid>/nodes/ops" \
  -H 'Authorization: Bearer dev-<name>' -H 'Content-Type: application/json' \
  -H 'If-Match: "rev-0"' -H 'Idempotency-Key: lock-op-0001' \
  -d '{"operations":[{"op":"rename","nodeId":"<root>","title":"x"}]}'
# before fix: 500 "Internal Server Error"; after fix: 503 {"error":{"code":"STORAGE_BUSY",...}}
```

**Expected:** a structured error with a stable code and `retryable` flag, no
driver/SQL text, and a prompt failure.

**Actual:** unhandled `sqlalchemy.exc.OperationalError` reached Starlette's
default 500 handler; the pysqlite busy `timeout` was hardcoded to 20 s.

**Root cause:** no exception handler for `SQLAlchemyError`; fixed
`connect_args={"timeout": 20}` in `db.engine_for`.

**Fix:** add a pure `storage_error_status()` mapper
(`locked` `OperationalError` → `503 STORAGE_BUSY retryable=true`; other
`SQLAlchemyError` → `500 STORAGE_ERROR`; anything else → `500 INTERNAL_ERROR`),
register handlers that log the traceback server-side and return the unified JSON
envelope, and make the SQLite busy wait configurable via
`TRACEMAP_SQLITE_TIMEOUT` (default 20 s).

**Files:** `apps/api/tracemap/main.py`, `apps/api/tracemap/db.py`.

**Related tests:**
`test_storage_error_status_mapping_is_pure_and_safe`,
`test_locked_database_returns_structured_retryable_error`.

**Verification:** `python -m pytest -q apps/api/tests` → **34 passed**; the
locked-DB test asserts 503 + `retryable=true` + absence of `locked`/`sqlite` in
the body, and that the database is writable again once the lock is released.

**Prevention:** keep every error on the unified envelope, never echo driver text,
and keep timeouts configurable for tests/ops.

**Links:** commit `771b3f4` (this review).

## GT-0021 — `crypto.randomUUID is not a function` on a plain-HTTP LAN origin

**Status:** RESOLVED
**Class:** Frontend / Deployment (secure context)
**Severity:** P1
**First seen:** 2026-11-09
**Environment:** Chromium, `http://192.168.169.223:5173` (LAN IP, plain HTTP), commit `c7ef5fd`.

**Symptoms:** when the workbench is opened from another machine on the LAN, the
UI loads but **every write fails**: the feedback banner shows
`!crypto.randomUUID is not a function` and no project/source can be created
(GET requests still render fine).

**Minimal reproduction:**
```bash
# API on loopback, Vite bound to the LAN IP
scripts/dev-start.sh
apps/web/node_modules/.bin/vite apps/web --host 192.168.169.223 --port 5173 --strictPort
# in a browser on another machine: http://192.168.169.223:5173 → 创建研究项目
```
In the console: `window.isSecureContext === false`, `typeof crypto.randomUUID === 'undefined'`
(but `crypto.getRandomValues` is a function).

**Expected:** the workbench works over the LAN.

**Actual:** `crypto.randomUUID` is a **secure-context-only** API. `127.0.0.1`,
`localhost` and HTTPS are secure contexts; a plain-HTTP **LAN IP is not**, so the
property is absent and each `Idempotency-Key` generation threw.

**Root cause:** `apps/web/src/api.ts` used `const key = () => crypto.randomUUID();`
with no fallback.

**Fix:** add `newId()` — use `crypto.randomUUID` when available, otherwise build
an RFC 4122 v4 UUID from `crypto.getRandomValues` (available in insecure
contexts), with a `Math.random` last resort.

**Files:** `apps/web/src/api.ts`.

**Related tests:** `apps/web/e2e/insecure-context.spec.ts` (removes
`crypto.randomUUID` before load, then performs two writes).

**Verification:** Playwright against the real LAN origin reported
`isSecureContext=false`, `randomUUID=undefined`, and successfully created a
project ("新项目已创建"); `npm run test:e2e` → **5 passed**.

**Prevention:** keep the E2E stubbing `randomUUID`; if HTTPS is ever added this
becomes moot, but the fallback stays harmless. Any future `crypto.subtle` usage
would have the same secure-context constraint — plan to terminate TLS for LAN use.

**Links:** commit `ebbec19`.

## GT-0022 — Reasoning-model truncation broke LLM generation intermittently

**Status:** RESOLVED
**Class:** Backend / LLM provider
**Severity:** P2
**First seen:** 2026-11-09
**Environment:** `iagent/standard` (OpenAI-compatible reasoning model), `.env`
`TRACEMAP_GENERATION_MODE=llm`, first real end-to-end generate call.

**Symptoms:** `POST /api/v1/projects/{pid}/generate` intermittently returned
`502 LLM_INVALID_OUTPUT · 模型输出不是合法 JSON` after ~40 s, while other calls
succeeded. The draft was never created.

**Minimal reproduction:**
```bash
# repeat a real generate; roughly 1 in 3 attempts hit max_tokens
for i in 1 2 3; do curl -sS -X POST .../generate -H 'Authorization: Bearer dev-<name>' \
  -H 'If-Match: "rev-1"' -H 'Idempotency-Key: gt22-'$i'00' -d '{...}'; echo; done
```

**Expected:** a deterministic success, or a clear, diagnosable failure.

**Actual:** the model spent the entire `max_tokens` (4096) budget on *hidden
reasoning* (`finish_reason=length`), so the JSON object was cut off mid-string:
`Unterminated string starting at ... char 838`. The adapter reported it as a
generic "not valid JSON", hiding the real cause.

**Root cause:** `apps/api/tracemap/llm.py::_chat` ignored `finish_reason` and
defaulted `max_tokens` to 4096 — too small for a reasoning model. Measured:
attempt 1 `finish=length len=848` (fail), attempts 2–3 `finish=stop` (ok).

**Fix:** detect `finish_reason == "length"` and raise `LLM_OUTPUT_TRUNCATED`
(502, retryable) instead of a misleading parse error; retry once automatically
(in `draft_from_llm`); raise the default budget to `TRACEMAP_LLM_MAX_TOKENS=8192`.

**Files:** `apps/api/tracemap/llm.py`; `.env` / `.env.example`.

**Related tests:** `test_chat_detects_truncated_output`,
`test_draft_from_llm_retries_truncation`.

**Verification:** after the fix a real generate succeeded (~33 s, 10 nodes,
**0** dropped anchors, 4646 tokens) and the regression tests pass
(`python -m pytest -q apps/api/tests/test_llm.py` → 9 passed).

**Prevention:** always inspect `finish_reason`; keep a generous output budget for
reasoning models; retry once before surfacing an error.

**Links:** `docs/LLM_PROVIDER.md`; commit `7efe4fd`; follow-up in PR #7.

**Follow-up — second occurrence (same day).** The error resurfaced on a real
5580-character Markdown source. Measurement showed the model spent the *entire*
budget on hidden reasoning and returned **no content at all**, even at the
provider's documented maximum of 16384 tokens (`finish_reason=length,
content_len=0`) — so raising `max_tokens` cannot fix it. The real cause was an
**open-ended prompt**. Tightening the system prompt (JSON only, "do not write any
analysis/reasoning", at most 12 nodes, title ≤60 / note ≤40 chars, and demanding
the JSON immediately as the last user line) made the same document succeed:
`finish=stop`, ~1.6–4.0k completion tokens, 12 grounded nodes, **0** dropped
anchors. New constants `MAX_LLM_NODES=12`, `MAX_LLM_NOTE_CHARS=240`; the error
message now states the model returned nothing because reasoning exhausted the
budget. Regression tests: `test_system_prompt_forces_concise_json_only_output`,
`test_build_tree_caps_node_count_and_note_length`.

---

## GT-0023 — Markdown export does not convey node type, notes or verification

**Status:** OPEN (product decision required)
**Class:** Export / Frontend
**Severity:** P3
**First seen:** 2026-11-09
**Environment:** reviewed on a real LLM draft committed to the map.

**Symptoms:** in `GET /export?format=md`, every non-topic node renders as an
identical `###` heading. A `counterpoint`, a `question`, an `evidence` node and a
`claim` are indistinguishable, node `note` text is absent, and a node's
`verified_by_user` state is not shown anywhere in the file.

**Minimal reproduction:**
```bash
curl -sS "$B/api/v1/projects/$PID/export?format=md" -H "$AUTH"
# headings are all "### <title>"; only the evidence appendix carries anchorStatus
```

**Expected (arguably):** a reader of the export can tell node types and which
nodes a human verified.

**Actual:** `core.markdown_export` emits heading levels for hierarchy plus an
evidence appendix (source title · paragraph id prefix · `anchorStatus` ·
verbatim quote). This keeps headings clean for Xmind Markdown import — a
deliberate trade-off — but loses type/verification/note.

**Root cause:** by design in `core.markdown_export`; the format targets Xmind
compatibility rather than full-fidelity round-trip.

**Fix:** none yet. Options: (a) append a compact `— [type · verification]` suffix
in the appendix lines only; (b) add an opt-in `format=md-full`; (c) leave as is.
Changing headings risks polluting Xmind node text.

**Files:** `apps/api/tracemap/core.py` (`markdown_export`).

**Related tests:** `apps/api/tests/test_core.py::test_degrade_deleted_source_and_export`,
`apps/api/tests/test_api.py::test_export_md_and_json`, `scripts/smoke-test.sh` md check.

**Verification:** sample export reviewed (PR #6 comment). Not a regression.

**Prevention / next step:** decide the format; if labels are added, extend the
export tests and keep existing heading substrings stable.

**Links:** PR #6; `docs/LLM_PROVIDER.md`.

---

## GT-0024 — Model claims with invalid or out-of-scope anchors survived

**Status:** RESOLVED — tested in GitHub CI on Ubuntu (not a private-server validation)
**Class:** Algorithm / Evidence integrity
**Severity:** P1
**First seen:** 2026-11-09
**Environment:** PR #7 `llm.py::build_tree` at `701cb335`.

**Symptoms:** a model-produced claim with nonexistent `paragraphId`, empty
`exactQuote` or an out-of-scope source can survive as a candidate node with
`evidenceRefs: []`. A source within the same project but not supplied in
`sourceIds` can also pass the full-project paragraph index check.

**Minimal reproduction:** feed `build_tree` a valid first proposal, then
a second claim with a forged paragraph or a `sourceId` not in `source_titles`.
Inspect the candidate titles; before the fix, the unsupported claim remained.

**Expected:** only model claims that cite a verbatim quote from an explicitly
selected source should appear as candidate claims.
**Actual (before):** bad anchors were dropped, but their claim nodes remained.
**Root cause:** validation cleared refs without rejecting the node, and
the evidence lookup was broader than the selected source scope.
**Fix:** all model-proposed nodes must have an anchored, selected-source
reference; count and skip malformed/out-of-scope candidates. If none survive,
return `LLM_INVALID_OUTPUT` without mutating the saved map.
**Files:** `apps/api/tracemap/llm.py`, `apps/api/tests/test_llm.py`.
**Tests:** test_build_tree_keeps_valid_refs_and_drops_hallucinated,
test_build_tree_excludes_valid_anchor_from_unselected_source,
test_all_ungrounded_model_candidates_fail_closed.
**Verification:** CI pending; no live LLM provider call is used in these
deterministic tests.
**Prevention:** fail closed on missing evidence; keep selected-source scopes
in the model response validation layer.
**Limitation:** an exact quote only proves textual presence, not that the
candidate's assertion is logically entailed by the quote.

## GT-0025 — Synchronous generation looked frozen

**Status:** RESOLVED — tested in GitHub CI on Ubuntu (not a private-server validation)
**Class:** Frontend / Generation UX
**Severity:** P2
**First seen:** 2026-11-09
**Environment:** PR #7 synchronous `/generate` endpoint; real model calls
reported around 33 seconds, with default upstream timeout up to 180 seconds
and a single retry for truncated output.

**Symptoms:** the interface showed only generic `正在处理…`, while the
candidate draft request was blocked awaiting a slow response.

**Minimal reproduction:** use Playwright to delay the `/generate` response
for >2 seconds; observe the prior map button/header without any elapsed time
or granular request/wait/draft retrieval feedback.

**Expected:** the user sees a truthful elapsed timer, waiting state and
an explicit explanation that the model may take time.
**Actual (before):** no generation-specific progress status.
**Root cause:** a single global busy boolean masked synchronous network work.
**Fix:** `GenerationProgress` component with explicit client-observed
waiting/reading phases, elapsed time, indeterminate (non-percent) indicator,
slow request explanation, duplicate-request lock and full cleanup on errors.
**Files:** `apps/web/src/App.tsx`,
`apps/web/src/components/GenerationProgress.tsx`,
`apps/web/src/academic-theme.css`,
`apps/web/e2e/generation-progress.spec.ts`.
**Tests:** delayed success, upstream error, LLM-label and 390px layout
Playwright cases.
**Verification:** [CI run #42591405795](https://github.com/1998x-stack/TraceMap/actions/runs/42591405795) completed with 50 Python and 9 Chromium tests passed.
**Prevention:** do not invent server-side completion percent. A future durable
job must report real states through polling or authorized events.
**Limitation:** the current client has no precise backend progress, cancellation
or cross-reload recovery; those require a queued job architecture.

See `docs/UI_ACADEMIC_GENERATION_V0.4.md` for design and behavior contracts.

---

## GT-0026 — Shell dotenv loader overwrote explicit empty environment variables

**Status:** RESOLVED — tested in GitHub CI (not a private-server audit)
**Class:** Linux Deployment / Configuration consistency
**Severity:** P1
**First seen:** 2026-11-09
**Environment:** PR #7 `scripts/dev-common.sh` vs `tracemap/config.py`.

**Symptoms:** with `TRACEMAP_LLM_API_KEY=''` explicitly exported and a key
specified in `.env`, the Python loader preserves the empty value, but the
Bash launcher imported the file value instead. Whitespace in key values also
had inconsistent handling. This can unexpectedly enable a configured provider.

**Minimal reproduction:** source `scripts/dev-common.sh` with a temporary
`TRACEMAP_ENV_FILE`, an exported empty `TRACEMAP_TEST_EMPTY`, and a nonempty
value for that key in the file. Before this change, the shell value was
overwritten even though the variable was explicitly set.

**Expected:** explicit operator environment variables (including empty ones)
always take precedence over the .env file, exactly as in `config.py`.
**Actual (before):** `[[ -z "${!key:-}" ]]` treated an empty but defined
variable as absent.
**Root cause:** the shell loader checked value emptiness rather than whether
the variable was set, and omitted Python's `value.strip()` behavior.
**Fix:** switch to `[[ ! -v "$key" ]]` and trim value whitespace before
removing matched quotes.
**Files:** `scripts/dev-common.sh`, `apps/api/tests/test_config.py`.
**Related tests:** `test_shell_dotenv_respects_explicit_empty_env_and_trims_values`.
**Verification:** [CI #42592992349](https://github.com/1998x-stack/TraceMap/actions/runs/42592992349) — 51 Python tests and 8 Linux deployment safety tests passed, including this cross-language precedence regression.
**Prevention:** retain cross-language configuration parity tests; never log
actual `TRACEMAP_LLM_API_KEY` values.

**Scope:** this prevents accidental overwrite at shell startup. It does not
replace production secret management or a security audit of arbitrary
operator-configured LLM URLs.

---

## GT-0027 — Truncation retry reused the same token budget

**Status:** RESOLVED — verified in GitHub CI (Linux runner)
**Class:** Backend / LLM reliability and cost control
**Severity:** P1
**First seen:** 2026-11-09
**Environment:** PR #7 LLM provider adapter; OpenAI-compatible reasoning models.

**Symptoms:** the provider returns finish_reason=length, TraceMap reports
LLM_OUTPUT_TRUNCATED, retries once, but the second request has exactly the
same max_tokens and may fail in the same way. A larger configured default
alone is not a robust recovery strategy when the current model/provider needs
more completion budget.

**Minimal reproduction:** set TRACEMAP_LLM_MAX_TOKENS=4096; inject a transport
that records the budget and raises LLM_OUTPUT_TRUNCATED on the first call.
Before the fix the recorded sequence was [4096, 4096].

**Expected:** one bounded retry with a larger completion budget; if the ceiling
is still insufficient, return a useful actionable error and do not create a
partial draft.
**Actual (before):** retry reused the initial budget and repeated the same
failure.
**Root cause:** the retry loop repeated the transport call without changing
config["max_tokens"].
**Fix:** first attempt defaults to 8192; after finish_reason=length, retry
once with up to 2× the initial budget, capped by
TRACEMAP_LLM_RETRY_MAX_TOKENS (default 16384). If the provider truncates
again, or the configured ceiling equals the initial budget, stop and return
LLM_OUTPUT_TRUNCATED with the reached budget and configuration guidance.
The prompt also limits output to 16 concise nodes, 240-character notes and
1200-character exact quotes to reduce avoidable output volume.
**Files:** apps/api/tracemap/llm.py, apps/api/tests/test_llm.py,
.env.example, docs/LLM_PROVIDER.md.
**Tests:** token escalation, custom ceiling, ceiling exhaustion and no
same-budget retry.
**Verification:** [CI #42595375357](https://github.com/1998x-stack/TraceMap/actions/runs/42595375357) passed 54 Python tests, 12 Chromium E2E tests, frontend build, 31 Linux smoke checks and 8 restart checks.
**Prevention:** use the smallest adequate first budget and an explicit,
provider-compatible retry ceiling; monitor actual usage and costs.
**Limitation:** the provider's context/output ceiling still applies. If it
rejects the larger budget, configure a supported ceiling or reduce the selected
source scope. A token retry is bounded but can increase request cost.


---

## GT-0028 — Source delete left derived evidence in live records

**Status:** RESOLVED — regression tests added; verify the Phase 0 PR checks before deployment
**Class:** Data lifecycle / privacy
**Severity:** P1
**First seen:** 2026-11-09
**Environment:** Phase 0 source deletion review; DELETE /api/v1/projects/{pid}/sources/{sid}.

**Symptoms:** deleting Source and Paragraph rows removed the original text but left
copied exactQuote values in Project.map_json, Draft.payload, and
Change.before_json / Change.after_json. Markdown/JSON exports could continue
to expose the quote, and old draft payloads could still be read.

**Reproduction:** create a source containing a unique sentinel; cite it from a
map node; generate a draft; create a map revision; delete the source; search
the live project map, all Draft payloads, every Change snapshot and both export
formats for the sentinel. Before the fix, the API returned success while the
sentinel remained in derived rows.

**Expected:** deletion is an irreversible logical purge. Remove nodes citing
the source and their descendants from the current map and every historical map
snapshot; invalidate and clear all project drafts; remove the Source/Paragraph
rows; record a source-delete audit event whose snapshots are already scrubbed.
The operation is atomic in one database transaction.

**Fix:** purge_source() removes evidence-linked subtrees conservatively,
reindexes remaining siblings, and preserves the structural root. The API
scrubs every Change snapshot and replaces every Draft payload with a minimal
invalidation marker before deleting the Source. A purged draft cannot be
committed. The response identifies deletionMode=permanent_purge and reports
purged node / invalidated draft counts.

**Important limitation:** this is logical deletion from live SQLite rows and
API-visible exports, not forensic secure erasure. SQLite WAL/free pages,
filesystem snapshots and external backups may retain old bytes. Do not promise
secure erasure until encrypted storage, key destruction and backup expiry are
implemented. Manually authored text with no evidence reference cannot be
reliably attributed to a source; source-linked claims and descendants are
removed, but the system cannot infer arbitrary paraphrases without provenance.

**Prevention:** preserve this end-to-end sentinel test. Any new cache, search
index, job payload or derived table containing source text must be added to the
same purge transaction or have an explicit retention contract.

---

## GT-0029 — PDF extraction ran inside the API process

**Status:** RESOLVED — process worker and resource-limit tests added; verify the Phase 0 PR checks
**Class:** Upload handling / availability
**Severity:** P1
**First seen:** 2026-11-09
**Environment:** POST /api/v1/projects/{pid}/sources for PDF uploads.

**Symptoms:** synchronous pypdf extraction ran inside the async API handler.
A complex PDF could block the event loop; the 10 MB upload limit and 100-page
limit did not bound CPU time or address-space consumption.

**Expected:** parse outside the API process with a hard wall-clock timeout,
CPU limit, address-space limit, page count and extracted-text cap. The API must
remain responsive and terminate an over-time worker.

**Fix:** tracemap.pdf_worker.parse_pdf_isolated() starts a fresh spawned child,
applies POSIX RLIMIT_CPU and RLIMIT_AS, returns only extracted page text,
and terminates/kills the child when the wall-clock deadline expires. Upload
ownership, idempotency replay and source-count quota are checked before parser
work; parsing is dispatched off the event loop.

**Important limitation:** this is a separate process under the same OS user,
not a container/UID/seccomp sandbox. It does not provide malware scanning or
network/filesystem isolation. Public hostile uploads remain blocked until a
dedicated unprivileged worker/container and storage policy exist.

**Prevention:** keep the worker timeout/resource tests, retain file/page/text
limits, and never move PdfReader extraction back into the API request process.

---

## GT-0030 — Dev API trusted loopback proxy metadata

**Status:** RESOLVED — regression tests added; verify the Phase 0 PR checks
**Class:** Development security boundary
**Severity:** P1
**First seen:** 2026-11-09
**Environment:** dev-only FastAPI middleware with fake Bearer dev-* identity.

**Symptoms:** the middleware accepted any request whose TCP peer was loopback.
A same-host reverse proxy could therefore forward a remote request to
127.0.0.1; the old middleware did not reject forwarded headers or an external
Host value.

**Expected:** the local development API rejects common forwarding/client-IP
headers and non-local Host values, in addition to requiring a loopback peer.
It must never trust X-Forwarded-For as proof of the original client.

**Fix:** middleware rejects Forwarded, X-Forwarded-*, X-Real-IP,
CF-Connecting-IP, True-Client-IP, and related headers, checks the Host
allowlist, and retains the loopback peer check.

**Important limitation:** application middleware cannot distinguish a
same-host reverse proxy that strips every forwarding header and rewrites Host
to localhost. This remains a local-development-only service. Never put it
behind Nginx/Caddy/another proxy, never expose the API/Vite ports, and never
use Bearer dev-* as production authentication.

**Prevention:** use the documented loopback-only launcher or an SSH tunnel.
A real externally reachable deployment requires managed authentication,
revocable sessions, trusted proxy configuration and a separate production
security review.
