#!/usr/bin/env bash
# Mav — container entrypoint. One image, one role per container:
#
#   engine   the opencode agent engine (restarted when the web app asks)
#   worker   routines, watching, memory, notifications (restarted with it)
#   web      the web app and its API (applies the database schema first)
#
# Everything Mav keeps lives in /data (one volume shared by the three):
#   /data/home      the engine's $HOME: ~/.config/opencode (model, helpers,
#                   connections) and ~/workspace (with mav-files/)
#   /data/bot       routines, auth, usage, media, push keys
#   /data/config    server.env (API keys) and mav.env (model), 0600
#   /data/run       restart requests and start times
set -euo pipefail

role="${1:-web}"
shift || true

DATA="${MAV_DATA:-/data}"
APP="${MAV_APP:-/app}"
RUN_UID="${MAV_UID:-1000}"
RUN_GID="${MAV_GID:-1000}"

export HOME="$DATA/home" MAV_USER_HOME="$DATA/home"
export BOT_DIR="$DATA/bot"
export MAV_ENV_SERVER="$DATA/config/server.env"
export MAV_ENV_BOT="$DATA/config/mav.env" MAV_ENV_DASH="$DATA/config/mav.env"
export MAV_RUNTIME=docker
export MAV_RESTART_FLAG="$DATA/run/engine.restart"
export MAV_ENGINE_STARTED="$DATA/run/engine.started"
export MAV_FILES="$HOME/workspace/mav-files"
CONF_DIR="$HOME/.config/opencode"

log() { printf '[mav %s] %s\n' "$role" "$*"; }

# --------------------------------------------------------------- as root
# Create the layout once, owned by the unprivileged user, then drop to it.
if [[ "$(id -u)" == 0 ]]; then
  mkdir -p "$CONF_DIR/agent" "$MAV_FILES" "$BOT_DIR" "$DATA/config" "$DATA/run"
  # Created once: touching them on every start would look like a key change
  # ("restart needed") to the web app.
  for f in "$MAV_ENV_SERVER" "$MAV_ENV_BOT"; do [[ -f "$f" ]] || install -m 600 /dev/null "$f"; done
  chown -R "$RUN_UID:$RUN_GID" "$DATA" 2>/dev/null || chown -R "$RUN_UID:$RUN_GID" "$HOME" "$BOT_DIR" "$DATA/config" "$DATA/run"
  exec setpriv --reuid="$RUN_UID" --regid="$RUN_GID" --init-groups "$0" "$role" "$@"
fi

# Read KEY=value files without executing them (values may hold any character).
load_env() {
  local f line
  for f in "$MAV_ENV_BOT" "$MAV_ENV_SERVER"; do
    [[ -f "$f" ]] || continue
    while IFS= read -r line || [[ -n "$line" ]]; do
      [[ "$line" =~ ^[A-Za-z_][A-Za-z0-9_]*= ]] || continue
      export "${line%%=*}=${line#*=}"
    done <"$f"
  done
}

# Everyday helpers: added when missing, updated when the copy is one we
# shipped (never edited), left alone when customised. Same rule as install.sh.
install_helpers() {
  local tpl dest sum
  for tpl in "$APP"/agents/*.md; do
    [[ -e "$tpl" ]] || continue
    dest="$CONF_DIR/agent/$(basename "$tpl")"
    if [[ ! -f "$dest" ]]; then
      cp "$tpl" "$dest"
    elif ! cmp -s "$tpl" "$dest"; then
      sum="$(sha256sum <"$dest" | cut -d' ' -f1)"
      if grep -qx "$sum  $(basename "$tpl")" "$APP/agents/shipped.sha256" 2>/dev/null; then
        cp "$tpl" "$dest"
      fi
    fi
  done
}

# A model given in .env (MAV_PROVIDER + MAV_MODEL) is applied once, on the
# first start; afterwards the web app (Settings → Model) is the place.
seed_provider() {
  [[ -n "${MAV_PROVIDER:-}" && -n "${MAV_MODEL:-}" ]] || return 0
  if [[ -f "$CONF_DIR/opencode.json" ]] && grep -q '"model"' "$CONF_DIR/opencode.json"; then
    return 0
  fi
  log "configuring the model from .env: $MAV_PROVIDER/$MAV_MODEL"
  python3 "$APP/dashboard/server/mav_provider.py" apply \
    --config-dir "$CONF_DIR" --env-server "$MAV_ENV_SERVER" --env-file "$MAV_ENV_BOT" \
    --provider "$MAV_PROVIDER" --model "$MAV_MODEL" --base-url "${MAV_BASE_URL:-}" \
    || log "could not apply the model from .env — set it in the web app"
}

ensure_schema() {
  python3 - "$APP/scripts/schema.sql" <<'PY'
import os, sys, time
import psycopg2
dsn = os.environ.get("PG_DSN", "")
sql = open(sys.argv[1], encoding="utf-8").read()
for attempt in range(60):
    try:
        conn = psycopg2.connect(dsn, connect_timeout=3)
        break
    except Exception as exc:  # noqa: BLE001
        if attempt == 59:
            print(f"[mav web] database unreachable: {exc}", file=sys.stderr)
            sys.exit(0)  # start anyway: memory is off until it is back
        time.sleep(2)
with conn, conn.cursor() as cur:
    cur.execute(sql)
conn.close()
print("[mav web] database schema ready")
PY
}

# Run "$@", restart it when the web app asks (the flag file changes) or when
# it exits; re-read the env files on every start (new model, new keys).
child=0
stop() { [[ "$child" != 0 ]] && kill "$child" 2>/dev/null; wait "$child" 2>/dev/null; exit 0; }
trap stop TERM INT
supervise() {
  local seen now
  while true; do
    load_env
    "$@" &
    child=$!
    date +%s >"$DATA/run/$role.started"
    [[ "$role" == engine ]] && date +%s >"$MAV_ENGINE_STARTED"
    seen="$(stat -c %Y "$MAV_RESTART_FLAG" 2>/dev/null || echo 0)"
    while kill -0 "$child" 2>/dev/null; do
      sleep 2 &
      wait $! || true
      now="$(stat -c %Y "$MAV_RESTART_FLAG" 2>/dev/null || echo 0)"
      if [[ "$now" != "$seen" ]]; then
        log "restart requested"
        kill "$child" 2>/dev/null || true
        break
      fi
    done
    wait "$child" 2>/dev/null || true
    child=0
    sleep 1
  done
}

case "$role" in
  engine)
    install_helpers
    seed_provider
    cd "$HOME/workspace"
    export MAV_OPENCODE_HOST=0.0.0.0 MAV_OPENCODE_PORT="${MAV_OPENCODE_PORT:-4096}"
    log "starting the engine on :$MAV_OPENCODE_PORT"
    supervise "$APP/run-opencode.sh"
    ;;
  worker)
    cd "$APP/bot"
    log "starting the worker"
    supervise python3 mav_worker.py
    ;;
  web)
    ensure_schema
    load_env
    cd "$APP/dashboard/server"
    export MAV_STATIC="$APP/dashboard" MAV_API_BIND=0.0.0.0 MAV_API_PORT="${MAV_API_PORT:-8787}"
    log "web app on :$MAV_API_PORT"
    exec python3 mav_api.py
    ;;
  *)
    exec "$role" "$@"
    ;;
esac
