// Ask for the current password only when the mobile number or email actually changes.
import { $ } from "../core/util.js";

export default function init() {
  const phone = $("#phone");
  const email = $("#email");
  const box = $("[data-reauth]");
  if (!phone || !email || !box) return;
  const initial = { phone: phone.value, email: email.value };
  const update = () => {
    const changed = phone.value.trim() !== initial.phone || email.value.trim().toLowerCase() !== initial.email.toLowerCase();
    box.hidden = !changed;
    const input = $("input", box);
    input.required = changed;
    if (!changed) input.value = "";
  };
  phone.addEventListener("input", update);
  email.addEventListener("input", update);
}
