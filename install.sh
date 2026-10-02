#!/usr/bin/env bash
# ============================================================================
#  Mav — unified installer (Telegram bot + web dashboard + Postgres + services)
#
#  Usage :
#     sudo ./install.sh              # install / update
#     sudo ./install.sh --yes        # all defaults, no questions
#     sudo ./install.sh --dry-run    # show what would happen, change nothing
#     sudo ./install.sh --uninstall  # remove services, files, container
#
#  Idempotent: safe to re-run without breaking an existing install.
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
DO_UPDATE=0
for arg in "$@"; do
  case "$arg" in
    -y|--yes) ASSUME_YES=1 ;;
    --update|-u) DO_UPDATE=1 ;;
    --dry-run) DRY_RUN=1 ;;
    --uninstall) DO_UNINSTALL=1 ;;
    -h|--help)
      cat <<'HELP'
Mav — unified installer (Telegram bot + web dashboard + Postgres + services)

Usage :
  sudo ./install.sh              install (or re-run the wizard)
  sudo ./install.sh --update     update code/services, keep existing config
  sudo ./install.sh --yes        all defaults, no questions
  sudo ./install.sh --dry-run    show what would happen, change nothing
  sudo ./install.sh --uninstall  remove services, configs and container

Idempotent: safe to re-run without breaking an existing install.
HELP
      exit 0 ;;
    *) echo "Unknown option: $arg"; exit 2 ;;
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
# ask "<question>" "<default>" [secret]
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

# Default answer from the environment (for automation).
# ex. MAV_TELEGRAM_TOKEN=... MAV_ALLOWED_CHAT_IDS=... MAV_OPENCODE_MODEL=...
env_default() {
  local var="MAV_$1"
  printf '%s' "${!var:-}"
}

# ask_env "<question>" "<VAR>" [secret]: default = env value if present.
ask_env() {
  local q="$1" var="$2" secret="${3:-}"
  local d; d="$(env_default "$var")"
  ask "$q" "$d" "$secret"
}

# Like ask_required, but the default can come from the environment (MAV_<VAR>).
ask_env_required() {
  local q="$1" var="$2" secret="${3:-}"
  local d; d="$(env_default "$var")"
  if [[ $ASSUME_YES -eq 1 && -z "$d" ]]; then
    die "Missing required field: $var. Set MAV_$var or re-run interactively."
  fi
  ask_required "$q" "$d" "$secret"
}

ask_required() {
  local q="$1" def="${2:-}" secret="${3:-}" val=""
  if [[ $ASSUME_YES -eq 1 && -z "$def" ]]; then
    die "Required field without default: \"$q\". Re-run without --yes to enter it."
  fi
  while :; do
    val="$(ask "$q" "$def" "$secret")"
    [[ -n "$val" ]] && { echo "$val"; return; }
    warn "This field is required."
  done
}

