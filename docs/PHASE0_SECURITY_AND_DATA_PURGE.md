# TraceMap Phase 0 — Security Boundary & Data Protection

**Status:** Code and CI verification PASS in [GitHub Actions run 42606956716](https://github.com/1998x-stack/TraceMap/actions/runs/42606956716). Live Linux host listener/configuration inspection is NOT RUN and remains an operator deployment check.

## Scope

Phase 0 closes three prototype risks before broader data-model work:

1. Local-only development API accidentally trusted same-host reverse-proxy metadata.
2. Source deletion removed Source/Paragraph rows but left source-derived quotes in maps, drafts and historical snapshots.
3. PDF parsing ran synchronously inside the API process without CPU, memory or wall-clock ceilings.

This does not turn the prototype into a production service. Real authentication, multi-tenancy, private object storage, backup governance and a dedicated sandbox remain later release gates.

## 1. Development API boundary

The development middleware now requires all of the following:

- TCP peer is loopback.
- Host is one of localhost, 127.0.0.1, ::1 or the test-only TestClient host.
- No common proxy/client-IP forwarding headers are present: Forwarded, X-Forwarded-*, X-Real-IP, X-Original-*, Via, X-Envoy-External-Address, X-Cluster-Client-IP, X-Client-IP, True-Client-IP or CF-Connecting-IP.
- TRACEMAP_ENV remains exactly development.

The launcher independently binds API and Vite to 127.0.0.1 and refuses public bind overrides. It also rejects a PID-reuse race only as successful shutdown when the expected listener is already free; if the port remains occupied or unknown, it fails closed.

**Hard limitation:** middleware cannot distinguish a same-host proxy that strips all forwarding headers and rewrites Host to localhost. Never put this dev API behind Nginx, Caddy or another reverse proxy. Use SSH tunneling for remote development. Bearer dev-* is an impersonable development identity, not authentication.

## 2. Source deletion semantics

DELETE /api/v1/projects/{pid}/sources/{sid} is an irreversible logical purge, performed in one database transaction:

1. Validate project ownership and revision.
2. Remove every map node that cites the source, plus its descendants. This is conservative because descendants may have been derived from the deleted evidence.
3. Remove remaining references to the source and compact sibling order.
4. Invalidate and clear every project Draft. No old generation or patch candidate can be committed after purge.
5. Scrub every Change.before_json and Change.after_json snapshot.
6. Delete Source and cascading Paragraph rows.
7. Write a source_delete audit event whose snapshots are already scrubbed.
8. Advance project revision and persist the idempotent response.

The response includes deletionMode=permanent_purge, purgedNodeCount and invalidatedDraftCount.

The test contract searches a unique sentinel across the current map, both export formats, every Draft payload and every historical Change snapshot. It also verifies that the old Draft cannot be committed.

**Limits of the guarantee:**

- This is logical deletion from live database/API-visible rows, not forensic secure erasure. SQLite WAL files, free pages, filesystem snapshots and external backups may retain bytes.
- Manually authored text without an EvidenceRef cannot be reliably attributed to a source. Evidence-linked nodes and descendants are removed; arbitrary unlinked paraphrases cannot be inferred safely.
- No raw uploaded binary is retained by this prototype. The extracted text is the retained source payload.

Do not promise secure deletion until database/object storage encryption, per-object key destruction, backup expiry and complete derived-data lineage are implemented.

## 3. PDF parser process isolation

The upload route checks file size, project ownership, idempotency replay and source-count quota before parser work. PDF extraction is dispatched off the API event loop to a fresh spawned process.

Default limits:

| Limit | Default | Bounds |
|---|---:|---:|
| Upload size | 10 MiB | fixed |
| Pages | 100 | fixed |
| Extracted text | 80,000 Unicode code points | project cap |
| Wall-clock time | 15 s | 1–60 s |
| CPU time | 10 s | 1–60 s |
| Address space | 1,024 MiB | 256–4,096 MiB |

Environment variables: TRACEMAP_PDF_TIMEOUT_SECONDS, TRACEMAP_PDF_CPU_SECONDS and TRACEMAP_PDF_MEMORY_MB. Invalid/out-of-range values fall back to safe defaults.

The child applies POSIX RLIMIT_CPU and RLIMIT_AS, returns only extracted page text, and is terminated/killed when the parent deadline expires. If resource limits cannot be applied, parsing fails closed.

**Hard limitation:** this is a separate process under the same OS user. It is not a container, separate UID, seccomp sandbox, malware scanner or network/filesystem isolation. Public hostile uploads remain blocked until a dedicated unprivileged worker/container is deployed.

## 4. Regression and release gates

- Source purge sentinel: current map, JSON export, Markdown export, all Drafts and all Change snapshots contain no sentinel after deletion.
- Purged Draft commit returns 409.
- Forwarded proxy headers and external Host values return 403; normal loopback and TestClient health checks remain available.
- PDF worker extracts a valid PDF, rejects encrypted and over-page PDFs, and terminates a worker on timeout.
- Existing Python API, Linux deployment lifecycle, web build and Chromium E2E checks remain required.
- Live Linux deployment must still be inspected for listeners: API and Vite must bind only to 127.0.0.1. Middleware is not a substitute for host firewall/process configuration.

## 5. Verified CI evidence (2026-11-09)

- Python API: **62 passed**, 1 dependency deprecation warning.
- Web build: PASS.
- Chromium browser E2E: **12 passed**.
- Linux deployment lifecycle: live smoke **31 passed**, isolated restart/persistence cycles **8 passed** each; no failures or skips.
- The CI environment is not the user's Linux host. Actual listener inspection, firewall rules and backup/WAL retention on that host are **NOT RUN**.

A green CI run does not prove backup erasure or production security.
