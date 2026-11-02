#!/bin/sh
# Start command for cloud hosts (Render, Railway): migrate, seed, then serve on $PORT.
set -e

# Render tells the app its public address; use it unless BASE_URL is set explicitly.
if [ -z "$BASE_URL" ] && [ -n "$RENDER_EXTERNAL_URL" ]; then
  export BASE_URL="$RENDER_EXTERNAL_URL"
fi

# Uploads and backups folders must be writable (on Railway they live on a volume).
for d in "${UPLOAD_DIR:-storage/uploads}" "${BACKUP_DIR:-storage/backups}"; do
  mkdir -p "$d" 2>/dev/null || true
  if ! touch "$d/.write-test" 2>/dev/null; then
    echo "ERROR: cannot write to $d. On Railway, add the variable RAILWAY_RUN_UID=0 so the app can write to the volume." >&2
    exit 1
  fi
  rm -f "$d/.write-test"
done

alembic upgrade head
if [ "$DEMO_MODE" = "true" ]; then
  python -m scripts.seed --demo
else
  python -m scripts.seed
fi

exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --workers "${WEB_CONCURRENCY:-2}" \
  --proxy-headers --forwarded-allow-ips="${FORWARDED_ALLOW_IPS:-*}" --no-server-header
