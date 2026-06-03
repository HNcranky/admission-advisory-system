// modules/markdown.js
// Wraps window.marked with a defense-in-depth sanitizer. Content is trusted
// (server-generated) but we still strip script/style/on*/javascript: URLs and
// force safe link attributes.

const JS_URL_RE = /^\s*javascript:/i;

function sanitize(html) {
  const doc = new DOMParser().parseFromString(html, "text/html");

  doc.querySelectorAll("script, style").forEach((el) => el.remove());

  doc.querySelectorAll("*").forEach((el) => {
    // Strip on*= event handlers and any javascript: URLs.
    [...el.attributes].forEach((attr) => {
      const name = attr.name.toLowerCase();
      const value = attr.value || "";
      if (name.startsWith("on")) {
        el.removeAttribute(attr.name);
        return;
      }
      if ((name === "href" || name === "src") && JS_URL_RE.test(value)) {
        el.removeAttribute(attr.name);
      }
    });
  });

  doc.querySelectorAll("a").forEach((a) => {
    a.setAttribute("target", "_blank");
    a.setAttribute("rel", "noopener nofollow");
  });

  return doc.body.innerHTML;
}

export function renderMarkdown(src) {
  if (src == null) return "";
  if (typeof window === "undefined" || !window.marked) {
    // Fallback: escape and preserve newlines so the user still sees something.
    const div = document.createElement("div");
    div.textContent = String(src);
    return div.innerHTML.replace(/\n/g, "<br>");
  }
  const raw = window.marked.parse(String(src), { breaks: true, gfm: true });
  return sanitize(raw);
}