ask_choice() {
  # ask_choice "<question>" "<opt1|opt2|...>" "<default>"
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

# --------------------------------------------------------------- update mode
# On re-run, the answers live in the generated env files. We reconstruct the
# wizard answers from them so `--update` never asks a question.

# Read one KEY=value from a file (keeps spaces, strips surrounding quotes).
env_get() {
  local file="$1" key="$2" line
  [[ -f "$file" ]] || { echo ""; return; }
  line="$(grep -E "^${key}=" "$file" | tail -1)"
  [[ -z "$line" ]] && { echo ""; return; }
  line="${line#*=}"
  line="${line%$'\r'}"
  # strip one layer of surrounding quotes
  line="${line%\"}"; line="${line#\"}"
  line="${line%\'}"; line="${line#\'}"
  echo "$line"
}

# True if an install already exists (any of the env files present).
detect_existing_install() {
  [[ -f "$ENV_BOT" || -f "$ENV_DASH" || -f "/etc/systemd/system/$BOT_UNIT.service" ]]
}

config_home_for_user() {
  local u="$1"
  local h
  h="$(getent passwd "$u" 2>/dev/null | cut -d: -f6)"
  echo "${h:-/home/$u}"
}

# Rebuild the A[] answers from the existing env files. Used by --update.
load_existing_config() {
  local bot_home dash_bind
  A[INSTALL_USER]="${MAV_INSTALL_USER:-$(env_get "$ENV_BOT" MAV_INSTALL_USER)}"
  BOT_DIR="$(env_get "$ENV_BOT" BOT_DIR)"
  if [[ -z "${A[INSTALL_USER]}" ]]; then
    # Infer from the BOT_DIR owner, else the service User=, else current SUDO_USER.
    if [[ -n "$BOT_DIR" ]]; then
      A[INSTALL_USER]="$(stat -c '%U' "$BOT_DIR" 2>/dev/null || true)"
    fi
    : "${A[INSTALL_USER]:=${SUDO_USER:-mav}}"
  fi
  [[ "${A[INSTALL_USER]}" == "root" ]] && A[INSTALL_USER]="mav"
  A[INSTALL_HOME]="$(config_home_for_user "${A[INSTALL_USER]}")"

  # Telegram + engine
  A[TELEGRAM_TOKEN]="$(env_get "$ENV_BOT" TELEGRAM_TOKEN)"
  A[ALLOWED_CHAT_IDS]="$(env_get "$ENV_BOT" ALLOWED_CHAT_IDS)"
  A[CLEAR_ALLOWED_CHAT_IDS]="$(env_get "$ENV_BOT" CLEAR_ALLOWED_CHAT_IDS)"
  A[OPENCODE_MODEL_REF]="$(env_get "$ENV_BOT" OPENCODE_MODEL)"
  A[OPENCODE_AGENT]="$(env_get "$ENV_BOT" OPENCODE_AGENT)"
  A[OPENCODE_SERVER_USERNAME]="$(env_get "$ENV_BOT" OPENCODE_SERVER_USERNAME)"
  A[OPENCODE_SERVER_PASSWORD]="$(env_get "$ENV_BOT" OPENCODE_SERVER_PASSWORD)"
  A[ANSWER_MODE]="$(env_get "$ENV_BOT" ANSWER_MODE)"
  A[PLAIN_TEXT_IS_ASK]="$(env_get "$ENV_BOT" PLAIN_TEXT_IS_ASK)"
  A[SHOW_PROGRESS]="$(env_get "$ENV_BOT" SHOW_PROGRESS)"
  A[IDLE_TIMEOUT]="$(env_get "$ENV_BOT" IDLE_TIMEOUT)"
  A[MEMORY]="$(env_get "$ENV_BOT" MEMORY)"
  A[MEMORY_TOP]="$(env_get "$ENV_BOT" MEMORY_TOP)"
  A[WATCH_INTERVAL]="$(env_get "$ENV_BOT" WATCH_INTERVAL)"
  A[NOTIFY_QUIET]="$(env_get "$ENV_BOT" NOTIFY_QUIET)"
  A[JOB_RETRIES]="$(env_get "$ENV_BOT" JOB_RETRIES)"
  A[PROXMOX_HOST]="$(env_get "$ENV_BOT" PROXMOX_HOST)"
  A[PROXMOX_USER]="$(env_get "$ENV_BOT" PROXMOX_USER)"
  A[PROXMOX_TOKEN_NAME]="$(env_get "$ENV_BOT" PROXMOX_TOKEN_NAME)"
  A[PROXMOX_TOKEN_VALUE]="$(env_get "$ENV_BOT" PROXMOX_TOKEN_VALUE)"

  # Provider: inferred from the model ref (provider/model) + opencode config.
  A[OPENCODE_MODEL]="${A[OPENCODE_MODEL_REF]#*/}"
  A[PROVIDER_ID]="${A[OPENCODE_MODEL_REF]%%/*}"
  case "${A[PROVIDER_ID]}" in
    anthropic) A[PROVIDER_NPM]="@ai-sdk/anthropic" ;;
    openai)    A[PROVIDER_NPM]="@ai-sdk/openai" ;;
    *)         A[PROVIDER_NPM]="@ai-sdk/openai-compatible" ;;
  esac
  # Base URL + API key from the existing opencode config / server env.
  A[PROVIDER_BASEURL]="$(python3 - "$(config_dir_guess)" "${A[PROVIDER_ID]}" 2>/dev/null <<'PY' || true
import json, sys, pathlib
cfg = pathlib.Path(sys.argv[1]) / "opencode.json"
if cfg.is_file():
    try:
        d = json.loads(cfg.read_text())
        p = (d.get("provider") or {}).get(sys.argv[2]) or {}
        print((p.get("options") or {}).get("baseURL", ""))
    except Exception:
        pass
PY
)"
  A[PROVIDER_APIKEY]=""
  case "${A[PROVIDER_ID]}" in
    anthropic) A[PROVIDER_APIKEY]="$(env_get "$ENV_SERVER" ANTHROPIC_API_KEY)" ;;
    openai)    A[PROVIDER_APIKEY]="$(env_get "$ENV_SERVER" OPENAI_API_KEY)" ;;
    ollama)    A[PROVIDER_APIKEY]="$(env_get "$ENV_SERVER" OLLAMA_API_KEY)" ;;
  esac

  # Postgres
  local dsn; dsn="$(env_get "$ENV_DASH" PG_DSN)"
  : "${dsn:=$(env_get "$ENV_BOT" PG_DSN)}"
  A[POSTGRES_USER]="$(echo "$dsn" | sed -n 's/.*user=\([^ ]*\).*/\1/p')"
  A[POSTGRES_PASSWORD]="$(echo "$dsn" | sed -n 's/.*password=\([^ ]*\).*/\1/p')"
  A[POSTGRES_DB]="$(echo "$dsn" | sed -n 's/.*dbname=\([^ ]*\).*/\1/p')"
  A[POSTGRES_PORT]="$(echo "$dsn" | sed -n 's/.*port=\([^ ]*\).*/\1/p')"
  : "${A[POSTGRES_USER]:=mav}"
  : "${A[POSTGRES_DB]:=mav}"
  : "${A[POSTGRES_PORT]:=5432}"

  # Dashboard
  A[MAV_API_BIND]="$(env_get "$ENV_DASH" MAV_API_BIND)"
  A[MAV_API_PORT]="$(env_get "$ENV_DASH" MAV_API_PORT)"
  A[MAV_TLS_PORT]="$(env_get "$ENV_DASH" MAV_TLS_PORT)"
  A[MAV_CHAT_ID]="$(env_get "$ENV_DASH" MAV_CHAT_ID)"
  A[MAV_DASH_AGENT]="$(env_get "$ENV_DASH" MAV_DASH_AGENT)"
  A[VAPID_EMAIL]="$(env_get "$ENV_BOT" MAV_VAPID_SUB)"
  A[VAPID_EMAIL]="${A[VAPID_EMAIL]#mailto:}"
  : "${A[MAV_API_BIND]:=0.0.0.0}"
  : "${A[MAV_API_PORT]:=80}"
  : "${A[MAV_TLS_PORT]:=443}"
  : "${A[OPENCODE_MODEL_REF]:=${MAV_OPENCODE_MODEL:-}}"
}

