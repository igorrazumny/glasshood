#!/usr/bin/env bash
# File: deploy/app-site/build.sh
# Purpose: REQ-GHA-018 — build app.glasshood.ai: the React app (talking to the API at
# the container app's address), Cypher's waking page at /waking/, and the static-site
# config (SPA fallback, crawlers told not to visit, no caching of the waking page).
# Needs: API_BASE, CONTROLLER (…/api), RECAPTCHA_SITE_KEY.
set -euo pipefail
: "${API_BASE:?}" "${CONTROLLER:?}" "${RECAPTCHA_SITE_KEY:?}"
root=$(cd "$(dirname "$0")/../.." && pwd)
out="$root/deploy/app-site/out"
rm -rf "$out"

(cd "$root/frontend" && npm ci --silent && \
  VITE_API_BASE="$API_BASE" VITE_CONTROLLER="$CONTROLLER" VITE_RECAPTCHA_SITE_KEY="$RECAPTCHA_SITE_KEY" \
  npx vite build --outDir "$out" --emptyOutDir)

mkdir -p "$out/waking"
python3 - "$root/deploy/waking-page/index.html" "$out/waking/index.html" "$CONTROLLER" "$RECAPTCHA_SITE_KEY" <<'PY'
import re, sys
src, dst, controller, site_key = sys.argv[1:]
html = open(src).read()
# The page must speak the controller's verified-wake contract (REQ-GHA-018 design v6).
for needed in ("recaptcha_token", "use_token", "glasshood_use_token"):
    assert needed in html, f"waking page lacks the verified-wake contract ({needed})"
def set_const(name, value):
    global html
    pattern = re.compile(r'var %s = "[^"]*";' % name)
    assert len(pattern.findall(html)) == 1, f"waking page {name} constant not found exactly once"
    html = pattern.sub(lambda m: f'var {name} = "{value}";', html)
set_const("CONTROLLER", controller)
set_const("RECAPTCHA_SITE_KEY", site_key)      # the same key the React app is built with
open(dst, "w").write(html)
PY
cp "$root/deploy/app-site/staticwebapp.config.json" "$root/deploy/app-site/robots.txt" "$out/"
echo "built $out"
