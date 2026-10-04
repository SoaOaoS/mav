#!/usr/bin/env bash
# ============================================================================
#  Mav — one-line install bootstrap
#
#     curl -fsSL https://raw.githubusercontent.com/SoaOaoS/mav/main/get.sh | bash
#
#  This script downloads the repo, then runs install.sh while reattaching the
#  terminal (essential: when you pipe into bash, stdin holds the
#  script and the prompt reader would have nothing left to read).
#
#  Environment variables accepted (useful for automation, with
#  install.sh --yes): MAV_PROVIDER, MAV_PROVIDER_APIKEY, MAV_OPENCODE_MODEL,
#  MAV_VAPID_EMAIL, … (see the README).
# ============================================================================
set -euo pipefail

REPO="${MAV_REPO:-SoaOaoS/mav}"
REF="${MAV_REF:-main}"
TARBALL="https://codeload.github.com/${REPO}/tar.gz/refs/heads/${REF}"

B=$'\033[1m'; R=$'\033[0m'; DIM=$'\033[2m'
RED=$'\033[31m'; GRN=$'\033[32m'; YEL=$'\033[33m'; CYA=$'\033[36m'

info() { printf "  ${DIM}%s${R}\n" "$*"; }
ok()   { printf "  ${GRN}✓${R} %s\n" "$*"; }
warn() { printf "  ${YEL}!${R} %s\n" "$*"; }
die()  { printf "${RED}✗ %s${R}\n" "$*" >&2; exit 1; }

printf "${B}${CYA}  Mav — installation${R}\n"

# root ?
if [[ $EUID -ne 0 ]]; then
  die "Run the command with sudo:  curl -fsSL .../get.sh | sudo bash"
fi

command -v curl >/dev/null 2>&1 || {
  command -v wget >/dev/null 2>&1 || die "curl or wget is required."
}
command -v tar >/dev/null 2>&1 || die "tar is required."

TMP="$(mktemp -d /tmp/mav-install.XXXXXX)"
trap 'rm -rf "$TMP"' EXIT

info "Downloading repository ($REPO@$REF)…"
if command -v curl >/dev/null 2>&1; then
  curl -fsSL "$TARBALL" -o "$TMP/mav.tar.gz" || die "Download failed."
else
  wget -qO "$TMP/mav.tar.gz" "$TARBALL" || die "Download failed."
fi
tar xzf "$TMP/mav.tar.gz" -C "$TMP" --strip-components=1 || die "Extraction failed."
[[ -f "$TMP/install.sh" ]] || die "install.sh not found in the archive."
ok "Repository ready."

# Run install.sh while reattaching the terminal: the wizard questions then read
# your real answers, even though this script was piped.
cd "$TMP"
ARGS=("$@")
if [[ " ${ARGS[*]} " == *" --yes "* ]] || ! [ -e /dev/tty ]; then
  # Automatic mode (or no terminal): do not reattach stdin.
  bash "$TMP/install.sh" "${ARGS[@]}"
else
  bash "$TMP/install.sh" "${ARGS[@]}" </dev/tty
fi
