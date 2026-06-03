// web/static/js/modules/theme.js
//
// Theme management for the advisory-agent chat UI.
//
// The inline FOUC-guard script in base.html has already set
// `<html data-theme="light|dark">` before this module loads. This module:
//   - wires the #theme-toggle button click,
//   - listens to system prefers-color-scheme changes (only honors them
//     when the user has not made an explicit choice in localStorage),
//   - exposes toggleTheme() for programmatic flips.

const STORAGE_KEY = "theme";
const VALID = new Set(["light", "dark"]);

function readStored() {
  try {
    const v = window.localStorage.getItem(STORAGE_KEY);
    return VALID.has(v) ? v : null;
  } catch (e) {
    return null;
  }
}

function writeStored(theme) {
  try {
    window.localStorage.setItem(STORAGE_KEY, theme);
  } catch (e) {
    /* ignore quota / private-mode errors */
  }
}

function applyTheme(theme) {
  if (!VALID.has(theme)) return;
  document.documentElement.dataset.theme = theme;
  document.dispatchEvent(
    new CustomEvent("theme-change", { detail: { theme } })
  );
}

export function toggleTheme() {
  const current = document.documentElement.dataset.theme === "dark" ? "dark" : "light";
  const next = current === "dark" ? "light" : "dark";
  applyTheme(next);
  writeStored(next);
  return next;
}

export function initTheme() {
  const button = document.getElementById("theme-toggle");
  if (button) {
    button.addEventListener("click", () => {
      toggleTheme();
    });
  }

  // Honor system preference changes only when the user has not chosen.
  if (typeof window.matchMedia === "function") {
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const handler = (event) => {
      if (readStored() !== null) return; // explicit choice wins
      applyTheme(event.matches ? "dark" : "light");
    };
    if (typeof mq.addEventListener === "function") {
      mq.addEventListener("change", handler);
    } else if (typeof mq.addListener === "function") {
      // Safari < 14 fallback
      mq.addListener(handler);
    }
  }
}
