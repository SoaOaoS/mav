#!/usr/bin/env bash
# ============================================================================
#  Mav — installer
#
#  Your own everyday AI assistant: a web app (chat, routines, memory) backed by
#  the opencode agent engine, Postgres for memory, and your model of choice.
#
#  Usage:
#     sudo ./install.sh              install (or update / reconfigure)
#     sudo ./install.sh --update     update code and services, keep the config
#     sudo ./install.sh --yes        no questions (MAV_* variables, defaults)
#     sudo ./install.sh --dry-run    show what would happen, change nothing
#     sudo ./install.sh --uninstall  remove services, configs and container
#
#  Idempotent: safe to re-run. Details of every step go to the log file.
# ============================================================================
set -Eeuo pipefail

# Never stop silently: say where an unexpected error happened.
on_error() {
  local rc=$? line="$1" cmd="$2"
  printf "\n  \033[31m✗ Unexpected error (line %s): %s\033[0m\n" "$line" "$cmd" >&2
  printf "  Please report it with the log: %s\n" "${LOG:-/var/log/mav-install.log}" >&2
  exit "$rc"
}
trap 'on_error "$LINENO" "$BASH_COMMAND"' ERR

# ------------------------------------------------------------------ constants
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SELF="${BASH_SOURCE[0]}"

WORKER_UNIT="${MAV_WORKER_UNIT:-mav-worker}"
SERVER_UNIT="${MAV_SERVER_UNIT:-mav-server}"
DASH_UNIT="${MAV_DASH_UNIT:-mav-dashboard}"
LEGACY_BOT_UNIT="${MAV_BOT_UNIT:-mav-bot}"   # the former Telegram bridge
ENV_BOT="${MAV_ENV_BOT:-/etc/mav.env}"
ENV_DASH="${MAV_ENV_DASH:-/etc/mav-dashboard.env}"
ENV_SERVER="${MAV_ENV_SERVER:-/etc/mav-server.env}"
COMPOSE_FILE="${MAV_COMPOSE_FILE:-/etc/mav/docker-compose.yml}"
PG_VOLUME="${MAV_PG_VOLUME:-mav_pgdata}"
PG_CONTAINER="${MAV_PG_CONTAINER:-mav-postgres}"
OPENCODE_PORT="${MAV_OPENCODE_PORT:-4096}"
LOG="${MAV_INSTALL_LOG:-/var/log/mav-install.log}"
# Where `mav update` downloads new versions from, and which ones.
MAV_REPO="${MAV_REPO:-SoaOaoS/mav}"
MAV_CHANNEL="${MAV_CHANNEL:-release}"   # release (tags vX.Y.Z) or main
PROVIDER_PY="$SCRIPT_DIR/dashboard/server/mav_provider.py"

# The version being installed: given by get.sh / `mav update`, else from git
# (a clone), else whatever was installed before.
detect_version() {
  if [[ -n "${MAV_VERSION:-}" ]]; then echo "$MAV_VERSION"; return; fi
  if [[ -d "$SCRIPT_DIR/.git" ]] && command -v git >/dev/null 2>&1; then
    git -C "$SCRIPT_DIR" describe --tags --always --dirty 2>/dev/null && return
  fi
  if [[ -r /etc/mav/version ]]; then head -1 /etc/mav/version; return; fi
  echo "unknown"
}
VERSION="$(detect_version)"

ASSUME_YES=0
DRY_RUN=0
DO_UNINSTALL=0
DO_UPDATE=0
for arg in "$@"; do
  case "$arg" in
    -y|--yes) ASSUME_YES=1 ;;
    -u|--update) DO_UPDATE=1 ;;
    --dry-run) DRY_RUN=1 ;;
    --uninstall) DO_UNINSTALL=1 ;;
    -h|--help)
      sed -n '2,17p' "$SELF" | sed 's/^#  \{0,1\}//'
      exit 0 ;;
    *) echo "Unknown option: $arg (try --help)"; exit 2 ;;
  esac
done

# ------------------------------------------------------------------ output
if [[ -t 1 ]]; then
  B=$'\033[1m'; DIM=$'\033[2m'; R=$'\033[0m';
  RED=$'\033[31m'; GRN=$'\033[32m'; YEL=$'\033[33m'; CYA=$'\033[36m'; MAG=$'\033[35m'
else
  B=""; DIM=""; R=""; RED=""; GRN=""; YEL=""; CYA=""; MAG=""
fi
TTY=0
[[ -t 0 && -t 1 ]] && TTY=1

info()  { printf "  ${DIM}%s${R}\n" "$*"; }
ok()    { printf "  ${GRN}✓${R} %s\n" "$*"; }
warn()  { printf "  ${YEL}!${R} %s\n" "$*"; }
die()   { printf "\n  ${RED}✗ %s${R}\n" "$*" >&2; [[ -f "$LOG" ]] && printf "  ${DIM}Details: %s${R}\n" "$LOG" >&2; exit 1; }
title() { printf "\n${B}%s${R}\n" "$*"; }

STEP=0
STEPS=3
step() {
  STEP=$((STEP + 1))
  printf "\n${MAG}${B}[%d/%d]${R} ${B}%s${R}\n" "$STEP" "$STEPS" "$*"
}

# Run a command behind a spinner; its output goes to the log file.
#   task "Doing something" cmd args...      (fatal on failure)
#   TASK_SOFT=1 task "…" cmd …               (warn on failure)
task() {
  local label="$1"; shift
  if [[ $DRY_RUN -eq 1 ]]; then
    printf "  ${DIM}[dry-run] %s — %s${R}\n" "$label" "$*"
    return 0
  fi
  printf "\n=== %s — %s\n" "$(date '+%F %T')" "$label" >>"$LOG"
  "$@" >>"$LOG" 2>&1 &
  local pid=$! i=0
  local -a frames=("⠋" "⠙" "⠹" "⠸" "⠼" "⠴" "⠦" "⠧" "⠇" "⠏")
  if [[ -t 1 ]]; then
    while kill -0 "$pid" 2>/dev/null; do
      printf "\r  ${CYA}%s${R} %s " "${frames[i++ % 10]}" "$label"
      sleep 0.1
    done
  fi
  local rc=0
  wait "$pid" || rc=$?
  if [[ $rc -eq 0 ]]; then
    printf "\r\033[K  ${GRN}✓${R} %s\n" "$label"
  elif [[ "${TASK_SOFT:-0}" == 1 ]]; then
    printf "\r\033[K  ${YEL}!${R} %s ${DIM}(failed, continuing — see %s)${R}\n" "$label" "$LOG"
  else
    printf "\r\033[K  ${RED}✗${R} %s\n" "$label"
    tail -n 15 "$LOG" | sed 's/^/    /' >&2
    die "\"$label\" failed."
  fi
  return 0
}
run() {
  if [[ $DRY_RUN -eq 1 ]]; then printf "  ${DIM}[dry-run] %s${R}\n" "$*"; else "$@"; fi
}

