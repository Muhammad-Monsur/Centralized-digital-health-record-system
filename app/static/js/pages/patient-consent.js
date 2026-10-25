// Consent flow on the patient side: approve -> OTP -> active; decline; revoke (with confirmations).
import { post, ApiError } from "../core/http.js";
import { confirmDialog, toast } from "../core/ui.js";
import { setLoading } from "../core/forms.js";
import { $ } from "../core/util.js";

function showOtp(card, consentId) {
  card.dataset.consent = consentId;
  $("[data-answer-step]", card).hidden = true;
  const step = $("[data-otp-step]", card);
  step.hidden = false;
  $("input[name=code]", step).focus();
}

export default function init() {
  document.addEventListener("click", async (e) => {
    const approve = e.target.closest("[data-approve]");
    if (approve) {
      const card = approve.closest("[data-request]");
      const hours = Number($(`input[name="dur-${approve.dataset.approve}"]:checked`, card)?.value || 24);
      setLoading(approve, true);
      try {
        const res = await post(`/api/v1/patient/consent/requests/${approve.dataset.approve}/approve`, { duration_hours: hours });
        toast(res.detail, "success");
        showOtp(card, res.consent_id);
      } catch (err) {
        toast(err.message, "error");
      } finally {
        setLoading(approve, false);
      }
      return;
    }

    const resend = e.target.closest("[data-resend]");
    if (resend) {
      const card = resend.closest("[data-request]");
      setLoading(resend, true);
      try {
        const res = await post(`/api/v1/patient/consent/${card.dataset.consent}/resend`);
        toast(res.detail, "success");
      } catch (err) {
        toast(err.message, "error");
      } finally {
        setLoading(resend, false);
      }
      return;
    }

    const reject = e.target.closest("[data-reject]");
    if (reject) {
      const ok = await confirmDialog({
        title: "Decline this request?",
        body: `${reject.dataset.doctor} won't be able to see your private records. They can still see records you've made public.`,
        confirmText: "Decline request",
        iconName: "x",
      });
      if (!ok) return;
      try {
        const res = await post(`/api/v1/patient/consent/requests/${reject.dataset.reject}/reject`);
        toast(res.detail, "success");
        setTimeout(() => location.reload(), 700);
      } catch (err) {
        toast(err.message, "error");
      }
      return;
    }

    const revoke = e.target.closest("[data-revoke]");
    if (revoke) {
      const ok = await confirmDialog({
        title: "Revoke access now?",
        body: `${revoke.dataset.doctor} will lose access to your private records immediately.`,
        confirmText: "Revoke access",
        iconName: "unlock",
      });
      if (!ok) return;
      try {
        const res = await post(`/api/v1/patient/consent/${revoke.dataset.revoke}/revoke`);
        toast(res.detail, "success");
        setTimeout(() => location.reload(), 700);
      } catch (err) {
        toast(err.message, "error");
      }
    }
  });

  document.addEventListener("submit", async (e) => {
    const form = e.target.closest("[data-otp-step]");
    if (!form) return;
    e.preventDefault();
    const card = form.closest("[data-request]");
    const input = $("input[name=code]", form);
    const errSlot = $('[data-error-for="code"]', form);
    errSlot.textContent = "";
    input.removeAttribute("aria-invalid");
    const code = input.value.replace(/\D/g, "");
    if (code.length !== 6) {
      errSlot.textContent = "Enter the 6-digit code.";
      input.setAttribute("aria-invalid", "true");
      input.focus();
      return;
    }
    const btn = $('[type="submit"]', form);
    setLoading(btn, true);
    try {
      const res = await post(`/api/v1/patient/consent/${card.dataset.consent}/verify`, { code });
      toast(res.detail, "success");
      location.assign(res.redirect);
    } catch (err) {
      errSlot.textContent = err instanceof ApiError ? err.message : "Something went wrong.";
      input.setAttribute("aria-invalid", "true");
      input.select();
      setLoading(btn, false);
    }
  });

  // Paste-friendly OTP field: keep digits only.
  document.addEventListener("input", (e) => {
    if (e.target.matches?.(".otp-input")) e.target.value = e.target.value.replace(/\D/g, "").slice(0, 6);
  });
}
