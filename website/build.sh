#!/usr/bin/env bash
# Builds the two static sites from one set of source files (REQ-GHA-018 clauses 1-2):
#   <out>/site          glasshood.ai: website/public, with architecture/ at /architecture/
#   <out>/architecture  architecture.glasshood.ai: the architecture page at / (a direct 200),
#                       with its files at /architecture/, where the page links them
# and stops if a served text file holds an email address (clause 3).
# Usage: website/build.sh [out-dir]    (default: website/out)
# The out-dir is replaced on every build, so before anything is deleted it is resolved to
# its real path and checked: inside the repository only website/out is accepted; the
# repository and every directory above it are refused; and an existing directory must be
# empty or carry the mark of a previous build.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd -P)"
MARK=".glasshood-site-build"

# canon PATH: the real absolute path, symlinks resolved, whether PATH exists or not.
# Its parent directory must exist.
canon() {
  local dir base
  dir=$(dirname -- "$1")
  base=$(basename -- "$1")
  dir=$(cd -- "$dir" 2>/dev/null && pwd -P) || return 1
  case "$base" in
    .)  printf '%s\n' "$dir" ;;
    ..) (cd -- "$dir/.." && pwd -P) ;;
    *)  if [ -d "$dir/$base" ]; then (cd -- "$dir/$base" && pwd -P); else printf '%s\n' "${dir%/}/$base"; fi ;;
  esac
}

ARG="${1:-$ROOT/website/out}"
OUT=$(canon "$ARG") || { echo "ERROR: $ARG: its parent directory does not exist" >&2; exit 1; }
refuse() { echo "ERROR: refusing to build into $OUT ($ARG): $1" >&2; exit 1; }
case "$ROOT/" in "${OUT%/}/"*) refuse "it is the repository or a directory above it" ;; esac
case "$OUT/" in "$ROOT/"*) [ "$OUT" = "$ROOT/website/out" ] || refuse "inside the repository only website/out may be used" ;; esac
if [ -e "$OUT" ] || [ -L "$OUT" ]; then
  [ -d "$OUT" ] && [ ! -L "$OUT" ] || refuse "it exists and is not a directory"
  if [ -n "$(ls -A "$OUT")" ] && [ ! -f "$OUT/$MARK" ]; then
    refuse "it holds files that no build made"
  fi
fi

rm -rf "$OUT"
mkdir -p "$OUT/site" "$OUT/architecture"
: > "$OUT/$MARK"
cp -R "$ROOT/website/public/." "$OUT/site/"
cp -R "$ROOT/architecture" "$OUT/site/architecture"
cp -R "$ROOT/architecture" "$OUT/architecture/architecture"
cp "$ROOT/architecture/index.html" "$OUT/architecture/index.html"
cp -R "$ROOT/website/architecture/." "$OUT/architecture/"
find "$OUT" -name .DS_Store -delete

# No email address anywhere on the site (clause 3), in any text file that is served.
FOUND=0
grep -rIlE '[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}' "$OUT/site" "$OUT/architecture" >&2 || FOUND=$?
case "$FOUND" in
  0) echo "ERROR: the files above would show an email address (REQ-GHA-018 clause 3)" >&2; exit 1 ;;
  1) ;;
  *) echo "ERROR: could not search $OUT for email addresses (grep exit $FOUND)" >&2; exit 1 ;;
esac
echo "Built $OUT/site and $OUT/architecture"
