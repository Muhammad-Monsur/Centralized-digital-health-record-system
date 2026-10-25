# Manual test checklist

Run before a demo or release, after `python -m scripts.seed --demo` (password for every demo
account: `Demo@12345`). OTP codes appear in the server log in development (`[DEV SMS]`).
Tick each box in a real browser, at desktop width and on a phone (or DevTools 390 px).

## Sign-in portals
- [ ] `/login` signs in `patient`; the same credentials on `/doctor/login` show "username or password isn't right"
- [ ] `/doctor/login` signs in `dr.hasan@cdhrs.example.com`; `/hospital-admin/login` signs in `hadmin@cdhrs.example.com`; `/system-admin/login` signs in `sysadmin@cdhrs.example.com`
- [ ] Five wrong passwords lock the account for 15 minutes (correct password refused meanwhile)
- [ ] Opening `/doctor` while signed out goes to `/doctor/login`, and returns to `/doctor` after sign-in
- [ ] Password eye button shows/hides the password; strength bar fills as you type
- [ ] With the session idle (set `SESSION_IDLE_TIMEOUT_MINUTES=2`), a warning dialog counts down; "Stay signed in" works; letting it reach 0 signs you out to the right login page

## Patient
- [ ] Register at `/register`: tomorrow's date of birth is refused; today's is accepted; a UPI is shown on the dashboard health card
- [ ] Copy button on the UPI shows "Copied!" and the clipboard holds the UPI
- [ ] Upload a PDF and a PNG; a `.exe` renamed to `.pdf` is refused; a file over 10 MB is refused
- [ ] Records list: typing in Search filters in place with skeleton rows; type/visibility filters and pagination keep the URL in sync
- [ ] Record page: switch to Public (confirmation dialog), back to Private; both changes appear in the update-history timeline with time and name; "Last updated" changes
- [ ] Delete a document you uploaded (confirmation dialog); a doctor-written record has no Delete button
- [ ] Print a record (Ctrl+P): no sidebar, buttons or toggles; black on white; patient name and UPI at the top (also from dark mode)
- [ ] Changing mobile number asks for the current password; the old number gets an SMS (server log)

## Consent and emergency (two browsers: patient + doctor)
- [ ] Doctor opens the patient's UPI: only public records; "N private records hidden"; Demographics hidden if the profile is private
- [ ] Doctor sends a request with a reason; patient sees it on "Access requests" with the reason
- [ ] Patient picks a duration, approves, enters the 6-digit code; a wrong code shows attempts left; the code works once
- [ ] Doctor reloads: all records visible with "Consent until …"
- [ ] Patient revokes (confirmation dialog); doctor's next reload shows public records only
- [ ] Doctor uses Emergency access: reason under 20 characters and missing confirmation are refused; then records open with a pulsing "Emergency access until …"
- [ ] Patient gets a notification + SMS; Access history → "Emergency only" shows it in red with the reason
- [ ] Hospital admin sees it under "Emergency access → Active now" and can end it; doctor's next reload is public-only
- [ ] `staff.lab` can open public records and add a lab result, but has no Request/Emergency buttons

## Admins
- [ ] Hospital admin creates a doctor (name, email, designation, licence, password); the doctor signs in at `/doctor/login` and is sent to "Set your own password" before anything else
- [ ] Hospital admin cannot see Riverside's doctors, patients, Roles, System or Backups
- [ ] Deactivate a doctor (confirmation): their open session ends immediately
- [ ] System admin: add a hospital, create its hospital admin, deactivate the hospital (its doctors lose clinical access)
- [ ] Roles: untick a doctor permission and save (confirmation), confirm the doctor loses that page, then "Restore defaults"
- [ ] Audit log filters by area/user/date; Export CSV downloads; a hospital admin's export only has their hospital
- [ ] Backups: create, then restore (must type RESTORE); everyone is signed out; a "pre-restore" safety copy appears

## Shared UI
- [ ] Dark-mode toggle persists across pages and reloads with no white flash; follows the OS setting until toggled
- [ ] Sticky header gains a shadow on scroll; scroll progress bar fills; back-to-top appears after scrolling and returns to top
- [ ] Mobile menu: opens, Tab stays inside it, Escape closes it and returns focus to the menu button, tapping a link closes it
- [ ] Skip link is the first Tab stop and moves focus to the main content
- [ ] Search (header icon on public pages, top bar in portals): arrow keys + Enter open results; a doctor finds a patient only by full UPI
- [ ] FAQ: Enter/Space opens, arrow keys move between questions
- [ ] Newsletter: invalid email shows an error; a valid one shows "Subscribed"; the same email again says already subscribed
- [ ] Floating contact button opens the form; sending shows a success toast
- [ ] Cookie notice appears once; the choice is remembered
- [ ] `/no-such-page` shows the branded 404; a doctor opening `/admin` sees the 403 page
- [ ] With "Reduce motion" enabled in the OS, nothing slides or floats; content is visible without scrolling animations
- [ ] Keyboard only: every button, link, toggle and dialog is reachable and has a visible focus ring
