#!/usr/bin/env bash
# Integration test with a real postgres:16-alpine container (needs Docker;
# skipped otherwise). Uses the installer's own functions.
#
# Reproduces the v1.0.1 failure: on a brand-new volume the database is not
# created yet while the image's temporary init server already answers on the
# socket ("database mav does not exist").
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if ! docker info >/dev/null 2>&1; then
  echo "skip: Docker is not available"
  exit 0
fi
T="$(mktemp -d)"
ID="mavtest$$"
# Used by the installer functions loaded below.
# shellcheck disable=SC2034
PG_CONTAINER="$ID-postgres" PG_VOLUME="${ID}_pgdata" COMPOSE_FILE="$T/mav/docker-compose.yml" SCRIPT_DIR="$ROOT"
mkdir -p "$T/mav"
cleanup() {
  docker compose -f "$COMPOSE_FILE" down -v >/dev/null 2>&1 || true
  docker rm -f "$PG_CONTAINER" >/dev/null 2>&1 || true
  rm -rf "$T"
}
trap cleanup EXIT

declare -A A=([PG_USER]=mav [PG_PASSWORD]=first-Pass1 [PG_DB]=mav [PG_PORT]=55433)
# The installer's functions, as shipped.
eval "$(sed -n '/^pg_up() {/,/^}/p; /^pg_ready() {/,/^}/p; /^pg_local() {/,/^}/p; /^pg_wait_and_schema() {/,/^}/p; /^write_compose() {/,/^}/p; /^load_compose_credentials() {/,/^}/p' "$ROOT/install.sh")"

fail=0
step() {  # step "name" command…
  local name="$1"; shift
  if "$@" >"$T/out" 2>&1; then echo "ok   $name"
  else echo "FAIL $name"; sed 's/^/     /' "$T/out" | tail -20; fail=1; fi
}

step "write the compose file"        write_compose
step "start Postgres on a new volume" pg_up
step "wait, create, migrate (fresh volume)" pg_wait_and_schema
step "tables exist" bash -c "docker exec $PG_CONTAINER psql -U mav -d mav -tAc \"select count(*) from information_schema.tables where table_name in ('conversations','facts','notifications')\" | grep -qx 3"

# An interrupted install re-run with another password: the volume keeps the
# first one, the installer must re-align it.
A[PG_PASSWORD]="second-'Pass\"2"
step "re-run with a new password" pg_wait_and_schema
step "login with the new password over TCP" \
  docker exec -e PGPASSWORD="${A[PG_PASSWORD]}" "$PG_CONTAINER" psql -X -h 127.0.0.1 -U mav -d mav -tAc 'select 1'

# A compose file left by an interrupted install gives its credentials back.
unset 'A[PG_PASSWORD]' 'A[PG_USER]' 'A[PG_DB]' 'A[PG_PORT]'
load_compose_credentials
step "credentials read back from the compose file" \
  test "${A[PG_PASSWORD]:-}:${A[PG_USER]:-}:${A[PG_DB]:-}:${A[PG_PORT]:-}" = "first-Pass1:mav:mav:55433"
exit "$fail"
