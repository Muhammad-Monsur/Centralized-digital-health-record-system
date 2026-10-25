// Scroll reveals (IntersectionObserver) and animated counters. transform/opacity only.
import { $$, prefersReducedMotion } from "./util.js";

function animateCount(node) {
  const target = Number(node.dataset.count);
  if (!Number.isFinite(target)) return;
  const fmt = new Intl.NumberFormat("en");
  if (prefersReducedMotion()) {
    node.textContent = fmt.format(target) + (node.dataset.suffix || "");
    return;
  }
  const dur = 1200;
  const start = performance.now();
  const step = (now) => {
    const p = Math.min(1, (now - start) / dur);
    const eased = 1 - Math.pow(1 - p, 3);
    node.textContent = fmt.format(Math.round(target * eased)) + (node.dataset.suffix || "");
    if (p < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}

export function initMotion() {
  document.documentElement.classList.add("motion-ready");
  // Stagger index for children of [data-stagger] groups (set once, no reflow).
  $$("[data-stagger]").forEach((group) => [...group.children].forEach((c, i) => c.style.setProperty("--i", String(i))));

  const reveals = $$("[data-reveal]");
  const counters = $$("[data-count]");
  if (!("IntersectionObserver" in window)) {
    reveals.forEach((n) => n.classList.add("is-visible"));
    counters.forEach(animateCount);
    return;
  }
  const io = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue;
        const n = entry.target;
        if (n.hasAttribute("data-reveal")) n.classList.add("is-visible");
        if (n.hasAttribute("data-count")) animateCount(n);
        io.unobserve(n);
      }
    },
    { rootMargin: "0px 0px -8% 0px", threshold: 0.12 },
  );
  reveals.forEach((n) => io.observe(n));
  counters.forEach((n) => io.observe(n));
}
