#!/usr/bin/env bash
# Installer smoke tests (dry-run: nothing is changed on the machine).
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
T="$(mktemp -d)"
trap 'rm -rf "$T"' EXIT
mkdir -p "$T/bin"
# Arch-like system: `hostname -I` does not exist (it made v1.0.0 stop silently).
printf '#!/bin/sh\necho "hostname: invalid option -- I" >&2\nexit 64\n' >"$T/bin/hostname"
chmod +x "$T/bin/hostname"
export PATH="$T/bin:$PATH" MAV_ENV_BOT="$T/none" MAV_ENV_DASH="$T/none" MAV_ENV_SERVER="$T/none"
fail=0
check() {  # check "name" "expected" command…
  local name="$1" want="$2" out; shift 2
  out="$("$@" 2>&1)"
  if [[ "$out" == *"$want"* ]]; then echo "ok   $name"
  else echo "FAIL $name — wanted: $want"; echo "$out" | tail -15 | sed 's/^/     /'; fail=1; fi
}
cd "$ROOT" || exit 1
# Interactive answers: "set up later", no email, advanced settings with defaults.
answers=$'7\n\ny\n\n\n\n\n\n\ny\n'
check "advanced settings, no hostname -I" "is ready" \
  bash -c "printf '%s' \"\$1\" | bash install.sh --dry-run" _ "$answers"
check "unattended (--yes)" "is ready" bash install.sh --yes --dry-run
check "Arch: uses pacman" "pacman_install python git curl openssl" \
  env MAV_PKG=pacman bash install.sh --yes --dry-run
check "Fedora: uses dnf" "dnf install -y -q python3" env MAV_PKG=dnf bash install.sh --yes --dry-run
# An unexpected error is reported, never silent.
check "errors are reported" "Unexpected error (line" bash -c "
  set -Eeuo pipefail
  $(sed -n '/^on_error() {/,/^trap /p' install.sh)
  false"
exit "$fail"
