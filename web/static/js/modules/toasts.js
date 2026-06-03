// modules/toasts.js
// Non-blocking toast notifications. Self-contained ES module, no deps.

const STACK_ID = "toast-stack";
const MAX_TOASTS = 3;
const DEFAULT_TIMEOUT_MS = 4000;
const ERROR_TIMEOUT_MS = 8000;

function stack() {
  return document.getElementById(STACK_ID);
}

function evictOldest(list) {
  while (list.children.length >= MAX_TOASTS) {
    const first = list.firstElementChild;
    if (!first) break;
    first.remove();
  }
}

function dismiss(el) {
  if (!el || el.dataset.dismissing === "1") return;
  el.dataset.dismissing = "1";
  el.classList.add("toast--leaving");
  window.setTimeout(() => el.remove(), 200);
}

/**
 * Show a non-blocking toast.
 * @param {string} message
 * @param {{ variant?: 'info'|'warning'|'error', timeoutMs?: number }} [opts]
 */
export function toast(message, opts = {}) {
  const list = stack();
  if (!list) return;

  const variant = opts.variant || "info";
  const timeoutMs =
    opts.timeoutMs != null
      ? opts.timeoutMs
      : variant === "error"
      ? ERROR_TIMEOUT_MS
      : DEFAULT_TIMEOUT_MS;

  evictOldest(list);

  const item = document.createElement("li");
  item.className = `toast toast--${variant}`;
  item.setAttribute("role", variant === "error" ? "alert" : "status");

  const body = document.createElement("span");
  body.className = "toast__body";
  body.textContent = message;
  item.append(body);

  if (variant === "error") {
    const close = document.createElement("button");
    close.type = "button";
    close.className = "toast__close";
    close.setAttribute("aria-label", "Đóng");
    close.textContent = "×";
    close.addEventListener("click", () => dismiss(item));
    item.append(close);
  }

  list.append(item);

  if (timeoutMs > 0) {
    window.setTimeout(() => dismiss(item), timeoutMs);
  }
}
