# Mastra-Style Chat UI — Implementation Plans

**Spec:** [`../../specs/2026-05-29-mastra-style-chat-ui-design.md`](../../specs/2026-05-29-mastra-style-chat-ui-design.md)

Implements a Mastra-inspired UI refresh for the advisory-agent chat web app, staying on Jinja2 + vanilla JS (no React, no bundler). Light/dark theming, 3-column collapsible layout, markdown rendering, Vietnamese-labeled trace timeline, debug-gated JSON expansion.

## Slice order

Execute slices **in order**. Each slice ships a working, testable end-state; later slices assume the prior slices' files exist.

| # | File | Theme | Approx. tasks | Key outputs |
|---|---|---|---|---|
| 01 | [`01-tokens-and-theme.md`](./01-tokens-and-theme.md) | Foundation | 8 | `tokens.css`, `theme.js`, FOUC init, marked CDN, theme toggle button, `ADVISORY_THEME_DEFAULT` env |
| 02 | [`02-shell-and-layout.md`](./02-shell-and-layout.md) | Layout | 9 | 3-col grid in `chat.html`, full `chat.css` rewrite, `layout.js` with collapse + mobile drawer scaffold |
| 03 | [`03-messages-and-markdown.md`](./03-messages-and-markdown.md) | Chat thread | 10 | `messages.js`, `markdown.js`, `chat-markdown.css`, new bubble anatomy, auto-grow textarea, Ctrl+Enter |
| 04 | [`04-trace-panel-hybrid.md`](./04-trace-panel-hybrid.md) | Trace | 7 | `trace.js`, `STAGE_LABELS` server-side, lucide SVG sprite, Vietnamese labels, debug-gated JSON expand |
| 05 | [`05-states-tests-docs.md`](./05-states-tests-docs.md) | Polish | 11 | Empty states, skeleton pulse, loading dots, `toasts.js`, mobile drawer polish, help popover, QUICKSTART update |

## Cross-slice contracts

These names are introduced in one slice and consumed by later slices. If you rename one, update every consumer:

| Symbol | Defined in | Consumed by |
|---|---|---|
| `theme_default` (template context) | 01 | 04 (preserves in pages.py edit) |
| `ADVISORY_THEME_DEFAULT` (env) | 01 | — |
| `<html data-theme-default="...">` | 01 | inline FOUC script |
| `initTheme()`, `toggleTheme()` (`theme.js`) | 01 | `chat.js` |
| `var(--surface-*)`, `var(--text-*)`, `var(--space-*)`, `var(--col-left/right)` (tokens.css) | 01 | all later CSS |
| `#profile-panel`, `#chat-panel`, `#trace-panel` (IDs) | 02 | `test_chat_page.py`, all later tests |
| `#collapse-left`, `#collapse-right`, `#open-left-drawer`, `#open-right-drawer` | 02 | `layout.js`, 05 polish |
| `initCollapseHandles()`, `openDrawer()`, `closeDrawer()` (`layout.js`) | 02 | `chat.js`, 05 polish |
| `.app-shell`, `.app-header`, `.grid-3col`, `.panel`, `.composer`, `.is-collapsed` (CSS classes) | 02 | 03 + 04 + 05 |
| `renderMarkdown()` (`markdown.js`) | 03 | `messages.js`, 05 popover (if needed) |
| `renderTranscript()`, `appendMessage()`, `renderRecommendationCard()` (`messages.js`) | 03 | `chat.js`, 05 (`renderGreeting` added) |
| `chat-markdown.css` | 03 | base.html `<link>` |
| `STAGE_LABELS` (`pages.py`), `stage_labels` (template ctx) | 04 | `chat.html` Jinja loop |
| `window.__stageLabels`, `window.__debugUi` (JS globals) | 04 | `trace.js` |
| `debugUiEnabled()`, `renderTrace()`, `startTracePolling()`, `stopTracePolling()` (`trace.js`) | 04 | `chat.js` |
| `#icon-<stage>`, `#icon-status-<state>` (SVG `<symbol>` IDs) | 04 | `chat.css` `<use href>` |
| `renderGreeting()` (`messages.js`) | 05 | `messages.js` internal in `renderTranscript` |
| `toast(message, opts)` (`toasts.js`) | 05 | `chat.js`, `trace.js` |
| `app_version` (template ctx, read from `pyproject.toml`) | 05 | `chat.html` help popover |

## Out-of-scope (not touched by any slice)

- Backend `/api/sessions/*` routes — contract unchanged.
- Backend `/api/sessions/{token}/trace` endpoint — contract unchanged.
- The 6 agent stages backend pipeline — unchanged.
- Multi-conversation thread list (single session per browser as today).
- Continuous drag-resize column splitters (replaced with discrete collapse/expand).
- Token-by-token streaming (snapshot polling stays).

## How to execute

Per slice:

1. Open the slice plan file.
2. Use one of:
   - **`superpowers:subagent-driven-development`** — dispatch a fresh subagent per task, two-stage review between tasks (recommended for higher quality + lower context drift).
   - **`superpowers:executing-plans`** — execute inline in your current session, batching with checkpoints.
3. Verify the "Slice N Done When" checklist before moving to the next slice.
4. Each slice commits its work; no PR opened until all 5 are done (per spec §11 — single PR).

## Risks watched (from spec §13)

- `oklch()` browser support — fall back to hex via `@supports not (color: oklch(0% 0 0))` only if a smoke test reveals an issue in a target browser. Not pre-emptively added.
- `marked.js` CDN reachability — SRI hash in slice 01 + `onerror` fallback noted; if CDN blocks become a recurring issue in target environment, bundle locally in a follow-up.
- Slice 04 regression risk during the JS refactor — slice 04 Task 5 explicitly lists every symbol to delete from `chat.js` to make the refactor mechanical and reviewable.
