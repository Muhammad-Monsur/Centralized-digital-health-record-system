// After the forced password change, continue to the user's portal.
export default function init() {
  document.addEventListener("form:success", (e) => {
    if (e.target.matches("[data-change-password]")) setTimeout(() => location.assign(e.detail.portal || "/"), 700);
  });
}
