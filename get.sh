#!/usr/bin/env bash
# ============================================================================
#  Mav — bootstrap d'installation en une ligne
#
#     curl -fsSL https://raw.githubusercontent.com/SoaOaoS/mav/main/get.sh | bash
#
#  Ce script télécharge le dépôt, puis lance install.sh en reconnectant le
#  terminal (indispensable : quand on « pipe » vers bash, stdin contient le
#  script et le lecteur de questions n'aurait plus rien à lire).
#
#  Variables d'environnement acceptées (utile pour l'automatisation, avec
#  install.sh --yes) : MAV_TELEGRAM_TOKEN, MAV_ALLOWED_CHAT_IDS,
#  MAV_OPENCODE_MODEL, MAV_API_BIND, … (voir le README).
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
  die "Lance la commande avec sudo :  curl -fsSL .../get.sh | sudo bash"
fi

command -v curl >/dev/null 2>&1 || {
  command -v wget >/dev/null 2>&1 || die "curl ou wget requis."
}
command -v tar >/dev/null 2>&1 || die "tar requis."

TMP="$(mktemp -d /tmp/mav-install.XXXXXX)"
trap 'rm -rf "$TMP"' EXIT

info "Téléchargement du dépôt ($REPO@$REF)…"
if command -v curl >/dev/null 2>&1; then
  curl -fsSL "$TARBALL" -o "$TMP/mav.tar.gz" || die "Téléchargement impossible."
else
  wget -qO "$TMP/mav.tar.gz" "$TARBALL" || die "Téléchargement impossible."
fi
tar xzf "$TMP/mav.tar.gz" -C "$TMP" --strip-components=1 || die "Extraction impossible."
[[ -f "$TMP/install.sh" ]] || die "install.sh introuvable dans l'archive."
ok "Dépôt prêt."

# Lance install.sh en réattachant le terminal : les questions du wizard lisent
# alors tes vraies réponses, même si ce script a été « pipé ».
cd "$TMP"
ARGS=("$@")
if [[ " ${ARGS[*]} " == *" --yes "* ]] || ! [ -e /dev/tty ]; then
  # Mode automatique (ou pas de terminal) : on ne réattache pas stdin.
  bash "$TMP/install.sh" "${ARGS[@]}"
else
  bash "$TMP/install.sh" "${ARGS[@]}" </dev/tty
fi