# Where opencode's user config lives (for reading baseURL on update).
config_dir_guess() {
  echo "${MAV_USER_HOME:-${A[INSTALL_HOME]:-}}/.config/opencode"
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
  printf "${R}${DIM}  Telegram bot + dashboard, in one command.${R}\n"
}

# ------------------------------------------------------------------ prerequisites
require_root() {
  if [[ $EUID -ne 0 ]]; then
    if [[ $DRY_RUN -eq 1 ]]; then
      warn "dry-run without root: real actions would be refused."
      return
    fi
    die "Run as root:  sudo $SELF"
  fi
}

require_debian() {
  if [[ -f /etc/os-release ]]; then
    # shellcheck disable=SC1091
    . /etc/os-release
    case "${ID:-}" in
      debian|ubuntu|raspbian) ok "System: ${PRETTY_NAME:-$ID}" ;;
      *) warn "Untested system: ${PRETTY_NAME:-unknown}. Continuing anyway." ;;
    esac
  fi
}

install_prereqs() {
  step "System dependencies"
  export DEBIAN_FRONTEND=noninteractive
  run apt-get update -qq
  run apt-get install -y -qq \
    python3 python3-venv python3-pip git curl openssl ca-certificates
  if ! command -v docker >/dev/null 2>&1; then
    warn "Docker missing — installing from the official repository"
    run sh -c 'curl -fsSL https://get.docker.com | sh'
  fi
  run systemctl enable --now docker
  # Le plugin « docker compose » n'est pas toujours fourni : on s'en assure.
  if ! docker compose version >/dev/null 2>&1; then
    warn "'docker compose' plugin missing — installing"
    run apt-get install -y -qq docker-compose-plugin 2>/dev/null || warn "Installez docker-compose-plugin manuellement."
  fi
  ok "OK"
}

# Starts the docker compose service, falling back to 'docker run' if the plugin
# is not available.
pg_up() {
  local user="$1" pass="$2" db="$3" port="$4"
  if docker compose version >/dev/null 2>&1; then
    run docker compose -f "$COMPOSE_FILE" up -d
    return
  fi
  warn "No compose plugin: starting via 'docker run'."
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
  # The opencode engine, in the user's HOME (official binary).
  local home="$1" user="$2"
  step "Moteur opencode"

  # Already present in the user's expected location?
  if [[ -x "$home/.opencode/bin/opencode" ]]; then
    OPENCODE_BIN="$home/.opencode/bin/opencode"
    ok "opencode already installed ($("$OPENCODE_BIN" --version 2>/dev/null || echo '?'))"
    return
  fi

  if [[ $DRY_RUN -eq 1 ]]; then
    info "[dry-run] would install opencode into $home"
    OPENCODE_BIN="$home/.opencode/bin/opencode"
    return
  fi

  # Try the official installer as the user.
  info "Downloading opencode (agent engine)…"
  su - "$user" -c 'curl -fsSL https://opencode.ai/install | bash' >/dev/null 2>&1 || true

  # Locate the binary wherever it actually ended up: the user's own install,
  # the login-shell PATH, or a system-wide install. This makes the installer
  # work whether opencode was installed by us, by the user by hand, or by root.
  OPENCODE_BIN="$(resolve_opencode_bin "$home" "$user")"
  if [[ -n "$OPENCODE_BIN" ]]; then
    ok "opencode found at $OPENCODE_BIN"
  else
    warn "opencode not found. Install it, then re-run this installer:"
    warn "  curl -fsSL https://opencode.ai/install | bash"
    OPENCODE_BIN="$home/.opencode/bin/opencode"
  fi
}

