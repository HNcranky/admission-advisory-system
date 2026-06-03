// web/static/js/modules/trace.js
//
// Trace panel renderer + polling lifecycle.
// Exported API:
//   debugUiEnabled()                                — boolean, combines template flag + ?debug=1
//   renderTrace(events, { debug, stageLabels })    — mutates the 6 cards in-place
//   startTracePolling(token, { debug, stageLabels })
//   stopTracePolling()
//
// Card row promotion (div -> button) happens lazily inside renderTrace
// the first time it sees a card with debug=true. Promotion is tracked
// via dataset.debugWired so we never wire twice.

import { toast } from "./toasts.js";

const TRACE_POLL_INTERVAL_MS = 1000;

let lastTraceToastAt = 0;

function maybeToastTraceFailure() {
  const now = Date.now();
  if (now - lastTraceToastAt < 10_000) return;
  lastTraceToastAt = now;
  toast("Mất kết nối tới trace, đang thử lại...", { variant: "warning" });
}

let tracePollTimer = null;
const expandedStages = new Set();

export function debugUiEnabled() {
  const fromGlobal = window.__debugUi === true;
  const fromTemplate = document.querySelector(".chat-shell")?.dataset.debugUi === "true";
  const fromUrl = new URLSearchParams(window.location.search).get("debug") === "1";
  return fromGlobal || fromTemplate || fromUrl;
}

function formatDuration(ms) {
  if (ms == null) return "";
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

function statusMeta(event) {
  switch (event.status) {
    case "completed": return formatDuration(event.duration_ms);
    case "running":   return "";           // spinner alone communicates state
    case "failed":    return "Lỗi";
    default:          return "";           // pending: empty (no "pending" noise)
  }
}

function statusSymbolId(status) {
  switch (status) {
    case "completed": return "icon-status-completed";
    case "running":   return "icon-status-running";
    case "failed":    return "icon-status-failed";
    default:          return "icon-status-pending";
  }
}

function setStatusIcon(card, status) {
  const useEl = card.querySelector(".trace-card__status .icon use");
  if (useEl) {
    useEl.setAttribute("href", `#${statusSymbolId(status)}`);
  }
}

function promoteRowToButton(card) {
  if (card.dataset.debugWired === "true") return;
  const row = card.querySelector(".trace-card__row");
  if (!row || row.tagName === "BUTTON") {
    card.dataset.debugWired = "true";
    return;
  }
  const button = document.createElement("button");
  button.type = "button";
  button.className = row.className;
  button.setAttribute("aria-expanded", "false");
  while (row.firstChild) button.appendChild(row.firstChild);
  row.replaceWith(button);

  button.addEventListener("click", () => {
    const stage = card.dataset.stage;
    const body = card.querySelector(".trace-card__body");
    const expanded = expandedStages.has(stage);
    if (expanded) {
      expandedStages.delete(stage);
      body.hidden = true;
      button.setAttribute("aria-expanded", "false");
    } else {
      expandedStages.add(stage);
      body.hidden = false;
      button.setAttribute("aria-expanded", "true");
    }
  });

  card.dataset.debugWired = "true";
}

export function renderTrace(events, { debug, stageLabels } = {}) {
  const root = document.getElementById("trace-cards");
  if (!root) return;

  events.forEach((event) => {
    const card = root.querySelector(`[data-stage="${event.stage}"]`);
    if (!card) return;

    // Status class
    card.classList.remove(
      "trace-card--pending",
      "trace-card--running",
      "trace-card--completed",
      "trace-card--failed",
    );
    card.classList.add(`trace-card--${event.status}`);

    // Status icon swap
    setStatusIcon(card, event.status);

    // Meta text
    const metaEl = card.querySelector(".trace-card__meta");
    if (metaEl) metaEl.textContent = statusMeta(event);

    // Body content — debug-gated
    const body = card.querySelector(".trace-card__body");
    if (!body) return;

    if (debug) {
      promoteRowToButton(card);

      if (event.status === "completed" && event.output_json) {
        body.textContent = JSON.stringify(event.output_json, null, 2);
      } else if (event.status === "failed") {
        body.textContent = event.error_text || "(no error text)";
      } else {
        body.textContent = "";
      }

      // Restore expanded state
      const isExpanded = expandedStages.has(event.stage);
      body.hidden = !isExpanded;
      const row = card.querySelector(".trace-card__row");
      if (row && row.tagName === "BUTTON") {
        row.setAttribute("aria-expanded", String(isExpanded));
      }
    } else {
      // End-user mode: never inject JSON into the DOM
      body.textContent = "";
      body.hidden = true;
    }
  });
  // stageLabels is currently unused by renderTrace but reserved for
  // future i18n of meta strings ("Lỗi", duration suffix, etc.).
  void stageLabels;
}

async function fetchTrace(sessionToken) {
  const r = await fetch(`/api/sessions/${sessionToken}/trace`);
  if (!r.ok) throw new Error("trace fetch failed");
  return r.json();
}

export function stopTracePolling() {
  if (tracePollTimer) {
    window.clearTimeout(tracePollTimer);
    tracePollTimer = null;
  }
}

export function startTracePolling(sessionToken, opts = {}) {
  stopTracePolling();

  const tick = async () => {
    try {
      const payload = await fetchTrace(sessionToken);
      renderTrace(payload.events, opts);
      if (payload.run_status === "running" || payload.run_status === "queued") {
        tracePollTimer = window.setTimeout(tick, TRACE_POLL_INTERVAL_MS);
      }
    } catch (e) {
      // trace fetch failures must not interfere with the chat UX
      maybeToastTraceFailure();
      tracePollTimer = window.setTimeout(tick, TRACE_POLL_INTERVAL_MS * 2);
    }
  };

  tick();
}
