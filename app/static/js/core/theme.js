// Dark-mode toggle. The initial theme is set by the inline no-flash script in <head>;
// this module only handles toggling, persisting, and following the OS when unset.
import { storage } from "./util.js";

const KEY = "cdhrs-theme";
const root = document.documentElement;

function apply(theme) {
  root.setAttribute("data-theme", theme);
  document.querySelectorAll("[data-theme-toggle]").forEach((b) => {
    b.setAttribute("aria-label", theme === "dark" ? "Switch to light theme" : "Switch to dark theme");
    b.setAttribute("aria-pressed", String(theme === "dark"));
  });
}

export function initTheme() {
  apply(root.getAttribute("data-theme") || "light");
  document.addEventListener("click", (e) => {
    if (!e.target.closest("[data-theme-toggle]")) return;
    const next = root.getAttribute("data-theme") === "dark" ? "light" : "dark";
    storage(KEY, next);
    apply(next);
  });
  // Follow OS changes only while the user hasn't chosen explicitly.
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", (m) => {
    if (!storage(KEY)) apply(m.matches ? "dark" : "light");
  });
}
