// Role-aware global search (combobox pattern). The server decides what the current
// user may see; this module only renders results. Debounced, cancellable, keyboard friendly.
import { get } from "./http.js";
import { $$, debounce, el } from "./util.js";

export function initSearch(input) {
  const box = document.getElementById(input.getAttribute("aria-controls"));
  let ctrl = null;
  let active = -1;

  const close = () => {
    box.hidden = true;
    input.setAttribute("aria-expanded", "false");
    input.removeAttribute("aria-activedescendant");
    active = -1;
  };

  const render = (groups, q) => {
    const frag = document.createDocumentFragment(); // one DOM write
    let i = 0;
    for (const g of groups) {
      if (!g.items.length) continue;
      frag.append(el("div", { class: "group", text: g.label, role: "presentation" }));
      for (const item of g.items) {
        frag.append(el("a", { href: item.url, role: "option", id: `sr-${i++}`, "aria-selected": "false" }, [item.title, item.subtitle ? el("small", { text: item.subtitle }) : null]));
      }
    }
    if (!i) frag.append(el("div", { class: "none", text: `No results for "${q}".` }));
    box.replaceChildren(frag);
    box.hidden = false;
    input.setAttribute("aria-expanded", "true");
    active = -1;
  };

  const run = debounce(async () => {
    const q = input.value.trim();
    if (q.length < 2) return close();
    ctrl?.abort();
    ctrl = new AbortController();
    try {
      const data = await get(`/api/v1/search?q=${encodeURIComponent(q)}`, { signal: ctrl.signal });
      if (input.value.trim() === q) render(data.groups, q);
    } catch (e) {
      if (e.name !== "AbortError") render([], q);
    }
  }, 220);

  input.addEventListener("input", run);
  input.addEventListener("keydown", (e) => {
    const opts = $$('[role="option"]', box);
    if (e.key === "Escape") return close();
    if (!opts.length || box.hidden) return;
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      active = (active + (e.key === "ArrowDown" ? 1 : -1) + opts.length) % opts.length;
      opts.forEach((o, i) => o.setAttribute("aria-selected", String(i === active)));
      input.setAttribute("aria-activedescendant", opts[active].id);
      opts[active].scrollIntoView({ block: "nearest" });
    } else if (e.key === "Enter" && active >= 0) {
      e.preventDefault();
      location.assign(opts[active].href);
    }
  });
  document.addEventListener("click", (e) => {
    if (!e.target.closest("[data-global-search]")) close();
  });
  if (input.value.trim().length >= 2) run();
}
