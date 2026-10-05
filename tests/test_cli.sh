#!/usr/bin/env bash
# Tests for scripts/mav, with stubbed curl / systemctl / journalctl.
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
T="$(mktemp -d)"
trap 'rm -rf "$T"' EXIT
mkdir -p "$T/bin" "$T/pkg" "$T/local" "$T/etc"

# A fake release archive whose installer records how it was called.
cat >"$T/pkg/install.sh" <<'SH'
echo "installer args=$* version=${MAV_VERSION:-} channel=${MAV_CHANNEL:-}" >>"$STUB_LOG"
SH
tar czf "$T/release.tar.gz" -C "$T" pkg
cp "$T/pkg/install.sh" "$T/local/install.sh"

cat >"$T/bin/curl" <<'SH'
#!/usr/bin/env bash
out=""; url=""
while [[ $# -gt 0 ]]; do
  case "$1" in -o) out="$2"; shift ;; http*) url="$1" ;; esac; shift
done
echo "curl $url" >>"$STUB_LOG"
case "$url" in
  # The releases Atom feed is the primary source (no rate limit).
  */releases.atom) [[ -n "${STUB_NO_ATOM:-}${STUB_NO_RELEASE:-}" ]] && exit 22
    echo '<feed><entry><link rel="alternate" type="text/html" href="https://github.com/o/r/releases/tag/v1.2.0"/></entry></feed>' ;;
  # The anonymous API is rate-limited (403) by default: it must never be required.
  */releases/latest) [[ -n "${STUB_API_OK:-}" ]] && { echo '{"tag_name":"v1.5.0"}'; exit 0; }; exit 22 ;;
  */tar.gz/*) [[ -n "${STUB_DL_FAIL:-}" ]] && exit 22; cp "$STUB_TARBALL" "$out" ;;
  *) exit 7 ;;
esac
SH
for c in systemctl journalctl; do
  printf '#!/usr/bin/env bash\necho "%s $*" >>"$STUB_LOG"\n' "$c" >"$T/bin/$c"
done
chmod +x "$T/bin/"*

export PATH="$T/bin:$PATH" MAV_TEST=1 STUB_LOG="$T/log" STUB_TARBALL="$T/release.tar.gz"
export MAV_CLI_ENV="$T/none" MAV_VERSION_FILE="$T/etc/version" MAV_SRC="$T/local"
export MAV_LOCK_FILE="$T/lock" MAV_ENV_DASH="$T/none" MAV_OPENCODE_PORT=1
MAV="$ROOT/scripts/mav"
fail=0
check() {  # check "name" "expected substring" command…
  local name="$1" want="$2"; shift 2
  : >"$T/log"
  local out; out="$("$@" 2>&1; echo "rc=$?")"
  out="$out
$(cat "$T/log")"
  if [[ "$out" == *"$want"* ]]; then echo "ok   $name"
  else echo "FAIL $name — wanted: $want"; echo "$out" | sed 's/^/     /'; fail=1; fi
}

echo v1.0.0 >"$T/etc/version"
check "help"                 "mav update"                    "$MAV" help
check "unknown command"      "rc=2"                          "$MAV" frobnicate
check "version: update"      "update available"              "$MAV" version
check "update --check"       "Update available: v1.0.0 → v1.2.0" "$MAV" update --check
check "update installs tag"  "installer args=--update version=v1.2.0 channel=release" "$MAV" update
check "update downloads tag" "tar.gz/refs/tags/v1.2.0"       "$MAV" update
echo v1.2.0 >"$T/etc/version"
check "already up to date"   "Already up to date (v1.2.0)"   "$MAV" update
check "--force reinstalls"   "installer args=--update version=v1.2.0" "$MAV" update --force
STUB_DL_FAIL=1 check "download fails → local copy" "installer args=--update version=v1.2.0 channel=" "$MAV" update --force
STUB_NO_RELEASE=1 check "no release → main"  "tar.gz/refs/heads/main" "$MAV" update
# The API may be reachable even when the Atom feed is not: fall back to it.
STUB_NO_ATOM=1 STUB_API_OK=1 check "atom unreachable → API fallback" "latest:    v1.5.0" "$MAV" version
# Regression: the API is rate-limited (403) by default in the stub, so the
# version must still resolve via the Atom feed instead of "main@<date>".
check "tag found despite API 403"  "tar.gz/refs/tags/v1.2.0" "$MAV" update --force
check "--local"              "installer args=--update"      "$MAV" update --local
check "restart worker"       "systemctl restart mav-worker" "$MAV" restart worker
check "restart bad service"  "Unknown service"              "$MAV" restart toaster
check "logs engine -n 5"     "journalctl -u mav-server -n 5 --no-pager" "$MAV" logs engine -n 5
check "logs all"             "-u mav-server -u mav-worker -u mav-dashboard" "$MAV" logs -n 1
exit "$fail"
