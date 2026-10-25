// Declarative AJAX forms: <form data-api-form="/api/v1/..." [data-method] [data-redirect]
//   [data-reset-on-success] [data-close-on-success] [data-success="Message"] [data-reload]>
// Client-side checks use the browser's constraint validation (same rules as the server's
// Pydantic schemas); the server remains the authority and its field errors are shown inline.
import { api, ApiError } from "./http.js";
import { closeModal, toast } from "./ui.js";
import { $, $$ } from "./util.js";

function clearErrors(form) {
  $$("[data-error-for]", form).forEach((n) => (n.textContent = ""));
  $$('[aria-invalid="true"]', form).forEach((n) => n.removeAttribute("aria-invalid"));
  const banner = $("[data-form-error]", form.parentElement);
  if (banner) banner.hidden = true;
}

export function showErrors(form, fields = {}, message = "") {
  let firstBad = null;
  for (const [name, msg] of Object.entries(fields)) {
    const input = form.elements.namedItem(name.split(".").pop());
    const slot = $(`[data-error-for="${CSS.escape(name.split(".").pop())}"]`, form);
    if (slot) slot.textContent = msg;
    if (input && input.setAttribute) {
      input.setAttribute("aria-invalid", "true");
      firstBad ??= input;
    }
  }
  const banner = $("[data-form-error]", form.parentElement);
  if (message && (!Object.keys(fields).length || !firstBad)) {
    if (banner) {
      banner.querySelector("p").textContent = message;
      banner.hidden = false;
    } else toast(message, "error");
  }
  firstBad?.focus();
}

function clientValidate(form) {
  const fields = {};
  for (const input of form.elements) {
    if (!input.name || input.disabled || !input.willValidate) continue;
    if (!input.checkValidity()) {
      const label = form.querySelector(`label[for="${input.id}"]`)?.firstChild?.textContent?.trim() || "This field";
      let msg = input.validationMessage;
      if (input.validity.valueMissing) msg = `${label} is required.`;
      else if (input.validity.typeMismatch && input.type === "email") msg = "Enter a valid email address.";
      else if (input.validity.patternMismatch) msg = document.getElementById(`${input.id}-hint`)?.textContent?.trim() || msg;
      fields[input.name] = msg;
    }
  }
  return fields;
}

export function serialize(form) {
  const hasFile = $$('input[type="file"]', form).some((i) => i.files?.length);
  if (hasFile || form.enctype === "multipart/form-data") return new FormData(form);
  const out = {};
  for (const [k, v] of new FormData(form).entries()) {
    const input = form.elements.namedItem(k);
    if (input?.type === "checkbox") out[k] = true;
    else if (input?.dataset?.type === "int") out[k] = v === "" ? null : Number(v);
    else out[k] = v === "" && input?.dataset?.nullable !== undefined ? null : v;
  }
  $$('input[type="checkbox"][name]', form).forEach((c) => {
    if (!c.checked && c.value === "on") out[c.name] = false;
  });
  return out;
}

export function setLoading(btn, on) {
  if (!btn) return;
  btn.classList.toggle("is-loading", on);
  btn.disabled = on;
  btn.setAttribute("aria-busy", String(on));
}

export function initForms() {
  // Clear a field's error as soon as the person edits it, so the red state never outlives the problem.
  document.addEventListener("input", (e) => {
    const el = e.target;
    if (!el?.form || el.getAttribute?.("aria-invalid") !== "true") return;
    el.removeAttribute("aria-invalid");
    const slot = el.form.querySelector(`[data-error-for="${CSS.escape(el.name)}"]`);
    if (slot) slot.textContent = "";
  });
  document.addEventListener("submit", async (e) => {
    const form = e.target.closest("form[data-api-form]");
    if (!form) return;
    e.preventDefault();
    clearErrors(form);
    const clientErrors = clientValidate(form);
    if (Object.keys(clientErrors).length) {
      showErrors(form, clientErrors);
      return;
    }
    const btn = e.submitter || $('[type="submit"]', form);
    setLoading(btn, true);
    let navigating = false;
    try {
      const data = await api(form.dataset.apiForm, { method: form.dataset.method || "POST", body: serialize(form) });
      form.dispatchEvent(new CustomEvent("form:success", { detail: data, bubbles: true }));
      if (form.hasAttribute("data-redirect") && data?.redirect) {
        navigating = true; // keep the spinner while the next page loads
        location.assign(data.redirect);
        return;
      }
      const msg = form.dataset.success || data?.detail;
      if (msg) toast(msg, "success");
      if (form.hasAttribute("data-reset-on-success")) form.reset();
      if (form.hasAttribute("data-close-on-success")) closeModal(form.closest(".modal"));
      if (form.hasAttribute("data-reload")) setTimeout(() => location.reload(), 600);
    } catch (err) {
      if (err instanceof ApiError) showErrors(form, err.fields, err.message);
      else if (err.name !== "AbortError") toast("Something went wrong. Try again.", "error");
    } finally {
      if (!navigating) setLoading(btn, false);
    }
  });
}