# Find the opencode binary. Returns an absolute path, or empty if absent.
resolve_opencode_bin() {
  local home="$1" user="$2" p
  # 1. Standard per-user install location.
  for p in "$home/.opencode/bin/opencode"; do
    [[ -x "$p" ]] && { echo "$p"; return; }
  done
  # 2. The target user's login PATH (covers custom install dirs).
  p="$(su - "$user" -c 'command -v opencode' 2>/dev/null | tail -1 | tr -d '\r')"
  [[ -n "$p" && -x "$p" ]] && { echo "$p"; return; }
  # 3. Our own PATH and common system locations.
  p="$(command -v opencode 2>/dev/null || true)"
  [[ -n "$p" && -x "$p" ]] && { echo "$p"; return; }
  for p in /usr/local/bin/opencode /usr/bin/opencode /root/.opencode/bin/opencode; do
    [[ -x "$p" ]] && { echo "$p"; return; }
  done
  echo ""
}

# ------------------------------------------------------------------ uninstall
uninstall() {
  step "Uninstall"
  for u in "$SERVER_UNIT" "$BOT_UNIT" "$DASH_UNIT"; do
    run systemctl disable --now "$u" 2>/dev/null || true
    run rm -f "/etc/systemd/system/$u.service"
  done
  run rm -f "$ENV_BOT" "$ENV_DASH"
  if [[ -f "$COMPOSE_FILE" ]]; then
    run docker compose -f "$COMPOSE_FILE" down 2>/dev/null || true
  fi
  run systemctl daemon-reload
  ok "Services, configs and container removed."
  info "Install folders and the Postgres volume are kept."
  info "To remove everything: the install folder + 'docker volume rm mav_pgdata'."
  exit 0
}

# ============================================================================
#                               PRINCIPAL
# ============================================================================
banner
require_root
require_debian
if [[ $DO_UNINSTALL -eq 1 ]]; then uninstall; fi

# Smart default: if an install already exists and the user did not explicitly
# ask to reconfigure, behave like --update (no questions, keep the config).
# This makes "just run install.sh again" painless.
if [[ $DO_UPDATE -eq 0 && $ASSUME_YES -eq 0 ]]; then
  if detect_existing_install; then
    printf "\n${YEL}An existing install was found.${R}\n"
    printf "  ${DIM}[U]${R} update it (keep my config)   ${DIM}[R]${R} reconfigure from scratch\n"
    printf "${CYA}?${R} [U/R] : "
    read -r _ans || _ans=""
    case "${_ans:-U}" in
      [Rr]*) : ;;                 # keep DO_UPDATE=0 -> wizard
      *)     DO_UPDATE=1 ;;       # update by default
    esac
  fi
fi

# ------------------------------------------------------------------ 0. update
# --update (or re-running on an existing install with --yes) skips the wizard
# and reuses the saved configuration. No questions asked.
if [[ $DO_UPDATE -eq 1 ]]; then
  if ! detect_existing_install; then
    die "No existing install found. Run without --update to set one up first."
  fi
  step "Update (reusing existing configuration)"
  load_existing_config
  _tls=""
  if [[ -n "${A[MAV_TLS_PORT]}" ]]; then _tls=" + TLS ${A[MAV_TLS_PORT]}"; fi
  info "User:     ${A[INSTALL_USER]} (${A[INSTALL_HOME]})"
  info "Model:    ${A[OPENCODE_MODEL_REF]:-—}"
  info "Chat IDs: ${A[ALLOWED_CHAT_IDS]:-—}"
  info "Dashboard bind: ${A[MAV_API_BIND]}:${A[MAV_API_PORT]}${_tls}"
  ASSUME_YES=1   # never prompt during an update
fi

# ------------------------------------------------------------------ 1. wizard
if [[ $DO_UPDATE -eq 0 ]]; then
step "Configuration (answer, or accept the defaults)"

DEFAULT_USER="${SUDO_USER:-$(logname 2>/dev/null || echo 'mav')}"
if [[ "$DEFAULT_USER" == "root" ]]; then DEFAULT_USER="mav"; fi

A[INSTALL_USER]="$(ask "System user that runs the bot" "${MAV_INSTALL_USER:-$DEFAULT_USER}")"
if [[ "${A[INSTALL_USER]}" == "root" ]]; then die "Choose a non-root user for the bot."; fi
A[INSTALL_HOME]="$(ask "That user's home directory" "${MAV_INSTALL_HOME:-/home/${A[INSTALL_USER]}}")"

# Telegram
echo
info "— Telegram —"
A[TELEGRAM_TOKEN]="$(ask_env_required "Bot token (from @BotFather)" "TELEGRAM_TOKEN" secret)"
A[ALLOWED_CHAT_IDS]="$(ask_env_required "Your Telegram chat ID (numeric)" "ALLOWED_CHAT_IDS")"
A[CLEAR_ALLOWED_CHAT_IDS]="$(ask_env "Chat IDs allowed to /clear (empty = disabled)" "CLEAR_ALLOWED_CHAT_IDS")"

