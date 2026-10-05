#!/usr/bin/env bash
# Regenerate agents/shipped.sha256: the checksum of every version of the helper
# files ever shipped. The installer uses it to update a helper the user never
# edited, and to leave alone one they customised.
#   scripts/agent-hashes.sh        (run after changing a file in agents/)
set -euo pipefail
cd "$(dirname "$0")/.."
out=agents/shipped.sha256
{
  echo "# sha256  helper — every shipped version (scripts/agent-hashes.sh)"
  {
    for c in $(git log --format=%H -- agents/); do
      for f in $(git ls-tree --name-only "$c" agents/ | grep '\.md$'); do
        printf '%s  %s\n' "$(git show "$c:$f" | sha256sum | cut -d' ' -f1)" "$(basename "$f")"
      done
    done
    for f in agents/*.md; do
      printf '%s  %s\n' "$(sha256sum <"$f" | cut -d' ' -f1)" "$(basename "$f")"
    done
  } | sort -u -k2,2 -k1,1
} >"$out"
echo "wrote $out ($(($(wc -l <"$out") - 1)) entries)"
