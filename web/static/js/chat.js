import { initTheme } from "./modules/theme.js";
import { initCollapseHandles } from "./modules/layout.js";
import {
  renderTranscript,
  appendMessage,
  appendThinking,
  removeThinking,
  renderRecommendationCard,
} from "./modules/messages.js";
import { revealBubble } from "./modules/typewriter.js";
import {
  renderTrace,
  startTracePolling,
  stopTracePolling,
  debugUiEnabled,
} from "./modules/trace.js";
import { toast } from "./modules/toasts.js";

const COMPOSER_MAX_PX = 240;

function autoGrow(textarea) {
  if (!textarea) return;
  textarea.style.height = "auto";
  textarea.style.height = Math.min(textarea.scrollHeight, COMPOSER_MAX_PX) + "px";
}

function syncSendDisabled() {
  const input = document.getElementById("chat-input");
  const button = document.getElementById("send-button");
  if (!input || !button) return;
  const empty = input.value.trim().length === 0;
  // Disabled while empty, or while a turn is in flight (stops a second submit
  // from racing an in-progress run).
  button.disabled = empty || thinkingActive;
}

const SESSION_KEY = "student-advisory-session-token";
const POLL_INTERVAL_MS = 1200;

let pollTimer = null;
let currentSessionToken = null;
// True from the moment a message is sent until its answer (a follow-up question
// or the final advisory result) lands. Drives the "Đang suy nghĩ..." bubble and
// keeps the send button disabled while a turn is in flight.
let thinkingActive = false;

function setThinking(active) {
  thinkingActive = active;
  syncSendDisabled();
}

// Typewriter state. revealedCount = how many transcript messages have already
// been shown; only a newly-arrived assistant message is animated. suppress is
// set on bootstrap/reset so existing history renders in full (no re-typing).
let revealedCount = 0;
let suppressTypewriter = true;
let currentReveal = null;

const traceOpts = () => ({
  debug: debugUiEnabled(),
  stageLabels: window.__stageLabels || [],
});

function getProfileState(snapshot) {
  return snapshot?.session?.profile_state_json || {};
}

function getLatestRecommendation(messages) {
  return [...messages].reverse().find((message) => message.kind === "assistant_result") || null;
}

function profileIsEmpty(profile) {
  if (!profile) return true;
  return Object.values(profile).every(
    (v) => v == null || v === "" || (Array.isArray(v) && v.length === 0),
  );
}

function renderProfileSummary(snapshot) {
  const node = document.getElementById("profile-summary");
  if (!node) return;
  const profile = getProfileState(snapshot);

  if (profileIsEmpty(profile)) {
    node.innerHTML =
      '<p class="card-empty">Hồ sơ sẽ tự cập nhật khi em trò chuyện.</p>';
    return;
  }

  const entries = [
    ["Năm tuyển sinh", profile.admission_year],
    ["Tổng điểm", profile.total_score],
    ["Ngành quan tâm", (profile.preferred_majors || []).join(", ")],
    ["Khu vực", profile.location_preference],
    ["Còn thiếu", (profile.missing_slots || []).join(", ")],
  ].filter(([, value]) => value);

  if (entries.length === 0) {
    node.innerHTML =
      '<p class="card-empty">Hồ sơ sẽ tự cập nhật khi em trò chuyện.</p>';
    return;
  }

  node.innerHTML = entries
    .map(([label, value]) => `<p><strong>${label}:</strong> ${value}</p>`)
    .join("");
}

function renderRecommendation(snapshot) {
  const node = document.getElementById("recommendation-panel");
  if (!node) return;
  const latest = getLatestRecommendation(snapshot.messages || []);
  const status = snapshot.session?.status;

  if (!latest && (status === "running" || status === "queued")) {
    node.innerHTML = `
      <div class="skeleton" aria-hidden="true">
        <div class="skeleton-line skeleton-line--100"></div>
        <div class="skeleton-line skeleton-line--85"></div>
        <div class="skeleton-line skeleton-line--60"></div>
      </div>
      <span class="visually-hidden">Đang soạn khuyến nghị...</span>`;
    return;
  }

  if (!latest) {
    node.innerHTML = '<p class="card-empty">Chưa có khuyến nghị.</p>';
    return;
  }

  renderRecommendationCard(node, latest.content);
}

// How close (px) to the bottom still counts as "following the conversation".
const STICK_TO_BOTTOM_PX = 80;

function scrollToBottom(transcript) {
  if (transcript) transcript.scrollTop = transcript.scrollHeight;
}

