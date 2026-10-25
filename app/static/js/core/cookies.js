// Cookie notice: shown once, remembers the visitor's choice.
import { $, storage } from "./util.js";

const KEY = "cdhrs-cookie-consent";

export function initCookieBanner() {
  const banner = $("[data-cookie-banner]");
  if (!banner || storage(KEY)) return;
  banner.hidden = false;
  requestAnimationFrame(() => requestAnimationFrame(() => banner.classList.add("is-visible")));
  banner.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-cookie-choice]");
    if (!btn) return;
    storage(KEY, `${btn.dataset.cookieChoice}:${new Date().toISOString().slice(0, 10)}`);
    banner.classList.remove("is-visible");
    setTimeout(() => (banner.hidden = true), 400);
  });
}