# Provider LLM (moteur opencode)
echo
info "— Model (LLM provider) —"
info "  Supported providers: ollama, anthropic (Claude), openai, custom"
A[PROVIDER]="$(ask_choice "Provider" "ollama|anthropic|openai|custom" "${MAV_PROVIDER:-ollama}")"

case "${A[PROVIDER]}" in
  ollama)
    A[PROVIDER_BASEURL]="$(ask "Endpoint Ollama" "${MAV_PROVIDER_BASEURL:-http://localhost:11434/v1}")"
    A[PROVIDER_APIKEY]="$(ask "Ollama API key (empty if not required)" "${MAV_PROVIDER_APIKEY:-}" secret)"
    A[PROVIDER_ID]="ollama"; A[PROVIDER_NPM]="@ai-sdk/openai-compatible"
    A[OPENCODE_MODEL]="$(ask_env_required "Model (e.g. llama3.1, qwen2.5-coder)" "OPENCODE_MODEL")"
    ;;
  anthropic)
    A[PROVIDER_BASEURL]="$(ask "Anthropic endpoint (empty = default)" "${MAV_PROVIDER_BASEURL:-}")"
    A[PROVIDER_APIKEY]="$(ask_env_required "Anthropic API key" "ANTHROPIC_API_KEY" secret)"
    A[PROVIDER_ID]="anthropic"; A[PROVIDER_NPM]="@ai-sdk/anthropic"
    A[OPENCODE_MODEL]="$(ask "Anthropic model" "${MAV_OPENCODE_MODEL:-claude-sonnet-4-5}")"
    ;;
  openai)
    A[PROVIDER_BASEURL]="$(ask "OpenAI endpoint (empty = default)" "${MAV_PROVIDER_BASEURL:-}")"
    A[PROVIDER_APIKEY]="$(ask_env_required "OpenAI API key" "OPENAI_API_KEY" secret)"
    A[PROVIDER_ID]="openai"; A[PROVIDER_NPM]="@ai-sdk/openai"
    A[OPENCODE_MODEL]="$(ask "OpenAI model" "${MAV_OPENCODE_MODEL:-gpt-4o}")"
    ;;
  custom)
    A[PROVIDER_ID]="$(ask_required "Provider id (e.g. openrouter)" "custom")"
    A[PROVIDER_BASEURL]="$(ask_required "Endpoint (baseURL, compatible OpenAI)" "")"
    A[PROVIDER_APIKEY]="$(ask "API key (optional)" "" secret)"
    A[PROVIDER_NPM]="@ai-sdk/openai-compatible"
    A[OPENCODE_MODEL]="$(ask_env_required "Model" "OPENCODE_MODEL")"
    ;;
  *) die "Unknown provider: ${A[PROVIDER]}" ;;
esac
A[OPENCODE_MODEL_REF]="${A[PROVIDER_ID]}/${A[OPENCODE_MODEL]}"
A[OPENCODE_AGENT]="$(ask "Default agent (empty = opencode default)" "${MAV_OPENCODE_AGENT:-}")"
A[OPENCODE_URL]="http://127.0.0.1:${OPENCODE_PORT}"
A[OPENCODE_SERVER_USERNAME]=""
A[OPENCODE_SERVER_PASSWORD]=""

# Postgres
echo
info "— Postgres (Docker) —"
A[POSTGRES_USER]="$(ask "Postgres user" "${MAV_POSTGRES_USER:-mav}")"
A[POSTGRES_PASSWORD]="$(ask "Postgres password (empty = generated)" "${MAV_POSTGRES_PASSWORD:-$(gen_password)}" secret)"
A[POSTGRES_DB]="$(ask "Database name" "${MAV_POSTGRES_DB:-mav}")"
A[POSTGRES_PORT]="$(ask "Postgres port (loopback)" "${MAV_POSTGRES_PORT:-5432}")"

