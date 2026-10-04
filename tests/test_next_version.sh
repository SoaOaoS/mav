#!/usr/bin/env bash
# Tests for scripts/next-version.sh on a throwaway git repository.
set -euo pipefail
V="$(cd "$(dirname "$0")/.." && pwd)/scripts/next-version.sh"
T="$(mktemp -d)"
trap 'rm -rf "$T"' EXIT
cd "$T"
git init -q
git config user.email test@example.com
git config user.name test
c() { git commit -q --allow-empty -m "$1"; }
fail=0
expect() {
  local want="$1" got
  got="$("$V" 2>/dev/null || true)"
  if [[ "$got" == "$want" ]]; then echo "ok   $2 → $got"; else echo "FAIL $2: want $want, got ${got:-<none>}"; fail=1; fi
}

c "chore: init";                     expect v0.0.1 "first commit, no tag"
c "feat!: first public version";     expect v1.0.0 "breaking change from 0.x"
git tag v1.0.0;                      expect "" "HEAD already tagged"
c "fix: a bug";                      expect v1.0.1 "fix"
c "feat(ui): a feature"; c "docs: x"; expect v1.1.0 "feat then docs"
git tag v1.1.0
c "fix: a"; c "refactor(api)!: drop it"; c "docs: z"; expect v2.0.0 "bang in the middle"
git tag v2.0.0
c "$(printf 'fix: y\n\nBREAKING CHANGE: config renamed')"; expect v3.0.0 "BREAKING CHANGE footer"
git tag v3.0.0
c "Merge pull request #9 from x/y";  expect v3.0.1 "merge commit"
exit "$fail"
