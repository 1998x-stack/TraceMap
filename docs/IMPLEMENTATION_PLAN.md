# TraceMap implementation gates

Status key: **PASS** = tested; **PARTIAL** = prototype behavior, remaining work; **NOT STARTED** = placeholder only.

| Gate | Scope | Evidence / stage |
| --- | --- | --- |
| G0 — structure + contracts | Monorepo structure, ADR, dev README, CI, deterministic validators | [CI PASS](https://github.com/1998x-stack/TraceMap/actions/runs/42553780626): 14 Python tests, strict frontend build and 1 Chromium E2E |
| P0 — prototype safety | Local-only API boundary; source logical purge; legacy residue sweep; resource-limited PDF child process | **PASS in CI** (run 42606956716); live Linux host inspection NOT RUN |\n| G1 — sources | Project CRUD; dev-only identity isolation; SQLite persistence; inline text/MD/PDF; stable paragraph anchors; quotas | Process/resource-limited PDF parser is implemented; dedicated unprivileged sandbox, managed auth and private object storage remain open (PARTIAL) |
| G2 — map | React Flow canvas; manual add/rename/delete/verify; revision control; idempotency; rollback; JSON/MD export | Local API tests; frontend build via CI; move/reorder UI and full history screen pending (PARTIAL) |
| G3 — LLM generation | Provider adapter; cost budget; untrusted document handling; schema validation; durable generation jobs | NOT STARTED — extractive demonstration draft only, clearly labelled |
| G4 — AI Patch | Real LLM operations; per-op Diff dependencies; TTL; protected edits; 409; atomic apply | PARTIAL — rule-based question proposals with opt-in apply; no LLM or real condense |
| G5 — production/research | Secure identity; PostgreSQL migration; private S3; dedicated UID/container PDF sandbox; user study; Xmind import matrix | NOT STARTED; explicit production guard prevents accidental public launch |

## Verified baseline (2026-11-09)

- [CI run 42553780626](https://github.com/1998x-stack/TraceMap/actions/runs/42553780626): Python API passed **14 tests**, TypeScript/Vite build passed, Playwright Chromium E2E **1 passed**.
- Browser test covers source→draft preview→commit→citation→Patch preview→apply→undo→Markdown. This does **not** validate real LLM behavior or Xmind import.
- Open implementation issues: [G1](https://github.com/1998x-stack/TraceMap/issues/1), [G2](https://github.com/1998x-stack/TraceMap/issues/2), [G3](https://github.com/1998x-stack/TraceMap/issues/3), [G4](https://github.com/1998x-stack/TraceMap/issues/4), [G5](https://github.com/1998x-stack/TraceMap/issues/5).

## Test exit criteria for the current prototype

1. `python -m pytest -q apps/api/tests`: every unit and integration test must pass.
2. `npm run build` in `apps/web`: strict TypeScript + Vite bundle build must pass on CI.
3. `npm run test:e2e` in `apps/web`: Chromium must exercise the entire local happy path and produce a trace on failure.
4. Confirm cross-user IDOR returns 404; forged anchor returns 422; stale writes return 409; mock draft/patch cannot change map without confirmation.
5. Verify README links and all source files exist on GitHub; CI green on the final head commit.
6. Future gates are **not marked complete** on the strength of scaffold code alone.

## Hardening update v0.3 (2026-11-09)

- [Algorithm](ALGORITHM_OPTIMIZATION_V0.3.md) + [Backend](BACKEND_OPTIMIZATION_V0.3.md) + [verification](VERIFICATION_V0.3.md): malformed JSON 500 regression tests, sub-tree AI scope validation, source-add/delete revision audit, verified-claim invalidation, lexical source-balanced paragraph ranking and synthetic performance benchmark.
- This is an incremental G0/G1/G2 **development hardening pass**, not full G1 (managed authentication, private object storage and dedicated sandbox), G2 (PostgreSQL/durable jobs) or G3/G4 (true LLM) completion.\n\n## Phase 0 verification (2026-11-09)\n\n- [PR #9](https://github.com/1998x-stack/TraceMap/pull/9) implements the local API guard, transactional source purge, startup cleanup of legacy missing-source references, and resource-limited PDF child process.\n- [CI run 42606956716](https://github.com/1998x-stack/TraceMap/actions/runs/42606956716): Python **62 passed**, web build PASS, Chromium **12 passed**, deployment lifecycle smoke/restart checks PASS (31 + 8 + 8).\n- **NOT RUN:** actual user Linux host listener/firewall inspection and forensic backup/WAL erasure verification. Phase 0 code/CI is complete; host confirmation remains a deployment checklist item.

## Next engineering changes in priority order

- G1.1 replace dev token with real managed authentication + revocable sessions.
- G1.2 deploy PDF parsing in a dedicated unprivileged UID/container with seccomp/network/filesystem restrictions; add private original-object storage and retention/cleanup policies. The current bounded child process is prototype hardening, not the final sandbox.
- G2.1 add production PostgreSQL schema migrations and concurrency tests; expose operation audit/history and view preferences.
- G3.1 implement provider adapter with schema, budget, source scoping, injection-resistance and golden-set accuracy tests.
- G4.1 implement complete Patch operation set, independent Diff and safe rebase rules.
- G5.1 perform real Xmind Markdown import matrix and accessibility / performance benchmarks.
