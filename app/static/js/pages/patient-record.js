// Single record: visibility switch (optimistic, rolls back on error) and delete with confirmation.
import { del, patch } from "../core/http.js";
import { confirmDialog, toast } from "../core/ui.js";
import { $, el, icon } from "../core/util.js";

export default function init() {
  const toggle = $("[data-visibility-toggle]");
  const label = $("[data-vis-label]");
  const badgeSlot = $("[data-vis-badge]");

  const paint = (vis) => {
    label.textContent = vis === "public" ? "Public" : "Private";
    badgeSlot.replaceChildren(
      vis === "public" ? el("span", { class: "badge badge-public" }, [icon("globe"), "Public"]) : el("span", { class: "badge badge-private" }, [icon("lock"), "Private"]),
    );
  };

  toggle?.addEventListener("change", async () => {
    const vis = toggle.checked ? "public" : "private";
    if (vis === "public") {
      const ok = await confirmDialog({
        title: "Make this record public?",
        body: "Any verified clinician who has your patient ID will be able to read it without asking you. You can switch it back to private at any time.",
        confirmText: "Make public",
        tone: "primary",
        iconName: "globe",
      });
      if (!ok) {
        toggle.checked = false;
        return;
      }
    }
    toggle.disabled = true;
    paint(vis);
    try {
      const res = await patch(`/api/v1/patient/records/${toggle.dataset.visibilityToggle}/visibility`, { visibility: vis });
      toast(res.detail, "success");
      setTimeout(() => location.reload(), 900); // refresh the update-history timeline
    } catch (e) {
      toggle.checked = !toggle.checked;
      paint(toggle.checked ? "public" : "private");
      toast(e.message, "error");
    } finally {
      toggle.disabled = false;
    }
  });

  document.addEventListener("click", async (e) => {
    if (e.target.closest("[data-print]")) return window.print();
    const btn = e.target.closest("[data-delete-record]");
    if (!btn) return;
    const ok = await confirmDialog({
      title: "Delete this document?",
      body: "It will disappear from your records and no doctor will be able to see it. The deletion is kept in the audit trail.",
      confirmText: "Delete document",
      iconName: "trash",
    });
    if (!ok) return;
    try {
      const res = await del(`/api/v1/patient/records/${btn.dataset.deleteRecord}`);
      toast(res.detail, "success");
      location.assign(res.redirect);
    } catch (err) {
      toast(err.message, "error");
    }
  });
}
