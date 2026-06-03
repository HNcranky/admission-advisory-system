# Mastra-Style Chat UI — Design Spec

**Status:** Draft
**Date:** 2026-05-29
**Owner:** Tu Hoa / Cranky
**Related:** [2026-05-28-agent-trace-viewer-design.md](./2026-05-28-agent-trace-viewer-design.md) (replaces its UI layer)

---

## 1. Goal

Refresh the advisory-agent chat web UI to mimic the visual language and information architecture of [Mastra's playground UI](https://github.com/mastra-ai/mastra) (React 19 + Tailwind v4 + shadcn/ui + `@assistant-ui/react`), while staying on the **existing Jinja2 + vanilla JS** stack — no React, no bundler, no npm pipeline.

The result must look modern, support light/dark theming, render markdown in assistant outputs, expose agent stages as a friendly "thinking timeline" to students, and preserve full developer trace inspection behind the existing `?debug=1` / `ADVISORY_DEBUG_UI=1` gate.

## 2. Non-Goals

- **No React / SPA rewrite.** Mastra's choice of React, Tailwind v4, shadcn/ui, `@assistant-ui/react`, `react-resizable-panels`, and CodeMirror is explicitly out of scope. We borrow visual patterns, not the toolchain.
- **No multi-conversation thread list.** One session per browser via `localStorage` token, unchanged from today. No "chat history sidebar" backend work.
- **No continuous drag-resize column splitters.** Replaced with discrete collapse/expand toggles.
- **No streaming token-by-token chat.** The backend is request/response with snapshot polling; not changed by this spec.
- **No avatar uploads, attachments, voice input, or file uploads.**

## 3. Audience and Use Cases

| Audience | View |
|---|---|
| Vietnamese high-school students using the advisor end-to-end | Full new UI, light theme default, "Phân tích của AI" timeline visible in the right column (no JSON), markdown-rendered recommendation. |
| Developers debugging stage outputs | Same UI, plus `?debug=1` (or env flag) enables clickable trace cards that expand to pretty-printed `output_json`, durations, and error text. |
| Thesis demo viewers | Polished light-mode walkthrough; dark mode available via header toggle. |

## 4. Tech Stack & Constraints

- **Server:** FastAPI + Jinja2 templating (unchanged). `web/routes/pages.py` extended to pass new context (`theme_default`, `stage_labels`, etc.).
- **Markup:** Jinja2 with `<script type="module">` ES modules — no bundler.
- **Styles:** Plain CSS with custom properties; new `tokens.css` holds the design-system layer.
- **Client deps:** `marked.js` (~12 KB) loaded from CDN with SRI hash; everything else vanilla. Lucide icons inlined as SVG strings (no runtime loader).
- **Browsers:** Modern evergreen (Chrome / Edge / Firefox / Safari last 2 versions). `oklch()` colors require Safari 15.4+ / Chrome 111+ — acceptable.
- **No TypeScript, no JSX, no build step.**

## 5. Architecture

### 5.1 File layout

```
web/
├── templates/
│   ├── base.html              (modify: load marked CDN, inline theme-init script)
│   └── chat.html              (rewrite: 3-column shell + header + composer)
├── static/
│   ├── css/
│   │   ├── tokens.css         (NEW: oklch tokens, [data-theme="light"|"dark"])
│   │   ├── chat.css           (rewrite: layout + components, consumes tokens)
│   │   └── chat-markdown.css  (NEW: prose styles for markdown output)
│   └── js/
│       ├── chat.js            (rewrite: thin orchestrator)
│       └── modules/
│           ├── theme.js       (NEW: toggle + localStorage + system pref listener)
│           ├── markdown.js    (NEW: marked wrapper + simple sanitizer)
│           ├── messages.js    (NEW: renderTranscript + bubble templates)
│           ├── trace.js       (NEW: i18n stage names + render + polling)
│           └── layout.js      (NEW: collapse/expand column handlers + mobile drawer)
└── routes/
    └── pages.py               (modify: pass theme_default + stage_labels)
```

ES modules are imported relatively: `import { renderTranscript } from "./modules/messages.js"`. No build step, served as static files.

Global state remains minimal (existing `currentSessionToken`, `pollTimer`, `tracePollTimer`). New modules export pure functions; no class instances.

### 5.2 Server-side additions

`web/routes/pages.py`:

```python
STAGE_LABELS: list[dict[str, str]] = [
    {"id": "profile",  "label": "Phân tích hồ sơ",         "icon": "user-circle"},
    {"id": "retrieve", "label": "Tra cứu chương trình",    "icon": "search"},
    {"id": "conflict", "label": "Đối chiếu nguồn dữ liệu", "icon": "git-compare"},
    {"id": "reason",   "label": "Suy luận khuyến nghị",    "icon": "lightbulb"},
    {"id": "policy",   "label": "Đối chiếu quy chế",       "icon": "shield-check"},
    {"id": "explain",  "label": "Soạn lời giải thích",     "icon": "message-square"},
]
```

Passed to template as `stage_labels`. The Jinja loop renders them once into the trace panel skeleton; JS only mutates status/duration/expand body.

`pages.py` continues to expose `debug_ui_enabled` from `ADVISORY_DEBUG_UI`. A new `theme_default` field reads optional `ADVISORY_THEME_DEFAULT` env (`"light"` | `"dark"`, default `"light"`) — informs the inline theme-init script's fallback before `localStorage` is consulted.

## 6. Visual Layout

### 6.1 Overall structure

```
┌──────────────────────────────────────────────────────────────────────┐
│ Header bar (56px sticky)                                              │
│   [logo + title]              [spacer]    [🌙 theme]  [? help]        │
├────────────────┬───────────────────────────────┬─────────────────────┤
│ Profile panel  │ Chat panel                    │ Trace panel         │
│ (280px)        │ (1fr, min 480px)              │ (320px)             │
│                │                                │                     │
│ ► Hồ sơ        │ ┌── transcript (scroll) ──┐   │ Phân tích của AI    │
│   tạm thời     │ │ user (right, max 70%)    │  │                     │
│   (card)       │ │ ai   (left,  max 70%)    │  │  ✓ Phân tích hồ sơ │
│                │ │ ai result (left, full,   │  │  ⟳ Tra cứu...      │
│ ► Khuyến nghị  │ │   markdown rendered)     │  │  ○ Đối chiếu...    │
│   mới nhất     │ └──────────────────────────┘  │  ○ Suy luận...     │
│   (markdown)   │ ────── divider ──────         │  ○ Đối chiếu QC    │
│                │ ┌── composer (sticky) ──┐     │  ○ Soạn lời giải   │
│                │ │ [textarea autogrow]   │     │                     │
│                │ │ hint  spinner  [Gửi]  │     │                     │
│                │ └────────────────────────┘    │                     │
│  [◀ collapse] │                                │ [collapse ▶]       │
└────────────────┴───────────────────────────────┴─────────────────────┘
```

CSS Grid:
```css
.chat-shell {
  display: grid;
  grid-template-columns: var(--col-left, 280px) 1fr var(--col-right, 320px);
  grid-template-rows: var(--header-h) 1fr;
  min-height: 100vh;
}
.chat-shell.left-collapsed   { --col-left: 32px;  }
.chat-shell.right-collapsed  { --col-right: 32px; }
```

Collapsed columns shrink to a 32px gutter showing only the chevron-icon button to re-expand. `aria-hidden` flips on children inside.

### 6.2 Responsive

| Breakpoint | Behavior |
|---|---|
| ≥ 1100px | Full 3-column |
| 900–1099px | Trace panel collapses to gutter by default (user can open) |
| < 900px | Both side panels become drawers: header gains `Hồ sơ` / `Phân tích` icon buttons that overlay the screen; chat occupies full width |

Mobile drawer is a `<dialog>`-like overlay (`position: fixed`, backdrop, slide-in 200ms).

### 6.3 Trace panel visibility

| Condition | Right column |
|---|---|
| No run yet, not debug | `display: none` (chat panel widens) |
| Run started OR debug flag | Visible with skeleton timeline |
| Run completed, not debug | Visible, all checks green, persists until user resets |

## 7. Design Tokens

`tokens.css` defines:

```css
:root {
  /* Typography */
  --font-sans: ui-sans-serif, system-ui, "Segoe UI", -apple-system, sans-serif;
  --font-mono: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  --text-xs: 12px; --text-sm: 13px; --text-base: 14px; --text-md: 15px;
  --text-lg: 17px; --text-xl: 20px; --text-2xl: 24px;
  --leading-tight: 1.3; --leading-base: 1.55;

  /* Spacing (4px base) */
  --space-1: 4px;  --space-2: 8px;  --space-3: 12px;
  --space-4: 16px; --space-5: 24px; --space-6: 32px; --space-8: 48px;

  /* Radius */
  --radius-sm: 4px; --radius-md: 6px; --radius-lg: 10px; --radius-pill: 999px;

  /* Layout */
  --col-left: 280px; --col-right: 320px; --header-h: 56px;
  --bubble-max: 70%;

  /* Motion */
  --transition-fast: 120ms ease;
  --transition-base: 200ms ease;

  /* Shadow */
  --shadow-sm: 0 1px 2px rgba(0,0,0,0.04);
  --shadow-md: 0 4px 12px rgba(0,0,0,0.06);
}

[data-theme="light"] {
  --surface-1: oklch(99% 0.003 250);   /* page bg */
  --surface-2: oklch(97% 0.005 250);   /* panel bg */
  --surface-3: oklch(94% 0.008 250);   /* card bg, hover */
  --surface-4: oklch(89% 0.012 250);   /* borders */
  --text-1:    oklch(20% 0.02 250);
  --text-2:    oklch(40% 0.02 250);
  --text-3:    oklch(60% 0.015 250);
  --accent-1:        oklch(55% 0.18 255);
  --accent-1-hover:  oklch(50% 0.18 255);
  --accent-1-contrast: oklch(99% 0 0);
  --positive:  oklch(55% 0.15 145);
  --warning:   oklch(70% 0.16 75);
  --negative:  oklch(55% 0.20 25);
  --user-bubble:  oklch(95% 0.04 145);
  --assistant-bg: var(--surface-2);
}

[data-theme="dark"] {
  --surface-1: oklch(15% 0.01 250);
  --surface-2: oklch(19% 0.012 250);
  --surface-3: oklch(24% 0.015 250);
  --surface-4: oklch(32% 0.018 250);
  --text-1:    oklch(95% 0.005 250);
  --text-2:    oklch(75% 0.01 250);
  --text-3:    oklch(55% 0.012 250);
  --accent-1:        oklch(70% 0.18 255);
  --accent-1-hover:  oklch(75% 0.18 255);
  --accent-1-contrast: oklch(15% 0.01 250);
  --positive:  oklch(70% 0.15 145);
  --warning:   oklch(78% 0.16 75);
  --negative:  oklch(70% 0.20 25);
  --user-bubble:  oklch(28% 0.05 145);
  --assistant-bg: var(--surface-2);
}
```

Theme is set on `<html data-theme="...">` via an inline init script in `base.html` `<head>` to prevent FOUC:

```html
<script>
  (function() {
    var stored = localStorage.getItem('theme');
    var sys = matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
    document.documentElement.dataset.theme = stored || "{{ theme_default }}" || sys;
  })();
</script>
```

## 8. Components

### 8.1 Header bar

- 56px tall, `position: sticky; top: 0`, full width.
- Left: small logo icon + title `Tư vấn tuyển sinh AI`.
- Right cluster (icon buttons, 32px, no labels — `aria-label` + tooltip):
  - Theme toggle: `🌙` (light → dark) / `☀` (dark → light)
  - Help: opens a small popover with version + a "Bắt đầu lại" link (replaces today's prominent header button to declutter the chat panel header)

### 8.2 Profile panel (left)

Two cards stacked, both inside a `<aside class="profile-panel">`:

1. **Hồ sơ tạm thời** — labels + values from `profile_state_json` (admission year, score, majors, location, missing slots). Each row: `label` muted small + `value` bold. Empty state: "Hồ sơ sẽ tự cập nhật khi em trò chuyện."
2. **Khuyến nghị mới nhất** — renders the most recent `assistant_result` content as **markdown** (so school names bold, bullet lists, etc.). Empty: greyed "Chưa có khuyến nghị." Pending (run in progress): 3-line skeleton with pulse animation.

Panel scrolls independently; cards have `--shadow-sm` and `--radius-md`.

### 8.3 Chat panel (center)

**Transcript area** (scrolls, flex column, gap `--space-3`):
- User bubble: right-aligned, `max-width: var(--bubble-max)`, `background: var(--user-bubble)`, radius `10px 10px 2px 10px`.
- Assistant question/follow-up bubble: left-aligned, `background: var(--assistant-bg)`, radius `10px 10px 10px 2px`.
- Assistant result bubble: left-aligned, **full width** (no `max-width` cap), markdown-rendered, slightly larger padding.
- Assistant error bubble: left-aligned, `background` red-tinted, includes "Bấm 'Bắt đầu lại' để thử lại" CTA.
- Each bubble: tiny timestamp `HH:mm` outside on the trailing side, color `--text-3`.
- Greeting empty state: centered card with welcome text + 2–3 example chips (click to fill composer).

**Composer** (sticky bottom):
- Textarea: auto-grow on `input` (cap = `min(6 lines, 240px)`), font `--font-sans`, `--text-md`.
- Hint line under textarea: `Ctrl+Enter để gửi` muted small.
- Right side: spinner + status text when pending (`Đang phân tích...`) and primary `Gửi` button.
- Send disabled when input empty or status pending.
- Submit on Ctrl/⌘+Enter; Enter inserts newline.

### 8.4 Trace panel (right)

Top: heading `Phân tích của AI` + (debug only) toggle "Hiện thêm chi tiết".

Body: `<ol>` of 6 cards driven by `stage_labels` order. Per card:

| Element | Content |
|---|---|
| Icon | Stage icon (lucide SVG inline). Color/animation per status. |
| Name | Vietnamese label from `stage_labels`. |
| Status indicator | `○` pending, `⟳` running (CSS `@keyframes` spin), `✓` completed, `✕` failed. |
| Meta | Empty when pending; `1.2s` when completed; `failed` when failed. |
| Expand body (`<pre>`) | Hidden by default. In **debug mode** the card becomes a `<button>` toggling visibility; the body shows pretty-printed JSON of `output_json` (completed) or `error_text` (failed). Hidden entirely in end-user mode (the `<button>` becomes a `<div>` and no body element exists in the DOM). |

Vertical 1px connector line between cards (using a `::before` pseudo on each card except the last) gives a subtle "timeline" feel.

### 8.5 Toasts (error feedback)

- Fixed top-right, stack up to 3, auto-dismiss after 4s (errors after 8s, with × button).
- Variants: `info` (accent), `warning`, `error` (negative).
- Used for network failures, retry notifications, "Phiên cũ đã hết hạn" cleanup messages.

## 9. JavaScript module contracts

### `modules/theme.js`
```js
export function initTheme();           // runs on DOMContentLoaded after the inline FOUC guard
export function toggleTheme();         // flip + persist + announce via dispatchEvent('theme-change')
```

### `modules/markdown.js`
```js
export function renderMarkdown(src);   // returns sanitized HTML string
```
Implementation: `marked.parse(src, { breaks: true, gfm: true })` then a simple sanitizer that strips `<script>`, `<style>`, `on*=` attributes, and `javascript:` URLs via regex on the parsed string. This is sufficient because content is trusted server output, but defense-in-depth.

### `modules/messages.js`
```js
export function renderTranscript(node, messages);            // wipes + rebuilds
export function appendMessage(node, message);                // optimistic UI
```
Handles bubble class selection by `message.kind`; calls `renderMarkdown` for `assistant_result`.

### `modules/trace.js`
```js
export function renderTrace(events, { debug, stageLabels }); // mutates 6 cards in place
export function startTracePolling(sessionToken, opts);       // unchanged behavior from slice 04
export function stopTracePolling();
```
Polling lifecycle, fetch, render-card status — same logic as today, just relocated.

### `modules/layout.js`
```js
export function initCollapseHandles();   // wires buttons + restores localStorage state
export function openDrawer(side);        // mobile drawer
export function closeDrawer();
```

### `chat.js` (orchestrator)
Wires DOMContentLoaded: theme init, layout init, session bootstrap, form/reset/composer events. ~80–120 lines after refactor (down from ~280 today).

## 10. Server changes

`web/routes/pages.py`:
- Add module constant `STAGE_LABELS` (list of dicts).
- Add `_theme_default()` reading `ADVISORY_THEME_DEFAULT` env (default `"light"`).
- Pass `stage_labels=STAGE_LABELS` and `theme_default=_theme_default()` into the template context alongside existing `debug_ui_enabled`.

`web/templates/base.html`:
- Add inline FOUC-guard theme-init script in `<head>`.
- Add `<script>` tag for marked CDN with SRI hash before `chat.js`.
- Convert `chat.js` `<script>` to `type="module"`.

`web/templates/chat.html`:
- Full rewrite per the layout in §6.1.
- Loop `stage_labels` into trace panel skeleton.

No changes to `/api/sessions/*` endpoints or `/api/sessions/{token}/trace`.

## 11. Migration plan (high-level)

Single slice ("big-bang replace"). Concrete steps are detailed in the implementation plan (see §15) but the order is:

1. Add `tokens.css` + inline theme init + theme toggle.
2. Rewrite `chat.html` shell with 3-column grid + header + composer (no styling polish yet).
3. Rewrite `chat.css` consuming tokens; verify all four panels render correctly.
4. Split JS into modules; messages.js + markdown.js render new bubble styles.
5. trace.js with Vietnamese labels + debug-gated body rendering.
6. layout.js with collapse + mobile drawer.
7. Empty/error/skeleton states.
8. Manual smoke + tests.

All in one branch, one PR. Slice 04 (`/trace` API + 6 stages backend) is **not** touched — only its UI consumer is replaced.

## 12. Testing

**Automated:**
- `tests/web/test_pages.py` — extend: assert `data-theme` attribute renders, `stage_labels` appear in HTML (search for "Phân tích hồ sơ").
- `tests/web/test_chat_page.py` — extend: assert header theme-toggle button id exists, 3 panels (`#profile-panel`, `#chat-panel`, `#trace-panel`) exist, composer textarea + send button still present.
- `tests/web/test_chat_template_render.py` — **NEW**: snapshot-style check that all 6 stage labels are rendered with their icons.
- `tests/web/test_trace_endpoint*.py` — unchanged (API contract not modified).
- `tests/e2e/test_chat_web_flow.py` — verify it still passes with new selectors (update if it queried old class names).

**Manual smoke checklist** (added to QUICKSTART.md):
1. Light → click `🌙` → dark applied immediately, reload → still dark.
2. Toggle left/right column collapse → reload → state persisted.
3. Send "Em muốn học CNTT" → user bubble right, AI follow-up bubble left.
4. Complete profile, trigger run → trace cards flip pending → running (spinner) → completed (duration), Vietnamese labels visible.
5. Visit `/?debug=1` → trace cards become clickable, expand to show `output_json`.
6. Final recommendation: bold school names + bullet list render correctly (markdown).
7. Resize browser < 900px → side panels become drawers, header gains drawer-open icons.
8. Disconnect network mid-run → toast appears, polling auto-retries with backoff.

## 13. Risks & open questions

| Risk | Mitigation |
|---|---|
| `oklch()` color support on older browsers | Fallback `@supports not (color: oklch(0% 0 0))` block with hex equivalents (added in implementation if needed). |
| `marked.js` CDN reachability | SRI hash + `onerror` fallback that displays raw text instead of failing. |
| Inline SVG icons bloating HTML | Define icons once in a hidden `<svg>` `<symbol>` block, reference via `<use href="#icon-search">` — single download. |
| Slice 04 regression while rewriting | Run full `pytest -m "not integration"` after each module rewrite; e2e smoke before commit. |
| Theme flash on first load | Inline `<script>` in `<head>` sets `data-theme` before stylesheet loads. |

**Open question (not blocking implementation):**
- Should the help popover surface app version / build hash? Probably yes for thesis demo, but trivial to add later.

## 14. Done When

- A non-debug visitor sees a polished 3-column UI with light theme by default, can toggle dark, can collapse side panels, sees a friendly Vietnamese "Phân tích của AI" timeline as runs progress, and gets a markdown-rendered recommendation card.
- A debug visitor sees the same UI plus clickable trace cards that expand to `output_json`.
- Mobile (< 900px) viewers see a single-column chat with drawer-accessible side panels.
- All existing `tests/web/*` and `tests/e2e/test_chat_web_flow.py` pass.
- QUICKSTART manual checklist passes.
- No new Python deps; one new CDN-loaded JS lib (`marked`) with SRI.

## 15. Next steps

Once this spec is approved, the implementation plan will be drafted by `superpowers:writing-plans` into:

```
docs/superpowers/plans/2026-05-29-mastra-style-chat-ui/
  ├── 01-tokens-and-theme.md
  ├── 02-shell-and-layout.md
  ├── 03-messages-and-markdown.md
  ├── 04-trace-panel-hybrid.md
  └── 05-states-tests-docs.md
```

(or as a single plan file if appropriately sized; that decision belongs to the planning step).