# Dashboard
echo
info "— Web dashboard —"
A[MAV_API_BIND]="$(ask_required "Dashboard bind IP (the machine's network IP)" "${MAV_API_BIND:-0.0.0.0}")"
A[MAV_API_PORT]="$(ask "HTTP port" "${MAV_API_PORT:-80}")"
A[MAV_TLS_PORT]="$(ask "HTTPS port (empty = no TLS)" "${MAV_TLS_PORT:-443}")"
A[MAV_CHAT_ID]="$(ask "Chat ID to attach watch alerts to" "${MAV_CHAT_ID:-${A[ALLOWED_CHAT_IDS]}}")"
A[MAV_DASH_AGENT]="$(ask "Dashboard default agent (empty = default)" "${MAV_DASH_AGENT:-}")"
A[VAPID_EMAIL]="$(ask "Contact email (Web Push notifications)" "${MAV_VAPID_EMAIL:-}")"

# Comportement du bot
echo
info "— Bot behaviour (recommended defaults) —"
A[ANSWER_MODE]="$(ask_choice "Answer mode" "last|all" "last")"
A[PLAIN_TEXT_IS_ASK]="$(ask_choice "Plain text = question?" "1|0" "1")"
A[SHOW_PROGRESS]="$(ask_choice "Show progress" "1|0" "1")"
A[MEMORY]="$(ask_choice "Cross-session memory" "1|0" "1")"
A[MEMORY_TOP]="$(ask "Remembered exchanges to inject" "3")"
A[IDLE_TIMEOUT]="$(ask "Idle timeout before giving up (s)" "1800")"
A[WATCH_INTERVAL]="$(ask "Watch interval (s)" "300")"
A[NOTIFY_QUIET]="$(ask "Push quiet hours (e.g. 23-7, 0-0 = off)" "23-7")"
A[JOB_RETRIES]="$(ask "Auto-retries for failed jobs" "1")"

# Proxmox (optional)
echo
info "— Proxmox (optional, press Enter to skip) —"
A[PROXMOX_HOST]="$(ask "Proxmox host (e.g. 10.0.0.10, empty to skip)" "")"
A[PROXMOX_USER]="$(ask "Proxmox user" "root@pam")"
A[PROXMOX_TOKEN_NAME]="$(ask "API token name" "mcp")"
A[PROXMOX_TOKEN_VALUE]="$(ask "API token value" "" secret)"
fi  # end wizard (skipped in --update)

# Always derivable, no need to ask.
A[OPENCODE_URL]="http://127.0.0.1:${OPENCODE_PORT}"
[[ -z "${A[OPENCODE_MODEL_REF]:-}" ]] && [[ -n "${A[OPENCODE_MODEL]:-}" ]] && \
  A[OPENCODE_MODEL_REF]="${A[PROVIDER_ID]:-}/${A[OPENCODE_MODEL]}"

# ------------------------------------------------------------------ summary
step "Summary"
cat <<EOF

  ${B}User${R}      ${A[INSTALL_USER]}  (${A[INSTALL_HOME]})
  ${B}Bot${R}            ${A[INSTALL_HOME]}/bot
  ${B}Dashboard${R}      ${A[INSTALL_HOME]}/workspace/mav-dashboard
  ${B}Postgres${R}       ${A[POSTGRES_USER]}@127.0.0.1:${A[POSTGRES_PORT]}/${A[POSTGRES_DB]}
  ${B}Dashboard URL${R}  http${A[MAV_TLS_PORT]:+s}://${A[MAV_API_BIND]}${A[MAV_TLS_PORT]:+:${A[MAV_TLS_PORT]}}
  ${B}Model${R}         ${A[OPENCODE_MODEL_REF]}
  ${B}Quiet hours${R}  ${A[NOTIFY_QUIET]}
EOF

if [[ $ASSUME_YES -eq 0 ]]; then
  printf "\n${CYA}Is this correct?${R} ${DIM}[Y/n]${R} : "
  read -r confirm || confirm=""
  if [[ "${confirm:-O}" =~ ^[Nn] ]]; then die "Install aborted."; fi
fi

# ------------------------------------------------------------------ 2. prerequisites
install_prereqs

BOT_DIR="${A[INSTALL_HOME]}/bot"
DASH_DIR="${A[INSTALL_HOME]}/workspace/mav-dashboard"
PG_DSN="host=127.0.0.1 port=${A[POSTGRES_PORT]} user=${A[POSTGRES_USER]} password=${A[POSTGRES_PASSWORD]} dbname=${A[POSTGRES_DB]}"

# ------------------------------------------------------------------ 3. user
step "System user"
if id "${A[INSTALL_USER]}" >/dev/null 2>&1; then
  ok "User ${A[INSTALL_USER]} already exists."
else
  run useradd -m -s /bin/bash "${A[INSTALL_USER]}"
  ok "User ${A[INSTALL_USER]} created."
fi
# The home directory must belong to the user (useradd -m does not always
# when the folder pre-exists, and opencode installs into it).
if [[ $DRY_RUN -eq 0 && -d "${A[INSTALL_HOME]}" ]]; then
  chown "${A[INSTALL_USER]}:${A[INSTALL_USER]}" "${A[INSTALL_HOME]}"
fi
run usermod -aG docker "${A[INSTALL_USER]}"

# ------------------------------------------------------------------ 3b. opencode
install_opencode "${A[INSTALL_HOME]}" "${A[INSTALL_USER]}"

# ------------------------------------------------------------------ 4. fichiers
step "Copying files"
run mkdir -p "$BOT_DIR" "$DASH_DIR" "${A[INSTALL_HOME]}/workspace" "$(dirname "$COMPOSE_FILE")"
if [[ $DRY_RUN -eq 0 ]]; then
  cp -a "$SCRIPT_DIR/bot/." "$BOT_DIR/"
  cp -a "$SCRIPT_DIR/dashboard/." "$DASH_DIR/"
  # Rewrite inherited absolute paths: example jobs may reference /home/USER/bot.
  if [[ -f "$BOT_DIR/jobs.json" ]]; then
    sed -i -E "s|/home/[^/ ]+/bot|$BOT_DIR|g" "$BOT_DIR/jobs.json"
  fi
  chown -R "${A[INSTALL_USER]}:${A[INSTALL_USER]}" "$BOT_DIR" "$DASH_DIR"
  chown "${A[INSTALL_USER]}:${A[INSTALL_USER]}" "${A[INSTALL_HOME]}/workspace" 2>/dev/null || true

  # Keep a persistent copy of the installer so `mav update` works later, even
  # when the original run came from a temporary directory (curl | bash).
  MAV_SRC="${A[INSTALL_HOME]}/.mav"
  rm -rf "$MAV_SRC"
  mkdir -p "$MAV_SRC"
  cp -a "$SCRIPT_DIR/." "$MAV_SRC/"
  chown -R "${A[INSTALL_USER]}:${A[INSTALL_USER]}" "$MAV_SRC"
  # A tiny CLI: `mav update`, `mav reconfigure`, `mav uninstall`, `mav status`.
  cat > /usr/local/bin/mav <<CLI
#!/usr/bin/env bash
# Mav control command (generated by install.sh)
SRC="$MAV_SRC"
if [[ ! -f "\$SRC/install.sh" ]]; then
  echo "Mav installer source not found (\$SRC)." >&2
  exit 1
fi
case "\${1:-}" in
  update|up)       exec sudo bash "\$SRC/install.sh" --update ;;
  reconfigure|config) exec sudo bash "\$SRC/install.sh" ;;
  uninstall|remove)   exec sudo bash "\$SRC/install.sh" --uninstall ;;
  status|st)
    systemctl status $SERVER_UNIT $BOT_UNIT $DASH_UNIT --no-pager 2>/dev/null || true
    ;;
  logs)  exec journalctl -u "$BOT_UNIT" -f ;;
  ""|-h|--help|help)
    cat <<'EOF'
