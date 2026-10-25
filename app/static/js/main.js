// Entry module (loaded on every page). Shared behaviour is small and loaded eagerly;
// page-specific code and heavy features (search) are code-split with dynamic import().
import { initCookieBanner } from "./core/cookies.js";
import { initForms } from "./core/forms.js";
import { initMotion } from "./core/motion.js";
import { initNav } from "./core/nav.js";
import { initSessionTimeout } from "./core/session.js";
import { initTheme } from "./core/theme.js";
import { initUI } from "./core/ui.js";

initTheme();
initUI();
initForms();
initNav();
initMotion();
initSessionTimeout();
initCookieBanner();

// Global search: only fetched when the user first focuses the box.
const searchBox = document.getElementById("global-search");
if (searchBox) {
  let loaded = null;
  const load = () => (loaded ??= import("./core/search.js").then((m) => m.initSearch(searchBox)));
  searchBox.addEventListener("focus", load, { once: true });
  if (document.activeElement === searchBox) load();
}

// Templates opt in with {% block page_module %}name{% endblock %}. Explicit import() calls
// (not a template string) let the bundler code-split one chunk per page.
const PAGES = {
  landing: () => import("./pages/landing.js"),
  upload: () => import("./pages/upload.js"),
  "patient-records": () => import("./pages/patient-records.js"),
  "patient-record": () => import("./pages/patient-record.js"),
  "patient-consent": () => import("./pages/patient-consent.js"),
  "doctor-patient": () => import("./pages/doctor-patient.js"),
  admin: () => import("./pages/admin.js"),
  "admin-roles": () => import("./pages/admin-roles.js"),
  "change-password": () => import("./pages/change-password.js"),
  "patient-profile": () => import("./pages/patient-profile.js"),
};
const mod = document.body.dataset.module;
if (mod && PAGES[mod]) {
  PAGES[mod]().then((m) => m.default?.()).catch((err) => console.error("Page module failed", err));
}
