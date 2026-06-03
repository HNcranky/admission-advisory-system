// modules/typewriter.js
// Client-side "streaming" effect. The bubble is already rendered in full
// (markdown -> HTML); we reveal its text node-by-node so structure/markup never
// appears half-parsed. Total duration is capped so long answers don't drag.

const MAX_DURATION_MS = 1200;
const FRAME_MS = 16;

function prefersReducedMotion() {
  try {
    return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  } catch {
    return false;
  }
}

function collectTextNodes(root) {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const nodes = [];
  let node;
  while ((node = walker.nextNode())) {
    if (node.nodeValue && node.nodeValue.length) nodes.push(node);
  }
  return nodes;
}

// Progressively reveal `el`'s text. Returns a handle with cancel() that, when
// called, immediately restores the full text (used when a new render supersedes
// this animation). opts.onTick fires after each frame (e.g. to keep scrolled to
// bottom); opts.onDone fires once when fully revealed.
export function revealBubble(el, opts = {}) {
  const onTick = typeof opts.onTick === "function" ? opts.onTick : () => {};
  const onDone = typeof opts.onDone === "function" ? opts.onDone : () => {};

  const nodes = el ? collectTextNodes(el) : [];
  if (!nodes.length || prefersReducedMotion()) {
    onTick();
    onDone();
    return { cancel() {} };
  }

  const fulls = nodes.map((n) => n.nodeValue);
  const total = fulls.reduce((sum, t) => sum + t.length, 0);
  nodes.forEach((n) => { n.nodeValue = ""; });

  const charsPerFrame = Math.max(1, Math.ceil((total * FRAME_MS) / MAX_DURATION_MS));

  let nodeIdx = 0;
  let shownInNode = 0;
  let cancelled = false;
  let rafId = null;

  const restoreAll = () => nodes.forEach((n, i) => { n.nodeValue = fulls[i]; });

  const step = () => {
    if (cancelled) return;
    let budget = charsPerFrame;
    while (budget > 0 && nodeIdx < nodes.length) {
      const fullText = fulls[nodeIdx];
      const take = Math.min(budget, fullText.length - shownInNode);
      shownInNode += take;
      budget -= take;
      nodes[nodeIdx].nodeValue = fullText.slice(0, shownInNode);
      if (shownInNode >= fullText.length) {
        nodeIdx += 1;
        shownInNode = 0;
      }
    }
    onTick();
    if (nodeIdx >= nodes.length) {
      onDone();
      return;
    }
    rafId = window.requestAnimationFrame(step);
  };

  rafId = window.requestAnimationFrame(step);

  return {
    cancel() {
      if (cancelled) return;
      cancelled = true;
      if (rafId != null) window.cancelAnimationFrame(rafId);
      restoreAll();
      onTick();
    },
  };
}