# ------------------------------------------------------------------ prompts
# Arrow-key menu.  choose VAR "Question" "label|hint" "label|hint" …
# Sets VAR to the index of the picked option. Default: $DEFAULT_CHOICE (0).
choose() {
  local __var="$1" q="$2"; shift 2
  local opts=("$@") n=$# sel="${DEFAULT_CHOICE:-0}" i key rest
  if [[ $ASSUME_YES -eq 1 ]]; then printf -v "$__var" '%s' "$sel"; return; fi
  printf "${CYA}?${R} ${B}%s${R}\n" "$q"
  if [[ $TTY -eq 0 ]]; then
    for i in "${!opts[@]}"; do printf "   %d) %s\n" "$((i + 1))" "${opts[$i]%%|*}"; done
    read -rp "   Choice [$((sel + 1))]: " key || key=""
    [[ "$key" =~ ^[0-9]+$ && $key -ge 1 && $key -le $n ]] && sel=$((key - 1))
    printf -v "$__var" '%s' "$sel"; return
  fi
  printf "  ${DIM}↑/↓ to move, Enter to select${R}\n"
  tput civis 2>/dev/null || true
  local first=1
  while :; do
    [[ $first -eq 0 ]] && printf "\033[%dA" "$n"
    first=0
    for i in "${!opts[@]}"; do
      local label="${opts[$i]%%|*}" hint=""
      [[ "${opts[$i]}" == *"|"* ]] && hint="${opts[$i]#*|}"
      if [[ $i -eq $sel ]]; then
        printf "\033[K  ${CYA}❯ ${B}%s${R}" "$label"
      else
        printf "\033[K    %s" "$label"
      fi
      [[ -n "$hint" ]] && printf "  ${DIM}%s${R}" "$hint"
      printf "\n"
    done
    IFS= read -rsn1 key || key=""
    if [[ "$key" == $'\033' ]]; then
      read -rsn2 -t 0.05 rest || rest=""
      case "$rest" in
        "[A") sel=$(((sel - 1 + n) % n)) ;;
        "[B") sel=$(((sel + 1) % n)) ;;
      esac
    elif [[ "$key" == "k" ]]; then sel=$(((sel - 1 + n) % n))
    elif [[ "$key" == "j" ]]; then sel=$(((sel + 1) % n))
    elif [[ "$key" =~ ^[1-9]$ && $key -le $n ]]; then sel=$((key - 1))
    elif [[ -z "$key" ]]; then break
    fi
  done
  tput cnorm 2>/dev/null || true
  # Collapse the menu into a one-line answer.
  printf "\033[%dA\033[J" "$((n + 1))"
  printf "  ${GRN}✓${R} %s\n" "${opts[$sel]%%|*}"
  printf -v "$__var" '%s' "$sel"
}
trap '[[ -t 1 ]] && tput cnorm 2>/dev/null; true' EXIT

# ask VAR "Question" "default" [secret]
ask() {
  local __var="$1" q="$2" def="${3:-}" secret="${4:-}" val=""
  if [[ $ASSUME_YES -eq 1 ]]; then printf -v "$__var" '%s' "$def"; return; fi
  if [[ -n "$def" && "$secret" != "secret" ]]; then
    printf "${CYA}?${R} ${B}%s${R} ${DIM}(%s)${R} " "$q" "$def"
  else
    printf "${CYA}?${R} ${B}%s${R} " "$q"
  fi
  if [[ "$secret" == "secret" ]]; then
    read -rs val || val=""
    [[ -n "$val" ]] && printf "${DIM}%s${R}" "••••••••"
    echo
  else
    read -r val || val=""
  fi
  [[ -z "$val" ]] && val="$def"
  printf -v "$__var" '%s' "$val"
}
confirm() {  # confirm "Question" [Y|N]
  local q="$1" def="${2:-Y}" ans
  if [[ $ASSUME_YES -eq 1 ]]; then [[ "$def" == Y ]]; return; fi
  printf "${CYA}?${R} ${B}%s${R} ${DIM}[%s]${R} " "$q" "$([[ $def == Y ]] && echo "Y/n" || echo "y/N")"
  read -r ans || ans=""
  ans="${ans:-$def}"
  [[ "$ans" =~ ^[YyOo] ]]
}

gen_password() {
  openssl rand -base64 18 2>/dev/null | tr -d '/+=' | cut -c1-20 || tr -dc 'A-Za-z0-9' </dev/urandom | head -c 20
}

# Read one KEY=value from an env file (keeps spaces, strips quotes).
env_get() {
  local file="$1" key="$2" line
  [[ -f "$file" ]] || { echo ""; return; }
  line="$(grep -E "^${key}=" "$file" | tail -1 || true)"
  [[ -z "$line" ]] && { echo ""; return; }
  line="${line#*=}"; line="${line%$'\r'}"
  line="${line%\"}"; line="${line#\"}"; line="${line%\'}"; line="${line#\'}"
  echo "$line"
}

home_of() {
  local h
  h="$(getent passwd "$1" 2>/dev/null | cut -d: -f6 || true)"
  echo "${h:-/home/$1}"
}

# user:group for chown — the user's real primary group (on Arch it is often
# "users", not a group named after the user).
owner() {
  local u="${A[INSTALL_USER]}" g
  g="$(id -gn "$u" 2>/dev/null || true)"
  echo "$u:${g:-$u}"
}

# This machine's main IPv4 address (portable: no `hostname -I`, which is
# Debian-only and missing on Arch).
primary_ip() {
  local ip=""
  if command -v ip >/dev/null 2>&1; then
    ip="$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{for (i = 1; i < NF; i++) if ($i == "src") { print $(i + 1); exit }}' || true)"
    [[ -z "$ip" ]] && ip="$(ip -4 -o addr show scope global 2>/dev/null | awk '{split($4, a, "/"); print a[1]; exit}' || true)"
  fi
  # A "connected" UDP socket reveals the outgoing address; nothing is sent.
  [[ -z "$ip" ]] && ip="$(python3 -c 'import socket; s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.connect(("1.1.1.1", 53)); print(s.getsockname()[0])' 2>/dev/null || true)"
  [[ -z "$ip" ]] && ip="$( (hostname -I 2>/dev/null || true) | awk '{print $1}')"
  echo "${ip:-127.0.0.1}"
}

# Package manager: apt (Debian, Ubuntu…), pacman (Arch, Omarchy, Manjaro…)
# or dnf (Fedora…). Empty when none is supported.
detect_pkg() {
  local p
  for p in apt-get pacman dnf; do
    command -v "$p" >/dev/null 2>&1 && { echo "${p%-get}"; return; }
  done
  echo ""
}
PKG="${MAV_PKG:-$(detect_pkg)}"   # MAV_PKG: force one (tests)

