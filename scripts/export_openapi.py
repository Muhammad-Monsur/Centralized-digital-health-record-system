"""Export the OpenAPI spec and a readable endpoint reference.

    python -m scripts.export_openapi        -> docs/openapi.json, docs/API.md
"""
from __future__ import annotations

import json
from pathlib import Path

from app.config import BASE_DIR
from app.main import app

INTRO = """# CDHRS API reference

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
"""


def main() -> int:
    spec = app.openapi()
    docs = BASE_DIR / "docs"
    docs.mkdir(exist_ok=True)
    (docs / "openapi.json").write_text(json.dumps(spec, indent=2))
    groups: dict[str, list[str]] = {}
    for path, ops in sorted(spec["paths"].items()):
        for method, op in ops.items():
            tag = (op.get("tags") or ["other"])[0]
            summary = op.get("summary", "")
            desc = (op.get("description") or "").strip().split("\n")[0]
            line = f"| `{method.upper()}` | `{path}` | {summary}{' - ' + desc if desc and desc != summary else ''} |"
            groups.setdefault(tag, []).append(line)
    out = [INTRO]
    for tag in ("auth", "patient", "doctor", "admin", "common", "system", "other"):
        if tag in groups:
            out.append(f"\n### {tag.capitalize()}\n\n| Method | Path | Description |\n|---|---|---|")
            out.extend(groups[tag])
    (docs / "API.md").write_text("\n".join(out) + "\n")
    print(f"Wrote docs/openapi.json and docs/API.md ({sum(len(v) for v in groups.values())} operations)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
