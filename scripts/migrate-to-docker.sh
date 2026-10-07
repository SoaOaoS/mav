#!/usr/bin/env bash
# Mav — move an installer (systemd) install to Docker Compose, keeping
# everything: chats, memory, routines, helpers, connections, model, API keys,
# password and notification keys.
#
#   git clone https://github.com/SoaOaoS/mav.git && cd mav
#   sudo ./scripts/migrate-to-docker.sh
#
# What it does:
#   1. saves a backup of the memory database (pg_dump) to /var/backups/mav;
#   2. copies the engine config and chat history, your shared files, routines
#      and keys into the Docker data volume, rewriting host paths for Docker;
#   3. writes .env so the stack reuses the same Postgres volume (mav_pgdata)
#      with its current password: the memory database is not copied, it is
#      the same one;
#   4. stops and disables the systemd services, and starts the Docker stack.
#
# Nothing is deleted: the old install folders, units and /etc/mav*.env stay
# where they are, so you can go back (see the message at the end).
#
# Options: --yes (no question), --dry-run (stage the files, start nothing).
set -euo pipefail

ENV_DASH="${MAV_ENV_DASH:-/etc/mav-dashboard.env}"
ENV_BOT="${MAV_ENV_BOT:-/etc/mav.env}"
ENV_SERVER="${MAV_ENV_SERVER:-/etc/mav-server.env}"
CLI_ENV="${MAV_CLI_ENV:-/etc/mav/cli.env}"
OLD_COMPOSE="${MAV_COMPOSE_FILE:-/etc/mav/docker-compose.yml}"
BACKUP_DIR="${MAV_BACKUP_DIR:-/var/backups/mav}"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STAGE=""

YES=0
DRY=0
for a in "$@"; do
  case "$a" in
    -y|--yes) YES=1 ;;
    -n|--dry-run) DRY=1 ;;
    -h|--help) sed -n '2,23p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Unknown option: $a" >&2; exit 2 ;;
  esac
done

if [[ -t 1 ]]; then B=$'\e[1m'; G=$'\e[32m'; Y=$'\e[33m'; D=$'\e[2m'; R=$'\e[0m'; else B="" G="" Y="" D="" R=""; fi
say() { printf '%s\n' "$*"; }
step() { printf '\n%s→ %s%s\n' "$B" "$*" "$R"; }
ok() { printf '  %s✔%s %s\n' "$G" "$R" "$*"; }
warn() { printf '  %s!%s %s\n' "$Y" "$R" "$*"; }
die() { printf '\n%s✗ %s%s\n' "$Y" "$*" "$R" >&2; exit 1; }

# KEY=value files are read, never sourced (values can hold any character).
env_get() { [[ -r "$1" ]] && sed -n "s/^$2=//p" "$1" | tail -1 || true; }
dsn_get() { sed -n "s/.*\b$2=\([^ ]*\).*/\1/p" <<<"$1"; }

# ------------------------------------------------------------------ checks
[[ "$(id -u)" == 0 ]] || die "Run it as root: sudo $0"
[[ -f "$REPO/docker-compose.yml" ]] || die "Run it from a clone of the Mav repository (no docker-compose.yml in $REPO)."
[[ -f "$ENV_DASH" ]] || die "No installer install found here ($ENV_DASH is missing)."
if ! command -v docker >/dev/null || ! docker compose version >/dev/null 2>&1; then
  die "Docker with the compose plugin is needed: https://docs.docker.com/engine/install/"
fi

HOME_OLD="$(env_get "$ENV_DASH" MAV_USER_HOME)"
BOT_OLD="$(env_get "$ENV_DASH" BOT_DIR)"
DSN="$(env_get "$ENV_DASH" PG_DSN)"
[[ -n "$DSN" ]] || DSN="$(env_get "$ENV_BOT" PG_DSN)"
PG_USER="$(dsn_get "$DSN" user)"
PG_PASS="$(dsn_get "$DSN" password)"
PG_DB="$(dsn_get "$DSN" dbname)"
PORT="$(env_get "$ENV_DASH" MAV_API_PORT)"
PG_CONTAINER="$(env_get "$CLI_ENV" MAV_PG_CONTAINER)"; PG_CONTAINER="${PG_CONTAINER:-mav-postgres}"
UNITS=()
for k in MAV_SERVER_UNIT MAV_WORKER_UNIT MAV_DASH_UNIT; do
  u="$(env_get "$CLI_ENV" "$k")"
  [[ -n "$u" ]] || u="$(env_get "$ENV_DASH" "$k")"
  [[ -n "$u" ]] && UNITS+=("$u")