function renderSnapshot(snapshot) {
  const transcript = document.getElementById("chat-transcript");

  // A fresh render supersedes any in-flight typewriter: cancel it (which restores
  // the old bubble's full text) before renderTranscript discards the node.
  if (currentReveal) {
    currentReveal.cancel();
    currentReveal = null;
  }

  // The transcript is its own scroll container (see .chat-transcript in chat.css)
  // and renderTranscript() rebuilds it from scratch on every poll, which would
  // otherwise reset scrollTop to 0. Preserve the user's position: if they were
  // pinned to the bottom, keep following new messages; otherwise restore where
  // they were reading.
  let stickToBottom = true;
  let prevTop = 0;
  if (transcript) {
    prevTop = transcript.scrollTop;
    const distanceFromBottom =
      transcript.scrollHeight - prevTop - transcript.clientHeight;
    stickToBottom = distanceFromBottom <= STICK_TO_BOTTOM_PX;
  }

  const visible = (snapshot.messages || []).filter((m) => m && m.kind !== "system");
  renderTranscript(transcript, snapshot.messages || []);
  renderProfileSummary(snapshot);
  renderRecommendation(snapshot);

  // The "Đang suy nghĩ..." bubble is client-only state; renderTranscript just
  // rebuilt the list from server data and dropped it, so re-attach it while the
  // turn is still being processed (this survives every poll re-render).
  if (transcript && thinkingActive) appendThinking(transcript);

  if (transcript) {
    transcript.scrollTop = stickToBottom ? transcript.scrollHeight : prevTop;
  }

  maybeTypewrite(transcript, visible, stickToBottom);
}

// Animate the last message with a typewriter effect, but only when it is a
// newly-arrived assistant message. Existing history (bootstrap/reset) and the
// user's own bubble are shown in full.
function maybeTypewrite(transcript, visible, stickToBottom) {
  const count = visible.length;

  if (suppressTypewriter) {
    suppressTypewriter = false;
    revealedCount = count;
    return;
  }
  if (!transcript || count <= revealedCount) {
    revealedCount = count;
    return;
  }

  const last = visible[count - 1];
  revealedCount = count;

  const role = last?.role || "assistant";
  if (role === "user" || last?.kind === "assistant_error") return;

  const articles = transcript.querySelectorAll(".message:not(.message--thinking)");
  const bubble = articles[articles.length - 1]?.querySelector(".message__bubble");
  if (!bubble) return;

  currentReveal = revealBubble(bubble, {
    onTick: () => {
      if (stickToBottom) transcript.scrollTop = transcript.scrollHeight;
    },
    onDone: () => {
      currentReveal = null;
    },
  });
}

async function createSession() {
  let response;
  try {
    response = await fetch("/api/sessions", { method: "POST" });
  } catch (e) {
    toast("Không khởi tạo được phiên. Tải lại trang.", { variant: "error" });
    throw e;
  }
  if (!response.ok) {
    toast("Không khởi tạo được phiên. Tải lại trang.", { variant: "error" });
    throw new Error("Không thể tạo phiên chat mới.");
  }
  const payload = await response.json();
  currentSessionToken = payload.session.session_token;
  window.localStorage.setItem(SESSION_KEY, currentSessionToken);
  return payload;
}

async function fetchSessionSnapshot(sessionToken) {
  const response = await fetch(`/api/sessions/${sessionToken}`);
  if (!response.ok) {
    throw new Error("Không thể tải lại lịch sử hội thoại.");
  }
  return response.json();
}

async function ensureSession() {
  const stored = window.localStorage.getItem(SESSION_KEY);
  if (!stored) {
    return createSession();
  }

  try {
    currentSessionToken = stored;
    return await fetchSessionSnapshot(stored);
  } catch (error) {
    window.localStorage.removeItem(SESSION_KEY);
    currentSessionToken = null;
    toast("Phiên cũ đã hết hạn, đã tạo phiên mới.", { variant: "info" });
    return createSession();
  }
}

function stopPolling() {
  if (pollTimer) {
    window.clearTimeout(pollTimer);
    pollTimer = null;
  }
}

function schedulePolling(sessionToken) {
  stopPolling();
  pollTimer = window.setTimeout(async () => {
    try {
      const snapshot = await fetchSessionSnapshot(sessionToken);
      const status = snapshot.session.status;
      // Clear "thinking" before rendering so the bubble disappears exactly when
      // the result (or error) lands, rather than flashing alongside it.
      if (status === "completed" || status === "failed") {
        setThinking(false);
      }
      renderSnapshot(snapshot);
      if (status === "completed") {
        stopPolling();
        stopTracePolling();
        return;
      }
      if (status === "failed") {
        toast("Quá trình phân tích bị gián đoạn.", { variant: "error" });
        stopPolling();
        stopTracePolling();
        return;
      }
      schedulePolling(sessionToken);
    } catch (e) {
      toast("Mất kết nối, đang thử lại...", { variant: "warning" });
      pollTimer = window.setTimeout(() => schedulePolling(sessionToken), POLL_INTERVAL_MS);
    }
  }, POLL_INTERVAL_MS);
}

