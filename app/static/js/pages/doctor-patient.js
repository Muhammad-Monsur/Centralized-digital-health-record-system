// Doctor portal actions: end emergency access, cancel a request, filter, print.
import { post } from "../core/http.js";
import { confirmDialog, toast } from "../core/ui.js";

export default function init() {
  document.addEventListener("change", (e) => {
    if (e.target.matches("[data-autosubmit]")) e.target.form.requestSubmit();
  });

  document.addEventListener("click", async (e) => {
    if (e.target.closest("[data-print]")) return window.print();

    const end = e.target.closest("[data-end-emergency]");
    if (end) {
      const ok = await confirmDialog({
        title: "End emergency access?",
        body: "You'll go back to seeing only public records, unless the patient has given consent.",
        confirmText: "End access",
        tone: "emergency",
        iconName: "siren",
      });
      if (!ok) return;
      try {
        toast((await post(`/api/v1/doctor/emergency/${end.dataset.endEmergency}/end`)).detail, "success");
        setTimeout(() => location.reload(), 600);
      } catch (err) {
        toast(err.message, "error");
      }
      return;
    }

    const cancel = e.target.closest("[data-cancel-request]");
    if (cancel) {
      const ok = await confirmDialog({ title: "Cancel this request?", body: "The patient will no longer see it.", confirmText: "Cancel request", iconName: "x" });
      if (!ok) return;
      try {
        toast((await post(`/api/v1/doctor/access-requests/${cancel.dataset.cancelRequest}/cancel`)).detail, "success");
        setTimeout(() => location.reload(), 600);
      } catch (err) {
        toast(err.message, "error");
      }
    }
  });
}
