// Records list: in-place filtering with skeletons, server-side pagination, URL kept in sync.
import { get } from "../core/http.js";
import { toast } from "../core/ui.js";
import { $, debounce, el, icon } from "../core/util.js";

function badge(vis) {
  return vis === "public"
    ? el("span", { class: "badge badge-public" }, [icon("globe"), "Public"])
    : el("span", { class: "badge badge-private" }, [icon("lock"), "Private"]);
}

function row(r) {
  const meta = [el("span", { text: r.type_label }), el("span", { text: r.date }), el("span", { text: `Uploaded by ${r.author}` })];
  if (r.has_file) meta.push(el("span", { text: "Has attachment" }));
  return el("li", { class: "record-row" }, [
    el("span", { class: "ri" }, [icon(r.has_file ? "file-plus" : "file")]),
    el("div", { class: "rt" }, [el("a", { href: r.url, text: r.title }), el("div", { class: "rm" }, meta)]),
    el("div", { class: "rb" }, [badge(r.visibility)]),
  ]);
}

function skeleton(n = 5) {
  const frag = document.createDocumentFragment();
  for (let i = 0; i < n; i++) {
    frag.append(el("div", { class: "record-row", "aria-hidden": "true" }, [
      el("span", { class: "skeleton", style: "width:42px;height:42px;border-radius:12px" }),
      el("div", {}, [el("div", { class: "skeleton skeleton-line w-60" }), el("div", { class: "skeleton skeleton-line w-40", style: "margin:0" })]),
      el("span", { class: "skeleton", style: "width:70px;height:22px;border-radius:999px" }),
    ]));
  }
  return frag;
}

function pager(meta, onGo) {
  if (meta.total <= meta.per_page) return document.createDocumentFragment();
  const from = (meta.page - 1) * meta.per_page + 1;
  const to = Math.min(meta.page * meta.per_page, meta.total);
  const btn = (label, page, disabled, ico) =>
    el("button", { type: "button", class: "btn btn-sm", "aria-label": label, disabled, onclick: () => onGo(page) }, [icon(ico)]);
  return el("nav", { class: "pagination", "aria-label": "Pagination" }, [
    el("span", { text: `Showing ${from}–${to} of ${meta.total}` }),
    el("div", { class: "pages" }, [
      btn("Previous page", meta.page - 1, meta.page <= 1, "chevron-left"),
      el("span", { class: "btn btn-sm btn-ghost", "aria-current": "page", text: `Page ${meta.page} of ${meta.pages}` }),
      btn("Next page", meta.page + 1, meta.page >= meta.pages, "chevron-right"),
    ]),
  ]);
}

export default function init() {
  const form = $("[data-records-filter]");
  const region = $("[data-records-region]");
  if (!form || !region) return;
  let ctrl;

  async function load(page = 1) {
    const params = new URLSearchParams(new FormData(form));
    for (const [k, v] of [...params]) if (!v) params.delete(k);
    if (page > 1) params.set("page", String(page));
    history.replaceState(null, "", `/patient/records${params.size ? "?" + params : ""}`);

    ctrl?.abort();
    ctrl = new AbortController();
    region.setAttribute("aria-busy", "true");
    const list = el("ul", { class: "record-list" });
    list.append(skeleton());
    region.replaceChildren(list);
    try {
      const data = await get(`/api/v1/patient/records?${params}`, { signal: ctrl.signal });
      const frag = document.createDocumentFragment();
      if (data.items.length) {
        const ul = el("ul", { class: "record-list stagger" });
        data.items.forEach((r, i) => {
          const li = row(r);
          li.style.setProperty("--i", String(i));
          ul.append(li);
        });
        frag.append(ul);
      } else {
        frag.append(el("div", { class: "empty" }, [icon("search"), el("h2", { text: "No records match these filters" }), el("p", { text: "Try a different search or clear the filters." })]));
      }
      frag.append(pager(data, load));
      region.replaceChildren(frag); // single DOM write
    } catch (e) {
      if (e.name !== "AbortError") {
        toast(e.message, "error");
        region.replaceChildren(el("div", { class: "empty" }, [el("p", { text: "Couldn't load records." })]));
      }
    } finally {
      region.setAttribute("aria-busy", "false");
    }
  }

  const debounced = debounce(() => load(1), 300);
  form.addEventListener("input", (e) => (e.target.type === "search" ? debounced() : load(1)));
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    load(1);
  });
  // Server-rendered pagination links -> in-place loading
  region.addEventListener("click", (e) => {
    const a = e.target.closest(".pagination a[href]");
    if (!a || a.getAttribute("aria-disabled") === "true") return;
    e.preventDefault();
    load(Number(new URL(a.href).searchParams.get("page") || 1));
  });
  document.addEventListener("click", (e) => e.target.closest("[data-print]") && window.print());
}
