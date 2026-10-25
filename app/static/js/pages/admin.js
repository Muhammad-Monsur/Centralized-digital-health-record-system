// Admin portal: account dialog, confirmations for sensitive actions, settings, backups.
import { post, put } from "../core/http.js";
import { setLoading, showErrors } from "../core/forms.js";
import { confirmDialog, openModal, toast } from "../core/ui.js";
import { $, $$, el } from "../core/util.js";

function setKind(kind) {
  const form = $("[data-account-form]");
  if (!form) return;
  const radio = $(`input[name="kind"][value="${kind}"]`, form);
  if (radio) radio.checked = true;
  const current = $('input[name="kind"]:checked', form)?.value || "doctor";
  $$("[data-for-kind]", form).forEach((f) => (f.hidden = f.dataset.forKind !== current));
  $("#acc-title").textContent = { doctor: "Create a doctor account", staff: "Create a staff account", hospital_admin: "Create a hospital admin" }[current];
}

async function act(fn, reload = true) {
  try {
    const res = await fn();
    toast(res.detail, "success");
    if (res.redirect) setTimeout(() => location.assign(res.redirect), 900);
    else if (reload) setTimeout(() => location.reload(), 700);
  } catch (e) {
    toast(e.message, "error");
  }
}

export default function init() {
  // Account dialog: kind from the button that opened it; fields follow the chosen kind.
  document.addEventListener("click", (e) => {
    const opener = e.target.closest('[data-open-modal="account-modal"]');
    if (opener) setKind(opener.dataset.kind || "doctor");
  }, true);
  document.addEventListener("change", (e) => {
    if (e.target.matches('[data-account-form] input[name="kind"]')) setKind(e.target.value);
    if (e.target.matches("[data-autosubmit]")) e.target.form.requestSubmit();
  });
  const auto = $("[data-auto-open]");
  if (auto?.dataset.autoOpen) {
    setKind(auto.dataset.autoKind || "doctor");
    openModal(auto.dataset.autoOpen);
  } else setKind("doctor");

  document.addEventListener("click", async (e) => {
    const t = e.target;

    const st = t.closest("[data-user-status]");
    if (st) {
      const off = st.dataset.userStatus === "inactive";
      const ok = await confirmDialog({
        title: off ? `Deactivate ${st.dataset.name}?` : `Reactivate ${st.dataset.name}?`,
        body: off ? "They are signed out everywhere immediately and can't sign in until reactivated. Their records and audit history stay." : "They'll be able to sign in again.",
        confirmText: off ? "Deactivate" : "Reactivate", tone: off ? "danger" : "primary", iconName: off ? "lock" : "unlock",
      });
      if (ok) act(() => post(`/api/v1/admin/users/${st.dataset.user}/status`, { status: st.dataset.userStatus }));
      return;
    }
    const unlock = t.closest("[data-unlock]");
    if (unlock) return act(() => post(`/api/v1/admin/users/${unlock.dataset.unlock}/unlock`));

    const ver = t.closest("[data-verify]");
    if (ver) {
      const rejecting = ver.dataset.verify === "rejected";
      const note = el("textarea", { class: "textarea", id: "verify-note", maxlength: "500", placeholder: "Reason shown to the doctor (optional)" });
      const ok = await confirmDialog({
        title: rejecting ? "Reject this licence?" : "Verify this licence?",
        body: rejecting ? "The doctor loses all clinical access until verified again." : "The doctor gets clinical access at your hospital.",
        confirmText: rejecting ? "Reject" : "Verify", tone: rejecting ? "danger" : "primary", iconName: rejecting ? "x" : "check",
        extra: rejecting ? el("div", { class: "field" }, [el("label", { for: "verify-note", text: "Reason" }), note]) : null,
      });
      if (ok) act(() => post(`/api/v1/admin/users/${ver.dataset.user}/verify`, { status: ver.dataset.verify, note: note.value.trim() || null }));
      return;
    }
    const hs = t.closest("[data-hospital-status]");
    if (hs) {
      const off = hs.dataset.hospitalStatus === "inactive";
      const ok = await confirmDialog({
        title: off ? `Deactivate ${hs.dataset.name}?` : `Reactivate ${hs.dataset.name}?`,
        body: off ? "All its doctors and staff immediately lose clinical access, and its admins lose admin access." : "Its staff regain access.",
        confirmText: off ? "Deactivate hospital" : "Reactivate", tone: off ? "danger" : "primary", iconName: "hospital",
      });
      if (ok) act(() => post(`/api/v1/admin/hospitals/${hs.dataset.hospital}/status`, { status: hs.dataset.hospitalStatus }));
      return;
    }
    const em = t.closest("[data-admin-end-emergency]");
    if (em) {
      const ok = await confirmDialog({ title: "End this emergency access?", body: `${em.dataset.doctor} will immediately lose access to the patient's private records.`, confirmText: "End access", tone: "emergency", iconName: "siren" });
      if (ok) act(() => post(`/api/v1/admin/emergency/${em.dataset.adminEndEmergency}/end`));
      return;
    }
    const mk = t.closest("[data-create-backup]");
    if (mk) {
      setLoading(mk, true);
      await act(() => post("/api/v1/admin/backups"));
      setLoading(mk, false);
      return;
    }
    const rs = t.closest("[data-restore]");
    if (rs) {
      const input = el("input", { class: "input", id: "restore-confirm", autocomplete: "off", "aria-describedby": "restore-hint" });
      const err = el("p", { class: "error", role: "alert" });
      const ok = await confirmDialog({
        title: "Restore this backup?",
        body: `Every table and document goes back to ${rs.dataset.created} UTC. Changes since then are replaced (a safety backup is taken first) and everyone is signed out.`,
        confirmText: "Restore backup", iconName: "refresh",
        extra: el("div", { class: "field" }, [el("label", { for: "restore-confirm", text: "Type RESTORE to confirm" }), input, el("p", { class: "hint", id: "restore-hint", text: "This can't be undone from here except by restoring the safety backup." }), err]),
        validate: () => {
          if (input.value.trim() !== "RESTORE") {
            err.textContent = "Type RESTORE exactly.";
            input.focus();
            return "x";
          }
          return null;
        },
      });
      if (!ok) return;
      setLoading(rs, true);
      try {
        const res = await post(`/api/v1/admin/backups/${encodeURIComponent(rs.dataset.restore)}/restore`, { confirm: "RESTORE" });
        toast(res.detail, "success", 8000);
        setTimeout(() => location.assign(res.redirect), 2500);
      } catch (err2) {
        toast(err2.message, "error", 8000);
        setLoading(rs, false);
      }
    }
  });

  // Password reset needs an explicit confirmation before the generic form handler runs.
  document.addEventListener("submit", async (e) => {
    const form = e.target.closest("[data-confirm-reset]");
    if (!form || form.dataset.confirmed === "1") {
      if (form) delete form.dataset.confirmed;
      return;
    }
    e.preventDefault();
    e.stopImmediatePropagation();
    const ok = await confirmDialog({ title: `Reset ${form.dataset.confirmReset}'s password?`, body: "They'll be signed out everywhere and must use the new password.", confirmText: "Reset password", iconName: "key" });
    if (ok) {
      form.dataset.confirmed = "1";
      form.requestSubmit();
    }
  }, true);

  const sf = $("[data-settings-form]");
  sf?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const values = {};
    $$("[data-setting]", sf).forEach((i) => (values[i.dataset.setting] = i.type === "checkbox" ? String(i.checked) : i.value));
    const btn = $('[type="submit"]', sf);
    setLoading(btn, true);
    try {
      toast((await put("/api/v1/admin/settings", { values })).detail, "success");
    } catch (err) {
      showErrors(sf, err.fields || {}, err.message);
    } finally {
      setLoading(btn, false);
    }
  });
}
