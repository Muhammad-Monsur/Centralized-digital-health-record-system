/* CDHRS shared auth client - used by every portal (login, register, profile). */
(function () {
  const $ = (s, r = document) => r.querySelector(s);

  async function api(url, options = {}) {
    const res = await fetch(url, Object.assign({ credentials: "same-origin" }, options));
    let data = {};
    try { data = await res.json(); } catch (e) {}
    if (!res.ok) {
      let msg = data.detail || "Something went wrong. Please try again.";
      if (Array.isArray(msg)) msg = "Please fill in all required fields.";
      const err = new Error(msg); err.status = res.status; throw err;
    }
    return data;
  }
  const post = (url, body) => api(url, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {})
  });

  function showError(form, msg) {
    const box = $(".form-error", form);
    if (!box) return alert(msg);
    box.textContent = msg; box.hidden = false;
  }
  const clearError = (form) => { const b = $(".form-error", form); if (b) b.hidden = true; };

  /* ---------- login / register forms ---------- */
  const form = $("form[data-auth]");
  if (form) {
    const kind = form.dataset.auth;
    const btn = $('button[type="submit"]', form);
    const label = btn.textContent;

    // Buttons that aren't wired yet (Google / passkey)
    document.querySelectorAll(".auth-form .btn-outline").forEach((b) => {
      if (/google|passkey/i.test(b.textContent)) {
        b.addEventListener("click", () => showError(form, "This sign-in option isn't available yet. Please use your email and password."));
      }
    });

    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      clearError(form);
      const f = new FormData(form);
      const val = (n) => (f.get(n) || "").toString();
      try {
        let body, url;
        if (kind === "login") {
          if (!val("email").trim() || !val("password")) return showError(form, "Please enter your email and password.");
          url = "/api/auth/login";
          body = { email: val("email"), password: val("password"), portal: form.dataset.portal };
        } else {
          if (val("password") !== val("confirm_password")) return showError(form, "Passwords do not match.");
          if (!f.get("terms")) return showError(form, "Please accept the Terms of Service to continue.");
          url = "/api/auth/register";
          body = {
            full_name: val("full_name"), email: val("email"), phone: val("phone"),
            gender: val("gender").startsWith("Select") ? "" : val("gender"), dob: val("dob"),
            password: val("password"), confirm_password: val("confirm_password"),
          };
        }
        btn.disabled = true; btn.textContent = kind === "login" ? "Signing in…" : "Creating account…";
        const data = await post(url, body);
        window.location.href = data.redirect;
      } catch (err) {
        showError(form, err.message);
        btn.disabled = false; btn.textContent = label;
      }
    });
  }

  /* ---------- signed-in portal pages ---------- */
  if (document.body.dataset.portal) {
    const portal = document.body.dataset.portal;
    const goLogin = () => (window.location.href = `/${portal}/login.html`);

    api("/api/me").then((u) => {
      const parts = u.full_name.split(/\s+/).filter((w) => !/^dr\.?$/i.test(w));
      const initials = ((parts[0] || "?")[0] + (parts[1] ? parts[1][0] : "")).toUpperCase();

      const fields = {
        name: u.full_name, initials, email: u.email, phone: u.phone, gender: u.gender,
        sub: "Patient ID: " + (u.patient_id || "—") + (u.dob ? " · DOB: " + u.dob : ""),
      };
      document.querySelectorAll("[data-me]").forEach((el) => {
        const v = fields[el.dataset.me];
        el.textContent = v ? v : "—";
      });

      // top-bar user pill + sign-out menu
      const pill = $(".avatar-pill");
      if (pill) {
        pill.innerHTML = `<span class="avatar-circle">${initials}</span> ${u.full_name} ▾
          <div class="user-menu" hidden><button type="button" id="signOut">Sign out</button></div>`;
        pill.addEventListener("click", (e) => {
          if (e.target.id === "signOut") return;
          $(".user-menu", pill).hidden = !$(".user-menu", pill).hidden;
        });
        $("#signOut", pill).addEventListener("click", async () => {
          try { await post("/api/auth/logout"); } finally { goLogin(); }
        });
      }
      document.body.classList.add("ready");
    }).catch(goLogin);
  }
})();