Mav — control command

  mav update        update the code and services, keep your config
  mav reconfigure   re-run the setup wizard (change settings)
  mav uninstall     remove services, configs and the container
  mav status        show the service status
  mav logs          follow the bot logs
EOF
    ;;
  *) echo "Unknown command: \$1 (try: mav help)" >&2; exit 2 ;;
esac
CLI
  chmod 755 /usr/local/bin/mav
fi
ok "Fichiers en place."

# ------------------------------------------------------------------ 5. venvs
step "Python environments"
run python3 -m venv "$BOT_DIR/venv"
run "$BOT_DIR/venv/bin/pip" install --upgrade pip -q
run "$BOT_DIR/venv/bin/pip" install -r "$BOT_DIR/requirements.txt" -q

run python3 -m venv "$DASH_DIR/server/venv"
run "$DASH_DIR/server/venv/bin/pip" install --upgrade pip -q
run "$DASH_DIR/server/venv/bin/pip" install psycopg2-binary pywebpush py-vapid -q
ok "Python dependencies installed."

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
  info "Waiting for Postgres…"
  for i in $(seq 1 40); do
    if docker exec "$PG_CONTAINER" \
         pg_isready -U "${A[POSTGRES_USER]}" -d "${A[POSTGRES_DB]}" >/dev/null 2>&1; then
      break
    fi
    sleep 1
  done
  # Apply the schema (idempotent)
  docker exec -i "$PG_CONTAINER" \
    psql -v ON_ERROR_STOP=1 -U "${A[POSTGRES_USER]}" -d "${A[POSTGRES_DB]}" \
    < "$SCRIPT_DIR/scripts/schema.sql" >/dev/null
fi
ok "Database ready and schema applied."

# ------------------------------------------------------------------ 7. certs + vapid
step "TLS certificates and VAPID keys"
CERT_DIR="$DASH_DIR/certs"
if [[ $DRY_RUN -eq 0 && ! -f "$CERT_DIR/server.crt" ]]; then
  MAV_SAN_IP="${A[MAV_API_BIND]}" bash "$DASH_DIR/tools/make_certs.sh" >/dev/null 2>&1 || \
    warn "Certificate generation skipped (SAN/openssl)."
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
step "Configuration files"

