# TraceMap LLM provider (optional)

> **Status: optional, off by default, prototype-grade.** The deterministic
> extractive demo remains the default and needs no key or network. A real model
> is used only when explicitly enabled. This is **not** a production AI pipeline
> — see *Limitations*.

TraceMap can generate a candidate mind map with any **OpenAI-compatible**
`POST {baseUrl}/chat/completions` endpoint. The reference configuration is the
local pi agent's `iagent/standard` provider.

## Configuration (`.env`)

All settings live in the repository `.env` (see `.env.example`; `.env` is
git-ignored). The same keys can be provided as real environment variables, which
win over the file. `TRACEMAP_DOTENV=0` ignores the file entirely.

| Variable | Default | Meaning |
| --- | --- | --- |
| `TRACEMAP_GENERATION_MODE` | `extractive` | `extractive` (offline demo) or `llm` (real model). |
| `TRACEMAP_LLM_BASE_URL` | `https://iagent.iauto.com/v1` | OpenAI-compatible base URL. |
| `TRACEMAP_LLM_MODEL` | `iagent/standard` | Model id. |
| `TRACEMAP_LLM_TIMEOUT` | `180` | Per-request timeout in seconds. |
| `TRACEMAP_LLM_MAX_TOKENS` | `8192` | First-attempt output budget. |
| `TRACEMAP_LLM_INPUT_TOKEN_BUDGET` | `12000` | Estimated input budget including system prompt; retrieval is ranked and source-balanced within this limit. |
| `TRACEMAP_LLM_RETRY_MAX_TOKENS` | `16384` | Maximum output budget for one truncation retry. The retry uses up to 2× the first budget, capped here. Set equal to the first budget to disable escalation. |
| `TRACEMAP_LLM_API_KEY` | – | Inline key (keep out of Git). |
| `TRACEMAP_LLM_API_KEY_FILE` | `~/.config/ai-credentials/iauto_api_key` | Preferred: a private (`600`) key file. |

```bash
# .env  (git-ignored)
TRACEMAP_GENERATION_MODE=llm
TRACEMAP_LLM_BASE_URL=https://iagent.iauto.com/v1
TRACEMAP_LLM_MODEL=iagent/standard
TRACEMAP_LLM_INPUT_TOKEN_BUDGET=12000
TRACEMAP_LLM_API_KEY_FILE=/home/you/.config/ai-credentials/iauto_api_key
```

The key is resolved from `TRACEMAP_LLM_API_KEY`, else from the file at
`TRACEMAP_LLM_API_KEY_FILE`. It is **never** logged or returned by the API.

## Prompt construction and untrusted documents

1. `POST /api/v1/projects/{pid}/generate` ranks all paragraphs from selected
   sources using the research goal. The 40-paragraph per-source cap is applied
   **after** ranking, so relevant paragraphs near the end of a long document
   remain eligible.
2. Selection proceeds round-robin across sources and is bounded by
   `TRACEMAP_LLM_INPUT_TOKEN_BUDGET`. The estimate includes the system prompt,
   JSON payload and fixed message overhead.
3. The complete research goal and selected documents are sent as one JSON user
   payload. Source titles and paragraph text remain data fields; no source text is
   interpolated into delimiter markers that a document could forge. The system
   prompt explicitly treats fake role labels, JSON, apparent delimiters and
   instructions inside source text as untrusted data.
4. This structured representation improves boundary clarity but is **not** a
   security guarantee against model prompt injection. Never use model behavior
   as an authorization or secret-protection boundary.

## Output validation and evidence integrity

1. The model returns `{"nodes":[{type,title,note,sourceId,paragraphId,exactQuote}]}`.
   Every node requires a supported type, non-empty title, selected source and
   paragraph IDs, and an exact quote.
2. The response body is capped at 2 MiB before parsing. The JSON root must be an
   object and `nodes` must be a non-empty array within the 16-node limit.
   Malformed node fields are dropped; a response with no usable grounded nodes
   is rejected.
3. The server recomputes Unicode code-point `[start,end)` offsets locally and
   re-verifies every anchor with `core.verify_ref`. Only paragraphs actually
   included in the prompt are eligible. Invalid, paraphrased or out-of-scope
   evidence is dropped and counted in `droppedEvidenceCount`.
4. Draft metadata records the retrieval policy, estimated input tokens, selected
   source IDs, per-source paragraph counts and omitted source IDs.
5. The result is a **read-only draft**. The live map is unchanged until a human
   calls the commit endpoint with the existing revision/`If-Match` gate. The
   model never sets `verified_by_user` and never writes the database.
6. The provider call runs **outside** any database transaction.

