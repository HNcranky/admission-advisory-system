// web/static/js/modules/layout.js
// Layout helpers: collapse-able side panels (persisted) + mobile drawers.

const LAYOUT_STORAGE_KEY = "layout";
const MOBILE_QUERY = "(max-width: 899px)";

function readLayoutState() {
  try {
    const raw = window.localStorage.getItem(LAYOUT_STORAGE_KEY);
    if (!raw) return { left: false, right: false };
    const parsed = JSON.parse(raw);
    return {
      left: Boolean(parsed.left),
      right: Boolean(parsed.right),
    };
  } catch {
    return { left: false, right: false };
  }
}

function writeLayoutState(state) {
  try {
    window.localStorage.setItem(LAYOUT_STORAGE_KEY, JSON.stringify(state));
  } catch {
    /* storage unavailable; skip persistence */
  }
}

function applyCollapsed(shell, state) {
  shell.classList.toggle("left-collapsed", state.left);
  shell.classList.toggle("right-collapsed", state.right);
  const leftPanel = document.getElementById("profile-panel");
  const rightPanel = document.getElementById("trace-panel");
  if (leftPanel) leftPanel.setAttribute("aria-hidden", String(state.left));
  if (rightPanel) rightPanel.setAttribute("aria-hidden", String(state.right));
}

function wireCollapseButton(shell, state, side) {
  const buttonId = side === "left" ? "collapse-left" : "collapse-right";
  const button = document.getElementById(buttonId);
  if (!button) return;
  button.addEventListener("click", () => {
    state[side] = !state[side];
    applyCollapsed(shell, state);
    writeLayoutState(state);
  });
}

let activeDrawer = null;
let drawerOpener = null;
let escListener = null;

function backdrop() {
  return document.getElementById("drawer-backdrop");
}

function panelIdForSide(side) {
  return side === "right" ? "trace-panel" : "profile-panel";
}

export function openDrawer(side) {
  const panel = document.getElementById(panelIdForSide(side));
  if (!panel) return;
  if (activeDrawer && activeDrawer !== panel) {
    activeDrawer.classList.remove("panel--drawer-open");
  }
  drawerOpener = document.activeElement;
  activeDrawer = panel;
  panel.classList.add("panel--drawer-open");
  document.body.classList.add("drawer-open");
  const bd = backdrop();
  if (bd) {
    bd.hidden = false;
    bd.addEventListener("click", closeDrawer, { once: true });
  }
  if (!escListener) {
    escListener = (e) => { if (e.key === "Escape") closeDrawer(); };
    document.addEventListener("keydown", escListener);
  }
  const closeBtn = panel.querySelector(".panel__drawer-close");
  if (closeBtn) closeBtn.focus();
}

export function closeDrawer() {
  if (!activeDrawer) return;
  activeDrawer.classList.remove("panel--drawer-open");
  document.body.classList.remove("drawer-open");
  const bd = backdrop();
  if (bd) bd.hidden = true;
  if (escListener) {
    document.removeEventListener("keydown", escListener);
    escListener = null;
  }
  if (drawerOpener && typeof drawerOpener.focus === "function") {
    drawerOpener.focus();
  }
  activeDrawer = null;
  drawerOpener = null;
}

function wireDrawerButton(side) {
  const buttonId = side === "left" ? "open-left-drawer" : "open-right-drawer";
  const button = document.getElementById(buttonId);
  if (!button) return;
  button.addEventListener("click", () => openDrawer(side));
}

function wireDrawerDismiss() {
  const panels = ["profile-panel", "trace-panel"];
  panels.forEach((id) => {
    const closeBtn = document.getElementById(id)?.querySelector(".panel__drawer-close");
    if (closeBtn) closeBtn.addEventListener("click", closeDrawer);
  });
}

function syncDrawerForViewport(mql) {
  if (!mql.matches) closeDrawer();
}

export function initCollapseHandles() {
  const shell = document.querySelector(".app-shell");
  if (!shell) return;

  const state = readLayoutState();
  applyCollapsed(shell, state);

  wireCollapseButton(shell, state, "left");
  wireCollapseButton(shell, state, "right");
  wireDrawerButton("left");
  wireDrawerButton("right");
  wireDrawerDismiss();

  const mql = window.matchMedia(MOBILE_QUERY);
  syncDrawerForViewport(mql);
  if (typeof mql.addEventListener === "function") {
    mql.addEventListener("change", syncDrawerForViewport);
  } else if (typeof mql.addListener === "function") {
    // Safari < 14 fallback
    mql.addListener(syncDrawerForViewport);
  }
}
