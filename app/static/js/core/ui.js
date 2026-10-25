// Shared UI behaviour, wired with event delegation on document (one listener per
// event type, works for content added later).
import { $, $$, el, icon, prefersReducedMotion } from "./util.js";

/* ---------------- Toasts ---------------- */
export function toast(message, type = "info", timeout = 4500) {
  const region = $(".toasts");
  if (!region) return;
  const name = type === "success" ? "check-circle" : type === "error" ? "alert" : "info";
  const node = el("div", { class: `toast toast-${type}`, role: type === "error" ? "alert" : "status" }, [icon(name), el("div", { text: message })]);
  region.append(node);
  const remove = () => {
    node.classList.add("is-leaving");
    node.addEventListener("animationend", () => node.remove(), { once: true });
    setTimeout(() => node.remove(), 600);
  };
  setTimeout(remove, timeout);
  node.addEventListener("click", remove);
}

/* ---------------- Focus trap ---------------- */
const FOCUSABLE = 'a[href]:not([tabindex="-1"]), button:not([disabled]):not([tabindex="-1"]), input:not([disabled]):not([type="hidden"]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

export function trapFocus(container, event) {
  if (event.key !== "Tab") return;
  const items = $$(FOCUSABLE, container).filter((n) => n.offsetParent !== null || n === document.activeElement);
  if (!items.length) return;
  const first = items[0];
  const last = items[items.length - 1];
  if (event.shiftKey && document.activeElement === first) {
    last.focus();
    event.preventDefault();
  } else if (!event.shiftKey && document.activeElement === last) {
    first.focus();
    event.preventDefault();
  }
}

/* ---------------- Modals ---------------- */
const openStack = [];

export function openModal(id, opener = document.activeElement) {
  const modal = document.getElementById(id);
  if (!modal || !modal.hidden) return modal;
  modal.hidden = false;
  modal._opener = opener;
  openStack.push(modal);
  document.body.style.overflow = "hidden";
  requestAnimationFrame(() => {
    modal.classList.add("is-open");
    const target = $("[autofocus]", modal) || $("input, textarea, select", modal) || $(FOCUSABLE, $(".modal-dialog", modal));
    target?.focus();
  });
  return modal;
}

export function closeModal(modal) {
  if (!modal || modal.hidden) return;
  modal.classList.remove("is-open");
  const done = () => {
    modal.hidden = true;
    const idx = openStack.indexOf(modal);
    if (idx >= 0) openStack.splice(idx, 1);
    if (!openStack.length) document.body.style.overflow = "";
    modal._opener?.focus?.();
    modal.dispatchEvent(new CustomEvent("modal:closed"));
  };
  if (prefersReducedMotion()) done();
  else setTimeout(done, 240);
}

/**
 * Promise-based confirmation dialog for destructive or sensitive actions.
 * Resolves true/false. `extra` (a Node) is placed in the dialog (e.g. a reason field);
 * `validate()` can block confirmation and return an error message.
 */
export function confirmDialog({ title, body, confirmText = "Confirm", tone = "danger", iconName = "alert", extra = null, validate = null }) {
  const modal = document.getElementById("confirm-modal");
  if (!modal) return Promise.resolve(window.confirm(`${title}\n\n${body}`));
  $("[data-confirm-title]", modal).textContent = title;
  $("[data-confirm-body]", modal).textContent = body;
  const iconBox = $("[data-confirm-icon]", modal);
  iconBox.className = `modal-icon is-${tone}`;
  iconBox.replaceChildren(icon(iconName));
  const extraBox = $("[data-confirm-extra]", modal);
  extraBox.replaceChildren(...(extra ? [extra] : []));
  const ok = $("[data-confirm-ok]", modal);
  ok.className = `btn ${tone === "emergency" ? "btn-emergency" : tone === "danger" ? "btn-danger" : "btn-primary"}`;
  ok.textContent = confirmText;

  return new Promise((resolve) => {
    let settled = false;
    const finish = (value) => {
      if (settled) return;
      settled = true;
      ok.removeEventListener("click", onOk);
      $("[data-confirm-cancel]", modal).removeEventListener("click", onCancel);
      modal.removeEventListener("modal:closed", onClosed);
      closeModal(modal);
      resolve(value);
    };
    const onOk = () => {
      if (validate) {
        const err = validate();
        if (err) return;
      }
      finish(true);
    };
    const onCancel = () => finish(false);
    const onClosed = () => finish(false);
    ok.addEventListener("click", onOk);
    $("[data-confirm-cancel]", modal).addEventListener("click", onCancel);
    modal.addEventListener("modal:closed", onClosed);
    openModal("confirm-modal");
    if (extra) setTimeout(() => $("input, textarea, select", extraBox)?.focus(), 60);
    else setTimeout(() => $("[data-confirm-cancel]", modal).focus(), 60); // safe default
  });
}

/* ---------------- Clipboard ---------------- */
async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    const ta = el("textarea", { style: "position:fixed;opacity:0" });
    ta.value = text;
    document.body.append(ta);
    ta.select();
    const ok = document.execCommand("copy");
    ta.remove();
    return ok;
  }
}

