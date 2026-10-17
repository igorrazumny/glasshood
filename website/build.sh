#!/usr/bin/env bash
# Builds the two static sites from one set of source files (REQ-GHA-018 clauses 1-2):
#   <out>/site          glasshood.ai: website/public, with architecture/ at /architecture/
#   <out>/architecture  architecture.glasshood.ai: the architecture page at / (a direct 200),
#                       with its files at /architecture/, where the page links them
# and stops if a served text file holds an email address (clause 3).
# Usage: website/build.sh [out-dir]    (default: website/out)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${1:-$ROOT/website/out}"
case "$OUT" in
  "" | "/" | "$ROOT" | "$HOME") echo "ERROR: refusing to build into '$OUT'" >&2; exit 1 ;;
esac

rm -rf "$OUT"
mkdir -p "$OUT/site" "$OUT/architecture"
cp -R "$ROOT/website/public/." "$OUT/site/"
cp -R "$ROOT/architecture" "$OUT/site/architecture"
cp -R "$ROOT/architecture" "$OUT/architecture/architecture"
cp "$ROOT/architecture/index.html" "$OUT/architecture/index.html"
cp -R "$ROOT/website/architecture/." "$OUT/architecture/"
find "$OUT" -name .DS_Store -delete

# No email address anywhere on the site (clause 3), in any text file that is served.
FOUND=0
grep -rIlE '[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}' "$OUT" >&2 || FOUND=$?
case "$FOUND" in
  0) echo "ERROR: the files above would show an email address (REQ-GHA-018 clause 3)" >&2; exit 1 ;;
  1) ;;
  *) echo "ERROR: could not search $OUT for email addresses (grep exit $FOUND)" >&2; exit 1 ;;
esac
echo "Built $OUT/site and $OUT/architecture"
