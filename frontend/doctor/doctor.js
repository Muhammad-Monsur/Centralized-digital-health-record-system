/* CDHRS doctor portal - behaviour for every doctor page.
   Patient records below are sample data until the records API exists. What the doctor
   does (prescriptions, consent, emergency overrides, activity) is kept in localStorage. */
(function () {
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
  const esc = (v) => String(v == null ? "" : v).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  /* ---------------------------------------------------------------- sample data */
  const PATIENTS = {
    "P-000178": {
      name: "Rahim Ahmed", age: 22, gender: "Male", blood: "B+", phone: "+880 1712 345678",
      reports: [
        { id: "cbc-0918", name: "Complete Blood Count", type: "Lab", date: "2026-09-18", provider: "City Diagnostic Centre",
          summary: "Most values are within the reference range. Hemoglobin is slightly below the reference range.",
          note: "Shared by the patient on 19 Sep 2026.",
          tests: [
            { test: "Hemoglobin", result: "11.4", unit: "g/dL", range: "13.0 – 17.0", flag: "low" },
            { test: "WBC", result: "7.2", unit: "× 10⁹/L", range: "4.0 – 11.0", flag: "normal" },
            { test: "Platelets", result: "268", unit: "× 10⁹/L", range: "150 – 400", flag: "normal" },
            { test: "ESR", result: "12", unit: "mm/hr", range: "0 – 15", flag: "normal" },
          ] },
        { id: "cxr-0711", name: "Chest X-ray", type: "Imaging", date: "2026-07-11", provider: "Green Life Hospital",
          summary: "Clear lung fields. No active pulmonary lesion. Heart size within normal limits.",
          findings: ["Lung fields: clear", "Cardiothoracic ratio: normal", "Costophrenic angles: sharp"],
          note: "Shared by the patient on 12 Jul 2026." },
        { id: "fbs-0524", name: "Blood Glucose (Fasting)", type: "Lab", date: "2026-05-24", provider: "City Diagnostic Centre",
          summary: "Fasting glucose is within the normal range.", note: "Shared by the patient on 24 May 2026.",
          tests: [{ test: "Fasting blood glucose", result: "5.1", unit: "mmol/L", range: "3.9 – 5.6", flag: "normal" }] },
        { id: "cons-0402", name: "Consultation Summary", type: "Clinical note", date: "2026-04-02", provider: "CDHRS clinical record",
          summary: "Follow-up for seasonal allergic rhinitis. Symptoms improved with antihistamine.",
          findings: ["BP: 118/76 mmHg", "Pulse: 78 bpm", "Advice: avoid dust exposure"],
          note: "Added by Dr. Nusrat Jahan." },
        { id: "lipid-0315", name: "Lipid Profile", type: "Lab", date: "2026-03-15", provider: "Popular Diagnostic Centre", private: true,
          summary: "LDL cholesterol is above the desirable range.", note: "Marked private by the patient.",
          tests: [
            { test: "Total cholesterol", result: "212", unit: "mg/dL", range: "< 200", flag: "high" },
            { test: "LDL", result: "138", unit: "mg/dL", range: "< 100", flag: "high" },
            { test: "HDL", result: "46", unit: "mg/dL", range: "> 40", flag: "normal" },
            { test: "Triglycerides", result: "140", unit: "mg/dL", range: "< 150", flag: "normal" },
          ] },
        { id: "usg-0120", name: "Abdominal Ultrasound", type: "Imaging", date: "2026-01-20", provider: "Green Life Hospital", private: true,
          summary: "Mild fatty change of the liver. Other abdominal organs are normal.",
          findings: ["Liver: grade I fatty change", "Gall bladder: normal", "Kidneys: normal size and echotexture"],
          note: "Marked private by the patient." },
      ],
      prescriptions: [
        { diagnosis: "Acute viral fever", date: "2026-09-18", doctor: "Dr. Farhana Akter", status: "Active",
          meds: [{ medicine: "Paracetamol 500 mg", form: "Tablet", dose: "1 tablet, 3 times daily", duration: "3 days" },
                 { medicine: "Oral rehydration salts", form: "Other", dose: "As needed", duration: "3 days" }] },
        { diagnosis: "Seasonal allergic rhinitis", date: "2026-08-02", doctor: "Dr. Nusrat Jahan", status: "Completed",
          meds: [{ medicine: "Cetirizine 10 mg", form: "Tablet", dose: "1 tablet at night", duration: "5 days" }] },
      ],
    },
    "P-000205": {
      name: "Sadia Rahman", age: 34, gender: "Female", blood: "O+", phone: "+880 1819 220205",
      reports: [
        { id: "tsh-0902", name: "Thyroid Function Test", type: "Lab", date: "2026-09-02", provider: "Ibn Sina Diagnostic",
          summary: "TSH is mildly raised; free T4 is normal.", note: "Shared by the patient on 03 Sep 2026.",
          tests: [
            { test: "TSH", result: "5.8", unit: "mIU/L", range: "0.4 – 4.5", flag: "high" },
            { test: "Free T4", result: "1.1", unit: "ng/dL", range: "0.8 – 1.8", flag: "normal" },
          ] },
        { id: "ecg-0610", name: "ECG", type: "Imaging", date: "2026-06-10", provider: "Dhaka Medical Center",
          summary: "Normal sinus rhythm.", findings: ["Rate: 72 bpm", "No ST-T changes"], note: "Shared by the patient on 10 Jun 2026." },
      ],
      prescriptions: [],
    },
  };

  /* --------------------------------------------------------------------- store */
  const KEY = "cdhrs.doctor";
  const store = Object.assign({ current: "P-000178", prescriptions: {}, access: {}, overrides: [], activity: [] }, load());
  function load() { try { return JSON.parse(localStorage.getItem(KEY)) || {}; } catch (e) { return {}; } }
  function save() { try { localStorage.setItem(KEY, JSON.stringify(store)); } catch (e) {} }
  if (!PATIENTS[store.current]) store.current = "P-000178";

  let doctorName = "Dr. Farhana Akter";
  fetch("/api/me", { credentials: "same-origin" })
    .then((r) => (r.ok ? r.json() : null)).then((u) => { if (u && u.full_name) doctorName = u.full_name; })
    .catch(() => {});

  const OTP_MINUTES = 60, EMERGENCY_MINUTES = 30;
  const pid = () => store.current;
  const patient = () => PATIENTS[pid()];

  function log(action, detail, patientId = pid()) {
    store.activity.unshift({ time: Date.now(), action, detail, pid: patientId, patient: PATIENTS[patientId] ? PATIENTS[patientId].name : "" });
    store.activity = store.activity.slice(0, 200);
    save();
  }

  function access(id = pid()) {
    const a = store.access[id];
    return a && a.until > Date.now() ? a : null;
  }
  function grantAccess(type, minutes) {
    store.access[pid()] = { type, until: Date.now() + minutes * 60000 };
    save();
  }
  const visibleReports = () => patient().reports.filter((r) => !r.private || access());

  /* ------------------------------------------------------------------- helpers */
  const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const pad = (n) => String(n).padStart(2, "0");
  function fmtDate(iso) { const [y, m, d] = iso.split("-"); return `${d} ${MONTHS[m - 1]} ${y}`; }
  function fmtTime(ts) { const d = new Date(ts); return `${pad(d.getHours())}:${pad(d.getMinutes())}`; }
  function fmtDateTime(ts) { const d = new Date(ts); return `${fmtDate(today(d))}, ${fmtTime(ts)}`; }
  function today(d = new Date()) { return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`; }

  function showMsg(scope, sel, msg) {
    const box = $(sel, scope);
    if (!box) return;
    box.textContent = msg || "";
    box.hidden = !msg;
  }
  const showError = (scope, msg) => { showMsg(scope, ".notice", ""); showMsg(scope, ".form-error", msg); };
  const showNotice = (scope, msg) => { showMsg(scope, ".form-error", ""); showMsg(scope, ".notice", msg); };

  function normalizeId(raw) {
    const v = raw.trim().toUpperCase().replace(/\s+/g, "");
    const digits = v.replace(/^P-?/, "");
    return /^\d+$/.test(digits) ? "P-" + digits.padStart(6, "0") : v;
  }

  /* ------------------------------------------------------- patient + search */
  function renderPatient() {
    const p = patient(), a = access();
    const initials = p.name.split(/\s+/).map((w) => w[0]).slice(0, 2).join("").toUpperCase();
    const fields = {
      name: p.name, initials,
      meta: `Patient ID: ${pid()} · ${p.age} years · ${p.gender} · Blood group ${p.blood}`,
    };
    $$("[data-patient]").forEach((el) => {
      const k = el.dataset.patient;
      if (k in fields) return (el.textContent = fields[k]);
      if (k === "access") {
        el.className = "pill-badge " + (a ? "badge-success" : "badge-danger");
        el.textContent = a ? `🔓 Private access until ${fmtTime(a.until)}` : "🔒 Private records locked";
      }
    });
    $$("[data-patient-search] input").forEach((i) => { i.value = pid(); });
  }

  $$("[data-patient-search]").forEach((form) => {
    form.addEventListener("submit", (e) => {
      e.preventDefault();
      const id = normalizeId($("input", form).value);
      if (!id) return showError(form, "Please enter a patient ID.");
      if (!PATIENTS[id]) return showError(form, `No patient found with ID ${id}.`);
      showError(form, "");
      store.current = id;
      log("Patient search", `Opened record of ${PATIENTS[id].name}`);
      refresh();
    });
  });

  /* ------------------------------------------------------------ prescriptions */
  const allPrescriptions = () => (store.prescriptions[pid()] || []).concat(patient().prescriptions);
  const medText = (m) => `${m.medicine}${m.form && m.form !== "Other" ? " (" + m.form + ")" : ""} · ${m.dose} · ${m.duration}`;

  function renderPrescriptions() {
    const list = $("[data-rx-list]");
    if (!list) return;
    const all = allPrescriptions();
    const expanded = list.dataset.expanded === "true";
    const shown = expanded ? all : all.slice(0, 3);
    $$("[data-rx-count]").forEach((el) => (el.textContent = `${all.length} record${all.length === 1 ? "" : "s"}`));
    list.innerHTML = shown.length ? shown.map((rx) => `
      <article class="history-row">
        <div class="history-top">
          <div><strong>${esc(rx.diagnosis)}</strong><div class="history-meta">Issued ${fmtDate(rx.date)} · ${esc(rx.doctor)}</div></div>
          <span class="pill-badge ${rx.status === "Active" ? "badge-success" : "badge-neutral"}">${esc(rx.status)}</span>
        </div>
        <ul class="med-list">${rx.meds.map((m) => `<li>${esc(medText(m))}</li>`).join("")}</ul>
        ${rx.instructions ? `<div class="history-meta">Advice: ${esc(rx.instructions)}</div>` : ""}
      </article>`).join("") : `<div class="empty">No prescriptions for this patient yet.</div>`;
    const toggle = $("[data-rx-toggle]");
    if (toggle) {
      toggle.hidden = all.length <= 3;
      toggle.textContent = expanded ? "Show recent only" : `View full history (${all.length})`;
    }
  }

  const rxToggle = $("[data-rx-toggle]");
  if (rxToggle) rxToggle.addEventListener("click", () => {
    const list = $("[data-rx-list]");
    list.dataset.expanded = list.dataset.expanded === "true" ? "false" : "true";
    renderPrescriptions();
  });

  $$("form[data-rx-form]").forEach((form) => {
    const rows = $("[data-med-rows]", form);
    const template = rows.firstElementChild.cloneNode(true);

    $("[data-add-med]", form).addEventListener("click", () => {
      const row = template.cloneNode(true);
      $$("input, textarea", row).forEach((i) => (i.value = ""));
      $$("select", row).forEach((s) => (s.selectedIndex = 0));
      rows.appendChild(row);
      $("input", row).focus();
    });
    rows.addEventListener("click", (e) => {
      if (e.target.closest(".remove-med")) e.target.closest(".med-row").remove();
    });

    form.addEventListener("submit", (e) => {
      e.preventDefault();
      const val = (el, name) => { const f = $(`[name="${name}"]`, el); return f ? f.value.trim() : ""; };
      const diagnosis = val(form, "diagnosis");
      if (!diagnosis) return showError(form, "Please enter a diagnosis.");

      const meds = [];
      for (const row of $$(".med-row", rows)) {
        const m = { medicine: val(row, "medicine"), form: val(row, "form"), dose: val(row, "dose"), duration: val(row, "duration") };
        if (!m.medicine && !m.dose && !m.duration) continue;
        if (!m.medicine || !m.dose || !m.duration) return showError(form, "Each medicine needs a name, dose and duration.");
        meds.push(m);
      }
      if (!meds.length) return showError(form, "Please add at least one medicine.");

      const rx = { diagnosis, meds, instructions: val(form, "instructions"), date: today(), doctor: doctorName, status: "Active" };
      (store.prescriptions[pid()] = store.prescriptions[pid()] || []).unshift(rx);
      log("Prescription issued", `${diagnosis} · ${meds.length} medicine${meds.length === 1 ? "" : "s"}`);

      form.reset();
      $$(".med-row", rows).slice(1).forEach((r) => r.remove());
      showNotice(form, `Prescription saved to ${patient().name}'s record.`);
      renderPrescriptions();
    });
  });

  /* ------------------------------------------------------- private access: OTP */
  const otpCard = $("[data-otp]");
  if (otpCard) {
    let code = null;
    const box = $("[data-otp-box]", otpCard);
    $("[data-otp-request]", otpCard).addEventListener("click", () => {
      if (access()) return showNotice(otpCard, "You already have access to this patient's private records.");
      code = String(Math.floor(100000 + Math.random() * 900000));
      box.hidden = false;
      $("input", box).value = "";
      $("input", box).focus();
      showNotice(otpCard, `OTP sent to the patient's phone ending ${patient().phone.slice(-4)}. (Demo code: ${code})`);
      log("OTP requested", "Consent requested for private records");
    });
    $("[data-otp-verify]", otpCard).addEventListener("click", () => {
      const entered = $("input", box).value.trim();
      if (!code) return showError(otpCard, "Please request an OTP first.");
      if (entered !== code) return showError(otpCard, "Incorrect OTP. Please check the code and try again.");
      code = null;
      box.hidden = true;
      grantAccess("otp", OTP_MINUTES);
      log("Consent granted", `Private records unlocked for ${OTP_MINUTES} minutes (OTP)`);
      showNotice(otpCard, `Access granted for ${OTP_MINUTES} minutes.`);
      refresh();
    });
  }

  /* ------------------------------------------------------- emergency override */
  $$("form[data-emergency-form]").forEach((form) => {
    form.addEventListener("submit", (e) => {
      e.preventDefault();
      const justification = form.elements.justification.value.trim();
      const reason = form.elements.reason ? form.elements.reason.value : "Emergency";
      if (form.elements.reason && !reason) return showError(form, "Please select the emergency type.");
      if (justification.length < 20) return showError(form, "Please write a justification of at least 20 characters.");
      if (form.elements.confirm && !form.elements.confirm.checked) return showError(form, "Please confirm that this is a genuine emergency.");

      grantAccess("emergency", EMERGENCY_MINUTES);
      store.overrides.unshift({ time: Date.now(), pid: pid(), patient: patient().name, reason, justification, doctor: doctorName });
      log("Emergency override", `${reason}: ${justification}`);
      form.reset();
      showNotice(form, `Emergency access granted for ${EMERGENCY_MINUTES} minutes. This override has been logged.`);
      refresh();
    });
  });

  function renderOverrides() {
    const tbody = $("[data-override-rows]");
    if (!tbody) return;
    // only the latest override per patient can still be running
    const isActive = (o) => { const a = access(o.pid); return a && a.type === "emergency" && o === store.overrides.find((x) => x.pid === o.pid); };
    tbody.innerHTML = store.overrides.length ? store.overrides.map((o) => `
      <tr><td>${fmtDateTime(o.time)}</td><td><div class="item-name">${esc(o.patient)}</div><div class="item-sub">${esc(o.pid)}</div></td>
      <td>${esc(o.reason)}</td><td>${esc(o.justification)}</td>
      <td>${isActive(o) ? `<span class="pill-badge badge-warning">Active</span>` : `<span class="pill-badge badge-neutral">Expired</span>`}</td></tr>`).join("")
      : `<tr><td colspan="5" class="empty">No emergency overrides yet.</td></tr>`;
  }

  /* ------------------------------------------------------------ report lists */
  function reportDetail(r) {
    const tests = r.tests ? `<div class="detail-label">Results</div>
      <table><thead><tr><th>Test</th><th>Result</th><th>Reference</th></tr></thead><tbody>
      ${r.tests.map((t) => `<tr><td>${esc(t.test)}</td><td>${esc(t.result)} ${esc(t.unit)} ${flagBadge(t.flag)}</td><td>${esc(t.range)}</td></tr>`).join("")}
      </tbody></table>` : "";
    const findings = r.findings ? `<div class="detail-label">Key findings</div>
      <ul class="finding-list">${r.findings.map((f) => `<li>${esc(f)}</li>`).join("")}</ul>` : "";
    return `
      <div class="card-head"><div class="title">🧾 Report details</div>
        <span class="pill-badge ${r.private ? "badge-warning" : "badge-success"}">${r.private ? "Private" : "Shared"}</span></div>
      <div class="item-name">${esc(r.name)}</div>
      <div class="item-sub">${esc(r.type)} report · ${fmtDate(r.date)}</div>
      <div class="detail-label">Provider</div><div class="detail-value">${esc(r.provider)}</div>
      <div class="detail-label">Summary</div><div class="detail-value">${esc(r.summary)}</div>
      ${tests}${findings}
      <div class="detail-label">Note</div><div class="detail-value">${esc(r.note)}</div>
      <button class="btn btn-primary btn-block" type="button" data-print style="margin-top:18px;">Print report</button>`;
  }
  const flagBadge = (flag) => flag === "normal" ? "" :
    `<span class="pill-badge ${flag === "high" ? "badge-danger" : "badge-warning"}">${flag === "high" ? "High" : "Low"}</span>`;

  /* One table + detail panel. `filter(report)` limits which reports the page lists. */
  function reportBrowser(filter, rowHtml, emptyText) {
    const tbody = $("[data-report-rows]"), detail = $("[data-report-detail]");
    const search = $("[data-report-search]"), type = $("[data-report-type]");
    let selected = null;

    function render() {
      const all = patient().reports.filter(filter);
      const q = search.value.trim().toLowerCase(), t = type ? type.value : "";
      const rows = all.filter((r) => (!t || r.type === t) && (r.name + " " + r.provider).toLowerCase().includes(q));
      const open = (r) => !r.private || access();
      if (!all.some((r) => r.id === selected && open(r))) selected = (all.find(open) || {}).id;

      $$("[data-report-count]").forEach((el) => (el.textContent = `${rows.length} of ${all.length}`));
      tbody.innerHTML = rows.length ? rows.map((r) => rowHtml(r, open(r), r.id === selected)).join("")
        : `<tr><td colspan="6" class="empty">${emptyText}</td></tr>`;
      const cur = all.find((r) => r.id === selected);
      detail.innerHTML = cur ? reportDetail(cur) : `<div class="empty">Select a report to see its details.</div>`;
    }
    tbody.addEventListener("click", (e) => {
      const btn = e.target.closest("[data-view]");
      if (!btn) return;
      selected = btn.dataset.view;
      const r = patient().reports.find((x) => x.id === selected);
      log("Viewed report", r.name);
      render();
      if (window.innerWidth < 900) detail.scrollIntoView({ behavior: "smooth" });
    });
    detail.addEventListener("click", (e) => { if (e.target.closest("[data-print]")) window.print(); });
    search.addEventListener("input", render);
    if (type) type.addEventListener("change", render);
    return render;
  }

  const viewCell = (r, open) => open
    ? `<button class="btn btn-outline btn-sm" type="button" data-view="${r.id}" aria-label="View ${esc(r.name)}">View</button>`
    : `<a class="btn btn-outline btn-sm" href="profile.html" title="Needs patient consent or emergency access">🔒 Locked</a>`;
  const accessBadge = (r) => r.private
    ? `<span class="pill-badge badge-warning">Private</span>` : `<span class="pill-badge badge-success">Shared</span>`;

  function renderStats() {
    const reports = visibleReports();
    const latest = (t) => { const r = reports.find((x) => x.type === t); return r ? "Latest: " + fmtDate(r.date) : "None shared"; };
    const set = (k, v) => $$(`[data-stat="${k}"]`).forEach((el) => (el.textContent = v));
    const count = (t) => pad(reports.filter((r) => r.type === t).length);
    set("total", pad(reports.length));
    set("locked", patient().reports.length - reports.length ? `${patient().reports.length - reports.length} private locked` : "All records visible");
    set("lab", count("Lab")); set("lab-latest", latest("Lab"));
    set("imaging", count("Imaging")); set("imaging-latest", latest("Imaging"));
    const flagged = reports.filter((r) => r.tests).reduce((n, r) => n + r.tests.filter((t) => t.flag !== "normal").length, 0);
    set("flagged", pad(flagged));
  }

  /* -------------------------------------------------------------- activity log */
  function renderActivity() {
    const tbody = $("[data-activity-rows]");
    if (!tbody) return;
    const q = ($("[data-activity-search]") || {}).value || "";
    const type = ($("[data-activity-type]") || {}).value || "";
    const rows = store.activity.filter((a) => (!type || a.action === type)
      && (a.action + " " + a.detail + " " + a.patient + " " + a.pid).toLowerCase().includes(q.trim().toLowerCase()));
    const tone = { "Emergency override": "badge-danger", "Consent granted": "badge-success", "Prescription issued": "badge-success" };
    tbody.innerHTML = rows.length ? rows.map((a) => `
      <tr><td>${fmtDateTime(a.time)}</td><td><span class="pill-badge ${tone[a.action] || "badge-neutral"}">${esc(a.action)}</span></td>
      <td><div class="item-name">${esc(a.patient)}</div><div class="item-sub">${esc(a.pid)}</div></td><td>${esc(a.detail)}</td></tr>`).join("")
      : `<tr><td colspan="4" class="empty">${store.activity.length ? "No activity matches your filter." : "No activity recorded yet."}</td></tr>`;
    $$("[data-activity-count]").forEach((el) => (el.textContent = `${rows.length} entr${rows.length === 1 ? "y" : "ies"}`));
  }
  ["[data-activity-search]", "[data-activity-type]"].forEach((s) => {
    const el = $(s);
    if (el) el.addEventListener(el.tagName === "SELECT" ? "change" : "input", renderActivity);
  });

  /* ------------------------------------------------------------------ pages */
  let renderReports = null;
  const page = document.body.dataset.page;
  if (page === "medical-reports") {
    renderReports = reportBrowser(() => true, (r, open, sel) => `
      <tr class="${sel ? "selected" : ""}"><td><div class="item-name">${esc(r.name)}</div><div class="item-sub">${esc(r.provider)}</div></td>
      <td>${fmtDate(r.date)}</td><td>${esc(r.type)}</td><td>${accessBadge(r)}</td><td>${viewCell(r, open)}</td></tr>`,
      "No reports match your search.");
  } else if (page === "lab-reports") {
    renderReports = reportBrowser((r) => r.type === "Lab", (r, open, sel) => {
      const flags = open ? r.tests.filter((t) => t.flag !== "normal").length : 0;
      return `<tr class="${sel ? "selected" : ""}"><td><div class="item-name">${esc(r.name)}</div><div class="item-sub">${esc(r.provider)}</div></td>
      <td>${fmtDate(r.date)}</td><td>${open ? r.tests.length : "—"}</td>
      <td>${!open ? accessBadge(r) : flags ? `<span class="pill-badge badge-warning">${flags} abnormal</span>` : `<span class="pill-badge badge-success">All normal</span>`}</td>
      <td>${viewCell(r, open)}</td></tr>`;
    }, "No lab reports match your search.");
  }

  function refresh() {
    renderPatient();
    renderPrescriptions();
    renderStats();
    renderOverrides();
    renderActivity();
    if (renderReports) renderReports();
  }
  refresh();
})();
