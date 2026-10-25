# --- 1. Build static assets (Node is only needed at build time) -------------------
FROM node:22-alpine AS assets
WORKDIR /src
COPY package.json package-lock.json* ./
RUN npm ci --no-audit --no-fund || npm install --no-audit --no-fund
COPY scripts/build_assets.mjs scripts/
COPY app/static app/static
RUN node scripts/build_assets.mjs

# --- 2. Runtime ---------------------------------------------------------------------
FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    APP_ENV=production USE_BUILT_ASSETS=true COOKIE_SECURE=true
WORKDIR /app
RUN useradd --create-home --uid 10001 cdhrs
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY --chown=cdhrs:cdhrs . .
COPY --from=assets --chown=cdhrs:cdhrs /src/app/static/dist app/static/dist
RUN mkdir -p storage/uploads storage/backups && chown -R cdhrs:cdhrs storage
USER cdhrs
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --retries=5 CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/healthz',timeout=2)"
# --proxy-headers: trust X-Forwarded-For/Proto only from private-network proxies (the nginx
# container on the compose network). The app port itself is never published.
ENV FORWARDED_ALLOW_IPS="127.0.0.1,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16"
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers ${WEB_CONCURRENCY:-2} --proxy-headers --forwarded-allow-ips=\"$FORWARDED_ALLOW_IPS\" --no-server-header"]
