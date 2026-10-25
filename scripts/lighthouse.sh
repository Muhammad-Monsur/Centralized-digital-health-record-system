#!/usr/bin/env bash
# Lighthouse audit (mobile, simulated throttling) of the landing page, login and a
# signed-in patient dashboard. Prints category scores + Core Web Vitals and keeps the
# JSON/HTML reports in reports/lighthouse/<label>/.
#
#   npm i -g lighthouse            # once (or: npx lighthouse)
#   ./scripts/lighthouse.sh after [http://localhost:8000]
#
# Needs Chrome/Chromium (set CHROME_PATH if it isn't found) and the demo seed data.
# Running as root (e.g. in a container)? Add CHROME_FLAGS=--no-sandbox.
set -euo pipefail
LABEL=${1:-run}
BASE=${2:-http://localhost:8000}
OUT="reports/lighthouse/$LABEL"
mkdir -p "$OUT"
LH=$(command -v lighthouse || echo "npx --yes lighthouse")

JAR=$(mktemp)
curl -s -c "$JAR" -b "$JAR" -o /dev/null "$BASE/login"
TOKEN=$(curl -s -b "$JAR" "$BASE/api/v1/session/status" | python3 -c "import sys,json;print(json.load(sys.stdin)['csrf_token'])")
curl -s -c "$JAR" -b "$JAR" -o /dev/null "$BASE/api/v1/auth/login" -H "X-CSRF-Token: $TOKEN" \
  -H 'Content-Type: application/json' -d '{"identifier":"patient","password":"Demo@12345","portal":"patient"}'
SID=$(awk '/cdhrs_session/ {print $7}' "$JAR"); rm -f "$JAR"

run() {  # name path [cookie]
  local extra=()
  [ -n "${3:-}" ] && extra=(--extra-headers="{\"Cookie\":\"cdhrs_session=$3\"}")
  $LH "$BASE$2" --quiet --chrome-flags="--headless=new ${CHROME_FLAGS:-}" "${extra[@]}" \
    --only-categories=performance,accessibility,best-practices,seo \
    --output=json --output=html --output-path="$OUT/$1" >/dev/null 2>&1
  python3 - "$OUT/$1.report.json" "$1" <<'PY'
import json, sys
r = json.load(open(sys.argv[1])); c = r["categories"]; a = r["audits"]
scores = " ".join(f"{k[:4]}={round(v['score'] * 100)}" for k, v in c.items())
vitals = " ".join(f"{n} {a[k]['displayValue']}" for n, k in (("FCP", "first-contentful-paint"), ("LCP", "largest-contentful-paint"), ("TBT", "total-blocking-time"), ("CLS", "cumulative-layout-shift")))
print(f"{sys.argv[2]:<10} {scores} | {vitals}")
PY
}
run landing /
run login /login
run dashboard /patient "$SID"
echo "HTML reports: $OUT/*.report.html"
