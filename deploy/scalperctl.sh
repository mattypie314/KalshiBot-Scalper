#!/usr/bin/env bash
# Manage the persistent Kalshi BTC scalper systemd user service over SSH.
#
# Guide (system unit)              This Pi (user unit)
# sudo journalctl -u kalshi-scalper -f   →  kalshi-scalper-logs  /  scalperctl logs
# sudo systemctl status kalshi-scalper   →  kalshi-scalper-status / scalperctl status
# sudo systemctl stop kalshi-scalper     →  kalshi-scalper-stop   / scalperctl stop
set -euo pipefail

UNIT=kalshi-btc-scalper.service
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$(cd "$(dirname "$0")" && pwd)/${UNIT}"
DST="${HOME}/.config/systemd/user/${UNIT}"
ENV_FILE="${ROOT}/.env"

_health_probe() {
  local port token url code body
  port="$(systemctl --user show -p Environment --value "$UNIT" 2>/dev/null | tr ' ' '\n' | sed -n 's/^SCALPER_PORT=//p' | tail -1)"
  port="${port:-8787}"
  token=""
  if [[ -f "$ENV_FILE" ]]; then
    token="$(sed -n 's/^SCALPER_DASHBOARD_TOKEN=//p' "$ENV_FILE" | tail -1)"
  fi
  url="http://127.0.0.1:${port}/api/state"
  if [[ -n "$token" ]]; then
    body="$(curl -sS -m 3 -H "X-Scalper-Token: ${token}" "$url" 2>/dev/null || true)"
  else
    body="$(curl -sS -m 3 "$url" 2>/dev/null || true)"
  fi
  if [[ -z "$body" ]]; then
    echo "health: dashboard unreachable on :${port}"
    return 1
  fi
  printf '%s' "$body" | python3 -c '
import json, sys
d = json.load(sys.stdin)
keys = ("ok", "mode", "ws_ok", "uptime_s", "open", "paused", "live_ready", "tick")
print("health:", {k: d.get(k) for k in keys})
' 2>/dev/null || echo "health: non-JSON response from :${port}"
}

_status_extra() {
  local pid rss_kb nrestarts entered mem
  pid="$(systemctl --user show -p MainPID --value "$UNIT" 2>/dev/null || echo 0)"
  nrestarts="$(systemctl --user show -p NRestarts --value "$UNIT" 2>/dev/null || echo '?')"
  entered="$(systemctl --user show -p ActiveEnterTimestamp --value "$UNIT" 2>/dev/null || echo '?')"
  mem="$(systemctl --user show -p MemoryCurrent --value "$UNIT" 2>/dev/null || echo '')"
  rss_kb="?"
  if [[ -n "$pid" && "$pid" != 0 && -r "/proc/${pid}/status" ]]; then
    rss_kb="$(awk '/^VmRSS:/{print $2}' "/proc/${pid}/status")"
  fi
  echo "---"
  echo "MainPID=${pid}  NRestarts=${nrestarts}  ActiveEnter=${entered}"
  if [[ -n "$mem" && "$mem" != "[not set]" && "$mem" != "infinity" ]]; then
    echo "MemoryCurrent=${mem} bytes  VmRSS=${rss_kb} kB"
  else
    echo "VmRSS=${rss_kb} kB"
  fi
  _health_probe || true
}

cmd="${1:-status}"
case "$cmd" in
  install)
    mkdir -p "${HOME}/.config/systemd/user"
    install -m 644 "$SRC" "$DST"
    systemctl --user daemon-reload
    systemctl --user enable --now "$UNIT"
    systemctl --user status "$UNIT" --no-pager -l || true
    ;;
  start)   systemctl --user start "$UNIT" ;;
  stop)    systemctl --user stop "$UNIT" ;;
  restart) systemctl --user restart "$UNIT" ;;
  status)
    systemctl --user status "$UNIT" --no-pager -l || true
    _status_extra
    ;;
  health)
    _health_probe
    ;;
  logs|follow)
    # --user -u fails on this host ("No journal files"); --user-unit works.
    journalctl --user-unit="$UNIT" -f -n 80 --no-hostname
    ;;
  enable)
    systemctl --user enable "$UNIT"
    echo "enabled (Linger=$(loginctl show-user "$USER" -p Linger --value))"
    ;;
  disable)
    systemctl --user disable --now "$UNIT"
    ;;
  *)
    echo "usage: $0 {install|start|stop|restart|status|health|logs|follow|enable|disable}" >&2
    echo "SSH: kalshi-scalper-logs | kalshi-scalper-status | kalshi-scalper-stop" >&2
    exit 2
    ;;
esac
