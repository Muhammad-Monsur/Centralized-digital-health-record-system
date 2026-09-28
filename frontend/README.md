# CDHRS — Frontend (Portal-Separated Build)

Centralized Digital Health Record System — static frontend for the Patient,
Doctor, Hospital Admin and System Admin portals, built to match the approved
Figma UI. **Login now works**: credentials are checked by the FastAPI server
and you are redirected to your own portal's profile page. Profile pages are
still design-only (static sample data, except your name/email/phone).
Users are stored in a local SQLite file for now; MySQL (per the SRS) is next.

---

## 1. Project Structure

```
cdhrs-frontend/
├── app.py                 # FastAPI: static files + login/register/logout API
│                            # + protected profile pages (creates cdhrs.db on first run)
├── requirements.txt
├── index.html              # Public Landing Page (matches Figma) — entry point
├── preview.html            # Internal hub linking every page for QA
├── shared/
│   ├── auth.js             # Shared login/register/profile/sign-out client script
│   └── styles.css          # Single shared design system (colors, buttons,
│                            # cards, badges, auth layout, portal layout)
├── patient/
│   ├── register.html
│   ├── login.html
│   └── profile.html        # design only — static data, not wired up yet
├── doctor/
│   ├── login.html
│   └── profile.html        # design only
├── hospital-admin/
│   ├── login.html
│   └── profile.html        # design only
└── system-admin/
    ├── login.html
    └── profile.html        # design only
```

### Why it's split this way
Each portal folder is **self-contained** — it only depends on `shared/styles.css`
for its design tokens and components (colors, `.btn`, `.card`, `.pill-badge`,
`.sidebar`, `.topbar`, etc.). No portal's HTML/CSS/JS reaches into another
portal's files, and no class names or IDs collide between them.

That means:
- You (or another dev) can build/edit one portal without breaking the others.
- The four portals can be **merged into one app later** (e.g. one React app,
  or one FastAPI project with routers per portal) with no naming conflicts,
  because they all already share the same design-token vocabulary.
- Backend integration can be added portal-by-portal without touching the
  others.

---

## 2. Running it in PyCharm

1. Open the `cdhrs-frontend` folder as a PyCharm project.
2. Create a virtual environment (PyCharm will usually prompt you):
   ```
   python -m venv venv
   ```
3. Activate it and install dependencies:
   ```
   venv\Scripts\activate      (Windows)
   source venv/bin/activate   (macOS/Linux)
   pip install -r requirements.txt
   ```
4. Run the server (Run/Debug config: Script = `uvicorn`, params below, or
   just use the terminal):
   ```
   uvicorn app:app --reload
   ```
5. Open in your browser:
   - `http://127.0.0.1:8000/` — Landing Page (Login/Register go to patient pages; footer has staff links)
   - `http://127.0.0.1:8000/preview.html` — hub of every page
   - `http://127.0.0.1:8000/patient/register.html`
   - `http://127.0.0.1:8000/patient/login.html`
   - `http://127.0.0.1:8000/patient/profile.html`
   - `http://127.0.0.1:8000/doctor/login.html`
   - `http://127.0.0.1:8000/doctor/profile.html`
   - `http://127.0.0.1:8000/hospital-admin/login.html`
   - `http://127.0.0.1:8000/hospital-admin/profile.html`
   - `http://127.0.0.1:8000/system-admin/login.html`
   - `http://127.0.0.1:8000/system-admin/profile.html`

`preview.html` lists every page; the four `profile.html` links there will bounce
you to the login page until you sign in as that portal's user.

---

## 3. Demo Credentials (working)

These accounts are created automatically the first time the server starts.
Each account only works on **its own portal's** login page.

| Portal | Login page | Email | Password |
|---|---|---|---|
| System Admin | `/system-admin/login.html` | `sysadmin@cdhrs.bd` | `SysAdmin@12345` |
| Hospital Admin | `/hospital-admin/login.html` | `admin@cdhrs.bd` | `Admin@12345` |
| Doctor | `/doctor/login.html` | `dr.farhana@cdhrs.bd` | `Doctor@12345` |
| Patient | `/patient/login.html` | `rahim@email.com` | `Patient@12345` |

Behaviour to expect:
- Correct credentials → redirected to that portal's `profile.html`.
- Wrong password, or an account used on the wrong portal → red error message,
  no redirect. (5 failed attempts on one email locks it for 5 minutes.)
- Opening any `profile.html` without being signed in (or while signed in as a
  different role) sends you to that portal's login page.
- Patients can self-register at `/patient/register.html` (auto-signed-in,
  gets the next Patient ID, e.g. `P-000179`). Doctors are **not** self-service.
- Click your name (top-right of any profile) → **Sign out**.
- "Sign in with Google" and "security key / passkey" buttons are placeholders.

Passwords are stored as salted PBKDF2 hashes; sessions are signed, HttpOnly
cookies (8 hours). Before any real deployment set your own secret:
`CDHRS_SECRET=some-long-random-string` (environment variable), and change the
demo passwords. Delete `cdhrs.db` to reset all users back to the demo set.

> The pages must be opened through the server (`http://127.0.0.1:8000/...`).
> Double-clicking the `.html` files no longer works for login, because the
> API lives on the server.

---

## 4. What's built vs. what's next

**Built now:**
- Public Landing Page (`index.html`): nav, hero, features, about, 4 steps, footer
- Working login for all four portals + patient self-registration + sign-out
- Server-side route protection for every profile page
- All 4 profile/dashboard pages (static mock data, matches Figma)

**Not built yet (planned next):**
- FastAPI backend routes (`/api/...`) + MySQL models per the SRS ER diagram
- MySQL instead of SQLite; password reset; OTP verification
- Hospital Admin creating doctor accounts
- Working profile pages (edit info, upload records, consent approval flow)
- Role-based access control enforcement

---

## 5. Design System Reference

All colors, spacing, and component styles live in `shared/styles.css` as
CSS variables — update them there once and every portal updates together:

```css
--primary:      #4A4FBF
--primary-dark: #3B4590
--primary-light:#8B93E8
--bg-page:      #EEF0FC
--success:      #22C55E
--danger:       #EF4444
--warning:      #F59E0B
```