/* ---------------- Password visibility + strength ---------------- */
function passwordStrength(pw) {
  let score = 0;
  if (pw.length >= 10) score++;
  if (/[A-Z]/.test(pw) && /[a-z]/.test(pw)) score++;
  if (/\d/.test(pw)) score++;
  if (/[^A-Za-z0-9]/.test(pw)) score++;
  if (pw.length >= 14 && score === 4) score = 4;
  return pw ? Math.max(1, score) : 0;
}

/* ---------------- Ripple ---------------- */
function ripple(e) {
  const btn = e.target.closest(".btn, .fab");
  if (!btn || btn.disabled || prefersReducedMotion()) return;
  const rect = btn.getBoundingClientRect();
  const size = Math.max(rect.width, rect.height) * 2;
  const r = el("span", { class: "ripple" });
  r.style.width = r.style.height = `${size}px`;
  r.style.left = `${e.clientX - rect.left - size / 2}px`;
  r.style.top = `${e.clientY - rect.top - size / 2}px`;
  btn.append(r);
  r.addEventListener("animationend", () => r.remove(), { once: true });
}

/* ---------------- Accordion ---------------- */
function toggleAccordion(trigger, force) {
  const panel = document.getElementById(trigger.getAttribute("aria-controls"));
  const open = force ?? trigger.getAttribute("aria-expanded") !== "true";
  trigger.setAttribute("aria-expanded", String(open));
  if (panel) panel.hidden = !open;
}

/* ---------------- Tabs ---------------- */
function selectTab(tab) {
  const list = tab.closest('[role="tablist"]');
  $$('[role="tab"]', list).forEach((t) => {
    const on = t === tab;
    t.setAttribute("aria-selected", String(on));
    t.tabIndex = on ? 0 : -1;
    const panel = document.getElementById(t.getAttribute("aria-controls"));
    if (panel) panel.hidden = !on;
  });
  tab.focus();
  tab.dispatchEvent(new CustomEvent("tab:selected", { bubbles: true, detail: tab.dataset }));
}

export function initUI() {
  document.addEventListener("pointerdown", ripple, { passive: true });

  document.addEventListener("click", async (e) => {
    const t = e.target;
    const opener = t.closest("[data-open-modal]");
    if (opener) {
      e.preventDefault();
      openModal(opener.dataset.openModal, opener);
      return;
    }
    const closer = t.closest("[data-close-modal]");
    if (closer) {
      closeModal(closer.closest(".modal"));
      return;
    }
    const copy = t.closest("[data-copy]");
    if (copy) {
      if (await copyText(copy.dataset.copy)) {
        copy.classList.add("is-copied");
        copy.setAttribute("aria-label", "Copied!");
        toast("Copied to clipboard", "success", 1800);
        setTimeout(() => {
          copy.classList.remove("is-copied");
          copy.setAttribute("aria-label", "Copy");
        }, 1600);
      }
      return;
    }
    const pw = t.closest("[data-pw-toggle]");
    if (pw) {
      const input = document.getElementById(pw.dataset.pwToggle);
      const show = input.type === "password";
      input.type = show ? "text" : "password";
      pw.setAttribute("aria-pressed", String(show));
      pw.setAttribute("aria-label", show ? "Hide password" : "Show password");
      pw.querySelector("use").setAttribute("href", show ? "#i-eye-off" : "#i-eye");
      return;
    }
    const acc = t.closest(".accordion-trigger");
    if (acc) {
      toggleAccordion(acc);
      return;
    }
    const tab = t.closest('[role="tab"]');
    if (tab) selectTab(tab);
  });

  document.addEventListener("keydown", (e) => {
    const top = openStack[openStack.length - 1];
    if (top) {
      if (e.key === "Escape" && top.id !== "session-modal") closeModal(top);
      else trapFocus($(".modal-dialog", top), e);
      return;
    }
    // Accordion keyboard support: arrows / Home / End move between headers.
    const acc = e.target.closest?.(".accordion-trigger");
    if (acc && ["ArrowDown", "ArrowUp", "Home", "End"].includes(e.key)) {
      const all = $$(".accordion-trigger", acc.closest(".accordion"));
      let i = all.indexOf(acc);
      i = e.key === "ArrowDown" ? (i + 1) % all.length : e.key === "ArrowUp" ? (i - 1 + all.length) % all.length : e.key === "Home" ? 0 : all.length - 1;
      all[i].focus();
      e.preventDefault();
    }
    const tab = e.target.closest?.('[role="tab"]');
    if (tab && ["ArrowRight", "ArrowLeft"].includes(e.key)) {
      const tabs = $$('[role="tab"]', tab.closest('[role="tablist"]'));
      const i = tabs.indexOf(tab);
      selectTab(tabs[(i + (e.key === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length]);
      e.preventDefault();
    }
  });

  document.addEventListener("input", (e) => {
    const input = e.target;
    if (input.type !== "password" && !input.closest(".input-group")) return;
    const meter = document.querySelector(`[data-pw-meter="${input.id}"]`);
    if (!meter) return;
    const s = passwordStrength(input.value);
    meter.dataset.level = String(s);
    meter.firstElementChild.style.setProperty("--strength", String(s / 4));
  });
}