async function sendMessage(content) {
  const sessionToken = currentSessionToken || window.localStorage.getItem(SESSION_KEY);
  const response = await fetch(`/api/sessions/${sessionToken}/messages`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content }),
  });
  if (!response.ok) {
    throw new Error("Không gửi được tin nhắn.");
  }
  return response.json();
}

document.addEventListener("DOMContentLoaded", async () => {
  const form = document.getElementById("chat-form");
  const input = document.getElementById("chat-input");
  const resetButton = document.getElementById("reset-session");
  const sendButton = document.getElementById("send-button");

  input.addEventListener("input", () => {
    autoGrow(input);
    syncSendDisabled();
  });

  input.addEventListener("keydown", (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
      event.preventDefault();
      if (!sendButton.disabled) form.requestSubmit();
    }
  });

  // Initial state.
  autoGrow(input);
  syncSendDisabled();

  initCollapseHandles();
  initTheme();

  document.getElementById("chat-transcript")?.addEventListener("click", (event) => {
    const chip = event.target.closest(".chip[data-prompt]");
    if (!chip) return;
    const textarea = document.getElementById("chat-input");
    if (!textarea) return;
    textarea.value = chip.dataset.prompt;
    textarea.dispatchEvent(new Event("input", { bubbles: true }));
    textarea.focus();
  });

  const helpButton = document.getElementById("help-button");
  const helpPopover = document.getElementById("help-popover");
  if (helpButton && helpPopover && typeof helpPopover.showModal === "function") {
    helpButton.addEventListener("click", () => {
      if (helpPopover.open) helpPopover.close();
      else helpPopover.showModal();
    });
    helpPopover.addEventListener("click", (e) => {
      if (e.target === helpPopover) helpPopover.close();
    });
  }

  if (debugUiEnabled()) {
    const panel = document.getElementById("trace-panel");
    if (panel) panel.hidden = false;
  }

  try {
    const bootstrap = await ensureSession();
    renderSnapshot(bootstrap);
    if (debugUiEnabled() && bootstrap.session && bootstrap.session.status === "running") {
      startTracePolling(currentSessionToken, traceOpts());
    }
  } catch (error) {
    toast("Không thể khởi tạo phiên chat.", { variant: "error" });
    form.querySelector("button[type='submit']").disabled = true;
    return;
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const content = input.value.trim();
    if (!content) return;

    const transcript = document.getElementById("chat-transcript");

    // Optimistic UX: show the user's message + a "Đang suy nghĩ..." bubble
    // immediately, before the (synchronous) server round-trip, and clear the
    // composer right away. The optimistic user bubble is replaced by the
    // server's copy on the next renderSnapshot (no duplicate).
    transcript?.querySelector(".transcript-greeting")?.remove();
    appendMessage(transcript, {
      role: "user",
      kind: "text",
      content,
      created_at: new Date().toISOString(),
    });
    setThinking(true);
    appendThinking(transcript);
    scrollToBottom(transcript);

    input.value = "";
    autoGrow(input);
    syncSendDisabled();

    try {
      const result = await sendMessage(content);

      const snapshot = await fetchSessionSnapshot(currentSessionToken);

      if (result.should_start_run) {
        // A background run starts; keep "thinking" until polling sees it finish.
        renderSnapshot(snapshot);
        schedulePolling(currentSessionToken);
        startTracePolling(currentSessionToken, traceOpts());
        return;
      }

      // The quick follow-up answer is already in the snapshot — stop thinking.
      setThinking(false);
      renderSnapshot(snapshot);
    } catch (error) {
      setThinking(false);
      removeThinking(transcript);
      toast("Không gửi được tin nhắn.", { variant: "error" });
    }
  });

  resetButton?.addEventListener("click", async () => {
    stopPolling();
    stopTracePolling();
    setThinking(false);
    if (currentReveal) {
      currentReveal.cancel();
      currentReveal = null;
    }
    suppressTypewriter = true;
    window.localStorage.removeItem(SESSION_KEY);
    if (helpPopover?.open) helpPopover.close();
    const snapshot = await createSession();
    renderSnapshot(snapshot);
  });
});
