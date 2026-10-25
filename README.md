# CDHRS: Centralized Digital Health Record System

One place where **patients own their health records**, **doctors read them with the patient's
consent**, and **administrators** manage hospitals, accounts, auditing and backups.

Software Engineering Lab (CSE-314), University of Asia Pacific, Section D(1)
Supervisor: Md. Ashraful Alam (Lecturer, CSE)
Team: Abdullah Al Mahmud (Project Manager) · Md. Monsur (Team Lead) · Tahia Islam Raisa (QA Lead) · Nazmoon Nahar (Report Writing Lead)

> Demo data only. All names, IDs, phone numbers and records in the seed are fictional.

---

## Contents
1. [What it does](#1-what-it-does)
2. [Quick start](#2-quick-start)
3. [Demo accounts and sign-in pages](#3-demo-accounts-and-sign-in-pages)
4. [Configuration (environment variables)](#4-configuration)
5. [Running tests and checks](#5-tests-and-checks)
6. [Project structure](#6-project-structure)
7. [How access control works](#7-how-access-control-works)
8. [Security measures](#8-security-measures)
9. [Database schema and additions](#9-database-schema)
10. [Performance](#10-performance)
11. [Deployment (Docker, load balancer, HTTPS, CDN)](#11-deployment)
12. [Plugging in a real SMS provider](#12-plugging-in-a-real-sms-provider)
13. [Backups](#13-backups)
14. [API](#14-api)
15. [Extending the system](#15-extending-the-system)

---

## 1. What it does

| Portal | Sign-in page | Highlights |
|---|---|---|
| **Patient** | `/login` (self-registration at `/register`) | Unique Patient ID (UPI), upload documents, set each record public or private, approve/decline doctors' requests with an SMS code, revoke consent, full access history with emergencies flagged |
| **Doctor / healthcare staff** | `/doctor/login` (accounts are created by a hospital admin; no self-registration) | Find a patient by exact UPI, read public records, request consent for private ones, emergency access (logged, time-limited, patient notified), add and edit records |
| **Hospital admin** | `/hospital-admin/login` | Own hospital only: create doctor and staff accounts, verify licences, deactivate/reset accounts, hospital details, consent/emergency/audit oversight for that hospital |
| **System admin** | `/system-admin/login` | Everything: hospitals and their admins, roles and permissions, audit log (all), system settings and health, backup and restore |

Every record shows **who uploaded it** ("Uploaded by Ayesha Siddiqua (patient)" or
"Uploaded by Dr. Tanvir Hasan (doctor, Lakeview General Hospital)") and keeps an
**update-history timeline** (who changed what, when) with a "Last updated" stamp.

Shared UI: dark mode (no flash, remembers choice), sticky header, mobile menu, scroll progress,
back-to-top, skeleton loading, role-aware site search, skip link, floating contact form, FAQ
accordion, newsletter, cookie notice, confirmation dialogs for sensitive actions, branded
403/404/500 pages, print stylesheet, copy buttons, full keyboard and screen-reader support.

## 2. Quick start

**Requirements:** Python 3.11+ (tested on 3.11 and 3.13), MySQL 8.0, Redis 6+ (optional in
development), Node.js 18+ (only to build production assets).

```bash
git clone <your repo> cdhrs && cd cdhrs
python -m venv .venv
source .venv/bin/activate              # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt

cp .env.example .env                    # Windows: copy .env.example .env
# Edit .env: set SECRET_KEY (python -c "import secrets;print(secrets.token_urlsafe(48))")
#            and DATABASE_URL for your MySQL user/password.

docker compose up -d mysql redis        # or use your own MySQL 8 / XAMPP + Redis
alembic upgrade head                    # create the schema
python -m scripts.seed --demo           # roles, permissions + fictional demo data
uvicorn app.main:app --reload           # http://localhost:8000
```

Without Docker, create the database yourself:

```sql
CREATE DATABASE cdhrs CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'cdhrs'@'localhost' IDENTIFIED BY 'choose-a-password';
GRANT ALL ON cdhrs.* TO 'cdhrs'@'localhost';
```

Leave `REDIS_URL` empty to use the in-memory fallback (fine for one process in development).
In development the SMS codes are printed in the server log, e.g.
`[DEV SMS] to=+8801700000031 :: CDHRS: your code to approve record access is 482913 ...`

**Production assets** (minified, fingerprinted, CSS inlined on public pages):

```bash
npm install && npm run build            # writes app/static/dist + manifest.json
# then set USE_BUILT_ASSETS=true in .env
```

## 3. Demo accounts and sign-in pages

Password for every demo account: **`Demo@12345`**

| Role | Sign in at | Username / email |
|---|---|---|
| Patient (public profile) | `/login` | `patient` |
| Patient (private profile) | `/login` | `patient2`, `patient3` |
| Doctor, Lakeview General Hospital | `/doctor/login` | `dr.hasan@cdhrs.example.com` |
| Doctor, Riverside Medical Centre | `/doctor/login` | `dr.akter@cdhrs.example.com` |
| Doctor with licence pending | `/doctor/login` | `dr.pending@cdhrs.example.com` |
| Healthcare staff (lab), Lakeview | `/doctor/login` | `staff.lab@cdhrs.example.com` |
| Hospital admin, Lakeview | `/hospital-admin/login` | `hadmin@cdhrs.example.com` |
| Hospital admin, Riverside | `/hospital-admin/login` | `hadmin2@cdhrs.example.com` |
| System admin | `/system-admin/login` | `sysadmin@cdhrs.example.com` |

Each account can only sign in through its own portal; anything else gets the same
"username or password isn't right" message. The seed prints the patients' UPIs.
Accounts created by an admin (and admin password resets) must choose a new password at first sign-in.

## 4. Configuration

All settings come from environment variables or `.env` (see `.env.example`; never commit `.env`).

| Variable | Default | Purpose |
|---|---|---|
| `APP_ENV` | `development` | `development`, `test` or `production` |
| `SECRET_KEY` | required | Keys OTP hashing etc. At least 32 random characters |
| `DATABASE_URL` | local MySQL | `mysql+pymysql://user:pass@host:3306/cdhrs?charset=utf8mb4` |
| `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` / `DB_POOL_RECYCLE` | 10 / 20 / 1800 | Connection pool |
| `REDIS_URL` | empty | Sessions, rate limits, cache. Required for several instances and in production |
| `BASE_URL` | `http://localhost:8000` | Public origin (used for the CSRF Origin check) |
| `DISPLAY_TIMEZONE` | `Asia/Dhaka` | Times are stored in UTC and shown in this zone |
| `COOKIE_SECURE` | `true` | `false` only for plain-HTTP local development |
| `SESSION_IDLE_TIMEOUT_MINUTES` / `SESSION_ABSOLUTE_TIMEOUT_HOURS` | 15 / 8 | Session lifetime |
| `LOGIN_MAX_ATTEMPTS` / `LOGIN_LOCKOUT_MINUTES` | 5 / 15 | Account lockout |
| `OTP_TTL_SECONDS` / `OTP_MAX_ATTEMPTS` | 300 / 5 | Consent codes |
| `CONSENT_DEFAULT_HOURS` / `EMERGENCY_ACCESS_MINUTES` | 24 / 60 | Access durations |
| `SMS_PROVIDER` | `console` | `console` (dev, prints codes) or `http` (real gateway) |
| `SMS_HTTP_URL` / `SMS_HTTP_API_KEY` / `SMS_HTTP_SENDER_ID` | | Gateway settings for `http` |
| `UPLOAD_DIR` / `BACKUP_DIR` / `MAX_UPLOAD_MB` | `storage/...` / 10 | Files |
| `STATIC_URL_PREFIX` | `/static` | Set to your CDN origin, e.g. `https://cdn.example.com/static` |
| `USE_BUILT_ASSETS` | `false` | Serve the `npm run build` output |
| `ENABLE_API_DOCS` | empty | `/api/docs`. Empty = on in development, off in production |

**Production guard:** with `APP_ENV=production` the app refuses to start if the secret, database
or Redis password is a default, `COOKIE_SECURE` is false, `SMS_PROVIDER=console`, or `DEBUG` is on.

## 5. Tests and checks

```bash
pytest                                  # 261 tests against a real MySQL database (cdhrs_test)
pytest --cov=app                        # 92% coverage
python -m scripts.explain_indexes       # EXPLAIN of every hot query: all use an index
./scripts/lighthouse.sh after           # Lighthouse on landing, login, dashboard
```

Tests need a `cdhrs_test` database the same user can access (override with
`TEST_DATABASE_URL`). They build the schema through the Alembic migrations, so they also prove
the migrations match the models. The suite includes:

* **auth**: CSRF, cross-origin rejection, lockout (identical for unknown users), session rotation, password policy, role-specific portals
* **RBAC and leaks**: every registered route is enumerated automatically and must require sign-in; every mutation must carry a CSRF token; no role can reach another portal; patients can't touch each other's data; hospital admins are confined to their hospital
* **consent / OTP / emergency**: full flows, consent and emergency access ending with the doctor's session (sign-out, timeout, other device), wrong codes, attempt limit, expiry, single use, resend cooldown, immediate revocation, expiry of consent, emergency logging and notification, staff and unverified doctors refused
* **injection**: stored XSS, SQL-injection payloads, CSV injection, path traversal in backups/uploads
* **performance**: the number of SQL queries per page must not grow with data (N+1 guard)

`docs/MANUAL_TEST_CHECKLIST.md` lists what to click through by hand before a demo.

## 6. Project structure

```
cdhrs/
  app/
    main.py              app factory, middleware order, routers
    config.py            settings (pydantic-settings) + production guard
    database.py          engine, pool, session, UTC
    models/              SQLAlchemy models (Model)
    schemas/             Pydantic request validation
    controllers/         FastAPI routers: pages + JSON API (Controller)
                         auth, patient, doctor, admin, common, portal, errors
    services/            business logic: patient, provider, consent, records, admin, backup, search
      common/            audit, notification, otp, sms/, file, session, cache, kvstore, permissions, security
    middleware/          session (+timeout), csrf, auth/RBAC dependencies, rate limit,
                         security headers (CSP), cache control, compression (brotli/gzip)
    views/templates/     Jinja2 views (View): layouts, partials, landing, auth, patient, doctor, admin, errors
    static/              css/, js/ (ES modules: core/ + per-page pages/), fonts/, img/
  migrations/            Alembic (4 revisions)
  tests/                 pytest suites
  scripts/               seed, backup, explain_indexes, export_openapi, build_assets.mjs, lighthouse.sh
  docs/                  API.md, openapi.json, PERFORMANCE.md, MANUAL_TEST_CHECKLIST.md
  Dockerfile  docker-compose.yml  nginx.conf  requirements*.txt  package.json  .env.example
```

Controllers stay thin: they validate input (schemas), call a service, and render a template or
return JSON. All authorisation and data rules live in the services and middleware.

## 7. How access control works

* **RBAC on the server, on every request.** Routes declare permissions
  (`Depends(require_permissions(P.RECORDS_CREATE))`), read from the ROLE / PERMISSION / USER_ROLE /
  ROLE_PERMISSION tables, editable in the admin's RBAC editor. Changes apply on the next request.
* **Scope on top of RBAC.** Patients' queries always filter by their own `patient_id`. Hospital
  admins' queries always filter by their hospital. Unverified, rejected or pending doctors and
  doctors of an inactive hospital lose all clinical permissions automatically.
* **Who sees a record.** Public: any verified clinician who has the patient's UPI. Private: only a
  doctor with an **active, unexpired consent** or **active emergency access**. This includes the doctor
  who wrote it: only the patient decides visibility, and records added by clinicians are always
  private. Consent and emergency access are re-checked in the database on every request, so
  revocation and expiry take effect immediately.
* **Consent flow:** doctor requests with a reason → patient approves and picks a duration (1 h to 7 days) →
  6-digit SMS code (hashed, 5-minute expiry, 5 attempts, single use) → access until the duration runs out,
  the patient revokes it, **or the doctor's sign-in session ends**, whichever comes first.
* **Consent is per session.** Consent works only in the sign-in session the request came from. Signing out,
  an idle or absolute timeout, a password change or signing in on another device all mean a new consent
  is needed. On sign-out it ends at once and the patient is notified; a session that just timed out is
  detected the next time either side opens the consent pages (reads never depend on that, because each
  read matches the live session). A waiting request closes too, so a patient can't approve a request
  from a doctor who has already left.
* **Emergency access:** verified doctors only, written reason (20+ characters) and explicit confirmation,
  60 minutes or until the doctor signs out, logged in the audit and access logs, patient notified in-app
  and by SMS, hospital admins alerted, can be ended early by the doctor or an admin.
* **Doctor accounts:** created and verified by their hospital admin (no self-registration and no separate
  system-admin approval step); a hospital admin can also mark a doctor's licence pending or rejected.
* **Every access is logged** (ACCESS_LOG) and shown to the patient; security-relevant actions go to AUDIT_LOG.

## 8. Security measures

| Area | Implementation |
|---|---|
| Passwords | Argon2id; 10+ chars with upper, lower, number and symbol; no username/email inside |
| Sessions | Random id in an `HttpOnly`, `Secure`, `SameSite=Lax` cookie (`__Host-` prefix over HTTPS); only a hash of the id is stored in Redis; rotated at sign-in and password change; 15-min idle and 8-h absolute timeout with a warning dialog; all sessions ended on deactivation, password change or reset |
| Admin-set passwords | Must be changed at first sign-in before anything else works |
| Brute force | Per-account lockout (5 tries, 15 min), per-IP limits on sign-in, registration, OTP, search, uploads; nginx limits as a second layer |
| CSRF | Token header on every mutation (masked differently on each response, against BREACH) plus Origin/Referer check |
| Input | Pydantic validation everywhere; SQLAlchemy parameterised queries only; uploads checked by file signature, size-limited while streaming, stored under random names outside `static/` |
| Output | Jinja2 autoescaping; JS builds DOM with `textContent`; strict CSP with per-request nonces; downloaded files sent with `nosniff` and a sandbox CSP |
| Headers | CSP, `X-Frame-Options: DENY`, `frame-ancestors 'none'`, HSTS (when HTTPS), `Referrer-Policy`, `Permissions-Policy`, COOP/CORP |
| Caching of health data | Everything dynamic is `Cache-Control: no-store` by default; only static files and public, identical-for-everyone data (FAQ, landing counts) are cacheable. The server cache never holds patient data |
| Contact details | Changing phone/email needs the current password; the old number is alerted |
| Audit | Sign-ins, failures, lockouts, record views/downloads/changes, consent changes, emergency access, admin actions, exports, backups. The audit log survives backup restores |
| Deployment | MySQL/Redis bound to localhost and password-protected; nginx overwrites `X-Forwarded-For`; non-root container; production guard (section 4) |

An independent code review found no cross-patient leaks or consent bypasses; its findings on
deployment and hardening were fixed and are covered by tests (`tests/test_security.py`).

## 9. Database schema

All tables from the specification are implemented with NOT NULL, UNIQUE, ENUM and FK
constraints. Additions, and why:

| Addition | Why |
|---|---|
| `medical_information_history` (table) | Per-record update history: one append-only row per change with a JSON `{field: {old, new}}` diff, who and when |
| `medical_information.created_by_user_id`, `updated_by_user_id`, `created_at`, `updated_at`, `file_original_name`, `file_mime`, `file_size` | "Uploaded by", "Last updated by", safe file handling |
| `medical_information.doctor_id` nullable | Patients upload their own documents |
| `user.full_name` | No name column existed |
| `user.failed_login_count`, `locked_until`, `last_login_at` | Lockout and account info |
| `user.must_change_password` | Forced change after an admin sets a password |
| `user.phone` nullable | Optional for staff accounts; still required for patients (OTP) |
| `doctor.designation`, `verification_note` | Set by the hospital admin; reason for a rejection |
| `healthcare_staff` (table) | Links staff to a hospital to scope their permissions |
| `access_request.session_ref`, `consent.session_ref`, `emergency_access.session_ref`, consent status `ended` | Bind consent and emergency access to the doctor's sign-in session (a SHA-256 reference, never the session id itself) |
| `access_request.responded_at`, `consent.duration_hours`, `otp_verification.attempts`, `invalidated_at`, `emergency_access.expires_at`, `ended_at` | Consent, OTP and emergency lifecycle |
| `access_log.information_id`, `consent_id`, `emergency_access_id`, `ip_address` | Show the patient what was accessed and on what basis |
| `audit_log.ip_address`, `details`, `hospital_id`, `user_id` nullable | Context, hospital-scoped audit, failed logins for unknown users |
| `notification`, `newsletter_subscriber`, `contact_message`, `system_setting` (tables) | Notifications, newsletter, contact form, admin-editable settings |

Indexes cover UPI, email/username, every foreign key, status columns and timestamps, plus composite
indexes for the hot paths (see `docs/PERFORMANCE.md` for the EXPLAIN output).

## 10. Performance

Final Lighthouse (mobile, simulated throttling):

| Page | Perf | A11y | Best practices | SEO | LCP |
|---|---|---|---|---|---|
| Landing | 99 | 100 | 100 | 100 | 1.8 s |
| Login | 99 | 100 | 100 | 100 | 1.8 s |
| Patient dashboard | 99 | 100 | 100 | 100 | 1.7 s |

axe-core: 0 violations across 35 pages in light and dark themes. Checked in Chromium, Firefox and WebKit.
Details, before/after numbers and query counts: [`docs/PERFORMANCE.md`](docs/PERFORMANCE.md).

## 11. Deployment

### Docker (load balanced)

```bash
cp .env.example .env    # set SECRET_KEY, MYSQL_PASSWORD, REDIS_PASSWORD, etc.
docker compose --profile full up -d --build
docker compose --profile full run --rm app1 alembic upgrade head
docker compose --profile full run --rm app1 python -m scripts.seed          # add --demo only for a demo
# http://localhost:8080
```

This runs MySQL, Redis, **three app instances** and **nginx** as the load balancer. Sessions,
rate limits and the cache live in Redis, so any instance can serve any request (no sticky
sessions); uploads and backups are on a shared volume. Tested: requests spread evenly and
nobody is signed out when an instance stops.

### HTTPS and production (needs your hosting provider)

1. Point your domain's DNS at the server.
2. Get a certificate (e.g. `certbot --nginx -d cdhrs.example.com`), then uncomment the
   `listen 443 ssl`, certificate and HTTP→HTTPS redirect lines in `nginx.conf`.
3. In `.env`: `APP_ENV=production`, `COOKIE_SECURE=true`, `BASE_URL=https://cdhrs.example.com`,
   strong `SECRET_KEY`/`MYSQL_PASSWORD`/`REDIS_PASSWORD`, `SMS_PROVIDER=http` (section 12).
4. Restrict the server firewall to ports 80/443 (MySQL and Redis are bound to localhost already).
5. Schedule backups (section 13) and copy them off-site, encrypted.

On a VPS without Docker: run `uvicorn app.main:app --workers 4 --proxy-headers
--forwarded-allow-ips=127.0.0.1` on ports 8001–8003 (systemd), and use `nginx.conf` with the
upstream servers changed to `127.0.0.1:8001` etc.

### CDN for static assets

1. `npm run build` produces content-hashed files (`main.LQWNRYJL.js`), so they can be cached forever.
2. Create a CDN distribution (Cloudflare, CloudFront, Bunny…) with your site as the origin, caching
   only `/static/*` and respecting origin headers (`public, max-age=31536000, immutable`).
3. Set `STATIC_URL_PREFIX=https://cdn.example.com/static` and `USE_BUILT_ASSETS=true`. The CSP is
   widened automatically to allow that origin.
4. Never route `/patient`, `/doctor`, `/admin` or `/api` through CDN caching. They are `no-store`
   anyway, but keep the CDN rule limited to `/static/*`.

I could not test a CDN here (it needs a real domain); the hashed URLs and headers it relies on are tested.

## 12. Plugging in a real SMS provider

Interface: `app/services/common/sms/base.py` (`SMSProvider.send(to, message) -> SMSResult`; must not raise).

* **Generic HTTP gateways** (most Bangladeshi providers, Twilio-style APIs): set `SMS_PROVIDER=http`,
  `SMS_HTTP_URL=https://…`, `SMS_HTTP_API_KEY=…`, `SMS_HTTP_SENDER_ID=…`. If your provider needs a
  different body or auth header, edit `_payload()` and the headers in `sms/http_provider.py`.
* **Custom SDK**: add `sms/myprovider.py` with a class implementing `SMSProvider`, and return it from
  `get_sms_provider()` in `sms/__init__.py` for a new `SMS_PROVIDER` value.

Messages never contain medical details. The console provider is refused in production.

## 13. Backups

* **In the app** (system admin → Backups): create, list, restore (type `RESTORE`; a safety backup is
  taken first; everyone is signed out afterwards; the audit log is kept).
* **CLI / schedule**: `python -m scripts.backup create --label nightly`, `… list`, `… restore <file> --yes`.
  Linux cron: `30 2 * * * cd /srv/cdhrs && .venv/bin/python -m scripts.backup create --label nightly`.
  Windows: Task Scheduler running the same command.
* A backup is one `.tar.gz` with every table (JSON), uploaded documents and a manifest with a
  SHA-256 checksum and schema revision; restore refuses tampered files or a different schema.
* Backups contain health data: files are owner-only and never downloadable from the browser. Copy
  them to encrypted off-site storage. For very large databases, add `mysqldump --single-transaction`.

## 14. API

Interactive docs at `/api/docs` (Swagger UI, with "Try it out" sending the CSRF token for you) and `/api/redoc`, when enabled. They load pinned Swagger UI / ReDoc bundles from cdn.jsdelivr.net, so the browser needs internet access. Reference: [`docs/API.md`](docs/API.md),
spec: [`docs/openapi.json`](docs/openapi.json) (regenerate with `python -m scripts.export_openapi`).
Session cookie + `X-CSRF-Token` header; see the top of `docs/API.md`.

## 15. Extending the system

Out of scope for now (appointments, payments, messaging, e-prescriptions, multilingual, external
integrations…). The structure leaves room for them:

* new feature = model + migration, schema, service, controller router, templates, page JS module
* new permissions go in `services/common/permissions.py` (seeded; then assignable in the RBAC editor)
* new notification channels reuse `services/common/notification.py` and the SMS interface
* `MedicalInformation.information_type` is an enum; e-prescriptions or lab orders can be new types or new tables linked to `patient_id`
* all user-facing strings are in templates, ready for i18n (e.g. Babel) later

Icons follow the Lucide style (ISC licence). Fonts: Public Sans and Source Serif 4 (SIL Open Font Licence), self-hosted.
About-section photo: Usman Yousaf on Unsplash ([Unsplash License](https://unsplash.com/license)); see `app/static/img/photos/CREDITS.md`.
