# TraceMap UI · Design system and interaction specification v0.2

> **Development-only UI / local React application** · 2026-11-09 · This is not the public GitHub Pages portfolio and is not an authenticated production service.

## 1. Product design thesis

The core job is not “draw a beautiful mind map.” It is **form a judgement without losing its evidence**. The UI should always make four questions answerable:

1. Which project and source am I working on?
2. Which conclusion is selected and what exact paragraph supports it?
3. Which parts have been **manually verified**, and which merely have a **locatable anchor**?
4. What will change if I approve an uncommitted draft or patch?

### Visual concept

**Research instrument / evidence lens.** A quiet dark shell houses a bright, paper-like reasoning canvas. Teal is the controlled action / anchor color, amber is *unverified*, and rose indicates destructive action. The design aims for investor-grade clarity rather than gratuitous animation, metrics, or claims of production maturity.

## 2. Three spatial zones

| Zone | Width at ≥1600 px | Intent |
| --- | --- | --- |
| Workspace rail | 251 px | Project switching, search, new-project creation and explicit dev-mode state |
| Source library | 279 px | Source quota, original documents and paste/upload composer |
| Reasoning canvas | Fluid | Semantic node tree, legend, map counters and gentle zoom controls |
| Evidence inspector | 312 px | Single selection, citation location, human verification, structured edit and reviewed changes |

Breakpoints: at ≤1600 px compact widths; at ≤1070 px inspector moves under the map; at ≤750 px entire workspace becomes stacked and **creation/import remain available**. No sidebar-only essential action may disappear on mobile.

## 3. Token vocabulary

| Token / Role | Color | Meaning |
| --- | --- | --- |
| Chrome background | `#09121a` / `#101b26` | Application frame, deliberate dark contrast |
| Canvas background | `#e7edef` | Content-first neutral; improves graph readability |
| Primary action | `#8de5cc` | Deliberate user action, not AI-authored fact |
| Source / anchored | `#3a9b83` | Exact source paragraph is locatable |
| Verification pending | `#f0bf7b` | A claim is not human-verified |
| Destructive | `#f2a0a8` | Delete / clear actions |
| Primary text | `#e8eff2` dark shell / `#19313b` light map | Legible contrast on each zone |

Text styles: DM Sans + native CJK fallback for reading; IBM Plex Mono for revision, stage and provenance metadata. Font fallbacks must remain functional without access to Google Fonts.

## 4. Node anatomy

A map node has: **semantic kind → origin → conclusion title → evidence status / citation count**. The node is a pure React Flow presentation component; edits happen in the inspector, not within the graph renderer.

- `topic`: dark teal root, for the research question only.
- `claim`: evidence-aware reasoning proposition.
- `evidence`: blue-tinted semantic top marker (not “verified” by default).
- `counterpoint`: rose semantic marker, preserving disagreement.
- `question`: amber semantic marker, for unresolved follow-up.
- `decision`: purple semantic marker, reserved for user interpretation.
- `verified_by_user`: separate, explicit state. A `source anchor == anchored` **does not** mean the cited proposition is externally true.

Node positions are deterministic, ordered, and centered on first and last descendant, allowing diff/undo to keep layout predictable. Selection shows a teal ring and remains keyboard-focusable through React Flow.

## 5. Dialog semantics and states

**Draft proposal:** no map mutation before confirmation; show number of proposed nodes, plain-language caveat, cancel and affirmative confirmation. Exit on Escape.

**Patch proposal:** default no operations selected. Every operation is individually inspectable; selected count and base revision are visible. Cancel discards only the proposal, never the formal tree. Applying requires the server to validate revision, scope, references and dependencies again. The current demo proposes rule-based candidates only.

**Errors:** conflicts retain unsent form data, refresh the authoritative revision, and ask the user to review. Successful operations show a status notice. Development identity, data privacy limitations and absence of LLM are permanently visible.

**Evidence panel:** displays the source title, original paragraph with Unicode codepoint quote highlight, and a clear warning that citations locate text but do not guarantee the source's real-world veracity. Source-list navigation and citation navigation use a request sequence guard to avoid stale responses overriding a new selection.

## 6. Accessibility and responsive quality bar

- Visible keyboard focus on buttons, fields and file-upload target.
- Semantic `tablist` / `tab` for inspector mode; modals have dialog role, title, and Escape dismissal.
- Source/verification information is conveyed with text + symbol, not color alone.
- Important actions remain reachable at 390 px viewport; no horizontal document overflow in Chromium.
- Animation is reduced if `prefers-reduced-motion` is active.
- Images are not used to fake evidence or business traction; no live LLM, secure auth or live multiuser collaboration is implied.

## 7. Validation strategy

All checks are implementation tests rather than concept art:

1. **Strict build:** TypeScript and production Vite bundle.
2. **Existing golden path:** upload → draft → commit → citation → reviewed patch → undo → Markdown.
3. **New desktop UI test:** source status and nodes, quote inspector, review modal guard and Escape.
4. **New mobile UI test:** can still create and import, document `scrollWidth` does not exceed viewport.
5. **Real Chromium screenshots:** CI stores desktop/mobile screenshots for human visual inspection. Screenshots cannot prove real-world desirability or production readiness.

### Open / intentionally out of scope

- Real user research and usability interviews; no validated preference claims.
- A production-ready auth/privacy system and async extraction Worker (tracked under G1/G2).
- Full LLM model integration and structured diff operators (G3/G4).
- True Xmind import verification, accessibility audit with assistive technology, production telemetry (G5).

## 8. Links

- [Product PRD](https://github.com/1998x-stack/projects/blob/main/projects/knowledge/llm-xmind/reports/prd-mvp-v1.0.md)
- [Frontend architecture](https://github.com/1998x-stack/projects/blob/main/projects/knowledge/llm-xmind/design/03-frontend.md)
- [TraceMap source repository](https://github.com/1998x-stack/TraceMap)
