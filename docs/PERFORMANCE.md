# Performance report (Phase 7)

Measured on a local server (single uvicorn process, MySQL 8.0.46, Redis), Lighthouse 13,
mobile preset with simulated throttling. Reproduce with `./scripts/lighthouse.sh <label>`
(HTML reports land in `reports/lighthouse/<label>/`).

## Lighthouse: before → after

| Page | Performance | Accessibility | Best practices | SEO | FCP | LCP | CLS |
|---|---|---|---|---|---|---|---|
| Landing `/` | 98 → **99** | 100 → **100** | 100 → **100** | 100 → **100** | 1.4 → **1.3 s** | 2.1 → **1.8 s** | 0 |
| Login `/login` | 99 → **99** | 100 → **100** | 100 → **100** | 100 → **100** | 1.4 → **1.3 s** | 2.0 → **1.8 s** | 0 |
| Patient dashboard `/patient` | 99 → **100** | 96 → **100** | 100 → **100** | 100 → **100** | 1.3 → **1.1 s** | 2.0 → **1.9 s** | 0 |

Landing page network: 24 → **10** requests, 9 → **0** render-blocking resources,
135 → **112 KiB** transferred (the two self-hosted variable fonts are ~78 KiB of that),
main-thread work 2.2 → **1.8 s**.

### What Lighthouse flagged, and what was done

| Finding | Fix |
|---|---|
| Render-blocking CSS (`@import` waterfall, 9 files) | esbuild bundles CSS into `core` / `portal` / `landing`; public pages **inline** it (no CSS request before first paint); portal pages use one fingerprinted, long-cached file per bundle |
| Short cache lifetime on CSS/JS/fonts | Content-hashed file names (`main.LQWNRYJL.js`) served with `Cache-Control: public, max-age=31536000, immutable` |
| Colour contrast: green "Public" badge 4.49:1 | `--success` darkened to `#166534` (6.3:1). All token pairs re-checked programmatically in both themes |
| Link `aria-label` didn't contain its visible text (brand link) | Removed the label; the visible text is the accessible name |
| Landing main-thread work 2.2 s | Blurred, animated background orbs (`filter: blur`) replaced by radial gradients; animated SVG `drop-shadow` filters replaced by a static shadow shape; below-the-fold sections use `content-visibility: auto` |
| bfcache blocked by `Cache-Control: no-store` | **Kept on purpose.** Section 8 requires `no-store` on anything containing health data; that intentionally rules out the back/forward cache for those pages |

## Bundle sizes (production build, `npm run build`)

| File | raw | brotli |
|---|---|---|
| `core.css` (inlined on public pages) | 36.5 KB | 7.4 KB |
| `portal.css` | 6.5 KB | 1.5 KB |
| `landing.css` (inlined on the landing page) | 7.3 KB | 1.8 KB |
| `main.js` (every page) | 6.6 KB | 2.3 KB |
| Largest page chunk (`patient-records`) | 3.2 KB | 1.3 KB |
| `search` chunk (loaded on first focus of the search box) | 1.6 KB | 0.7 KB |

## Database

**N+1 guard** (`tests/test_performance.py`): counts SQL statements per page, then grows
the data six-fold. Every page runs a constant number of queries:

```
/patient                    13 -> 13      /admin                       8 -> 8
/patient/records             6 -> 6       /admin/users                11 -> 11
/patient/access-history      8 -> 8       /admin/audit                 8 -> 8
/patient/consent            10 -> 10      /admin/hospitals            10 -> 10
/doctor                     15 -> 15      /admin/access                8 -> 8
/doctor/patients/<UPI>      13 -> 13      /admin/emergency?tab=inter   8 -> 8
```

Finding fixed along the way: `User.roles` was eager-loaded on every User, so any list that
showed a person's name also fetched their roles and permissions. It is now lazy and loaded
explicitly where needed (patient dashboard 17 → 13 queries, records list 10 → 6, doctor's
patient view 19 → 13).

**Index justification** (`python -m scripts.explain_indexes`, tables padded with ~1,000 rows):

| Hot query (page) | Index used |
|---|---|
| Patient by UPI (doctor lookup) | `uq_patient_UPI` (const) |
| Sign-in by email/username | `uq_user_email` / `uq_user_username` (const) |
| Patient's records with visibility filter | `ix_medinfo_patient_vis_status` |
| Patient's records by date | `ix_medinfo_patient_date` |
| Active consent check (every private read) | `ix_consent_patient_doctor_status_exp` / `ix_consent_doctor_status` |
| Active emergency check | `ix_emerg_patient_doctor_exp` / `ix_emergency_access_doctor_id` |
| Pending requests | `ix_accreq_patient_status` |
| Access history, newest first | `ix_accesslog_patient_time` |
| Doctor's recent patients | `ix_accesslog_user_time` |
| Audit log by area / user / entity | `ix_audit_action_time`, `ix_audit_user_time`, `ix_audit_entity` |
| Unread notifications badge | `ix_notification_user_read_time` |
| Record update history | `ix_medhist_info_changed` |
| Hospital admin's doctors | `ix_doctor_hospital_verification` |

**Connection pool**: `pool_size=10`, `max_overflow=20`, `pool_recycle=1800`, `pool_pre_ping`.

**Caching** (Redis, in-memory TTL fallback): system settings (5 min, invalidated on save),
landing-page aggregate counts (5 min), admin dashboard counters (30 s, invalidated on account
and hospital changes). A scan of every cached value finds no UPIs, names or medical text.
FAQ JSON is served with an `ETag` and `public, max-age=300`; everything with health data is `no-store`.

## Load balancer (tested)

`nginx.conf` + `docker-compose.yml --profile full` (nginx → 3 app containers, shared Redis):

* one sign-in, then 30 requests: 30/30 authenticated, spread 9 / 11 / 10 across the containers
* one instance stopped: 12/12 follow-up requests still succeed, nobody is signed out
* nginx serves `/static/dist/` itself with immutable caching and returns 413 for bodies over 12 MB
* the production image builds (Node asset stage + Python runtime, non-root user, health check)
