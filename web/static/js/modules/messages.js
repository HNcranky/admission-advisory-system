// modules/messages.js
// Owns all chat-bubble construction and the left-panel recommendation card.

import { renderMarkdown } from "./markdown.js";

function formatTimestamp(iso) {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  const hh = String(d.getHours()).padStart(2, "0");
  const mm = String(d.getMinutes()).padStart(2, "0");
  return { iso, label: `${hh}:${mm}` };
}

function timestampNode(message) {
  const ts = formatTimestamp(message.created_at);
  if (!ts) return null;
  const time = document.createElement("time");
  time.className = "message__timestamp";
  time.setAttribute("datetime", ts.iso);
  time.textContent = ts.label;
  return time;
}

function _messageEl(message) {
  const article = document.createElement("article");
  const role = message.role || "assistant";
  const kind = message.kind || "text";
  article.className = `message message--${role} message--${kind}`;
  article.dataset.kind = kind;
  article.dataset.role = role;

  const bubble = document.createElement("div");
  bubble.className = "message__bubble";

  if (kind === "assistant_result") {
    bubble.classList.add("message__bubble--full", "message__bubble--markdown");
    bubble.innerHTML = renderMarkdown(message.content || "");
  } else if (kind === "assistant_error") {
    bubble.textContent = message.content || "";
    const cta = document.createElement("p");
    cta.className = "message__cta";
    cta.textContent = "Bấm 'Bắt đầu lại' để thử lại";
    bubble.appendChild(cta);
  } else {
    bubble.textContent = message.content || "";
  }

  article.appendChild(bubble);

  const ts = timestampNode(message);
  if (ts) article.appendChild(ts);

  return article;
}

const GREETING_PROMPTS = [
  "Em muốn học ngành CNTT, điểm thi 25.",
  "Em ở Hà Nội, muốn học kinh tế ở trường công lập.",
  "Em đang phân vân giữa Bách Khoa và Kinh tế Quốc dân.",
];

export function renderGreeting(node) {
  if (!node) return;
  node.innerHTML = "";
  const wrap = document.createElement("div");
  wrap.className = "transcript-greeting";
  wrap.innerHTML = `
    <div class="transcript-greeting__icon" aria-hidden="true">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"
           stroke-linecap="round" stroke-linejoin="round" width="40" height="40">
        <path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"/>
      </svg>
    </div>
    <p class="transcript-greeting__title">
      Xin chào! Hãy mô tả tình hình xét tuyển của em...
    </p>
    <ul class="transcript-greeting__chips" role="list">
      ${GREETING_PROMPTS.map(
        (p) => `<li><button type="button" class="chip" data-prompt="${p.replace(/"/g, "&quot;")}">${p}</button></li>`,
      ).join("")}
    </ul>
  `;
  node.append(wrap);
}

export function renderTranscript(node, messages) {
  if (!node) return;
  const visible = (messages || []).filter((m) => m && m.kind !== "system");
  if (visible.length === 0) {
    renderGreeting(node);
    return;
  }
  node.innerHTML = "";
  visible.forEach((message) => {
    node.appendChild(_messageEl(message));
  });
}

export function appendMessage(node, message) {
  if (!node || !message) return;
  node.appendChild(_messageEl(message));
}

export const THINKING_TEXT = "Đang suy nghĩ";

// Client-only placeholder shown in the assistant slot while a turn is being
// processed. Idempotent — never stacks two indicators.
export function appendThinking(node) {
  if (!node || node.querySelector(".message--thinking")) return;
  const article = document.createElement("article");
  article.className = "message message--assistant message--thinking";
  article.dataset.role = "assistant";
  article.dataset.kind = "thinking";

  const bubble = document.createElement("div");
  bubble.className = "message__bubble message__bubble--thinking";
  bubble.textContent = THINKING_TEXT;
  article.appendChild(bubble);

  node.appendChild(article);
}

export function removeThinking(node) {
  if (!node) return;
  node.querySelector(".message--thinking")?.remove();
}

export function renderRecommendationCard(node, content) {
  if (!node) return;
  if (!content) {
    node.textContent = "Chưa có khuyến nghị.";
    node.classList.remove("recommendation--has-content");
    return;
  }
  node.classList.add("recommendation--has-content");
  node.innerHTML = `<div class="message__bubble message__bubble--markdown">${renderMarkdown(content)}</div>`;
}
