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
| `TRACEMAP_LLM_MAX_TOKENS` | `8192` | Output budget. Reasoning models need a large budget (GT-0022). |
| `TRACEMAP_LLM_API_KEY` | – | Inline key (keep out of Git). |
| `TRACEMAP_LLM_API_KEY_FILE` | `~/.config/ai-credentials/iauto_api_key` | Preferred: a private (`600`) key file. |

```bash
# .env  (git-ignored)
TRACEMAP_GENERATION_MODE=llm
TRACEMAP_LLM_BASE_URL=https://iagent.iauto.com/v1
TRACEMAP_LLM_MODEL=iagent/standard
TRACEMAP_LLM_API_KEY_FILE=/home/you/.config/ai-credentials/iauto_api_key
```

The key is resolved from `TRACEMAP_LLM_API_KEY`, else from the file at
`TRACEMAP_LLM_API_KEY_FILE`. It is **never** logged or returned by the API.

## What the model is allowed to do

1. `POST /api/v1/projects/{pid}/generate` sends the project's own paragraphs
   (bounded to `MAX_PROMPT_CHARS`) inside explicit
   `<<<UNTRUSTED_DOCUMENT_DATA>>> … <<<END…>>>` delimiters, with a system prompt
   that forbids following instructions found in the data.
2. The model returns `{"nodes":[{type,title,note,sourceId,paragraphId,exactQuote}]}`.
   It is told to copy `exactQuote` **verbatim** and to invent nothing.
3. The server **recomputes** the `[start,end)` offsets locally and re-verifies
   every anchor with `core.verify_ref`. Evidence that cannot be located, is
   paraphrased, or belongs to another project is **dropped and counted**
   (`droppedEvidenceCount` in the draft).
4. The result is a **read-only draft**. The live map is unchanged until a human
   calls the commit endpoint (the existing revision/`If-Match` gate). The model
   never sets `verified_by_user` and never writes the database.
5. The provider call runs **outside** any database transaction.

## Error contract

| Code | HTTP | Retryable | Meaning |
| --- | --- | --- | --- |
| `LLM_NOT_CONFIGURED` | 503 | no | `llm` mode selected but no key found. |
| `LLM_UNAVAILABLE` | 503 | yes | Cannot reach the endpoint (timeout/DNS). |
| `LLM_UPSTREAM_ERROR` | 502 | yes | Upstream returned a non-2xx status. |
| `LLM_OUTPUT_TRUNCATED` | 502 | yes | `finish_reason=length`; retried once automatically (GT-0022). |
| `LLM_INVALID_OUTPUT` | 502 | yes | No parseable/valid JSON, or no usable nodes; retried once. |

If `llm` mode is selected but no key is configured, the API **falls back to the
extractive demo** and the draft is labelled `extractive_demo`; `/health` shows
`llmConfigured:false`.

## Enable / disable / verify

```bash
# enable (then restart the API so .env is re-read)
$EDITOR .env            # TRACEMAP_GENERATION_MODE=llm + key
scripts/dev-stop.sh && scripts/dev-start.sh
curl -fsS http://127.0.0.1:8000/health | jq .
# {"status":"ok","generationProvider":"llm","generationModel":"iagent/standard","llmConfigured":true}

# disable (back to the deterministic demo)
# TRACEMAP_GENERATION_MODE=extractive
```

## Limitations (not production)

- **No hard cost cap.** There is a token budget (`TRACEMAP_LLM_MAX_TOKENS`) and a
  prompt-size bound, but no per-user/per-project spend limit or quota ledger.
- **Synchronous and slow.** A generate call blocks for ~10–60 s (reasoning
  models); there is no durable async job, retry queue or cancellation. The UI
  shows a busy state for the duration.
- **Prompt-injection resistance is best-effort** (delimiters + instructions +
  server-side verification). It is not a security boundary.
- **No accuracy evaluation.** Grounding is verified structurally (exact quotes
  resolve to real paragraphs); factual correctness of the *node titles/notes* is
  **not** validated. Treat every node as an unverified candidate.
- Single-process, SQLite, fake dev identity — all the usual prototype caveats
  (`docs/DEPLOYMENT_LINUX.md` §11).

## Tests

`apps/api/tests/test_llm.py` covers the adapter without any network or real key:
grounding/dropping, prompt construction, key handling, error mapping, truncation
detection + retry, the `/generate` LLM path (live map must not change), and
`/health`. The hermetic paths (`TRACEMAP_DOTENV=0`, `TRACEMAP_GENERATION_MODE=extractive`)
keep CI offline.

Observed on the reference host (2026-11-09): a synthetic 6-paragraph source
produced a 10-node draft (3 claims, 2 evidence, 1 counterpoint, 2 questions, 1
source topic, root) in ~33 s, **0 dropped anchors**, 4646 tokens.
