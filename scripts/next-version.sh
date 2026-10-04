#!/usr/bin/env bash
# ============================================================================
#  Next semantic version, from the commits since the last vX.Y.Z tag
#  (Conventional Commits):
#
#    type!: …  or a "BREAKING CHANGE:" footer   → major
#    feat: …                                     → minor
#    anything else (fix, docs, chore, merge…)    → patch
#
#  Prints the next tag (e.g. v1.4.0) and exits 0. Prints nothing and exits 3
#  when HEAD is already tagged (nothing new to release).
#
#  Usage:  scripts/next-version.sh [--explain]
# ============================================================================
set -euo pipefail

explain=0
[[ "${1:-}" == "--explain" ]] && explain=1

TAG_GLOB='v[0-9]*.[0-9]*.[0-9]*'

# Already released?
if git describe --tags --exact-match --match "$TAG_GLOB" HEAD >/dev/null 2>&1; then
  [[ $explain -eq 1 ]] && echo "HEAD is already tagged: $(git describe --tags --exact-match --match "$TAG_GLOB" HEAD)" >&2
  exit 3
fi

last="$(git describe --tags --abbrev=0 --match "$TAG_GLOB" HEAD 2>/dev/null || true)"
if [[ -n "$last" ]]; then
  range="$last..HEAD"
  base="${last#v}"
else
  range="HEAD"
  base="0.0.0"
fi

IFS=. read -r major minor patch <<<"$base"
major="${major:-0}"; minor="${minor:-0}"; patch="${patch%%[-+]*}"; patch="${patch:-0}"

bump="patch"
# %x00 separates commits; subject and body are both inspected.
while IFS= read -r -d $'\0' msg; do
  # git log separates entries with a newline: drop leading blank lines.
  msg="${msg#"${msg%%[![:space:]]*}"}"
  subject="${msg%%$'\n'*}"
  if [[ "$subject" =~ ^[a-zA-Z]+(\([^\)]*\))?!: ]] || grep -qE '^BREAKING[ -]CHANGE:' <<<"$msg"; then
    bump="major"
    break
  fi
  if [[ "$subject" =~ ^feat(\([^\)]*\))?: ]]; then
    bump="minor"
  fi
done < <(git log --format='%B%x00' "$range")

case "$bump" in
  major) major=$((major + 1)); minor=0; patch=0 ;;
  minor) minor=$((minor + 1)); patch=0 ;;
  patch) patch=$((patch + 1)) ;;
esac

next="v${major}.${minor}.${patch}"
if [[ $explain -eq 1 ]]; then
  echo "last tag: ${last:-none} · commits: $(git rev-list --count "$range") · bump: $bump → $next" >&2
fi
echo "$next"