banner() {
  printf "\n${B}${GRN}"
  cat <<'ASCII'
   __  __
  |  \/  | __ ___   __
  | |\/| |/ _` \ \ / /
  | |  | | (_| |\ V /
  |_|  |_|\__,_| \_/
ASCII
  printf "${R}  ${DIM}Your everyday AI assistant — on your machine, with your model.  %s${R}\n" "$VERSION"
}

# ------------------------------------------------------------------ config
declare -A A

detect_existing_install() {
  [[ -f "$ENV_DASH" || -f "$ENV_BOT" || -f "/etc/systemd/system/$DASH_UNIT.service" ]]
}

# Rebuild the answers from an existing install (update, or reconfigure while
# keeping what does not change — the Postgres password above all, since the
# database volume was initialised with it).
load_existing_config() {
  local dsn
  A[INSTALL_USER]="$(env_get "$ENV_DASH" MAV_INSTALL_USER)"
  : "${A[INSTALL_USER]:=$(env_get "$ENV_BOT" MAV_INSTALL_USER)}"
  : "${A[INSTALL_USER]:=${SUDO_USER:-mav}}"
  [[ "${A[INSTALL_USER]}" == "root" ]] && A[INSTALL_USER]="mav"
  A[INSTALL_HOME]="$(env_get "$ENV_DASH" MAV_USER_HOME)"
  : "${A[INSTALL_HOME]:=$(home_of "${A[INSTALL_USER]}")}"

  A[MODEL_REF]="$(env_get "$ENV_DASH" OPENCODE_MODEL)"
  : "${A[MODEL_REF]:=$(env_get "$ENV_BOT" OPENCODE_MODEL)}"
  A[AGENT]="$(env_get "$ENV_DASH" MAV_DASH_AGENT)"
  : "${A[AGENT]:=assistant}"

  # Owner id: memory and watch items are attached to it. Older installs used
  # the Telegram chat id: keep it so nothing is lost.
  A[OWNER_ID]="$(env_get "$ENV_DASH" MAV_CHAT_ID)"
  if [[ -z "${A[OWNER_ID]}" ]]; then
    A[OWNER_ID]="$(env_get "$ENV_BOT" ALLOWED_CHAT_IDS | tr ', ' '\n\n' | grep -E '^-?[0-9]+$' | head -1 || true)"
  fi
  : "${A[OWNER_ID]:=0}"

  dsn="$(env_get "$ENV_DASH" PG_DSN)"
  : "${dsn:=$(env_get "$ENV_BOT" PG_DSN)}"
  A[PG_USER]="$(sed -n 's/.*user=\([^ ]*\).*/\1/p' <<<"$dsn")"
  A[PG_PASSWORD]="$(sed -n 's/.*password=\([^ ]*\).*/\1/p' <<<"$dsn")"
  A[PG_DB]="$(sed -n 's/.*dbname=\([^ ]*\).*/\1/p' <<<"$dsn")"
  A[PG_PORT]="$(sed -n 's/.*port=\([^ ]*\).*/\1/p' <<<"$dsn")"

  A[BIND]="$(env_get "$ENV_DASH" MAV_API_BIND)"
  A[HTTP_PORT]="$(env_get "$ENV_DASH" MAV_API_PORT)"
  A[TLS_PORT]="$(env_get "$ENV_DASH" MAV_TLS_PORT)"
  A[EMAIL]="$(env_get "$ENV_DASH" MAV_VAPID_SUB)"
  A[EMAIL]="${A[EMAIL]#mailto:}"
  [[ "${A[EMAIL]}" == "admin@localhost" ]] && A[EMAIL]=""
  A[QUIET]="$(env_get "$ENV_BOT" NOTIFY_QUIET)"
  A[EXISTING]=1
}

# An install interrupted after Postgres was created has a compose file but no
# env files yet: reuse its credentials, the volume was initialised with them.
load_compose_credentials() {
  [[ -r "$COMPOSE_FILE" ]] || return 0
  local v
  v="$(sed -n 's/^ *POSTGRES_USER: *//p' "$COMPOSE_FILE" | head -1)"; [[ -n "$v" ]] && : "${A[PG_USER]:=$v}"
  v="$(sed -n 's/^ *POSTGRES_PASSWORD: *//p' "$COMPOSE_FILE" | head -1)"; [[ -n "$v" ]] && : "${A[PG_PASSWORD]:=$v}"
  v="$(sed -n 's/^ *POSTGRES_DB: *//p' "$COMPOSE_FILE" | head -1)"; [[ -n "$v" ]] && : "${A[PG_DB]:=$v}"
  v="$(sed -n 's/^ *- *"127\.0\.0\.1:\([0-9]*\):5432".*/\1/p' "$COMPOSE_FILE" | head -1)"; [[ -n "$v" ]] && : "${A[PG_PORT]:=$v}"
  return 0
}

defaults() {
  local u="${SUDO_USER:-$(logname 2>/dev/null || echo mav)}"
  [[ "$u" == "root" ]] && u="mav"
  : "${A[INSTALL_USER]:=${MAV_INSTALL_USER:-$u}}"
  : "${A[INSTALL_HOME]:=$(home_of "${A[INSTALL_USER]}")}"
  : "${A[AGENT]:=assistant}"
  : "${A[OWNER_ID]:=0}"
  : "${A[PG_USER]:=mav}"
  : "${A[PG_PASSWORD]:=$(gen_password)}"
  : "${A[PG_DB]:=mav}"
  : "${A[PG_PORT]:=${MAV_POSTGRES_PORT:-5432}}"
  : "${A[BIND]:=${MAV_API_BIND:-0.0.0.0}}"
  : "${A[HTTP_PORT]:=${MAV_API_PORT:-80}}"
  : "${A[TLS_PORT]:=${MAV_TLS_PORT-443}}"
  : "${A[QUIET]:=${MAV_NOTIFY_QUIET:-23-7}}"
  : "${A[EMAIL]:=${MAV_VAPID_EMAIL:-}}"
  return 0
}

# ------------------------------------------------------------------ provider
PROV_IDS=(anthropic openai ollama ollama-cloud-api openrouter custom later)
PROV_MENU=(
  "Anthropic|Claude models · API key from console.anthropic.com"
  "OpenAI|GPT models · API key from platform.openai.com"
  "Ollama (local)|models on this machine or your network · no key"
  "Ollama Cloud|hosted open models · API key from ollama.com"
  "OpenRouter|hundreds of models behind one key"
  "Another OpenAI-compatible API|LM Studio, vLLM, Groq, Mistral…"
  "Set it up later|from the dashboard: Settings → Model"
)
prov_base() {
  case "$1" in
    anthropic) echo "https://api.anthropic.com/v1" ;;
    openai) echo "https://api.openai.com/v1" ;;
    ollama) echo "http://localhost:11434/v1" ;;
    ollama-cloud-api) echo "https://ollama.com/v1" ;;
    openrouter) echo "https://openrouter.ai/api/v1" ;;
  esac
}

# The provider's recommended model (from mav_provider.py, the single source).
preset_model() {
  PYTHONPATH="$(dirname "$PROVIDER_PY")" python3 -c \
    "import sys, mav_provider as m; print(m.PRESETS.get(sys.argv[1], {}).get('model', ''))" "$1" 2>/dev/null || true
}

# Ask the provider for its models — also proves the key works.
list_models() {
  MAV_PROVIDER_APIKEY="${A[API_KEY]:-}" python3 "$PROVIDER_PY" models \
    --provider "${A[PROVIDER]}" --base-url "${A[BASE_URL]:-}" 2>&1
}

configure_provider() {
  local idx models rc pick
  local -a list

  if [[ $ASSUME_YES -eq 1 ]]; then
    A[PROVIDER]="${MAV_PROVIDER:-later}"
    A[API_KEY]="${MAV_PROVIDER_APIKEY:-}"
    A[BASE_URL]="${MAV_PROVIDER_BASEURL:-}"
    A[MODEL]="${MAV_OPENCODE_MODEL:-}"
    if [[ "${A[PROVIDER]}" != "later" && -z "${A[MODEL]}" ]]; then
      die "Set MAV_OPENCODE_MODEL with MAV_PROVIDER."
    fi
    return 0
  fi

  DEFAULT_CHOICE=0 choose idx "Which AI model provider do you want to use?" "${PROV_MENU[@]}"
  A[PROVIDER]="${PROV_IDS[$idx]}"
  if [[ "${A[PROVIDER]}" == "later" ]]; then
    info "You can connect a model anytime in the dashboard."
    return 0
  fi

  A[BASE_URL]="$(prov_base "${A[PROVIDER]}")"
  case "${A[PROVIDER]}" in
    ollama)
      ask A[BASE_URL] "Where does Ollama run?" "${A[BASE_URL]}" ;;
    custom)
      ask A[CUSTOM_ID] "Short name for this provider (e.g. groq)" "custom"
      while :; do
        ask A[BASE_URL] "API address (OpenAI-compatible, ends with /v1)" ""
        [[ "${A[BASE_URL]}" =~ ^https?:// ]] && break
        warn "Enter a URL starting with http:// or https://"
      done ;;
  esac

  while :; do
    case "${A[PROVIDER]}" in
      ollama|custom) ask A[API_KEY] "API key (Enter if none)" "" secret ;;
      *)
        A[API_KEY]=""
        while [[ -z "${A[API_KEY]}" ]]; do ask A[API_KEY] "Paste your API key" "" secret; done ;;
    esac

    printf "  ${CYA}⠿${R} Checking the connection…"
    rc=0
    models="$(list_models)" || rc=$?
    printf "\r\033[K"
    if [[ $rc -eq 0 ]]; then
      mapfile -t list < <(grep -v '^\s*$' <<<"$models")
      ok "Connected — ${#list[@]} model(s) available."
      break
    fi
    warn "${models:-Could not reach the provider.}"
    DEFAULT_CHOICE=0 choose pick "What now?" \
      "Try another key" \
      "Continue anyway|type the model name yourself" \
      "Set it up later|from the dashboard"
    case "$pick" in
      0) continue ;;
      1) list=(); break ;;
      2) A[PROVIDER]="later"; return ;;
    esac
  done

  # Pick the model from the provider's own list (top of it, plus "other").
  local preferred
  preferred="$(preset_model "${A[PROVIDER]}")"
  if [[ ${#list[@]} -gt 0 ]]; then
    local -a shown=()
    # The provider's recommended default first, then the rest.
    for m in "${list[@]}"; do [[ "$m" == "$preferred" ]] && shown+=("$m|recommended"); done
    for m in "${list[@]}"; do
      [[ "$m" == "$preferred" ]] && continue
      [[ ${#shown[@]} -ge 12 ]] && break
      shown+=("$m")
    done
    shown+=("Another model…|type its name")
    DEFAULT_CHOICE=0 choose pick "Which model?" "${shown[@]}"
    if [[ $pick -lt $((${#shown[@]} - 1)) ]]; then
      A[MODEL]="${shown[$pick]%%|*}"
      return
    fi
  fi
  while [[ -z "${A[MODEL]:-}" ]]; do ask A[MODEL] "Model name" "$preferred"; done
}

apply_provider() {
  [[ "${A[PROVIDER]:-later}" == "later" || -z "${A[MODEL]:-}" ]] && return 0
  local pid="${A[PROVIDER]}"
  [[ "$pid" == "custom" ]] && pid="${A[CUSTOM_ID]:-custom}"
  local -a args=(apply --config-dir "${A[INSTALL_HOME]}/.config/opencode" --env-server "$ENV_SERVER"
                 --env-file "$ENV_BOT" --env-file "$ENV_DASH" --provider "$pid" --model "${A[MODEL]}")
  [[ -n "${A[BASE_URL]:-}" && "$pid" != "anthropic" && "$pid" != "openai" ]] && args+=(--base-url "${A[BASE_URL]}")
  if [[ $DRY_RUN -eq 1 ]]; then info "[dry-run] provider $pid / ${A[MODEL]}"; return 0; fi
  local ref
  ref="$(MAV_PROVIDER_APIKEY="${A[API_KEY]:-}" python3 "$PROVIDER_PY" "${args[@]}" 2>>"$LOG")" ||
    die "Could not write the model configuration."
  A[MODEL_REF]="$ref"
  chown -R "$(owner)" "${A[INSTALL_HOME]}/.config/opencode" 2>/dev/null || true
  ok "Model set: $ref"
}

# ------------------------------------------------------------------ system
require_root() {
  if [[ $EUID -ne 0 ]]; then
    [[ $DRY_RUN -eq 1 ]] && { warn "dry-run without root: nothing will be changed."; return; }
    die "Run as root:  sudo $SELF"
  fi
}

pacman_install() {
  # Without a database sync first (no partial upgrade); if the local database
  # is too old to find the packages, do the full sync + upgrade Arch expects.
  pacman -S --needed --noconfirm "$@" || pacman -Syu --needed --noconfirm "$@"
}

install_prereqs() {
  case "$PKG" in
    apt)
      export DEBIAN_FRONTEND=noninteractive
      task "Updating package lists" apt-get update -qq
      task "Installing Python, git, curl, openssl" \
        apt-get install -y -qq python3 python3-venv python3-pip git curl openssl ca-certificates iproute2
      if ! command -v docker >/dev/null 2>&1; then
        task "Installing Docker" sh -c 'curl -fsSL https://get.docker.com | sh'
      fi
      ;;
    pacman)
      task "Installing Python, git, curl, openssl" \
        pacman_install python git curl openssl ca-certificates iproute2
      if ! command -v docker >/dev/null 2>&1 || ! docker compose version >/dev/null 2>&1; then
        task "Installing Docker" pacman_install docker docker-compose
      fi
      ;;
    dnf)
      task "Installing Python, git, curl, openssl" \
        dnf install -y -q python3 git curl openssl ca-certificates iproute
      if ! command -v docker >/dev/null 2>&1; then
        task "Installing Docker" sh -c 'curl -fsSL https://get.docker.com | sh'
      fi
      ;;
  esac
  task "Starting Docker" systemctl enable --now docker
  if ! docker compose version >/dev/null 2>&1; then
    case "$PKG" in
      apt) TASK_SOFT=1 task "Installing the docker compose plugin" apt-get install -y -qq docker-compose-plugin ;;
      dnf) TASK_SOFT=1 task "Installing the docker compose plugin" dnf install -y -q docker-compose-plugin ;;
    esac
  fi
}

resolve_opencode_bin() {
  local home="$1" user="$2" p
  [[ -x "$home/.opencode/bin/opencode" ]] && { echo "$home/.opencode/bin/opencode"; return; }
  p="$(su - "$user" -c 'command -v opencode' 2>/dev/null | tail -1 | tr -d '\r' || true)"
  [[ -n "$p" && -x "$p" ]] && { echo "$p"; return; }
  p="$(command -v opencode 2>/dev/null || true)"
  [[ -n "$p" && -x "$p" ]] && { echo "$p"; return; }
  for p in /usr/local/bin/opencode /usr/bin/opencode; do
    [[ -x "$p" ]] && { echo "$p"; return; }
  done
  echo ""
}

install_engine() {
  local home="$1" user="$2" bin
  bin="$(resolve_opencode_bin "$home" "$user")"
  if [[ -n "$bin" ]]; then
    ok "Agent engine already installed ($("$bin" --version 2>/dev/null || echo '?'))"
    return
  fi
  TASK_SOFT=1 task "Installing the agent engine (opencode)" \
    su - "$user" -c 'curl -fsSL https://opencode.ai/install | bash'
  [[ $DRY_RUN -eq 1 ]] && return
  bin="$(resolve_opencode_bin "$home" "$user")"
  if [[ -z "$bin" ]]; then
    warn "opencode not found — install it with: curl -fsSL https://opencode.ai/install | bash"
  fi
  return 0
}

pg_up() {
  if docker compose version >/dev/null 2>&1; then
    docker compose -f "$COMPOSE_FILE" up -d
  else
    docker rm -f "$PG_CONTAINER" >/dev/null 2>&1 || true
    docker run -d --name "$PG_CONTAINER" --restart unless-stopped \
      -e POSTGRES_USER="${A[PG_USER]}" -e POSTGRES_PASSWORD="${A[PG_PASSWORD]}" -e POSTGRES_DB="${A[PG_DB]}" \
      -p "127.0.0.1:${A[PG_PORT]}:5432" -v "${PG_VOLUME}:/var/lib/postgresql/data" postgres:16-alpine
  fi
}
# Wait for Postgres, then make the database match the configuration.
#
# On a brand-new volume the image first runs a temporary, socket-only server
# to initialise the data directory: `pg_isready` on the socket already says
# yes while the database does not exist yet (v1.0.1 failed there). Only the
# final server listens on TCP, so readiness is checked over TCP.
pg_ready() {
  docker exec "$PG_CONTAINER" pg_isready -q -h 127.0.0.1 -U "${A[PG_USER]}" >/dev/null 2>&1
}
pg_local() {  # psql inside the container, over the local socket (trusted)
  docker exec -i "$PG_CONTAINER" psql -X -q -v ON_ERROR_STOP=1 -U "${A[PG_USER]}" "$@"
}
pg_wait_and_schema() {
  local i
  for i in $(seq 1 120); do
    pg_ready && break
    if [[ "$(docker inspect -f '{{.State.Running}}' "$PG_CONTAINER" 2>/dev/null)" != "true" && $i -gt 10 ]]; then
      docker logs --tail 30 "$PG_CONTAINER" 2>&1 || true
      echo "The Postgres container stopped (logs above)." >&2
      return 1
    fi
    sleep 1
  done
  if ! pg_ready; then
    docker logs --tail 30 "$PG_CONTAINER" 2>&1 || true
    echo "Postgres did not become ready within 2 minutes (logs above)." >&2
    return 1
  fi
  # The database exists (a volume initialised with another name, or an
  # interrupted first start)…
  pg_local -d postgres -v db="${A[PG_DB]}" <<'SQL'
SELECT format('CREATE DATABASE %I', :'db')
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = :'db')\gexec
SQL
  # …the password is the configured one (the volume keeps the password it was
  # first created with, whatever the compose file says later)…
  pg_local -d postgres -v role="${A[PG_USER]}" -v pw="${A[PG_PASSWORD]}" <<'SQL'
ALTER ROLE :"role" WITH PASSWORD :'pw';
SQL
  # …the schema is up to date…
  pg_local -d "${A[PG_DB]}" <"$SCRIPT_DIR/scripts/schema.sql"
  # …and the services will be able to log in, exactly as they will.
  docker exec -e PGPASSWORD="${A[PG_PASSWORD]}" "$PG_CONTAINER" \
    psql -X -h 127.0.0.1 -U "${A[PG_USER]}" -d "${A[PG_DB]}" -tAc 'SELECT 1' >/dev/null
}

make_vapid() {
  "$BOT_DIR/venv/bin/python" - "$BOT_DIR" <<'PY'
import base64, pathlib, sys
from cryptography.hazmat.primitives import serialization
from py_vapid import Vapid01
d = pathlib.Path(sys.argv[1])
v = Vapid01(); v.generate_keys()
pem = v.private_key.private_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PrivateFormat.PKCS8,
    encryption_algorithm=serialization.NoEncryption()).decode()
raw = v.public_key.public_bytes(
    encoding=serialization.Encoding.X962,
    format=serialization.PublicFormat.UncompressedPoint)
(d / "vapid_private.pem").write_text(pem)
(d / "vapid_private.pem").chmod(0o600)
(d / "vapid_public.txt").write_text(base64.urlsafe_b64encode(raw).decode().rstrip("="))
PY
}

uninstall() {
  title "Uninstalling Mav"
  local u
  for u in "$SERVER_UNIT" "$WORKER_UNIT" "$DASH_UNIT" "$LEGACY_BOT_UNIT"; do
    run systemctl disable --now "$u" >/dev/null 2>&1 || true
    run rm -f "/etc/systemd/system/$u.service"
  done
  run rm -f "$ENV_BOT" "$ENV_DASH" "$ENV_SERVER" /usr/local/bin/mav
  if [[ -f "$COMPOSE_FILE" ]]; then
    run docker compose -f "$COMPOSE_FILE" down >/dev/null 2>&1 || true
  fi
  run systemctl daemon-reload
  ok "Services, configuration and container removed."
  local vol
  vol="$(docker volume ls -q 2>/dev/null | grep -E "^(mav_)?${PG_VOLUME}\$" | head -1 || true)"
  info "Your data is kept: the install folders and the Postgres volume (${vol:-$PG_VOLUME})."
  info "To erase everything:  docker volume rm ${vol:-$PG_VOLUME}"
  exit 0
}

# ============================================================================
#                                   MAIN
# ============================================================================
banner
require_root
if [[ $DRY_RUN -eq 0 ]]; then
  mkdir -p "$(dirname "$LOG")"; : >>"$LOG"; chmod 600 "$LOG"
else
  LOG=/dev/null
fi
[[ $DO_UNINSTALL -eq 1 ]] && uninstall

if [[ -f /etc/os-release ]]; then
  # Read the distro identifiers in a subshell: sourcing /etc/os-release into
  # this shell defines VERSION (e.g. "13 (trixie)"), which would clobber Mav's
  # own $VERSION. That wrong value then gets written to /etc/mav/version and
  # breaks `mav version` and the update check.
  # shellcheck disable=SC1091
  os_id="$(. /etc/os-release; printf '%s' "${ID:-}")"
  os_id_like="$(. /etc/os-release; printf '%s' "${ID_LIKE:-}")"
  os_pretty="$(. /etc/os-release; printf '%s' "${PRETTY_NAME:-unknown}")"
  case " ${os_id} ${os_id_like} " in
    *" debian "*|*" ubuntu "*|*" raspbian "*|*" arch "*|*" fedora "*) ;;
    *) warn "Untested system (${os_pretty}) — continuing anyway." ;;
  esac
fi
if [[ -z "$PKG" && $DRY_RUN -eq 0 ]]; then
  die "No supported package manager found (apt, pacman or dnf). Mav supports Debian/Ubuntu, Arch and Fedora."
fi
command -v systemctl >/dev/null 2>&1 || [[ $DRY_RUN -eq 1 ]] ||
  die "Mav needs systemd (systemctl not found)."

MODE="install"
if detect_existing_install; then
  load_existing_config
  if [[ $DO_UPDATE -eq 1 || $ASSUME_YES -eq 1 ]]; then
    MODE="update"
  else
    printf "\n  ${B}Mav is already installed${R} ${DIM}(model: %s)${R}\n\n" "${A[MODEL_REF]:-not set}"
    DEFAULT_CHOICE=0 choose pick "What do you want to do?" \
      "Update|new version, keep everything as it is" \
      "Change the model|provider, key or model" \
      "Reconfigure|answer the setup questions again" \
      "Uninstall|remove the services (your data is kept)"
    case "$pick" in
      0) MODE="update" ;;
      1) MODE="model" ;;
      2) MODE="install" ;;
      3) uninstall ;;
    esac
  fi
elif [[ $DO_UPDATE -eq 1 ]]; then
  die "No existing install found. Run without --update to install Mav."
fi
load_compose_credentials
defaults

# ------------------------------------------------------------------ questions
if [[ "$MODE" == "model" ]]; then
  STEPS=2
  step "Model"
  configure_provider
  apply_provider
  step "Applying"
  task "Restarting the assistant" systemctl restart "$SERVER_UNIT" "$WORKER_UNIT" "$DASH_UNIT"
  printf "\n  ${GRN}${B}Done.${R} Open the dashboard and say hello.\n\n"
  exit 0
fi

if [[ "$MODE" == "install" ]]; then
  STEPS=3
  step "Your model"
  configure_provider

  step "Notifications"
  info "Optional. Push notifications use it as a contact address (required by the"
  info "Web Push standard); nothing is ever sent to it by Mav."
  ask A[EMAIL] "Contact email (Enter to skip)" "${A[EMAIL]}"

  if [[ $ASSUME_YES -eq 0 ]] && confirm "Change advanced settings (user, ports, quiet hours)?" N; then
    ask A[INSTALL_USER] "System user that runs Mav" "${A[INSTALL_USER]}"
    [[ "${A[INSTALL_USER]}" == "root" ]] && die "Choose a non-root user."
    A[INSTALL_HOME]="$(home_of "${A[INSTALL_USER]}")"
    ask A[BIND] "Dashboard address to listen on" "${A[BIND]}"
    ask A[HTTP_PORT] "HTTP port" "${A[HTTP_PORT]}"
    ask A[TLS_PORT] "HTTPS port (empty = no HTTPS)" "${A[TLS_PORT]}"
    ask A[QUIET] "Quiet hours, no notifications (e.g. 23-7, 0-0 = never)" "${A[QUIET]}"
    ask A[PG_PORT] "Postgres port (local only)" "${A[PG_PORT]}"
  fi
else
  STEPS=1
fi

BOT_DIR="${A[INSTALL_HOME]}/bot"
DASH_DIR="${A[INSTALL_HOME]}/workspace/mav-dashboard"
CERT_DIR="$DASH_DIR/certs"
PG_DSN="host=127.0.0.1 port=${A[PG_PORT]} user=${A[PG_USER]} password=${A[PG_PASSWORD]} dbname=${A[PG_DB]}"
URL_SCHEME="http"; URL_PORT="${A[HTTP_PORT]}"
if [[ -n "${A[TLS_PORT]}" ]]; then URL_SCHEME="https"; URL_PORT="${A[TLS_PORT]}"; fi
HOST_SHOWN="${A[BIND]}"
if [[ "$HOST_SHOWN" == "0.0.0.0" ]]; then
  HOST_SHOWN="$(primary_ip)"
fi
DASH_URL="$URL_SCHEME://$HOST_SHOWN"
[[ "$URL_PORT" != "80" && "$URL_PORT" != "443" ]] && DASH_URL="$DASH_URL:$URL_PORT"

if [[ "$MODE" == "install" && $ASSUME_YES -eq 0 ]]; then
  printf "\n  ${B}Ready to install${R}\n"
  printf "  ${DIM}Model${R}       %s\n" "$([[ "${A[PROVIDER]:-later}" == later ]] && echo "set up later in the dashboard" || echo "${A[PROVIDER]} / ${A[MODEL]}")"
  printf "  ${DIM}Dashboard${R}   %s\n" "$DASH_URL"
  printf "  ${DIM}User${R}        %s\n" "${A[INSTALL_USER]}"
  confirm "Install now?" Y || die "Cancelled — nothing was changed."
fi

# ------------------------------------------------------------------ install
step "$([[ $MODE == update ]] && echo "Updating Mav" || echo "Installing")"
info "Details go to $LOG"
install_prereqs

if ! id "${A[INSTALL_USER]}" >/dev/null 2>&1; then
  task "Creating user ${A[INSTALL_USER]}" useradd -m -s /bin/bash "${A[INSTALL_USER]}"
fi
if [[ $DRY_RUN -eq 0 && -d "${A[INSTALL_HOME]}" ]]; then
  chown "$(owner)" "${A[INSTALL_HOME]}"
fi
TASK_SOFT=1 task "Giving ${A[INSTALL_USER]} access to Docker" usermod -aG docker "${A[INSTALL_USER]}"

install_engine "${A[INSTALL_HOME]}" "${A[INSTALL_USER]}"

# The shipped bot/jobs.json is an empty placeholder. Copying it over an
# existing file wiped every routine on update, so snapshot the user's routines
# before the copy and restore them after. (Kept as small helpers so the
# installer test can exercise them without touching the machine.)
snapshot_file() { [[ -f "$1" ]] && cat "$1" || true; }
restore_file() { [[ -n "$2" ]] && printf '%s' "$2" >"$1" || true; }

copy_files() {
  mkdir -p "$BOT_DIR" "$DASH_DIR" "$(dirname "$COMPOSE_FILE")"
  # Never overwrite the user's routines: the shipped bot/jobs.json is an empty
  # placeholder, so copying it over an existing file would wipe every routine.
  # (The dashboard's data/jobs.json is a mirror and gets refreshed afterwards.)
  local keep_jobs keep_jobs_state
  keep_jobs="$(snapshot_file "$BOT_DIR/jobs.json")"
  keep_jobs_state="$(snapshot_file "$BOT_DIR/jobs_state.json")"
  cp -a "$SCRIPT_DIR/bot/." "$BOT_DIR/"
  cp -a "$SCRIPT_DIR/dashboard/." "$DASH_DIR/"
  restore_file "$BOT_DIR/jobs.json" "$keep_jobs"
  restore_file "$BOT_DIR/jobs_state.json" "$keep_jobs_state"
  # Files from the former Telegram bridge.
  rm -f "$BOT_DIR/opencode_bot.py" "$BOT_DIR/ocformat.py" "$BOT_DIR/sessions.json"
  [[ -f "$BOT_DIR/jobs.json" ]] || echo "[]" >"$BOT_DIR/jobs.json"
  # Keep the dashboard's mirror in sync with the file the worker actually reads.
  if [[ -f "$BOT_DIR/jobs.json" ]]; then
    mkdir -p "$DASH_DIR/data"
    cp -f "$BOT_DIR/jobs.json" "$DASH_DIR/data/jobs.json"
  fi
  chown -R "$(owner)" "$BOT_DIR" "$DASH_DIR" "${A[INSTALL_HOME]}/workspace"

  # Persistent copy of the installer, for `mav update`.
  local src="${A[INSTALL_HOME]}/.mav"
  if [[ "$(cd "$SCRIPT_DIR" && pwd -P)" != "$(mkdir -p "$src" && cd "$src" && pwd -P)" ]]; then
    rm -rf "$src"; mkdir -p "$src"; cp -a "$SCRIPT_DIR/." "$src/"
  fi
  chown -R "$(owner)" "$src"

  # Everyday helper templates: added when missing, updated when the installed
  # copy is one we shipped (never edited), left alone when customised.
  local adir="${A[INSTALL_HOME]}/.config/opencode/agent" tpl dest sum
  mkdir -p "$adir"
  for tpl in "$SCRIPT_DIR"/agents/*.md; do
    [[ -e "$tpl" ]] || continue
    dest="$adir/$(basename "$tpl")"
    if [[ ! -f "$dest" ]]; then
      cp "$tpl" "$dest"
    elif ! cmp -s "$tpl" "$dest"; then
      sum="$(sha256sum <"$dest" | cut -d' ' -f1)"
      if grep -qx "$sum  $(basename "$tpl")" "$SCRIPT_DIR/agents/shipped.sha256" 2>/dev/null; then
        cp "$tpl" "$dest"
      fi
    fi
  done
  chown -R "$(owner)" "${A[INSTALL_HOME]}/.config"

  # The `mav` command, and what it needs to know about this install.
  install -m 755 "$SCRIPT_DIR/scripts/mav" /usr/local/bin/mav
  mkdir -p /etc/mav
  cat >/etc/mav/cli.env <<EOF
# Read by the mav command (generated by install.sh)
MAV_SRC=$src
MAV_REPO=$MAV_REPO
MAV_CHANNEL=$MAV_CHANNEL
MAV_SERVER_UNIT=$SERVER_UNIT
MAV_WORKER_UNIT=$WORKER_UNIT
MAV_DASH_UNIT=$DASH_UNIT
MAV_ENV_DASH=$ENV_DASH
MAV_ENV_BOT=$ENV_BOT
MAV_ENV_SERVER=$ENV_SERVER
MAV_PG_CONTAINER=$PG_CONTAINER
MAV_INSTALL_LOG=$LOG
MAV_OPENCODE_PORT=$OPENCODE_PORT
EOF
  echo "$VERSION" >/etc/mav/version
}
task "Copying Mav files" copy_files

task "Preparing the background worker" sh -c \
  "python3 -m venv '$BOT_DIR/venv' && '$BOT_DIR/venv/bin/pip' install -q --upgrade pip && '$BOT_DIR/venv/bin/pip' install -q -r '$BOT_DIR/requirements.txt'"
task "Preparing the web app" sh -c \
  "python3 -m venv '$DASH_DIR/server/venv' && '$DASH_DIR/server/venv/bin/pip' install -q --upgrade pip && '$DASH_DIR/server/venv/bin/pip' install -q psycopg2-binary pywebpush py-vapid cryptography"

write_compose() {
  cat >"$COMPOSE_FILE" <<EOF
services:
  postgres:
    image: postgres:16-alpine
    container_name: $PG_CONTAINER
    restart: unless-stopped
    environment:
      POSTGRES_USER: ${A[PG_USER]}
      POSTGRES_PASSWORD: ${A[PG_PASSWORD]}
      POSTGRES_DB: ${A[PG_DB]}
    ports:
      - "127.0.0.1:${A[PG_PORT]}:5432"
    volumes:
      - ${PG_VOLUME}:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${A[PG_USER]} -d ${A[PG_DB]}"]
      interval: 5s
      timeout: 5s
      retries: 12
volumes:
  ${PG_VOLUME}:
EOF
  chmod 600 "$COMPOSE_FILE"
}
[[ $DRY_RUN -eq 0 ]] && write_compose
task "Starting the memory database (Postgres)" pg_up
task "Preparing the database" pg_wait_and_schema

if [[ $DRY_RUN -eq 0 && -n "${A[TLS_PORT]}" && ! -f "$CERT_DIR/server.crt" ]]; then
  SAN_IP="${A[BIND]}"
  [[ "$SAN_IP" == "0.0.0.0" ]] && SAN_IP="$(primary_ip)"
  [[ "$SAN_IP" != "127.0.0.1" ]] && SAN_IP="$SAN_IP,127.0.0.1"
  SAN_DNS="$(uname -n 2>/dev/null || echo mav),$(uname -n 2>/dev/null || echo mav).local,mav.local"
  TASK_SOFT=1 task "Creating HTTPS certificates" \
    env MAV_SAN_IP="$SAN_IP" MAV_SAN_DNS="$SAN_DNS" bash "$DASH_DIR/tools/make_certs.sh"
fi
if [[ $DRY_RUN -eq 0 && ! -f "$BOT_DIR/vapid_private.pem" ]]; then
  task "Creating notification keys" make_vapid
  chown "$(owner)" "$BOT_DIR"/vapid_* 2>/dev/null || true
fi

write_env() {
  local model_ref="${A[MODEL_REF]:-}"
  cat >"$ENV_BOT" <<EOF
# Mav — background worker (generated by install.sh; edit, then: mav restart)
MAV_INSTALL_USER=${A[INSTALL_USER]}
BOT_DIR=$BOT_DIR
MAV_CHAT_ID=${A[OWNER_ID]}
OPENCODE_URL=http://127.0.0.1:${OPENCODE_PORT}
OPENCODE_MODEL=$model_ref
OPENCODE_AGENT=${A[AGENT]}
IDLE_TIMEOUT=1800
JOB_RETRIES=1
WATCH_INTERVAL=900
NOTIFY_QUIET=${A[QUIET]}
NOTIFY_DEDUP_WINDOW=21600
MAV_VAPID_SUB=mailto:${A[EMAIL]:-admin@localhost}
JOBS_FILE=$BOT_DIR/jobs.json
JOBS_STATE=$BOT_DIR/jobs_state.json
PUSH_FILE=$BOT_DIR/push_subs.json
PG_DSN=$PG_DSN
EOF
  cat >"$ENV_DASH" <<EOF
# Mav — web app (generated by install.sh; edit, then: mav restart)
MAV_STATIC=$DASH_DIR
BOT_DIR=$BOT_DIR
MAV_ATTACH=/tmp/mav-dashboard/attachments
OPENCODE_URL=http://127.0.0.1:${OPENCODE_PORT}
OPENCODE_MODEL=$model_ref
MAV_DASH_AGENT=${A[AGENT]}
MAV_CHAT_ID=${A[OWNER_ID]}
MAV_API_BIND=${A[BIND]}
MAV_API_PORT=${A[HTTP_PORT]}
MAV_TLS_PORT=${A[TLS_PORT]}
MAV_TLS_CERT=$CERT_DIR/server.crt
MAV_TLS_KEY=$CERT_DIR/server.key
MAV_PUSH_FILE=$BOT_DIR/push_subs.json
MAV_USER_HOME=${A[INSTALL_HOME]}
MAV_INSTALL_USER=${A[INSTALL_USER]}
MAV_SERVER_UNIT=$SERVER_UNIT
MAV_WORKER_UNIT=$WORKER_UNIT
MAV_ENV_SERVER=$ENV_SERVER
MAV_ENV_BOT=$ENV_BOT
MAV_ENV_DASH=$ENV_DASH
MAV_VERSION_FILE=/etc/mav/version
MAV_REPO=$MAV_REPO
MAV_VAPID_SUB=mailto:${A[EMAIL]:-admin@localhost}
PG_DSN=$PG_DSN
EOF
  # The engine env (API keys) is only ever edited by mav_provider.py.
  [[ -f "$ENV_SERVER" ]] || printf "# Mav — engine environment (API keys)\n" >"$ENV_SERVER"
  chmod 600 "$ENV_BOT" "$ENV_DASH" "$ENV_SERVER"
}
[[ $DRY_RUN -eq 0 ]] && task "Writing the configuration" write_env
apply_provider

write_units() {
  tpl() {
    sed -e "s|__USER__|${A[INSTALL_USER]}|g" \
        -e "s|__HOME__|${A[INSTALL_HOME]}|g" \
        -e "s|__BOT_DIR__|$BOT_DIR|g" \
        -e "s|__DASH_DIR__|$DASH_DIR|g" \
        -e "s|__DASH_USER__|root|g" \
        -e "s|__PORT__|$OPENCODE_PORT|g" \
        -e "s|__RUN_OPENCODE__|${A[INSTALL_HOME]}/.mav/run-opencode.sh|g" \
        -e "s|__ENV_BOT__|$ENV_BOT|g" \
        -e "s|__ENV_DASH__|$ENV_DASH|g" \
        -e "s|__ENV_SERVER__|$ENV_SERVER|g" \
        -e "s|__SERVER_UNIT__|$SERVER_UNIT|g" "$1"
  }
  mkdir -p "${A[INSTALL_HOME]}/workspace"
  tpl "$SCRIPT_DIR/systemd/opencode-server.service.tpl" >"/etc/systemd/system/$SERVER_UNIT.service"
  tpl "$SCRIPT_DIR/systemd/mav-worker.service.tpl" >"/etc/systemd/system/$WORKER_UNIT.service"
  tpl "$SCRIPT_DIR/systemd/mav-dashboard.service.tpl" >"/etc/systemd/system/$DASH_UNIT.service"
  # The former Telegram bridge is replaced by the worker.
  if [[ -f "/etc/systemd/system/$LEGACY_BOT_UNIT.service" ]]; then
    systemctl disable --now "$LEGACY_BOT_UNIT" >/dev/null 2>&1 || true
    rm -f "/etc/systemd/system/$LEGACY_BOT_UNIT.service"
  fi
  systemctl daemon-reload
  systemctl enable "$SERVER_UNIT" "$WORKER_UNIT" "$DASH_UNIT" >/dev/null 2>&1
}
[[ $DRY_RUN -eq 0 ]] && task "Installing the services" write_units

start_all() {
  systemctl restart "$SERVER_UNIT"
  local i
  for i in $(seq 1 30); do
    curl -fsS --max-time 2 "http://127.0.0.1:${OPENCODE_PORT}/global/health" >/dev/null 2>&1 && break
    sleep 1
  done
  systemctl restart "$WORKER_UNIT" "$DASH_UNIT"
  sleep 2
}
task "Starting Mav" start_all

# ------------------------------------------------------------------ check
if [[ $DRY_RUN -eq 0 ]]; then
  for u in "$SERVER_UNIT" "$WORKER_UNIT" "$DASH_UNIT"; do
    systemctl is-active --quiet "$u" || warn "$u is not running — see: journalctl -u $u -n 30"
  done
  curl -fsS --max-time 5 "http://127.0.0.1:${OPENCODE_PORT}/global/health" >/dev/null 2>&1 ||
    warn "The agent engine is still starting (or opencode is missing) — check: mav status"
fi

printf "\n  ${GRN}${B}Mav %s is ready.${R}\n\n" "$VERSION"
printf "  ${B}Open${R}  %s\n" "$DASH_URL"
if [[ ! -f "$BOT_DIR/auth.json" ]]; then
  printf "        ${DIM}and choose the password that protects it (first visit only).${R}\n"
fi
if [[ "${A[PROVIDER]:-}" == "later" || -z "${A[MODEL_REF]:-}" ]]; then
  printf "        ${DIM}then Settings → Model to connect your AI model.${R}\n"
fi
if [[ "$URL_SCHEME" == "https" ]]; then
  printf "\n  ${DIM}HTTPS uses a private certificate: to install the app and get notifications\n"
  printf "  on your phone, trust %s/certs/ca.cer on it first.${R}\n" "$DASH_URL"
fi
printf "\n  ${DIM}Manage it with:${R} mav status · mav doctor · mav update · mav help\n\n"
