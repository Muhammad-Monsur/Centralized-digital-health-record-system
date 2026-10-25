# CDHRS API reference

Generated from the OpenAPI spec by `python -m scripts.export_openapi`. Interactive docs:
`/api/docs` (Swagger UI) and `/api/redoc` while `ENABLE_API_DOCS` is on (default: on in
development, off in production). Raw spec: [`openapi.json`](openapi.json).

## How to call the API

* **Authentication**: a server-side session. Sign in with `POST /api/v1/auth/login`
  (`identifier`, `password`, `portal` = `patient` | `doctor` | `hospital-admin` | `system-admin`);
  the response sets an `HttpOnly` session cookie. Each role can only sign in through its own portal.
* **CSRF**: every `POST`/`PUT`/`PATCH`/`DELETE` needs an `X-CSRF-Token` header. Get a token from
  `GET /api/v1/session/status` (`csrf_token`) or the page's `<meta name="csrf-token">`. Tokens are
  masked differently on every response; any of them works for the session.
* **Errors**: JSON `{"detail": "...", "fields": {"field": "message"}}` with the HTTP status
  (401 sign in, 403 not allowed / CSRF, 404 not found or no access, 409 conflict,
  422 validation, 429 rate limited).
* **Pagination**: list endpoints take `page` and `per_page` (max 100) and return
  `items`, `page`, `per_page`, `total`, `pages`.
* **Caching**: responses with health data are `Cache-Control: no-store`.

## Endpoints


### Auth

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/v1/auth/login` | Sign in through a role's portal |
| `POST` | `/api/v1/auth/logout` | Sign out |
| `POST` | `/api/v1/auth/password` | Change your password (signs out other devices) |
| `POST` | `/api/v1/session/extend` | Extend the session (stay signed in) |
| `GET` | `/api/v1/session/status` | Session time left + CSRF token (does not extend) - Polled by the timeout warning. Does NOT extend the session. |

### Patient

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/v1/notifications/read` | Mark all notifications read |
| `POST` | `/api/v1/patient/consent/requests/{request_id}/approve` | Approve an access request (sends SMS code) |
| `POST` | `/api/v1/patient/consent/requests/{request_id}/reject` | Decline an access request |
| `POST` | `/api/v1/patient/consent/{consent_id}/resend` | Send a new SMS code |
| `POST` | `/api/v1/patient/consent/{consent_id}/revoke` | Revoke consent immediately |
| `POST` | `/api/v1/patient/consent/{consent_id}/verify` | Confirm approval with the SMS code |
| `PUT` | `/api/v1/patient/profile` | Update profile (password needed to change phone/email) |
| `GET` | `/api/v1/patient/records` | List own records (filter, search, paginate) |
| `POST` | `/api/v1/patient/records` | Upload a document / add a record |
| `DELETE` | `/api/v1/patient/records/{information_id}` | Delete a document you uploaded |
| `PATCH` | `/api/v1/patient/records/{information_id}/visibility` | Set a record public or private |
| `POST` | `/api/v1/patients/register` | Register a patient account (issues a UPI) |

### Doctor

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/v1/doctor/access-requests/{request_id}/cancel` | Cancel a pending request |
| `POST` | `/api/v1/doctor/emergency/{emergency_access_id}/end` | End emergency access early |
| `POST` | `/api/v1/doctor/patients/lookup` | Find a patient by exact UPI |
| `POST` | `/api/v1/doctor/patients/{upi}/access-requests` | Request consent for private records |
| `POST` | `/api/v1/doctor/patients/{upi}/emergency` | Start emergency access (logged, patient notified) |
| `POST` | `/api/v1/doctor/patients/{upi}/records` | Add a record for a patient (always private) |
| `PATCH` | `/api/v1/doctor/patients/{upi}/records/{information_id}` | Edit a record (own hospital, needs access) |
| `PUT` | `/api/v1/doctor/profile` | Update own phone / specialization |

### Admin

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/v1/admin/backups` | Create a backup |
| `POST` | `/api/v1/admin/backups/{name}/restore` | Restore a backup (type RESTORE) |
| `POST` | `/api/v1/admin/emergency/{emergency_access_id}/end` | End someone's emergency access |
| `GET` | `/api/v1/admin/health` | System health (JSON) |
| `POST` | `/api/v1/admin/hospitals` | Add a hospital (system admin) |
| `PUT` | `/api/v1/admin/hospitals/{hospital_id}` | Edit hospital details |
| `POST` | `/api/v1/admin/hospitals/{hospital_id}/status` | Activate or deactivate a hospital |
| `POST` | `/api/v1/admin/roles` | Create a role |
| `PUT` | `/api/v1/admin/roles/{role_id}/permissions` | Replace a role's permissions |
| `POST` | `/api/v1/admin/roles/{role_id}/reset` | Restore a built-in role's defaults |
| `POST` | `/api/v1/admin/roles/{role_id}/status` | Activate or deactivate a custom role |
| `PUT` | `/api/v1/admin/settings` | Change system settings |
| `POST` | `/api/v1/admin/users` | Create a doctor, staff or hospital-admin account |
| `PUT` | `/api/v1/admin/users/{user_id}` | Edit an account |
| `POST` | `/api/v1/admin/users/{user_id}/password` | Reset a password (user must change it) |
| `POST` | `/api/v1/admin/users/{user_id}/status` | Activate or deactivate an account |
| `POST` | `/api/v1/admin/users/{user_id}/unlock` | Unlock sign-in after lockout |
| `POST` | `/api/v1/admin/users/{user_id}/verify` | Verify or reject a doctor's licence |

### Common

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/v1/contact` | Send a contact message |
| `GET` | `/api/v1/faq` | FAQ (public, ETag-cached) - Public, non-sensitive, identical for everyone -> cacheable with an ETag. |
| `POST` | `/api/v1/newsletter` | Subscribe to the newsletter |
| `GET` | `/api/v1/search` | Role-aware site search |

### System

| Method | Path | Description |
|---|---|---|
| `GET` | `/healthz` | Liveness + database check (load balancer probe) - Liveness + database connectivity probe (used by nginx / docker). |