done
[[ ${#UNITS[@]} -gt 0 ]] || UNITS=(mav-server mav-worker mav-dashboard)

[[ -n "$HOME_OLD" && -d "$HOME_OLD" ]] || die "Cannot find the install's home folder (MAV_USER_HOME in $ENV_DASH)."
[[ "${PG_USER:-mav}" == mav && "${PG_DB:-mav}" == mav ]] ||
  die "The database user/name are $PG_USER/$PG_DB; the Docker stack expects mav/mav. Move it by hand: see docs.html#migrate."
[[ -n "$PG_PASS" ]] || die "No database password in $ENV_DASH (PG_DSN)."
case "$PG_PASS" in *[!A-Za-z0-9._~+-]*)
  die "The database password has characters .env cannot hold safely. Change it, or move by hand: see docs.html#migrate." ;;
esac

PG_VOLUME="$(docker inspect -f '{{range .Mounts}}{{if eq .Destination "/var/lib/postgresql/data"}}{{.Name}}{{end}}{{end}}' "$PG_CONTAINER" 2>/dev/null || true)"
[[ -z "$PG_VOLUME" || "$PG_VOLUME" == mav_pgdata ]] ||
  die "The memory database lives in volume '$PG_VOLUME', not mav_pgdata. Move it by hand: see docs.html#migrate."
if docker volume inspect mav_mav-data >/dev/null 2>&1; then
  die "A Docker install already has data here (volume mav_mav-data). Remove it first if it holds nothing you need: docker compose down && docker volume rm mav_mav-data"
fi

say ""
say "${B}Move Mav to Docker${R}"
say "  From   ${HOME_OLD} (systemd: ${UNITS[*]})"
say "  To     the Docker stack in ${REPO}, web app on port ${PORT:-8787}"
say "  Keeps  chats, memory, routines, helpers, connections, model, keys, password"
say "  ${D}Nothing is deleted; the old services are only stopped and disabled.${R}"
if [[ $DRY -eq 0 && $YES -eq 0 ]]; then
  read -r -p "Continue? [y/N] " r
  [[ "$r" =~ ^[YyOo] ]] || { say "Nothing changed."; exit 0; }
fi

# ------------------------------------------------------------------ 1. backup
step "Backing up the memory database"
mkdir -p "$BACKUP_DIR"
DUMP="$BACKUP_DIR/pre-docker-$(date +%Y%m%d-%H%M%S).sql.gz"
if docker exec "$PG_CONTAINER" pg_dump -U "$PG_USER" -d "$PG_DB" --no-owner 2>/dev/null | gzip >"$DUMP" && [[ -s "$DUMP" ]] && gzip -t "$DUMP"; then
  chmod 600 "$DUMP"
  ok "$DUMP"
else
  rm -f "$DUMP"
  [[ $YES -eq 1 || $DRY -eq 1 ]] && die "Could not back up the database (is $PG_CONTAINER running?)."
  warn "Could not back up the database (is $PG_CONTAINER running?)."
  read -r -p "Go on without a backup? [y/N] " r
  [[ "$r" =~ ^[YyOo] ]] || exit 1
fi

# ------------------------------------------------------------------ 2. stage
step "Collecting your files"
STAGE="$(mktemp -d /tmp/mav-migrate.XXXXXX)"
trap '[[ -n "$STAGE" && $DRY -eq 0 ]] && rm -rf "$STAGE"' EXIT
mkdir -p "$STAGE/home/.config" "$STAGE/home/.local/share" "$STAGE/home/workspace" "$STAGE/bot" "$STAGE/config"

copy_dir() {  # src dest label
  if [[ -d "$1" ]]; then cp -a "$1" "$2" && ok "$3"; else warn "$3: none found"; fi
}
copy_dir "$HOME_OLD/.config/opencode" "$STAGE/home/.config/opencode" "engine settings, helpers and connections"
copy_dir "$HOME_OLD/.local/share/opencode" "$STAGE/home/.local/share/opencode" "chat history"
copy_dir "$HOME_OLD/workspace/mav-files" "$STAGE/home/workspace/mav-files" "files Mav shared with you"

# The worker's data, without its code (the image brings its own).
if [[ -n "$BOT_OLD" && -d "$BOT_OLD" ]]; then
  tar -C "$BOT_OLD" --exclude='./venv' --exclude='*/__pycache__' --exclude='./__pycache__' \
    --exclude='*.py' --exclude='./requirements.txt' --exclude='./README.md' -cf - . | tar -C "$STAGE/bot" -xpf -
  ok "routines, password, usage, media and notification keys"
fi

# API keys as they are; other settings without host paths, ports or units.
[[ -f "$ENV_SERVER" ]] && install -m 600 "$ENV_SERVER" "$STAGE/config/server.env" && ok "API keys"
{
  echo "# Mav — moved from the installer install on $(date +%F)"
  declare -A seen=()
  for f in "$ENV_DASH" "$ENV_BOT"; do
    [[ -r "$f" ]] || continue
    while IFS= read -r line || [[ -n "$line" ]]; do
      [[ "$line" =~ ^([A-Za-z_][A-Za-z0-9_]*)=(.*)$ ]] || continue
      k="${BASH_REMATCH[1]}" v="${BASH_REMATCH[2]}"
      [[ -n "${seen[$k]:-}" ]] && continue
      case "$k" in
        BOT_DIR|PG_DSN|OPENCODE_URL|MAV_STATIC|MAV_ATTACH|MAV_API_BIND|MAV_API_PORT|MAV_TLS_*|MAV_PUSH_FILE|\
        MAV_USER_HOME|MAV_INSTALL_USER|MAV_*_UNIT|MAV_ENV_*|MAV_VERSION_FILE|MAV_REPO|JOBS_FILE|JOBS_STATE|PUSH_FILE) continue ;;
      esac
      [[ "$v" == /* ]] && continue
      seen[$k]=1
      printf '%s=%s\n' "$k" "$v"
    done <"$f"
  done
} >"$STAGE/config/mav.env"
chmod 600 "$STAGE/config/mav.env"
ok "model and notification settings"

# Host paths → container paths; services on this machine → host.docker.internal.
fix() {
  local f="$1"
  sed -i -e "s#${HOME_OLD%/}/#/data/home/#g" -e "s#${HOME_OLD%/}\"#/data/home\"#g" \
    -e 's#://\(127\.0\.0\.1\|localhost\|0\.0\.0\.0\)\([:/"]\)#://host.docker.internal\2#g' "$f"
}
for f in "$STAGE"/home/.config/opencode/*.json "$STAGE"/home/.config/opencode/*.jsonc "$STAGE/config/server.env" "$STAGE/config/mav.env"; do
  [[ -f "$f" ]] && fix "$f"
done
ok "paths rewritten for Docker (local services → host.docker.internal)"

if [[ $DRY -eq 1 ]]; then
  say ""
  say "Dry run: the files the Docker volume would receive are in $STAGE"
  find "$STAGE" -maxdepth 3 | sed "s#^$STAGE#  #" | sort
  exit 0
fi

# ------------------------------------------------------------------ 3. .env
step "Configuring the Docker stack"
cd "$REPO"
[[ -f .env ]] || cp .env.example .env
set_kv() {  # key value — replace or append in .env
  if grep -q "^$1=" .env; then sed -i "s#^$1=.*#$1=$2#" .env; else printf '%s=%s\n' "$1" "$2" >>.env; fi
}
set_kv POSTGRES_PASSWORD "$PG_PASS"
[[ -n "$PORT" ]] && set_kv MAV_PORT "$PORT"
chmod 600 .env
ok ".env: same database password${PORT:+, port $PORT}"

step "Getting the Mav image"
if docker compose pull -q 2>/dev/null; then ok "pulled"; else
  warn "no published image reachable, building it here (a few minutes)"
  docker compose build -q
fi

# ------------------------------------------------------------------ 4. switch
step "Stopping the systemd services"
for u in "${UNITS[@]}"; do
  if systemctl disable --now "$u" >/dev/null 2>&1; then ok "$u stopped and disabled"; else warn "$u was not running"; fi
done
# The old Postgres container belongs to a compose project also named "mav":
# take it down (its volume stays) and park its file so `mav uninstall` can
# never stop the new stack's database.
if [[ -f "$OLD_COMPOSE" ]]; then
  docker compose -f "$OLD_COMPOSE" down >/dev/null 2>&1 || true
  mv "$OLD_COMPOSE" "$OLD_COMPOSE.pre-docker"
  ok "old database container removed (data kept in mav_pgdata)"
fi
docker rm -f "$PG_CONTAINER" >/dev/null 2>&1 || true

step "Moving your files into the Docker volume"
tar -C "$STAGE" -cf - . | docker compose run --rm --no-deps -T --entrypoint tar web -xpf - -C /data
ok "done"

step "Starting Mav in Docker"
docker compose up -d --wait --wait-timeout 300
ok "running"

say ""
say "${G}${B}Mav now runs in Docker.${R} Open http://$(hostname -I 2>/dev/null | awk '{print $1}'):${PORT:-8787} and sign in with your usual password."
say ""
say "Good to know:"
say "  • Update with: docker compose pull && docker compose up -d   (in $REPO)"
say "  • The 'mav' command drives the old install; use docker compose instead."
say "  • Push notifications need HTTPS: put a reverse proxy (Caddy, Traefik, Tailscale serve)"
say "    in front of port ${PORT:-8787}, then allow notifications again on each device."
say "  • Backup of the database before the move: ${DUMP:-none}"
say ""
say "${D}To go back to the installer version:"
say "  cd $REPO && docker compose down"
say "  mv $OLD_COMPOSE.pre-docker $OLD_COMPOSE && docker compose -f $OLD_COMPOSE up -d"
say "  systemctl enable --now ${UNITS[*]}${R}"
