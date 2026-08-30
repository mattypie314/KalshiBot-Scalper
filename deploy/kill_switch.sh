#!/usr/bin/env bash
# Overnight drawdown kill-switch for kalshi-btc-scalper.
# Stops the trading service cleanly when equity falls $LOSS below baseline.
# systemctl stop does NOT auto-restart (unlike process crash with Restart=always).
set -euo pipefail

ROOT="${HOME}/KalshiBot-Scalper"
STATE_DIR="${HOME}/.local/state/kalshi-btc-scalper"
STATE="${STATE_DIR}/kill-switch.env"
STOP_NOTE="${STATE_DIR}/STOPPED.txt"
UNIT=kalshi-btc-scalper.service
ENV_FILE="${ROOT}/.env"
POLL_S="${POLL_S:-3}"

mkdir -p "$STATE_DIR"

token() {
  sed -n 's/^SCALPER_DASHBOARD_TOKEN=//p' "$ENV_FILE" | tail -1
}

equity_now() {
  local tok body
  tok="$(token)"
  body="$(curl -sS -m 5 -H "X-Scalper-Token: ${tok}" http://127.0.0.1:8787/api/state 2>/dev/null || true)"
  [[ -n "$body" ]] || return 1
  printf '%s' "$body" | python3 -c 'import sys,json; d=json.load(sys.stdin); print(float(d.get("equity") or 0))'
}

arm() {
  local eq loss
  loss="${1:-4}"
  eq="$(equity_now)" || { echo "cannot read equity — is the bot up?"; exit 1; }
  cat >"$STATE" <<EOF
BASELINE=${eq}
LOSS_LIMIT=${loss}
KILL_AT=$(python3 -c "print(round(${eq}-${loss}, 6))")
ARMED_AT=$(date -Is)
EOF
  rm -f "$STOP_NOTE"
  echo "armed: baseline=\$${eq}  stop if equity <= \$$(python3 -c "print(round(${eq}-${loss}, 4))")  (-${loss})"
}

status() {
  if [[ -f "$STOP_NOTE" ]]; then
    echo "STATUS=STOPPED"
    cat "$STOP_NOTE"
    return
  fi
  if [[ ! -f "$STATE" ]]; then
    echo "STATUS=DISARMED"
    return
  fi
  # shellcheck disable=SC1090
  source "$STATE"
  local eq
  if eq="$(equity_now 2>/dev/null)"; then
    local down
    down="$(python3 -c "print(round(${BASELINE}-float('${eq}'), 4))")"
    echo "STATUS=ARMED baseline=${BASELINE} equity=${eq} down=${down} kill_at=${KILL_AT} limit=${LOSS_LIMIT}"
  else
    echo "STATUS=ARMED (bot unreachable) kill_at=${KILL_AT} limit=${LOSS_LIMIT}"
  fi
}

watch() {
  if [[ ! -f "$STATE" ]]; then
    echo "not armed — run: $0 arm 4" >&2
    exit 2
  fi
  # shellcheck disable=SC1090
  source "$STATE"
  echo "watching kill_at=${KILL_AT} (baseline=${BASELINE} limit=${LOSS_LIMIT})"
  while true; do
    if ! systemctl --user is-active --quiet "$UNIT"; then
      echo "scalper already inactive — kill-switch exiting"
      exit 0
    fi
    eq="$(equity_now 2>/dev/null || echo "")"
    if [[ -n "$eq" ]]; then
      tripped="$(python3 -c "print(1 if float('${eq}') <= float('${KILL_AT}') + 1e-9 else 0)")"
      if [[ "$tripped" == "1" ]]; then
        down="$(python3 -c "print(round(float('${BASELINE}')-float('${eq}'), 4))")"
        {
          echo "STOPPED_AT=$(date -Is)"
          echo "REASON=equity drawdown"
          echo "BASELINE=${BASELINE}"
          echo "EQUITY=${eq}"
          echo "DOWN=${down}"
          echo "LIMIT=${LOSS_LIMIT}"
          echo "MESSAGE=Lost \$${down} (limit \$${LOSS_LIMIT}). Bot stopped until you start it again."
        } >"$STOP_NOTE"
        echo "KILL: equity=${eq} down=${down} — stopping ${UNIT}"
        # Pause first (best-effort), then hard-stop the unit so it stays down.
        tok="$(token)"
        curl -sS -m 3 -H "X-Scalper-Token: ${tok}" -H 'Content-Type: application/json' \
          -d '{"op":"pause"}' http://127.0.0.1:8787/api/action >/dev/null 2>&1 || true
        systemctl --user stop "$UNIT"
        echo "stopped. leave it until you come back. start with: systemctl --user start ${UNIT}"
        exit 0
      fi
    fi
    sleep "$POLL_S"
  done
}

cmd="${1:-status}"
case "$cmd" in
  arm) arm "${2:-4}" ;;
  status) status ;;
  watch) watch ;;
  disarm) rm -f "$STATE"; echo "disarmed (watcher may still run until stopped)" ;;
  *) echo "usage: $0 {arm [dollars]|watch|status|disarm}" >&2; exit 2 ;;
esac