# 8a. user opencode config (provider + model).
# For anthropic/openai, opencode already knows them: we only set the model,
# and the key goes through the env (read natively). For custom providers
# (including ollama), we declare the provider with its endpoint.
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
    # Native provider: key via env var, no redefinition.
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
print("opencode.json written")
PY
  # Engine env: the API key is read there (by the service, not from the JSON).
  {
    echo "# Mav — opencode engine env (generated)"
    case "${A[PROVIDER_ID]}" in
      anthropic) echo "ANTHROPIC_API_KEY=${A[PROVIDER_APIKEY]}" ;;
      openai)    echo "OPENAI_API_KEY=${A[PROVIDER_APIKEY]}" ;;
      ollama)    [[ -n "${A[PROVIDER_APIKEY]}" ]] && echo "OLLAMA_API_KEY=${A[PROVIDER_APIKEY]}" ;;
    esac
  } > "$ENV_SERVER"
  chmod 600 "$ENV_SERVER"

  # Install the generic agent templates (orchestrator + specialists) if the
  # user has none yet. Existing agent files are left untouched.
  AGENT_DIR="$OPENCODE_CFG_DIR/agent"
  mkdir -p "$AGENT_DIR"
  if [[ -d "$SCRIPT_DIR/agents" ]]; then
    for tpl in "$SCRIPT_DIR"/agents/*.md; do
      [[ -e "$tpl" ]] || continue
      base="$(basename "$tpl")"
      if [[ ! -f "$AGENT_DIR/$base" ]]; then
        cp "$tpl" "$AGENT_DIR/$base"
      fi
    done
  fi
  chown -R "${A[INSTALL_USER]}:${A[INSTALL_USER]}" "$OPENCODE_CFG_DIR"
fi
ok "opencode config + API key in place."

if [[ $DRY_RUN -eq 0 ]]; then
  cat > "$ENV_BOT" <<EOF
# Mav — bot configuration (generated by install.sh)
MAV_INSTALL_USER=${A[INSTALL_USER]}
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
# Mav — dashboard configuration (generated by install.sh)
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
MAV_INSTALL_USER=${A[INSTALL_USER]}
MAV_SERVER_UNIT=$SERVER_UNIT
MAV_VAPID_SUB=mailto:${A[VAPID_EMAIL]:-admin@localhost}
PG_DSN=$PG_DSN
EOF
  chmod 600 "$ENV_DASH"
fi
ok "written to $ENV_BOT and $ENV_DASH."

# ------------------------------------------------------------------ 9. systemd
step "systemd services"
tpl() { sed -e "s|__USER__|${A[INSTALL_USER]}|g" \
            -e "s|__HOME__|${A[INSTALL_HOME]}|g" \
            -e "s|__BOT_DIR__|$BOT_DIR|g" \
            -e "s|__DASH_DIR__|$DASH_DIR|g" \
            -e "s|__DASH_USER__|root|g" \
            -e "s|__PORT__|${OPENCODE_PORT:-4096}|g" \
            -e "s|__OPENCODE_BIN__|${OPENCODE_BIN:-$A[INSTALL_HOME]/.opencode/bin/opencode}|g" \
            -e "s|__RUN_OPENCODE__|${A[INSTALL_HOME]}/.mav/run-opencode.sh|g" \
            -e "s|__ENV_BOT__|$ENV_BOT|g" \
            -e "s|__ENV_DASH__|$ENV_DASH|g" \
            -e "s|__ENV_SERVER__|$ENV_SERVER|g" \
            -e "s|__SERVER_UNIT__|$SERVER_UNIT|g" "$1"; }

if [[ $DRY_RUN -eq 0 ]]; then
  tpl "$SCRIPT_DIR/systemd/opencode-server.service.tpl" > "/etc/systemd/system/$SERVER_UNIT.service"
  tpl "$SCRIPT_DIR/systemd/opencode-bot.service.tpl"    > "/etc/systemd/system/$BOT_UNIT.service"
  tpl "$SCRIPT_DIR/systemd/mav-dashboard.service.tpl"   > "/etc/systemd/system/$DASH_UNIT.service"
fi
run systemctl daemon-reload
run systemctl enable "$SERVER_UNIT" "$BOT_UNIT" "$DASH_UNIT" >/dev/null 2>&1
ok "Units installed."

# ------------------------------------------------------------------ 10. start
step "Starting"
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
step "Verification"
if [[ $DRY_RUN -eq 0 ]]; then
  if curl -fsS --max-time 5 "http://127.0.0.1:${OPENCODE_PORT}/global/health" >/dev/null 2>&1; then
    ok "opencode engine responds."
  else
    warn "opencode engine not responding yet (slow start?)."
  fi
  SCHEME=http; [[ -n "${A[MAV_TLS_PORT]}" ]] && SCHEME=https
  URL="$SCHEME://127.0.0.1:${A[MAV_TLS_PORT]:-${A[MAV_API_PORT]}}/api/status"
  if curl -fsSk --max-time 5 "$URL" >/dev/null 2>&1; then
    ok "Dashboard responds at $URL"
  else
    warn "Dashboard not responding yet ($URL)."
  fi
fi

# ------------------------------------------------------------------ fin
cat <<EOF

${B}${GRN}  Installation complete.${R}

  ${B}Dashboard${R}     https://${A[MAV_API_BIND]}/         (over VPN if on a private network)
  ${B}Telegram${R}      send /start to your bot
  ${B}Config bot${R}    $ENV_BOT
  ${B}Config dash${R}   $ENV_DASH
  ${B}Logs${R}          journalctl -u $BOT_UNIT -f   |   journalctl -u $DASH_UNIT -f
  ${B}Status${R}          systemctl status $BOT_UNIT $DASH_UNIT

  ${DIM}Next steps:${R}
  - Configure your opencode agent (model, MCP, agents) in ~/.config/opencode/
  - Install the certificate ${CERT_DIR}/ca.cer on your phone (Android)
  - Subscribe to Web Push from the dashboard (bell button)

EOF
