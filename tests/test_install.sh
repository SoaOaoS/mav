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
# Mav's own version must survive /etc/os-release, which also defines VERSION:
# sourcing it used to overwrite $VERSION, so /etc/mav/version ended up holding
# the distro version (e.g. "13 (trixie)") and broke `mav version` / updates.
check "version not clobbered by os-release" "Mav v9.9.9-test is ready" \
  env MAV_VERSION=v9.9.9-test bash install.sh --yes --dry-run
# An install interrupted after Postgres started gives its credentials back.
cat >"$T/compose.yml" <<'YML'
services:
  postgres:
    environment:
      POSTGRES_USER: mav
      POSTGRES_PASSWORD: Abc123xyz
      POSTGRES_DB: mav
    ports:
      - "127.0.0.1:5433:5432"
YML
check "credentials reused from an existing compose file" "mav:Abc123xyz:mav:5433" bash -c "
  declare -A A; COMPOSE_FILE='$T/compose.yml'
  $(sed -n '/^load_compose_credentials() {/,/^}/p' install.sh)
  load_compose_credentials
  echo \"\${A[PG_USER]}:\${A[PG_PASSWORD]}:\${A[PG_DB]}:\${A[PG_PORT]}\""
# An update must never wipe the user's routines: the shipped bot/jobs.json is
# an empty placeholder, so the snapshot/restore helpers have to bring the
# existing file back after the copy. A bot/jobs.json shipped empty once erased
# every routine on update.
check "routines survive an update" "KEEP-ME" bash -c "
  $(sed -n '/^snapshot_file() {/p; /^restore_file() {/p' install.sh)
  D='$T/jobs'; mkdir -p \"\$D/bot\"
  printf 'KEEP-ME' > \"\$D/bot/jobs.json\"
  snap=\$(snapshot_file \"\$D/bot/jobs.json\")
  echo '[]' > \"\$D/bot/jobs.json\"     # what the shipped placeholder does
  restore_file \"\$D/bot/jobs.json\" \"\$snap\"
  cat \"\$D/bot/jobs.json\""

# An unexpected error is reported, never silent.
check "errors are reported" "Unexpected error (line" bash -c "
  set -Eeuo pipefail
  $(sed -n '/^on_error() {/,/^trap /p' install.sh)
  false"
exit "$fail"
