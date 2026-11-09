# TraceMap

**Evidence-first AI research maps** · 证据可追溯的思维导图工作台

> **Engineering prototype v0.2 UI iteration — LOCAL DEVELOPMENT ONLY.** The code here is not a production SaaS, does **not** call an LLM, and must not be published as an authenticated service. AI generation is an explicitly labelled deterministic extractive demo.

**Product specification:** [PRD](https://github.com/1998x-stack/projects/blob/main/projects/knowledge/llm-xmind/reports/prd-mvp-v1.0.md) · [Architecture](https://github.com/1998x-stack/projects/tree/main/projects/knowledge/llm-xmind/design) · [Live test plan](docs/IMPLEMENTATION_PLAN.md).

## What is implemented

- Project creation, listing, read and deletion with local dev-identity isolation; SQLite persistence.
- Text, Markdown and text-layer PDF source parsing with 5-source, 10MB/file and 80k-character/project limits.
- Deterministic UTF-8/NFC paragraphs with stable IDs, exact Unicode codepoint quote anchors, server-side provenance validation.
- Editable tree: add, rename, move, delete, verify and attach evidence via atomic operations; 120 nodes and depth-5 structural constraints.
- Whole-project revision and `If-Match` optimistic concurrency, scoped idempotency and undo of the latest map change.
- Read-only generation drafts and Patch proposals (rule-based **demo**, not a model); explicit human commit; revision safety.
- UTF-8 Markdown and JSON export; React Flow research canvas with typed semantic nodes, evidence/source inspector, clear verification states, responsive mobile onboarding + hierarchy outline, and review-before-apply patch dialogue.
- API unit/integration tests and GitHub Actions for Python tests, frontend type/build checks, and Chromium end-to-end workflow + responsive UI checks.

## Quick start (local only)

Requires Python >= 3.12, Node >= 22 and npm. In two terminals:

```bash
# Terminal A
cd apps/api
python -m venv .venv
source .venv/bin/activate
pip install -e '.[test]'
TRACEMAP_ENV=development uvicorn tracemap.main:app --host 127.0.0.1 --port 8000 --reload

# Terminal B
cd apps/web
npm install
npm run dev
```

Open `http://127.0.0.1:5173` (frontend) or `http://127.0.0.1:8000/docs` (development API). The demo header `Authorization: Bearer dev-alice` is **not secure authentication**; it must never be deployed beyond the local loopback interface.

For a scripted, restart-safe local deployment on Linux — including start/stop/status/smoke scripts, an SSH-tunnel access recipe, backup/restore and a fault knowledge base — see [Linux local deployment](docs/DEPLOYMENT_LINUX.md) and [gotchas](docs/gotchas.md). Contributors and agents should start with [AGENTS.md](AGENTS.md).

## Test

```bash
cd apps/api
pip install -e '.[test]'
pytest -q

cd ../web
npm install
npm run build
npx playwright install chromium
npm run test:e2e
```

## Code categories

```text
TraceMap/
├── apps/
│   ├── api/              # FastAPI HTTP API, domain rules, SQLite dev storage
│   │   ├── tracemap/     # domain, storage and routes
│   │   └── tests/        # API and domain invariant tests
│   └── web/              # React + TypeScript + React Flow
│       └── src/          # canvas, inspector, workflows and API client
├── packages/
│   └── contracts/        # API contract notes; sync pending
├── infra/                # production infra placeholders
├── docs/                 # gate-by-gate roadmap, ADR and testing status
├── scripts/              # future developer tooling
└── .github/workflows/    # automated CI checks
```

## UI design system

The v0.2 UI redesign is documented in [UI design system](docs/UI_DESIGN_SYSTEM.md). It is a real React/TypeScript implementation—not a generated mockup—and is tested with desktop/mobile Chromium screenshots in CI. The visual hierarchy keeps original evidence, user verification, and uncommitted AI/rule suggestions visibly distinct.

## Backend and algorithm v0.3 hardening (2026-11-09)

- [Algorithm/evidence retrieval spec](docs/ALGORITHM_OPTIMIZATION_V0.3.md): exact Unicode anchors, quote SHA-256, source-balanced goal relevance, protected subtree rules, synthetic evaluation limits.
- [Backend transactions/security spec](docs/BACKEND_OPTIMIZATION_V0.3.md): strict payload validation, CAS/idempotency, 20-event metadata history, source lifecycle audit, verification invalidation and rollout blockers.
- [Reproducible test report](docs/VERIFICATION_V0.3.md): red/green proof, adversarial API tests and synthetic microbenchmark.

Implemented OpenAPI snapshot: [`packages/contracts/openapi.generated.json`](packages/contracts/openapi.generated.json); use `python scripts/export_openapi.py --check` to detect stable route-signature drift (not full DTO-schema compatibility).

Run `python scripts/benchmark_domain.py` for the deterministic **lexical-only** microbenchmark. `GET /api/v1/projects/{pid}/history` returns 20 recent change metadata entries, without exposing raw source contents. Source removal currently **does not guarantee erasure of quotes already copied into maps/drafts/history snapshots**; do not claim production-grade deletion or publish the dev API publicly.

## Status & transparency

| Area | State |
| --- | --- |
| Core domain + API unit/integration tests | **27 passed** on [CI](https://github.com/1998x-stack/TraceMap/actions/runs/42567240816) |
| React Flow interface | **Build passed; Chromium E2E 3 passed** on [CI](https://github.com/1998x-stack/TraceMap/actions/runs/42567240816) |
| Real LLM generation and rich AI Patch | **Not implemented**; extractive/rule demo only |
| External authentication + privacy controls | **Not implemented**; production blocked |
| Isolated job worker + PostgreSQL + S3 | **Not implemented** |
| Production release / real Xmind import testing | **Not implemented** |

No claims of model accuracy, Xmind compatibility, customer usage, security accreditation, or PMF are made. See [implementation gates](docs/IMPLEMENTATION_PLAN.md).

**Tracked next gates:** [G1 auth/isolated uploads](https://github.com/1998x-stack/TraceMap/issues/1) · [G2 durable database/jobs](https://github.com/1998x-stack/TraceMap/issues/2) · [G3 grounded LLM](https://github.com/1998x-stack/TraceMap/issues/3) · [G4 full Patch](https://github.com/1998x-stack/TraceMap/issues/4) · [G5 Xmind and release](https://github.com/1998x-stack/TraceMap/issues/5).
