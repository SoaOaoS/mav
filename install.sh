#!/usr/bin/env bash
# ============================================================================
#  Mav — installeur unifié (bot Telegram + dashboard web + Postgres + services)
#
#  Usage :
#     sudo ./install.sh              # installation / mise à jour
#     sudo ./install.sh --yes        # tout par défaut, aucune question
#     sudo ./install.sh --dry-run    # montre ce qui serait fait, ne touche à rien
#     sudo ./install.sh --uninstall  # retire services, fichiers, conteneur
#
#  Idempotent : relançable sans casser une install existante.
# ============================================================================
set -euo pipefail

# ------------------------------------------------------------------ constantes
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SELF="${BASH_SOURCE[0]}"

BOT_UNIT="${MAV_BOT_UNIT:-mav-bot}"
SERVER_UNIT="${MAV_SERVER_UNIT:-mav-server}"
DASH_UNIT="${MAV_DASH_UNIT:-mav-dashboard}"
ENV_BOT="${MAV_ENV_BOT:-/etc/mav.env}"
ENV_DASH="${MAV_ENV_DASH:-/etc/mav-dashboard.env}"
ENV_SERVER="${MAV_ENV_SERVER:-/etc/mav-server.env}"
COMPOSE_FILE="${MAV_COMPOSE_FILE:-/etc/mav/docker-compose.yml}"
PG_VOLUME="${MAV_PG_VOLUME:-mav_pgdata}"
PG_CONTAINER_SUFFIX="${MAV_PG_CONTAINER:-mav-postgres}"
OPENCODE_PORT="${MAV_OPENCODE_PORT:-4096}"
ASSUME_YES=0
DRY_RUN=0
DO_UNINSTALL=0
for arg in "$@"; do
  case "$arg" in
    -y|--yes) ASSUME_YES=1 ;;
    --dry-run) DRY_RUN=1 ;;
    --uninstall) DO_UNINSTALL=1 ;;
    -h|--help)
      cat <<'HELP'
Mav — installeur unifié (bot Telegram + dashboard web + Postgres + services)

Usage :
  sudo ./install.sh              installation / mise à jour
  sudo ./install.sh --yes        tout par défaut, aucune question
  sudo ./install.sh --dry-run    montre ce qui serait fait, ne touche à rien
  sudo ./install.sh --uninstall  retire services, configs et conteneur

Idempotent : relançable sans casser une installation existante.
HELP
      exit 0 ;;
    *) echo "Option inconnue : $arg"; exit 2 ;;
  esac
done

# ------------------------------------------------------------------ couleurs
if [[ -t 1 ]]; then
  B=$'\033[1m'; DIM=$'\033[2m'; R=$'\033[0m'
  RED=$'\033[31m'; GRN=$'\033[32m'; YEL=$'\033[33m'; BLU=$'\033[34m'; CYA=$'\033[36m'
else
  B=""; DIM=""; R=""; RED=""; GRN=""; YEL=""; BLU=""; CYA=""
fi

step()  { printf "\n${B}${BLU}▸ %s${R}\n" "$*"; }
info()  { printf "  ${DIM}%s${R}\n" "$*"; }
ok()    { printf "  ${GRN}✓${R} %s\n" "$*"; }
warn()  { printf "  ${YEL}!${R} %s\n" "$*"; }
die()   { printf "\n${RED}✗ %s${R}\n" "$*" >&2; exit 1; }

run() {
  if [[ $DRY_RUN -eq 1 ]]; then
    printf "  ${DIM}[dry-run] %s${R}\n" "$*"
  else
    "$@"
  fi
}

# ------------------------------------------------------------------ wizard
# ask "<question>" "<défaut>" [secret]
STATE_FILE="/etc/mav/install.answers"
declare -A A

ask() {
  local q="$1" def="${2:-}" secret="${3:-}"
  local val=""
  if [[ $ASSUME_YES -eq 1 ]]; then echo "$def"; return; fi
  if [[ -n "$def" ]]; then
    printf "${CYA}?${R} %s ${DIM}[%s]${R} : " "$q" "$def" >&2
  else
    printf "${CYA}?${R} %s : " "$q" >&2
  fi
  if [[ "$secret" == "secret" ]]; then
    read -rs val || val=""; echo >&2
  else
    read -r val || val=""
  fi
  [[ -z "$val" ]] && val="$def"
  echo "$val"
}

# Réponse par défaut depuis l'environnement (pour l'automatisation).
# ex. MAV_TELEGRAM_TOKEN=... MAV_ALLOWED_CHAT_IDS=... MAV_OPENCODE_MODEL=...
env_default() {
  local var="MAV_$1"
  printf '%s' "${!var:-}"
}

