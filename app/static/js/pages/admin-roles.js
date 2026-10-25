// RBAC editor: save a role's permission set, activate/deactivate custom roles, restore defaults.
import { post, put } from "../core/http.js";
import { setLoading } from "../core/forms.js";
import { confirmDialog, toast } from "../core/ui.js";
import { $, $$ } from "../core/util.js";

export default function init() {
  $$("[data-role-form]").forEach((form) => {
    const initial = new Set($$('input[name="perm"]:checked', form).map((i) => i.value));
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const chosen = $$('input[name="perm"]:checked', form).map((i) => i.value);
      const removed = [...initial].filter((p) => !chosen.includes(p));
      if (removed.length) {
        const ok = await confirmDialog({
          title: `Remove ${removed.length} permission${removed.length > 1 ? "s" : ""} from ${form.dataset.roleName}?`,
          body: `Users with this role lose: ${removed.join(", ")}. This takes effect on their next request.`,
          confirmText: "Save changes", iconName: "shield",
        });
        if (!ok) return;
      }
      const btn = $('[type="submit"]', form);
      setLoading(btn, true);
      try {
        const res = await put(`/api/v1/admin/roles/${form.dataset.roleForm}/permissions`, { permissions: chosen });
        toast(res.detail, "success");
        initial.clear();
        chosen.forEach((p) => initial.add(p));
      } catch (err) {
        toast(err.message, "error");
      } finally {
        setLoading(btn, false);
      }
    });
  });

  document.addEventListener("click", async (e) => {
    const st = e.target.closest("[data-role-status]");
    if (st) {
      const ok = await confirmDialog({ title: `${st.dataset.roleStatus === "inactive" ? "Deactivate" : "Activate"} this role?`, body: "Users with this role gain or lose its permissions on their next request.", confirmText: "Confirm", iconName: "shield" });
      if (!ok) return;
      try {
        toast((await post(`/api/v1/admin/roles/${st.dataset.role}/status`, { status: st.dataset.roleStatus })).detail, "success");
        setTimeout(() => location.reload(), 600);
      } catch (err) {
        toast(err.message, "error");
      }
    }
    const rs = e.target.closest("[data-role-reset]");
    if (rs) {
      const ok = await confirmDialog({ title: "Restore default permissions?", body: "Any changes you made to this built-in role are replaced by the defaults.", confirmText: "Restore defaults", iconName: "refresh" });
      if (!ok) return;
      try {
        toast((await post(`/api/v1/admin/roles/${rs.dataset.roleReset}/reset`)).detail, "success");
        setTimeout(() => location.reload(), 600);
      } catch (err) {
        toast(err.message, "error");
      }
    }
  });
}
