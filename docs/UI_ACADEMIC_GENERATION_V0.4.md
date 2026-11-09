# TraceMap — Scholarly Research Workspace & Honest Generation Feedback v0.4

> **Stage:** UI/code implementation for PR #7. This is a local development prototype, not a published scholarly product or a durable AI job engine.

## Design intent

TraceMap should look and behave like a **research notebook and source-critical reading environment**, not a growth dashboard:

- **Document-first hierarchy:** readable serif section headings, stable monospaced edition/revision labels, concise sans UI controls.
- **Material palette:** ivory paper (`#f7f4ec`), off-white evidence cards, ink (`#26343e`), muted archival green (`#516d69`), ochre manuscript accents, unobtrusive document rules.
- **Trust controls remain visible:** citations, exact quote highlighting, source labels and human verification never collapse into a generic AI success badge.
- **Desktop/mobile continuity:** desktop zoomable map is still a working surface; phones retain the readable outline introduced in v0.2.
- **Interaction preservation:** source intake, map editing, node inspection, patch review, export and undo are not changed by the visual skin.

The visual system is defined in `apps/web/src/academic-theme.css`, imported after the baseline `styles.css` so it can be reviewed and removed as one layer. No external fonts are required for functioning or offline fallbacks.

## Why generating a draft looked frozen

PR #7 changed `POST /api/v1/projects/{pid}/generate` to optionally call an LLM **synchronously** (the PR reports a real request around 33 seconds). The server does not create a running job first or stream any state. It sends the completed `draftId` only after model inference, server-side evidence checking and draft persistence. The existing frontend only showed a generic `busy` indicator.

**This redesign does not invent model progress**. While POST is pending, the UI can truthfully show:

1. **Request initiated** — the client initiated the HTTP request.
2. **Waiting for server response** — still awaiting a response; count up elapsed seconds.
3. **Reading the candidate draft** — only after POST returns `draftId`, before the GET `generation-drafts/{id}` completes.

The indeterminate 3-pixel animation indicates activity, **not a fraction completed**. The UI explicitly explains that no backend per-step events exist. At 20 seconds it explains longer model latency; at 90 seconds it clarifies the server has not responded. A backend error clears the panel and leaves the request button enabled again. The browser does not promise cancelability because aborting fetch would not stop the synchronous upstream model call.

## Behavior contract

- Only one generation request can be started from the same page; a ref lock prevents rapid double clicks before React state renders.
- The saved map/revision remains unchanged until explicit human confirmation.
- The elapsed timer resets on a new request and stops on completion/failure.
- The progress UI is a visible, named status region; only meaningful phase changes are announced to assistive technologies, not every ticking second.
- Long-running requests do not display percentage, ETA, a server retry count or inferred phases.
- Network errors, `LLM_UNAVAILABLE`, `LLM_OUTPUT_TRUNCATED` and revision conflicts re-use the existing error/feedback contract.
- The progress panel remains usable within the 390px mobile layout.
- `prefers-reduced-motion` disables the indeterminate animation.

## Grounding hardening in the same review

PR #7's `build_tree` previously kept LLM-generated claims even when `exactQuote` could not be verified, attaching no evidence. It also could accept a same-project source outside `sourceIds` because the validation dictionary covered all project paragraphs.

Now every retained model-proposed node needs a verified anchor **from an explicitly selected source**. Ungrounded or out-of-scope proposals are **discarded and counted**. If none remain, generation fails without writing a draft or map. The root/source-group nodes are structural; they do not represent verified claims.

This is necessary, but not sufficient, for factual trust: **a quote matching source text does not prove the statement inferred from it**. Human review remains mandatory.

## Verification checklist

- [ ] FastAPI/LLM tests: invalid quote, absent quote, same-project unselected source and all-invalid output.
- [ ] React/TypeScript production build.
- [ ] Chromium: delayed request shows elapsed timer and correct waiting label.
- [ ] Chromium: fulfilled response opens draft review and hides progress.
- [ ] Chromium: 503 response clears progress, leaves map untouched and enables retry.
- [ ] Chromium: `generationProvider=llm` uses the correct model-specific waiting label.
- [ ] Chromium: academic palette is applied and there is no horizontal overflow at 390px.
- [ ] Existing research/evidence/patch/undo, source import and accessibility tests.
- [ ] Real Linux-server LLM latency review (remote CI cannot assert upstream runtime/cost).

**Known architectural limitation:** to display true server-side milestones, queue position, attempts and reliable cancel/reconnect, introduce a durable background Job state machine and a status API/SSE with per-user authorization and TTL. Do not retrofit fake percentage into this synchronous endpoint.

## Follow-up risks for PR #7

1. Synchronous model inference, retry and `TRACEMAP_LLM_TIMEOUT` permit multi-minute request latency and loss of perceived responsiveness; needs durable jobs and per-request cost/time budget before production.
2. Retry/idempotency is recorded only after computation; two concurrent identical submissions can still duplicate expensive upstream calls.
3. Credentials and uploaded materials are sent to the configured upstream provider; treat endpoint, model and privacy policy as externally governed.
4. Prompt injection is only mitigated by source delimiters and anchor checking; a matching quote can still support a false inference.
5. `GT-0023` remains open: Markdown/Xmind-oriented export does not preserve all node semantics.

These are **review findings/risks**, not claims of a security certification or user-study pass.
