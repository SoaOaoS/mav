#!/usr/bin/env bash
# Copy the web app into docs/demo/ — the public demo on GitHub Pages.
# Served without the server, the app runs on its built-in sample data.
#   scripts/build-demo.sh        (run after changing dashboard/, commit docs/demo)
set -euo pipefail
cd "$(dirname "$0")/.."
out=docs/demo
rm -rf "$out"
mkdir -p "$out"
cp -r dashboard/assets dashboard/icons dashboard/manifest.webmanifest "$out/"
# data-demo: no service worker on the static copy, and the page says it is
# a demo before any request is made.
sed -e 's|<html lang="en">|<html lang="en" data-demo="1">|' \
  -e 's|<title>Mav</title>|<title>Mav — live demo</title>|' \
  dashboard/index.html >"$out/index.html"
grep -q 'data-demo="1"' "$out/index.html" || { echo "build-demo: could not mark index.html as demo" >&2; exit 1; }
echo "wrote $out ($(find "$out" -type f | wc -l) files)"
