"""Interactive API documentation (Swagger UI and ReDoc).

FastAPI's built-in pages use an inline start-up script. Our CSP only runs inline
scripts that carry the request's nonce, so those pages rendered blank. These
versions add the nonce, pin the library versions, and teach Swagger's
"Try it out" to send the session's CSRF token on state-changing requests.
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

SWAGGER_VERSION = "5.17.14"
REDOC_VERSION = "2.1.5"
CDN = "https://cdn.jsdelivr.net/npm"

router = APIRouter(include_in_schema=False)


def _nonce(request: Request) -> str:
    return getattr(request.state, "csp_nonce", "")


@router.get("/api/docs", response_class=HTMLResponse)
def swagger_ui(request: Request) -> HTMLResponse:
    nonce = _nonce(request)
    title = json.dumps(request.app.title)
    html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{request.app.title} - API documentation</title>
<link rel="icon" href="/static/img/favicon.svg" type="image/svg+xml">
<link rel="stylesheet" href="{CDN}/swagger-ui-dist@{SWAGGER_VERSION}/swagger-ui.css">
<style nonce="{nonce}">body{{margin:0;background:#fff}} .swagger-ui .topbar{{display:none}}</style>
</head>
<body>
<div id="swagger-ui"><p style="font-family:sans-serif;padding:2rem">Loading API documentation&hellip;</p></div>
<script nonce="{nonce}" src="{CDN}/swagger-ui-dist@{SWAGGER_VERSION}/swagger-ui-bundle.js"></script>
<script nonce="{nonce}">
(function () {{
  let csrf = null;
  async function token() {{
    if (csrf) return csrf;
    const r = await fetch("/api/v1/session/status", {{ credentials: "same-origin" }});
    csrf = (await r.json()).csrf_token || "";
    return csrf;
  }}
  if (typeof SwaggerUIBundle === "undefined") {{
    document.getElementById("swagger-ui").innerHTML =
      '<p style="font-family:sans-serif;padding:2rem">Could not load Swagger UI from cdn.jsdelivr.net. ' +
      'Check your internet connection, or read the spec at <a href="/api/openapi.json">/api/openapi.json</a>.</p>';
    return;
  }}
  window.ui = SwaggerUIBundle({{
    url: "/api/openapi.json",
    dom_id: "#swagger-ui",
    deepLinking: true,
    persistAuthorization: true,
    docExpansion: "list",
    filter: true,
    presets: [SwaggerUIBundle.presets.apis, SwaggerUIBundle.SwaggerUIStandalonePreset],
    layout: "BaseLayout",
    // Session cookie is sent automatically; add the CSRF header for POST/PUT/PATCH/DELETE.
    requestInterceptor: async (req) => {{
      req.credentials = "same-origin";
      if (!["GET", "HEAD", "OPTIONS"].includes((req.method || "GET").toUpperCase())) {{
        req.headers["X-CSRF-Token"] = await token();
      }}
      return req;
    }},
    responseInterceptor: (res) => {{ if (res.status === 403) csrf = null; return res; }},
  }});
  document.title = {title} + " - API documentation";
}})();
</script>
</body>
</html>"""
    return HTMLResponse(html)


@router.get("/api/redoc", response_class=HTMLResponse)
def redoc(request: Request) -> HTMLResponse:
    nonce = _nonce(request)
    html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{request.app.title} - API reference</title>
<link rel="icon" href="/static/img/favicon.svg" type="image/svg+xml">
<style nonce="{nonce}">body{{margin:0;padding:0}}</style>
</head>
<body>
<div id="redoc"><p style="font-family:sans-serif;padding:2rem">Loading API reference&hellip;</p></div>
<script nonce="{nonce}" src="{CDN}/redoc@{REDOC_VERSION}/bundles/redoc.standalone.js"></script>
<script nonce="{nonce}">
if (typeof Redoc === "undefined") {{
  document.getElementById("redoc").innerHTML =
    '<p style="font-family:sans-serif;padding:2rem">Could not load ReDoc from cdn.jsdelivr.net. ' +
    'Read the spec at <a href="/api/openapi.json">/api/openapi.json</a>.</p>';
}} else {{
  Redoc.init("/api/openapi.json", {{ hideDownloadButton: false }}, document.getElementById("redoc"));
}}
</script>
</body>
</html>"""
    return HTMLResponse(html)
