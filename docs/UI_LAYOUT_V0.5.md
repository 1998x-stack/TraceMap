# TraceMap — Independent Sidebars & Fullscreen Canvas v0.5

> UI behavior contract for the scholarly research workspace.

## Independent navigation and inspection panels

TraceMap has three independently collapsible sidebars:

1. **Project navigation rail** — the outer left rail. Collapsing it leaves project glyphs available for switching projects; search, project details, and creation form are hidden until expanded.
2. **Source library** — the left panel inside the research studio. Collapsing it leaves a narrow vertical “资料” tab.
3. **Evidence inspector** — the right panel. Collapsing it leaves a narrow vertical “审阅” tab.

The source library and inspector can be collapsed together. The center research canvas receives the released width. The collapsed tabs remain visible and keyboard-focusable, with accessible names and expanded/collapsed state exposed to assistive technology.

Layout preferences are stored independently in browser local storage. If storage is unavailable (for example, restrictive private browsing), controls still work for the current page session. No project data or research content is stored in these preferences.

On narrow screens, the outer navigation rail becomes a compact header when collapsed; source and inspector become 44px horizontal bars rather than narrow vertical strips. The existing mobile hierarchy outline remains the default reading experience outside fullscreen.

## Fullscreen canvas

The “全屏画布” control requests browser fullscreen on the map panel. The map header remains visible with the project title, generation action and an explicit exit control. The map metrics, React Flow zoom controls, minimap, and canvas remain available.

- Native Fullscreen API is preferred; browser Escape exits naturally.
- If the browser or origin denies fullscreen (common on restricted/insecure contexts), TraceMap falls back to a fixed-position focus mode with the same visible canvas and an Escape handler.
- On mobile, fullscreen intentionally switches from the compact outline back to the actual React Flow graph; the graph is not left hidden by the normal mobile CSS.
- Exiting fullscreen restores the previous sidebar collapse choices.
- The map and draft are not modified by entering/exiting fullscreen.

## Verification

[GitHub Actions #42595375357](https://github.com/1998x-stack/TraceMap/actions/runs/42595375357) passed 54 Python tests, 12 Chromium E2E cases, the strict frontend build, 31 Linux smoke checks and 8 restart checks. The Playwright suite in apps/web/e2e/layout-controls.spec.ts covers:

- Project rail, source library and inspector collapse independently.
- Both work panels collapsed simultaneously while the map remains visible.
- Browser Fullscreen API denial and CSS focus-mode fallback.
- Escape-key exit.
- Mobile collapse dimensions, no horizontal overflow, graph visibility in fullscreen, and return to the mobile outline.

The LLM budget regression suite covers a 4096 → 8192 token escalation, a configured 12000-token ceiling, and no repeated same-budget retry.

## Explicit limitations

- Fullscreen is a view state only; it does not add collaborative presentation or remote read-only sharing.
- The fallback focus mode covers the browser viewport but cannot hide browser chrome. Native fullscreen depends on browser permissions and user activation.
- The LLM retry is bounded to one escalation. It is not an unbounded retry queue, does not guarantee that a provider accepts the ceiling, and does not impose a per-user monetary quota.
