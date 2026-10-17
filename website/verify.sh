#!/usr/bin/env bash
# Checks the two static sites as served, after a deploy (REQ-GHA-018 clauses 1-3):
# every page and file answers 200 with the bytes that were built, /demo and /view go to
# the app's demo, an unknown address answers 404, the architecture host answers the page
# itself at / (no redirect), and the page, script and stylesheet revalidate on every load.
# Usage: website/verify.sh [site-origin] [architecture-origin] [built-dir]
# Defaults: the two Static Web Apps' own addresses and website/out (website/build.sh).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SITE="${1:-https://ashy-sea-07717d00f.4.azurestaticapps.net}"
ARCH="${2:-https://lemon-sand-00849da0f.5.azurestaticapps.net}"
OUT="${3:-$ROOT/website/out}"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
FAILED=0
fail() { echo "FAIL: $*" >&2; FAILED=1; }

# get <url>: body to $TMP/body, headers to $TMP/head; prints "<status> <location>"
get() { curl -sS --max-time 20 -o "$TMP/body" -D "$TMP/head" -w '%{http_code} %{redirect_url}' "$1"; }
sha() { shasum -a 256 "$1" | cut -d' ' -f1; }

# serves <url> <built file>: 200 and the same bytes
serves() {
  local got; got=$(get "$1") || { fail "$1: no answer"; return; }
  [ "${got%% *}" = 200 ] || { fail "$1: status ${got%% *}, expected 200"; return; }
  [ "$(sha "$TMP/body")" = "$(sha "$2")" ] || fail "$1: not the built ${2#$OUT/}"
}
# revalidates <url>: Cache-Control says no-cache
revalidates() {
  get "$1" >/dev/null || { fail "$1: no answer"; return; }
  grep -qi '^cache-control:.*no-cache' "$TMP/head" || fail "$1: not sent to revalidate"
}
# forwards <url> <target>: a redirect to exactly <target>
forwards() {
  local got; got=$(get "$1") || { fail "$1: no answer"; return; }
  case "${got%% *}" in 301|302|307|308) ;; *) fail "$1: status ${got%% *}, expected a redirect"; return ;; esac
  [ "${got#* }" = "$2" ] || fail "$1: goes to '${got#* }', expected $2"
}
# missing <url>: 404
missing() {
  local got; got=$(get "$1") || { fail "$1: no answer"; return; }
  [ "${got%% *}" = 404 ] || fail "$1: status ${got%% *}, expected 404"
}

# A new deployment can take a moment to reach every edge: wait up to 3 minutes for /.
for _ in $(seq 1 36); do
  got=$(get "$SITE/" 2>/dev/null || true)
  [ "${got%% *}" = 200 ] && [ "$(sha "$TMP/body" 2>/dev/null)" = "$(sha "$OUT/site/index.html")" ] && break
  sleep 5
done

S="$OUT/site"
serves "$SITE/" "$S/index.html"
serves "$SITE/contact/" "$S/contact/index.html"
serves "$SITE/architecture/" "$S/architecture/index.html"
for f in assets/site.css assets/contact.js architecture/app-state.js architecture/app.js architecture/styles.css robots.txt sitemap.xml; do
  serves "$SITE/$f" "$S/$f"
done
for f in architecture/ architecture/app.js architecture/app-state.js architecture/styles.css; do revalidates "$SITE/$f"; done
for p in /demo /demo/ /view; do forwards "$SITE$p" "https://app.glasshood.ai/demo"; done
missing "$SITE/no-such-page/"
get "$SITE/" >/dev/null && grep -qi '^x-content-type-options: *nosniff' "$TMP/head" || fail "$SITE/: no X-Content-Type-Options"

A="$OUT/architecture"
serves "$ARCH/" "$A/index.html"
for f in architecture/app.js architecture/app-state.js architecture/styles.css architecture/img/glasshood-logo.png; do
  serves "$ARCH/$f" "$A/$f"
done
for f in "" architecture/app.js architecture/app-state.js architecture/styles.css; do revalidates "$ARCH/$f"; done
missing "$ARCH/no-such-page/"

if [ "$FAILED" -ne 0 ]; then echo "Verification FAILED for $SITE and $ARCH" >&2; exit 1; fi
echo "Verified: $SITE and $ARCH serve the build"
