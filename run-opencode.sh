#!/usr/bin/env bash
# Mav — engine launcher.
#
# systemd executes this wrapper instead of the opencode binary directly, so the
# service never fails with 203 (EXEC) if opencode lives somewhere unexpected.
# It resolves the binary at runtime, then execs it.
set -euo pipefail

PORT="${MAV_OPENCODE_PORT:-4096}"
HOST="${MAV_OPENCODE_HOST:-127.0.0.1}"

find_opencode() {
  # 1. Explicit override.
  if [[ -n "${MAV_OPENCODE_BIN:-}" && -x "${MAV_OPENCODE_BIN}" ]]; then
    echo "${MAV_OPENCODE_BIN}"; return
  fi
  # 2. The user's own install locations.
  local p
  for p in "$HOME/.opencode/bin/opencode" "$HOME/.local/bin/opencode"; do
    [[ -x "$p" ]] && { echo "$p"; return; }
  done
  # 3. On PATH.
  p="$(command -v opencode 2>/dev/null || true)"
  [[ -n "$p" && -x "$p" ]] && { echo "$p"; return; }
  # 4. Common system locations.
  for p in /usr/local/bin/opencode /usr/bin/opencode /opt/opencode/bin/opencode; do
    [[ -x "$p" ]] && { echo "$p"; return; }
  done
  echo ""
}

BIN="$(find_opencode)"
if [[ -z "$BIN" ]]; then
  echo "mav: opencode binary not found. Install it, then: systemctl restart mav-server" >&2
  # Exit code 78 (EX_CONFIG) so it is clear this is a configuration issue,
  # not a crash loop. Restart=on-failure will retry later.
  exit 78
fi

exec "$BIN" serve --hostname "$HOST" --port "$PORT"
