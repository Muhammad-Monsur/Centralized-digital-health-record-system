// Session timeout warning. The server sends the remaining seconds in a <meta> tag;
// a warning dialog appears before expiry and offers "Stay signed in".
import { get, post } from "./http.js";
import { closeModal, openModal } from "./ui.js";
import { $, loginUrl } from "./util.js";

export function initSessionTimeout() {
  const meta = $('meta[name="session-expires"]');
  const modal = document.getElementById("session-modal");
  if (!meta || !modal) return;
  const warnAt = Number($('meta[name="session-warning"]')?.content || 60);
  let deadline = Date.now() + Number(meta.content) * 1000;
  let tick = null;
  let warnTimer = null;
  const countdown = $("[data-session-countdown]", modal);

  const schedule = () => {
    clearTimeout(warnTimer);
    const ms = deadline - Date.now() - warnAt * 1000;
    warnTimer = setTimeout(check, Math.max(0, ms));
  };

  // Before warning, re-check with the server: activity in another tab may have extended the session.
  async function check() {
    try {
      const s = await get("/api/v1/session/status");
      if (!s.authenticated) return expire();
      deadline = Date.now() + s.expires_in * 1000;
      if (s.expires_in > warnAt + 2) return schedule();
    } catch {
      /* offline: fall through to warning */
    }
    warn();
  }

  function warn() {
    openModal("session-modal");
    clearInterval(tick);
    const update = () => {
      const left = Math.max(0, Math.round((deadline - Date.now()) / 1000));
      countdown.textContent = String(left);
      if (left <= 0) expire();
    };
    update();
    tick = setInterval(update, 1000);
  }

  async function expire() {
    clearInterval(tick);
    const target = loginUrl(); // read before the session (and meta) is gone
    try {
      await post("/api/v1/auth/logout?reason=timeout");
    } catch {
      /* already gone */
    }
    location.assign(`${target}?reason=timeout&next=${encodeURIComponent(location.pathname)}`);
  }

  $("[data-session-extend]", modal).addEventListener("click", async () => {
    try {
      const s = await post("/api/v1/session/extend");
      deadline = Date.now() + s.expires_in * 1000;
      clearInterval(tick);
      closeModal(modal);
      schedule();
    } catch {
      expire();
    }
  });
  $("[data-session-logout]", modal).addEventListener("click", expire);

  // Any API call made by the page extends the session server-side; mirror that locally.
  document.addEventListener("form:success", () => {
    deadline = Date.now() + Number(meta.content) * 1000;
    schedule();
  });
  schedule();
}
