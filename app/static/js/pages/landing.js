// Landing page: the hero "how it works" cycle (partials/hero_cycle.html).
//
// Every 3 s the next scene slides into the glass card, its node lights up and the orbit dot travels
// to it. Auto-play pauses while the cycle is off-screen, the tab is hidden, or keyboard focus is
// inside it, and is off from the start with prefers-reduced-motion. The pause button and the step
// buttons always work. Only transform/opacity change.
import { $, $$, prefersReducedMotion } from "../core/util.js";

function initCycle(root) {
  const scenes = $$(".cy-scene", root);
  const nodes = $$(".cy-node-btn", root);
  const segs = $$(".cy-seg", root);
  const orbit = $(".cy-orbit", root);
  const count = $("[data-cy-count]", root);
  const bar = $("[data-cy-bar]", root);
  const pauseBtn = $("[data-cy-pause]", root);
  const N = scenes.length;
  const DUR = 3000;

  let current = 0;
  let angle = 0;
  let timer = 0;
  let startedAt = 0;
  let remaining = DUR;
  let userPaused = prefersReducedMotion();
  let hovered = false; // keyboard focus inside
  let visible = true;

  const running = () => !userPaused && !hovered && visible && !document.hidden;

  function restartBar() {
    bar.classList.remove("run");
    void bar.offsetWidth; // restart the CSS animation
    bar.classList.add("run");
  }

  function show(next, manual = false) {
    const prev = current;
    let delta = (next - prev + N) % N;
    if (manual && delta > N / 2) delta -= N; // jump back the short way
    angle += delta * (360 / N);
    current = next;

    scenes.forEach((s, k) => {
      const on = k === next;
      s.classList.toggle("is-active", on);
      s.classList.toggle("is-leaving", k === prev && !on);
      s.toggleAttribute("inert", !on);
      if (on) s.removeAttribute("aria-hidden");
      else s.setAttribute("aria-hidden", "true");
    });
    nodes.forEach((b, k) => {
      if (k === next) b.setAttribute("aria-current", "step");
      else b.removeAttribute("aria-current");
      b.classList.toggle("is-done", k < next);
    });
    segs.forEach((g, k) => g.classList.toggle("is-lit", k < next));
    if (orbit) orbit.style.transform = `rotate(${angle}deg)`;
    if (count) count.textContent = String(next + 1);

    remaining = DUR;
    restartBar();
    schedule();
  }

  function schedule() {
    clearTimeout(timer);
    const on = running();
    root.classList.toggle("is-paused", !on);
    if (!on) return;
    startedAt = performance.now();
    timer = setTimeout(() => show((current + 1) % N), remaining);
  }

  function hold() {
    if (root.classList.contains("is-paused")) return;
    remaining = Math.max(200, remaining - (performance.now() - startedAt));
    clearTimeout(timer);
    root.classList.add("is-paused");
  }

  function update() {
    if (running()) schedule();
    else hold();
  }

  function setUserPaused(p) {
    userPaused = p;
    root.classList.toggle("is-user-paused", p);
    pauseBtn.setAttribute("aria-pressed", String(p));
    pauseBtn.setAttribute("aria-label", p ? "Play the animation" : "Pause the animation");
    update();
  }

  pauseBtn.addEventListener("click", () => setUserPaused(!userPaused));
  nodes.forEach((b) => b.addEventListener("click", () => show(Number(b.dataset.step), true)));

  // Keyboard users get time to read; a mouse click on a step just jumps and carries on.
  root.addEventListener("focusin", (e) => { if (e.target.matches(":focus-visible")) { hovered = true; update(); } });
  root.addEventListener("focusout", (e) => { if (!root.contains(e.relatedTarget)) { hovered = false; update(); } });
  document.addEventListener("visibilitychange", update);
  if ("IntersectionObserver" in window) {
    new IntersectionObserver(([entry]) => { visible = entry.isIntersecting; update(); }, { threshold: 0.25 }).observe(root);
  }

  setUserPaused(userPaused);
  show(0);
}

export default function init() {
  const cycle = $("[data-cycle]");
  if (cycle) initCycle(cycle);
}