## Error contract

| Code | HTTP | Retryable | Meaning |
| --- | --- | --- | --- |
| `LLM_NOT_CONFIGURED` | 503 | no | `llm` mode selected but no key found. |
| `LLM_UNAVAILABLE` | 503 | yes | Cannot reach the endpoint (timeout/DNS). |
| `LLM_UPSTREAM_ERROR` | 502 | yes | Upstream returned a non-2xx status. |
| `LLM_OUTPUT_TRUNCATED` | 502 | yes | `finish_reason=length`; one bounded output-token retry is attempted. |
| `LLM_INVALID_OUTPUT` | 502 | yes | Invalid JSON root/schema or no usable grounded nodes; retried once. |
| `LLM_RESPONSE_TOO_LARGE` | 502 | no | Provider response body exceeded 2 MiB. |
| `LLM_INPUT_TOO_LARGE` | 413 | no | Configured input budget cannot fit any selected source paragraph. |

If `llm` mode is selected but no key is configured, the API falls back to the
extractive demo and the draft is labelled `extractive_demo`; `/health` shows
`llmConfigured:false`.

## Enable / disable / verify

```bash
# enable (then restart the API so .env is re-read)
$EDITOR .env
scripts/dev-stop.sh && scripts/dev-start.sh
curl -fsS http://127.0.0.1:8000/health | jq .

# disable (back to the deterministic demo)
# TRACEMAP_GENERATION_MODE=extractive
```

## Retrieval and evaluation contract

The lexical retriever uses CJK bigrams and Latin words, prioritizes exact goal
phrases, and then balances selection across sources. It is a deterministic
coverage heuristic, not semantic search, entailment or contradiction resolution.
The 40-paragraph cap is applied after relevance ranking.

The token estimator uses tiktoken when available for a known model and applies a
conservative UTF-8 byte floor. For custom OpenAI-compatible model names without
a known tokenizer, it uses the conservative UTF-8 estimate alone. Token counts
are therefore estimates; provider-reported usage is the measured count when
available. The input budget is a local safety limit, not a provider context-window
guarantee.

`apps/api/tests/fixtures/llm_golden_dataset.json` is a synthetic retrieval
regression dataset covering:
- Chinese relevance found late in a long source.
- English relevance found after unrelated opening paragraphs.
- Emoji-containing Unicode evidence.
- Injection-shaped document text containing apparent delimiters and fake roles.
- Contradictory statements across two sources, both of which must remain visible.

The tests assert deterministic retrieval and data serialization only. They do not
claim that a live model resisted every injection, understood contradictions,
produced logically entailed claims, or improved user outcomes.

## Limitations (not production)

- **No hard cost cap.** Input selection and completion-token retries are bounded,
  but there is no per-user/per-project spend ledger or quota.
- **Synchronous and slow.** A generate call blocks for ~10–60 seconds; there is
  no durable async job, retry queue or cancellation. The UI shows elapsed time
  and client-observed waiting phases, but no true server-side progress.
- **Prompt-injection resistance remains best-effort.** Structured JSON avoids
  forgeable delimiter boundaries, but the model may still follow malicious source
  instructions. Keep secrets out of source documents and never send sensitive
  documents to this prototype.
- **No live-model accuracy evaluation.** Exact quote verification proves textual
  presence, not that titles or notes are factually correct or logically entailed.
  Treat every generated node as an unverified candidate.
- Single-process, SQLite and fake dev identity — see `docs/DEPLOYMENT_LINUX.md` `11.

## Tests

`python -m pytest -q apps/api/tests/test_llm.py` covers the adapter without a
network or real key: grounding, structured prompt serialization, malformed JSON
roots and node types, bounded provider response bodies, relevance-ranked and
source-balanced token-budget retrieval, the synthetic Golden Dataset, key
handling, error mapping, truncation and invalid-output retries, and the `/generate`
path (the live map must not change). CI remains offline; no live-provider accuracy
or prompt-injection success rate is claimed.


## Phase 1 verification record

Verified on GitHub Actions run 42606702246 (2026-11-09):
- Python API suite: 70 passed, 1 existing deprecation warning.
- Chromium browser E2E: 12 passed.
- Deployment lifecycle: passed; the lifecycle log reported 31 checks passed and
  the smoke run reported 8 passed, 0 failed, 0 skipped.
- Web build: passed.
- OpenAPI signature check: 22 operations / 19 paths.
- Production-mode guard: passed.

Live provider integration, live-model prompt-injection resistance, and factual
accuracy evaluation: **NOT RUN**. The Golden Dataset is synthetic and verifies
retrieval/serialization contracts only.