# ask_env "<question>" "<VAR>" [secret] : défaut = valeur d'env si présente.
ask_env() {
  local q="$1" var="$2" secret="${3:-}"
  local d; d="$(env_default "$var")"
  ask "$q" "$d" "$secret"
}

# Comme ask_required, mais le défaut peut venir de l'environnement (MAV_<VAR>).
ask_env_required() {
  local q="$1" var="$2" secret="${3:-}"
  local d; d="$(env_default "$var")"
  if [[ $ASSUME_YES -eq 1 && -z "$d" ]]; then
    die "Champ obligatoire manquant : $var. Définis MAV_$var ou relance en interactif."
  fi
  ask_required "$q" "$d" "$secret"
}

ask_required() {
  local q="$1" def="${2:-}" secret="${3:-}" val=""
  if [[ $ASSUME_YES -eq 1 && -z "$def" ]]; then
    die "Champ obligatoire sans défaut : « $q ». Relance sans --yes pour le saisir."
  fi
  while :; do
    val="$(ask "$q" "$def" "$secret")"
    [[ -n "$val" ]] && { echo "$val"; return; }
    warn "Champ obligatoire."
  done
}

ask_choice() {
  # ask_choice "<question>" "<option1|option2|...>" "<défaut>"
  local q="$1" opts="$2" def="$3" val=""
  if [[ $ASSUME_YES -eq 1 ]]; then echo "$def"; return; fi
  printf "${CYA}?${R} %s ${DIM}(%s) [%s]${R} : " "$q" "$opts" "$def" >&2
  read -r val || val=""
  [[ -z "$val" ]] && val="$def"
  echo "$val"
}

gen_password() {
  openssl rand -base64 18 2>/dev/null | tr -d '/+=' | cut -c1-20 || \
    tr -dc 'A-Za-z0-9' </dev/urandom | head -c 20
}

