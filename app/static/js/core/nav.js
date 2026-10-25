// Header, scroll progress, back-to-top, mobile drawer, page transitions, logout.
import { post } from "./http.js";
import { trapFocus } from "./ui.js";
import { $, $$, loginUrl, prefersReducedMotion, rafThrottle } from "./util.js";

function initScroll() {
  const header = $("[data-sticky-header]");
  const bar = $(".scroll-progress");
  const top = $("[data-back-to-top]");
  const doc = document.documentElement;
  let max = 1;
  const measure = () => (max = Math.max(1, doc.scrollHeight - innerHeight)); // read once per resize
  measure();
  addEventListener("resize", rafThrottle(measure), { passive: true });
  new ResizeObserver(rafThrottle(measure)).observe(document.body);

  const onScroll = rafThrottle(() => {
    const y = scrollY;
    if (bar) bar.style.transform = `scaleX(${Math.min(1, y / max)})`; // transform only
    header?.classList.toggle("is-scrolled", y > 8);
    top?.classList.toggle("is-visible", y > 600);
  });
  addEventListener("scroll", onScroll, { passive: true });
  onScroll();

  top?.addEventListener("click", () => {
    scrollTo({ top: 0, behavior: prefersReducedMotion() ? "auto" : "smooth" });
    $("#main")?.focus({ preventScroll: true });
  });
}

function initDrawers() {
  let open = null;
  let opener = null;

  const close = () => {
    if (!open) return;
    const d = open;
    d.classList.remove("is-open");
    opener?.setAttribute("aria-expanded", "false");
    setTimeout(() => (d.hidden = true), prefersReducedMotion() ? 0 : 260);
    document.body.style.overflow = "";
    opener?.focus();
    open = null;
  };

  document.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-drawer-open]");
    if (btn) {
      const d = document.getElementById(btn.dataset.drawerOpen);
      opener = btn;
      d.hidden = false;
      open = d;
      btn.setAttribute("aria-expanded", "true");
      document.body.style.overflow = "hidden";
      requestAnimationFrame(() => {
        d.classList.add("is-open");
        $("a, button", $(".drawer-panel", d))?.focus();
      });
      return;
    }
    if (open && (e.target.closest("[data-drawer-close]") || e.target.closest(".drawer-panel a"))) close();
  });
  document.addEventListener("keydown", (e) => {
    if (!open) return;
    if (e.key === "Escape") close();
    else trapFocus($(".drawer-panel", open), e);
  });
  matchMedia("(min-width: 961px)").addEventListener("change", (m) => m.matches && close());
}

/** Same-origin link clicks: show the route loader and fade the page out (progressive enhancement). */
function initTransitions() {
  const loader = $(".route-loader");
  document.addEventListener("click", (e) => {
    const a = e.target.closest("a[href]");
    if (!a || e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    if (a.target || a.hasAttribute("download") || a.getAttribute("aria-disabled") === "true") {
      if (a.getAttribute("aria-disabled") === "true") e.preventDefault();
      return;
    }
    const url = new URL(a.href, location.href);
    if (url.origin !== location.origin || url.pathname.startsWith("/api/")) return;
    if (url.pathname === location.pathname && url.hash) return; // in-page anchor
    loader?.classList.add("is-active");
    if (!prefersReducedMotion()) document.body.classList.add("is-leaving");
  });
  // Back/forward cache restores: undo the leaving state.
  addEventListener("pageshow", () => {
    loader?.classList.remove("is-active");
    document.body.classList.remove("is-leaving");
  });
}

function initLogout() {
  document.addEventListener("click", async (e) => {
    const btn = e.target.closest("[data-logout]");
    if (!btn) return;
    btn.disabled = true;
    try {
      const res = await post("/api/v1/auth/logout");
      location.assign(res.redirect || loginUrl());
    } catch {
      location.assign(loginUrl());
    }
  });
}

export function initNav() {
  initScroll();
  initDrawers();
  initTransitions();
  initLogout();
  // Highlight current page in public nav
  $$(".nav-primary a").forEach((a) => {
    if (a.pathname === location.pathname && !a.hash) a.setAttribute("aria-current", "page");
  });
}