banner() {
  printf "${B}${GRN}"
  cat <<'ASCII'
  __  __                
 |  \/  | __ ___   __   
 | |\/| |/ _` \ \ / /   
 | |  | | (_| |\ V /    
 |_|  |_|\__,_| \_/     
ASCII
  printf "${R}${DIM}  bot Telegram + dashboard, en une commande.${R}\n"
}

# ------------------------------------------------------------------ prérequis
require_root() {
  if [[ $EUID -ne 0 ]]; then
    if [[ $DRY_RUN -eq 1 ]]; then
      warn "dry-run sans root : les actions réelles seraient refusées."
      return
    fi
    die "À lancer en root :  sudo $SELF"
  fi
}

require_debian() {
  if [[ -f /etc/os-release ]]; then
    # shellcheck disable=SC1091
    . /etc/os-release
    case "${ID:-}" in
      debian|ubuntu|raspbian) ok "Système : ${PRETTY_NAME:-$ID}" ;;
      *) warn "Système non testé : ${PRETTY_NAME:-inconnu}. Continue quand même." ;;
    esac
  fi
}

install_prereqs() {
  step "Dépendances système"
  export DEBIAN_FRONTEND=noninteractive
  run apt-get update -qq
  run apt-get install -y -qq \
    python3 python3-venv python3-pip git curl openssl ca-certificates
  if ! command -v docker >/dev/null 2>&1; then
    warn "Docker absent — installation via le dépôt officiel"
    run sh -c 'curl -fsSL https://get.docker.com | sh'
  fi
  run systemctl enable --now docker
  # Le plugin « docker compose » n'est pas toujours fourni : on s'en assure.
  if ! docker compose version >/dev/null 2>&1; then
    warn "Plugin 'docker compose' absent — installation"
    run apt-get install -y -qq docker-compose-plugin 2>/dev/null || warn "Installez docker-compose-plugin manuellement."
  fi
  ok "OK"
}

# Lance un service docker compose, avec repli sur 'docker run' si le plugin
# n'est pas disponible.
pg_up() {
  local user="$1" pass="$2" db="$3" port="$4"
  if docker compose version >/dev/null 2>&1; then
    run docker compose -f "$COMPOSE_FILE" up -d
    return
  fi
  warn "Pas de plugin compose : lancement via 'docker run'."
  if [[ $DRY_RUN -eq 1 ]]; then
    info "[dry-run] docker run postgres:16-alpine …"
    return
  fi
  docker rm -f "$PG_CONTAINER_SUFFIX" >/dev/null 2>&1 || true
  docker run -d --name "$PG_CONTAINER_SUFFIX" --restart unless-stopped \
    -e POSTGRES_USER="$user" -e POSTGRES_PASSWORD="$pass" -e POSTGRES_DB="$db" \
    -p "127.0.0.1:$port:5432" -v "${PG_VOLUME}:/var/lib/postgresql/data" \
    postgres:16-alpine >/dev/null
}

install_opencode() {
  # Le moteur opencode, dans le HOME de l'utilisateur (binaire officiel).
  local home="$1" user="$2"
  step "Moteur opencode"
  if [[ -x "$home/.opencode/bin/opencode" ]]; then
    ok "opencode déjà installé ($("$home/.opencode/bin/opencode" --version 2>/dev/null || echo '?'))"
    return
  fi
  if [[ $DRY_RUN -eq 1 ]]; then
    info "[dry-run] installation d'opencode dans $home"
    return
  fi
  if command -v opencode >/dev/null 2>&1; then
    ok "opencode déjà présent dans le PATH."
    return
  fi
  info "Téléchargement d'opencode (moteur d'agent)…"
  if ! su - "$user" -c 'curl -fsSL https://opencode.ai/install | bash' >/dev/null 2>&1; then
    warn "Installation automatique d'opencode impossible."
    warn "Installe-le manuellement puis relance : https://opencode.ai/docs"
    return
  fi
  ok "opencode installé."
}

# ------------------------------------------------------------------ uninstall
uninstall() {
  step "Désinstallation"
  for u in "$BOT_UNIT" "$DASH_UNIT"; do
    run systemctl disable --now "$u" 2>/dev/null || true
    run rm -f "/etc/systemd/system/$u.service"
  done
  run rm -f "$ENV_BOT" "$ENV_DASH"
  if [[ -f "$COMPOSE_FILE" ]]; then
    run docker compose -f "$COMPOSE_FILE" down 2>/dev/null || true
  fi
  run systemctl daemon-reload
  ok "Services, configs et conteneur retirés."
  info "Les dossiers d'installation et le volume Postgres sont conservés."
  info "Pour tout effacer : le dossier d'install + 'docker volume rm mav_pgdata'."
  exit 0
}

# ============================================================================
#                               PRINCIPAL
# ============================================================================
banner
require_root
require_debian
if [[ $DO_UNINSTALL -eq 1 ]]; then uninstall; fi

# ------------------------------------------------------------------ 1. wizard
step "Configuration (répondez ou validez les défauts)"

DEFAULT_USER="${SUDO_USER:-$(logname 2>/dev/null || echo 'mav')}"
if [[ "$DEFAULT_USER" == "root" ]]; then DEFAULT_USER="mav"; fi

A[INSTALL_USER]="$(ask "Utilisateur système qui fait tourner le bot" "${MAV_INSTALL_USER:-$DEFAULT_USER}")"
if [[ "${A[INSTALL_USER]}" == "root" ]]; then die "Choisissez un utilisateur non-root pour le bot."; fi
A[INSTALL_HOME]="$(ask "Dossier personnel de cet utilisateur" "${MAV_INSTALL_HOME:-/home/${A[INSTALL_USER]}}")"

# Telegram
echo
info "— Telegram —"
A[TELEGRAM_TOKEN]="$(ask_env_required "Token du bot (via @BotFather)" "TELEGRAM_TOKEN" secret)"
A[ALLOWED_CHAT_IDS]="$(ask_env_required "Votre chat ID Telegram (numérique)" "ALLOWED_CHAT_IDS")"
A[CLEAR_ALLOWED_CHAT_IDS]="$(ask_env "Chat IDs autorisés à /clear (vide = désactivé)" "CLEAR_ALLOWED_CHAT_IDS")"

# Provider LLM (moteur opencode)
echo
info "— Modèle (provider LLM) —"
info "  Providers supportés : ollama, anthropic (Claude), openai, custom"
A[PROVIDER]="$(ask_choice "Provider" "ollama|anthropic|openai|custom" "${MAV_PROVIDER:-ollama}")"

case "${A[PROVIDER]}" in
  ollama)
    A[PROVIDER_BASEURL]="$(ask "Endpoint Ollama" "${MAV_PROVIDER_BASEURL:-http://localhost:11434/v1}")"
    A[PROVIDER_APIKEY]="$(ask "Clé API Ollama (vide si non requise)" "${MAV_PROVIDER_APIKEY:-}" secret)"
    A[PROVIDER_ID]="ollama"; A[PROVIDER_NPM]="@ai-sdk/openai-compatible"
    A[OPENCODE_MODEL]="$(ask_env_required "Modèle (ex. llama3.1, qwen2.5-coder)" "OPENCODE_MODEL")"
    ;;
  anthropic)
    A[PROVIDER_BASEURL]="$(ask "Endpoint Anthropic (vide = défaut)" "${MAV_PROVIDER_BASEURL:-}")"
    A[PROVIDER_APIKEY]="$(ask_env_required "Clé API Anthropic" "ANTHROPIC_API_KEY" secret)"
    A[PROVIDER_ID]="anthropic"; A[PROVIDER_NPM]="@ai-sdk/anthropic"
    A[OPENCODE_MODEL]="$(ask "Modèle Anthropic" "${MAV_OPENCODE_MODEL:-claude-sonnet-4-5}")"
    ;;
  openai)
    A[PROVIDER_BASEURL]="$(ask "Endpoint OpenAI (vide = défaut)" "${MAV_PROVIDER_BASEURL:-}")"
    A[PROVIDER_APIKEY]="$(ask_env_required "Clé API OpenAI" "OPENAI_API_KEY" secret)"
    A[PROVIDER_ID]="openai"; A[PROVIDER_NPM]="@ai-sdk/openai"
    A[OPENCODE_MODEL]="$(ask "Modèle OpenAI" "${MAV_OPENCODE_MODEL:-gpt-4o}")"
    ;;
  custom)
    A[PROVIDER_ID]="$(ask_required "Identifiant du provider (ex. openrouter)" "custom")"
    A[PROVIDER_BASEURL]="$(ask_required "Endpoint (baseURL, compatible OpenAI)" "")"
    A[PROVIDER_APIKEY]="$(ask "Clé API (optionnel)" "" secret)"
    A[PROVIDER_NPM]="@ai-sdk/openai-compatible"
    A[OPENCODE_MODEL]="$(ask_env_required "Modèle" "OPENCODE_MODEL")"
    ;;
  *) die "Provider inconnu : ${A[PROVIDER]}" ;;
esac
A[OPENCODE_MODEL_REF]="${A[PROVIDER_ID]}/${A[OPENCODE_MODEL]}"
A[OPENCODE_AGENT]="$(ask "Agent par défaut (vide = défaut opencode)" "${MAV_OPENCODE_AGENT:-}")"
A[OPENCODE_URL]="http://127.0.0.1:${OPENCODE_PORT}"
A[OPENCODE_SERVER_USERNAME]=""
A[OPENCODE_SERVER_PASSWORD]=""

# Postgres
echo
info "— Postgres (Docker) —"
A[POSTGRES_USER]="$(ask "Utilisateur Postgres" "${MAV_POSTGRES_USER:-mav}")"
A[POSTGRES_PASSWORD]="$(ask "Mot de passe Postgres (vide = généré)" "${MAV_POSTGRES_PASSWORD:-$(gen_password)}" secret)"
A[POSTGRES_DB]="$(ask "Base de données" "${MAV_POSTGRES_DB:-mav}")"
A[POSTGRES_PORT]="$(ask "Port Postgres (loopback)" "${MAV_POSTGRES_PORT:-5432}")"

# Dashboard
echo
info "— Dashboard web —"
A[MAV_API_BIND]="$(ask_required "IP d'écoute du dashboard (IP réseau de la machine)" "${MAV_API_BIND:-0.0.0.0}")"
A[MAV_API_PORT]="$(ask "Port HTTP" "${MAV_API_PORT:-80}")"
A[MAV_TLS_PORT]="$(ask "Port HTTPS (vide = pas de TLS)" "${MAV_TLS_PORT:-443}")"
A[MAV_CHAT_ID]="$(ask "Chat ID de rattachement des surveillances" "${MAV_CHAT_ID:-${A[ALLOWED_CHAT_IDS]}}")"
A[MAV_DASH_AGENT]="$(ask "Agent par défaut du dashboard (vide = défaut)" "${MAV_DASH_AGENT:-}")"
A[VAPID_EMAIL]="$(ask "Email de contact (notifications Web Push)" "${MAV_VAPID_EMAIL:-}")"

# Comportement du bot
echo
info "— Comportement du bot (défauts conseillés) —"
A[ANSWER_MODE]="$(ask_choice "Mode de réponse" "last|all" "last")"
A[PLAIN_TEXT_IS_ASK]="$(ask_choice "Texte simple = question ?" "1|0" "1")"
A[SHOW_PROGRESS]="$(ask_choice "Afficher la progression" "1|0" "1")"
A[MEMORY]="$(ask_choice "Mémoire inter-sessions" "1|0" "1")"
A[MEMORY_TOP]="$(ask "Échanges mémorisés injectés" "3")"
A[IDLE_TIMEOUT]="$(ask "Délai d'inactivité avant abandon (s)" "1800")"
A[WATCH_INTERVAL]="$(ask "Intervalle de la veille (s)" "300")"
A[NOTIFY_QUIET]="$(ask "Heures calmes push (ex. 23-7, 0-0 = off)" "23-7")"
A[JOB_RETRIES]="$(ask "Relances auto des jobs en échec" "1")"

# Proxmox (optionnel)
echo
info "— Proxmox (optionnel, Entrée pour ignorer) —"
A[PROXMOX_HOST]="$(ask "Hôte Proxmox (ex. 192.168.1.28)" "")"
A[PROXMOX_USER]="$(ask "Utilisateur Proxmox" "root@pam")"
A[PROXMOX_TOKEN_NAME]="$(ask "Nom du token API" "mcp")"
A[PROXMOX_TOKEN_VALUE]="$(ask "Valeur du token API" "" secret)"

# ------------------------------------------------------------------ récap
step "Récapitulatif"
cat <<EOF

  ${B}Utilisateur${R}      ${A[INSTALL_USER]}  (${A[INSTALL_HOME]})
  ${B}Bot${R}            ${A[INSTALL_HOME]}/bot
  ${B}Dashboard${R}      ${A[INSTALL_HOME]}/workspace/mav-dashboard
  ${B}Postgres${R}       ${A[POSTGRES_USER]}@127.0.0.1:${A[POSTGRES_PORT]}/${A[POSTGRES_DB]}
  ${B}Dashboard URL${R}  http${A[MAV_TLS_PORT]:+s}://${A[MAV_API_BIND]}${A[MAV_TLS_PORT]:+:${A[MAV_TLS_PORT]}}
  ${B}Modèle${R}         ${A[OPENCODE_MODEL_REF]}
  ${B}Heures calmes${R}  ${A[NOTIFY_QUIET]}
EOF

if [[ $ASSUME_YES -eq 0 ]]; then
  printf "\n${CYA}Tout est correct ?${R} ${DIM}[O/n]${R} : "
  read -r confirm || confirm=""
  if [[ "${confirm:-O}" =~ ^[Nn] ]]; then die "Installation annulée."; fi
fi

# ------------------------------------------------------------------ 2. prérequis
install_prereqs

BOT_DIR="${A[INSTALL_HOME]}/bot"
DASH_DIR="${A[INSTALL_HOME]}/workspace/mav-dashboard"
PG_DSN="host=127.0.0.1 port=${A[POSTGRES_PORT]} user=${A[POSTGRES_USER]} password=${A[POSTGRES_PASSWORD]} dbname=${A[POSTGRES_DB]}"

# ------------------------------------------------------------------ 3. utilisateur
step "Utilisateur système"
if id "${A[INSTALL_USER]}" >/dev/null 2>&1; then
  ok "L'utilisateur ${A[INSTALL_USER]} existe déjà."
else
  run useradd -m -s /bin/bash "${A[INSTALL_USER]}"
  ok "Utilisateur ${A[INSTALL_USER]} créé."
fi
# Le home doit appartenir à l'utilisateur (useradd -m ne le fait pas toujours
# quand le dossier préexiste, et opencode s'installe dedans).
if [[ $DRY_RUN -eq 0 && -d "${A[INSTALL_HOME]}" ]]; then
  chown "${A[INSTALL_USER]}:${A[INSTALL_USER]}" "${A[INSTALL_HOME]}"
fi
run usermod -aG docker "${A[INSTALL_USER]}"

# ------------------------------------------------------------------ 3b. opencode
install_opencode "${A[INSTALL_HOME]}" "${A[INSTALL_USER]}"

# ------------------------------------------------------------------ 4. fichiers
step "Copie des fichiers"
run mkdir -p "$BOT_DIR" "$DASH_DIR" "${A[INSTALL_HOME]}/workspace" "$(dirname "$COMPOSE_FILE")"
if [[ $DRY_RUN -eq 0 ]]; then
  cp -a "$SCRIPT_DIR/bot/." "$BOT_DIR/"
  cp -a "$SCRIPT_DIR/dashboard/." "$DASH_DIR/"
  # Réécrit les chemins absolus hérités (jobs.json référence le script biotech).
  if [[ -f "$BOT_DIR/jobs.json" ]]; then
    sed -i "s|/home/opencode/bot|$BOT_DIR|g" "$BOT_DIR/jobs.json"
  fi
  chown -R "${A[INSTALL_USER]}:${A[INSTALL_USER]}" "$BOT_DIR" "$DASH_DIR"
  chown "${A[INSTALL_USER]}:${A[INSTALL_USER]}" "${A[INSTALL_HOME]}/workspace" 2>/dev/null || true
fi
ok "Fichiers en place."

# ------------------------------------------------------------------ 5. venvs
step "Environnements Python"
run python3 -m venv "$BOT_DIR/venv"
run "$BOT_DIR/venv/bin/pip" install --upgrade pip -q
run "$BOT_DIR/venv/bin/pip" install -r "$BOT_DIR/requirements.txt" -q

run python3 -m venv "$DASH_DIR/server/venv"
run "$DASH_DIR/server/venv/bin/pip" install --upgrade pip -q
run "$DASH_DIR/server/venv/bin/pip" install psycopg2-binary pywebpush py-vapid -q
ok "Dépendances Python installées."

# ------------------------------------------------------------------ 6. postgres
step "Postgres (Docker)"
PG_CONTAINER="$PG_CONTAINER_SUFFIX"
if [[ $DRY_RUN -eq 0 ]]; then
  cat > "$COMPOSE_FILE" <<EOF
services:
  postgres:
    image: postgres:16-alpine
    container_name: $PG_CONTAINER_SUFFIX
    restart: unless-stopped
    environment:
      POSTGRES_USER: ${A[POSTGRES_USER]}
      POSTGRES_PASSWORD: ${A[POSTGRES_PASSWORD]}
      POSTGRES_DB: ${A[POSTGRES_DB]}
    ports:
      - "127.0.0.1:${A[POSTGRES_PORT]}:5432"
    volumes:
      - ${PG_VOLUME}:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${A[POSTGRES_USER]} -d ${A[POSTGRES_DB]}"]
      interval: 5s
      timeout: 5s
      retries: 12
volumes:
  ${PG_VOLUME}:
EOF
  chmod 600 "$COMPOSE_FILE"
fi
pg_up "${A[POSTGRES_USER]}" "${A[POSTGRES_PASSWORD]}" "${A[POSTGRES_DB]}" "${A[POSTGRES_PORT]}"

if [[ $DRY_RUN -eq 0 ]]; then
  info "Attente de Postgres…"
  for i in $(seq 1 40); do
    if docker exec "$PG_CONTAINER" \
         pg_isready -U "${A[POSTGRES_USER]}" -d "${A[POSTGRES_DB]}" >/dev/null 2>&1; then
      break
    fi
    sleep 1
  done
  # Applique le schéma (idempotent)
  docker exec -i "$PG_CONTAINER" \
    psql -v ON_ERROR_STOP=1 -U "${A[POSTGRES_USER]}" -d "${A[POSTGRES_DB]}" \
    < "$SCRIPT_DIR/scripts/schema.sql" >/dev/null
fi
ok "Base prête et schéma appliqué."

# ------------------------------------------------------------------ 7. certs + vapid
step "Certificats TLS et clés VAPID"
CERT_DIR="$DASH_DIR/certs"
if [[ $DRY_RUN -eq 0 && ! -f "$CERT_DIR/server.crt" ]]; then
  MAV_SAN_IP="${A[MAV_API_BIND]}" bash "$DASH_DIR/tools/make_certs.sh" >/dev/null 2>&1 || \
    warn "Génération des certificats ignorée (SAN/openssl)."
fi
if [[ $DRY_RUN -eq 0 && ! -f "$BOT_DIR/vapid_private.pem" ]]; then
  "$BOT_DIR/venv/bin/python" - <<PY
from py_vapid import Vapid01
from cryptography.hazmat.primitives import serialization
import base64, pathlib
d = pathlib.Path("$BOT_DIR")
v = Vapid01(); v.generate_keys()
pem = v.private_key.private_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PrivateFormat.PKCS8,
    encryption_algorithm=serialization.NoEncryption()).decode()
raw = v.public_key.public_bytes(
    encoding=serialization.Encoding.X962,
    format=serialization.PublicFormat.UncompressedPoint)
(d/"vapid_private.pem").write_text(pem)
(d/"vapid_private.pem").chmod(0o600)
(d/"vapid_public.txt").write_text(base64.urlsafe_b64encode(raw).decode().rstrip("="))
PY
  chown "${A[INSTALL_USER]}:${A[INSTALL_USER]}" "$BOT_DIR/vapid_private.pem" "$BOT_DIR/vapid_public.txt" 2>/dev/null || true
fi
ok "OK."

# ------------------------------------------------------------------ 8. env files
step "Fichiers de configuration"

# 8a. config opencode de l'utilisateur (provider + modèle).
# Pour anthropic/openai, opencode les connaît déjà : on ne met que le modèle,
# et la clé passe par l'env (lue nativement). Pour les providers custom
# (ollama compris), on déclare le provider avec son endpoint.
OPENCODE_CFG_DIR="${A[INSTALL_HOME]}/.config/opencode"
OPENCODE_CFG="$OPENCODE_CFG_DIR/opencode.json"
if [[ $DRY_RUN -eq 0 ]]; then
  mkdir -p "$OPENCODE_CFG_DIR"
  OPENCODE_CFG="$OPENCODE_CFG" python3 - <<PY
import json, os
from pathlib import Path
p = Path(os.environ["OPENCODE_CFG"])
cfg = {}
if p.is_file():
    try: cfg = json.loads(p.read_text())
    except Exception: cfg = {}
pid = "${A[PROVIDER_ID]}"
model = "${A[OPENCODE_MODEL]}"
base = "${A[PROVIDER_BASEURL]}"
key = "${A[PROVIDER_APIKEY]}"
if pid in ("anthropic", "openai"):
    # Provider natif : clé par variable d'env, pas de redéfinition.
    pass
else:
    envname = {"ollama": "OLLAMA_API_KEY"}.get(pid)
    provider = {
        "npm": "${A[PROVIDER_NPM]}",
        "name": pid,
        "options": {},
        "models": {model: {"name": model}},
    }
    if base: provider["options"]["baseURL"] = base
    if key: provider["options"]["apiKey"] = ("{env:%s}" % envname) if envname else key
    cfg.setdefault("provider", {})[pid] = provider
cfg["model"] = "${A[OPENCODE_MODEL_REF]}"
p.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n")
print("opencode.json écrit")
PY
  # Env du moteur : la clé API y est lue (par le service, pas dans le JSON).
  {
    echo "# Mav — env du moteur opencode (généré)"
    case "${A[PROVIDER_ID]}" in
      anthropic) echo "ANTHROPIC_API_KEY=${A[PROVIDER_APIKEY]}" ;;
      openai)    echo "OPENAI_API_KEY=${A[PROVIDER_APIKEY]}" ;;
      ollama)    [[ -n "${A[PROVIDER_APIKEY]}" ]] && echo "OLLAMA_API_KEY=${A[PROVIDER_APIKEY]}" ;;
    esac
  } > "$ENV_SERVER"
  chmod 600 "$ENV_SERVER"
  chown -R "${A[INSTALL_USER]}:${A[INSTALL_USER]}" "$OPENCODE_CFG_DIR"
fi
ok "Config opencode + clé API en place."

if [[ $DRY_RUN -eq 0 ]]; then
  cat > "$ENV_BOT" <<EOF
# Mav — configuration du bot (généré par install.sh)
BOT_DIR=$BOT_DIR
TELEGRAM_TOKEN=${A[TELEGRAM_TOKEN]}
ALLOWED_CHAT_IDS=${A[ALLOWED_CHAT_IDS]}
CLEAR_ALLOWED_CHAT_IDS=${A[CLEAR_ALLOWED_CHAT_IDS]}
OPENCODE_URL=${A[OPENCODE_URL]}
OPENCODE_MODEL=${A[OPENCODE_MODEL_REF]}
OPENCODE_AGENT=${A[OPENCODE_AGENT]}
OPENCODE_SERVER_USERNAME=${A[OPENCODE_SERVER_USERNAME]}
OPENCODE_SERVER_PASSWORD=${A[OPENCODE_SERVER_PASSWORD]}
ANSWER_MODE=${A[ANSWER_MODE]}
PLAIN_TEXT_IS_ASK=${A[PLAIN_TEXT_IS_ASK]}
SHOW_PROGRESS=${A[SHOW_PROGRESS]}
IDLE_TIMEOUT=${A[IDLE_TIMEOUT]}
MEMORY=${A[MEMORY]}
MEMORY_TOP=${A[MEMORY_TOP]}
WATCH_INTERVAL=${A[WATCH_INTERVAL]}
NOTIFY_QUIET=${A[NOTIFY_QUIET]}
NOTIFY_DEDUP_WINDOW=21600
MAV_VAPID_SUB=mailto:${A[VAPID_EMAIL]:-admin@localhost}
JOB_RETRIES=${A[JOB_RETRIES]}
STATE_FILE=$BOT_DIR/sessions.json
MEMORY_FILE=$BOT_DIR/memory.json
JOBS_FILE=$BOT_DIR/jobs.json
JOBS_STATE=$BOT_DIR/jobs_state.json
PUSH_FILE=$BOT_DIR/push_subs.json
PG_DSN=$PG_DSN
PROXMOX_HOST=${A[PROXMOX_HOST]}
PROXMOX_USER=${A[PROXMOX_USER]}
PROXMOX_TOKEN_NAME=${A[PROXMOX_TOKEN_NAME]}
PROXMOX_TOKEN_VALUE=${A[PROXMOX_TOKEN_VALUE]}
EOF
  chmod 600 "$ENV_BOT"

  cat > "$ENV_DASH" <<EOF
# Mav — configuration du dashboard (généré par install.sh)
MAV_STATIC=$DASH_DIR
BOT_DIR=$BOT_DIR
MAV_ATTACH=/tmp/mav-dashboard/attachments
OPENCODE_URL=${A[OPENCODE_URL]}
OPENCODE_MODEL=${A[OPENCODE_MODEL_REF]}
MAV_DASH_AGENT=${A[MAV_DASH_AGENT]}
MAV_CHAT_ID=${A[MAV_CHAT_ID]}
MAV_API_BIND=${A[MAV_API_BIND]}
MAV_API_PORT=${A[MAV_API_PORT]}
MAV_TLS_PORT=${A[MAV_TLS_PORT]}
MAV_TLS_CERT=$CERT_DIR/server.crt
MAV_TLS_KEY=$CERT_DIR/server.key
MAV_PUSH_FILE=$BOT_DIR/push_subs.json
MAV_USER_HOME=${A[INSTALL_HOME]}
MAV_VAPID_SUB=mailto:${A[VAPID_EMAIL]:-admin@localhost}
PG_DSN=$PG_DSN
EOF
  chmod 600 "$ENV_DASH"
fi
ok "écrits dans $ENV_BOT et $ENV_DASH."

# ------------------------------------------------------------------ 9. systemd
step "Services systemd"
tpl() { sed -e "s|__USER__|${A[INSTALL_USER]}|g" \
            -e "s|__HOME__|${A[INSTALL_HOME]}|g" \
            -e "s|__BOT_DIR__|$BOT_DIR|g" \
            -e "s|__DASH_DIR__|$DASH_DIR|g" \
            -e "s|__DASH_USER__|root|g" \
            -e "s|__PORT__|${OPENCODE_PORT:-4096}|g" \
            -e "s|__ENV_BOT__|$ENV_BOT|g" \
            -e "s|__ENV_DASH__|$ENV_DASH|g" \
            -e "s|__ENV_SERVER__|$ENV_SERVER|g" "$1"; }

if [[ $DRY_RUN -eq 0 ]]; then
  tpl "$SCRIPT_DIR/systemd/opencode-server.service.tpl" > "/etc/systemd/system/$SERVER_UNIT.service"
  tpl "$SCRIPT_DIR/systemd/opencode-bot.service.tpl"    > "/etc/systemd/system/$BOT_UNIT.service"
  tpl "$SCRIPT_DIR/systemd/mav-dashboard.service.tpl"   > "/etc/systemd/system/$DASH_UNIT.service"
fi
run systemctl daemon-reload
run systemctl enable "$SERVER_UNIT" "$BOT_UNIT" "$DASH_UNIT" >/dev/null 2>&1
ok "Unités installées."

# ------------------------------------------------------------------ 10. démarrage
step "Démarrage"
run systemctl restart "$SERVER_UNIT"
if [[ $DRY_RUN -eq 0 ]]; then sleep 4; fi
run systemctl restart "$BOT_UNIT"
run systemctl restart "$DASH_UNIT"
if [[ $DRY_RUN -eq 0 ]]; then sleep 3; fi

if [[ $DRY_RUN -eq 0 ]]; then
  for u in "$SERVER_UNIT" "$BOT_UNIT" "$DASH_UNIT"; do
    if systemctl is-active --quiet "$u"; then ok "$u : actif"
    else warn "$u : inactif — journalctl -u $u -n 20"; fi
  done
fi

# ------------------------------------------------------------------ 11. health
step "Vérification"
if [[ $DRY_RUN -eq 0 ]]; then
  if curl -fsS --max-time 5 "http://127.0.0.1:${OPENCODE_PORT}/global/health" >/dev/null 2>&1; then
    ok "Moteur opencode répond."
  else
    warn "Moteur opencode ne répond pas encore (démarrage lent ?)."
  fi
  SCHEME=http; [[ -n "${A[MAV_TLS_PORT]}" ]] && SCHEME=https
  URL="$SCHEME://127.0.0.1:${A[MAV_TLS_PORT]:-${A[MAV_API_PORT]}}/api/status"
  if curl -fsSk --max-time 5 "$URL" >/dev/null 2>&1; then
    ok "Dashboard répond sur $URL"
  else
    warn "Dashboard ne répond pas encore ($URL)."
  fi
fi

# ------------------------------------------------------------------ fin
cat <<EOF

${B}${GRN}  Installation terminée.${R}

  ${B}Dashboard${R}     https://${A[MAV_API_BIND]}/         (via VPN si réseau privé)
  ${B}Telegram${R}      envoie /start à ton bot
  ${B}Config bot${R}    $ENV_BOT
  ${B}Config dash${R}   $ENV_DASH
  ${B}Logs${R}          journalctl -u $BOT_UNIT -f   |   journalctl -u $DASH_UNIT -f
  ${B}État${R}          systemctl status $BOT_UNIT $DASH_UNIT

  ${DIM}À faire ensuite :${R}
  - Configure ton agent opencode (modèle, MCP, agents) dans ~/.config/opencode/
  - Installe le certificat ${CERT_DIR}/ca.cer sur ton téléphone (Android)
  - Abonne-toi au Web Push depuis le dashboard (bouton cloche)

EOF
