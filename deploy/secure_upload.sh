#!/usr/bin/env bash
# Securely upload KalshiBot-Scalper code to a remote host over SSH/scp.
# NEVER bundles .env, .secrets, *.pem, or .venv with the code tree.
#
# Usage:
#   ./deploy/secure_upload.sh user@server:/home/user/KalshiBot-Scalper
#   ./deploy/secure_upload.sh --secrets user@server:/home/user/KalshiBot-Scalper
#
# First push code, then (optionally) push secrets in a second call with --secrets.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WITH_SECRETS=0
DEST=""

usage() {
  cat <<'EOF'
usage: secure_upload.sh [--secrets] user@host:/remote/path

  Default: rsync/scp code only (excludes .env .secrets .venv .git *.pem *.key)
  --secrets: also scp .env + .secrets/*.pem with mode 600 on the remote

Keys must never live in Python source. Remote layout expected:
  $DEST/.env
  $DEST/.secrets/kalshi_live.pem
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --secrets) WITH_SECRETS=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *)
      if [[ -n "$DEST" ]]; then echo "extra arg: $1" >&2; usage; exit 2; fi
      DEST="$1"; shift
      ;;
  esac
done

if [[ -z "$DEST" ]]; then
  usage
  exit 2
fi

# Split user@host:path
if [[ "$DEST" != *:* ]]; then
  echo "DEST must look like user@host:/absolute/path" >&2
  exit 2
fi
REMOTE_HOST="${DEST%%:*}"
REMOTE_PATH="${DEST#*:}"
if [[ "$REMOTE_PATH" != /* ]]; then
  echo "remote path must be absolute: got $REMOTE_PATH" >&2
  exit 2
fi

echo "==> code → ${REMOTE_HOST}:${REMOTE_PATH} (no secrets)"
ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new "$REMOTE_HOST" \
  "mkdir -p $(printf %q "$REMOTE_PATH")"

if command -v rsync >/dev/null 2>&1; then
  rsync -az --delete \
    --exclude '.env' \
    --exclude '.env.local' \
    --exclude '.secrets/' \
    --exclude '.venv/' \
    --exclude 'venv/' \
    --exclude '.git/' \
    --exclude '__pycache__/' \
    --exclude '.pytest_cache/' \
    --exclude '*.pem' \
    --exclude '*.key' \
    --exclude '*.log' \
    --exclude '.cursor/' \
    "$ROOT/" "${REMOTE_HOST}:${REMOTE_PATH}/"
else
  # Fallback: tar over ssh (still excludes secrets)
  tar -C "$ROOT" \
    --exclude='.env' \
    --exclude='.env.local' \
    --exclude='.secrets' \
    --exclude='.venv' \
    --exclude='venv' \
    --exclude='.git' \
    --exclude='__pycache__' \
    --exclude='.pytest_cache' \
    --exclude='*.pem' \
    --exclude='*.key' \
    --exclude='*.log' \
    --exclude='.cursor' \
    -czf - . \
    | ssh -o BatchMode=yes "$REMOTE_HOST" \
        "mkdir -p $(printf %q "$REMOTE_PATH") && tar -xzf - -C $(printf %q "$REMOTE_PATH")"
fi

if [[ "$WITH_SECRETS" -eq 1 ]]; then
  if [[ ! -f "$ROOT/.env" ]]; then
    echo "missing $ROOT/.env — copy from .env.example and fill keys first" >&2
    exit 1
  fi
  if [[ ! -f "$ROOT/.secrets/kalshi_live.pem" ]]; then
    echo "missing $ROOT/.secrets/kalshi_live.pem" >&2
    exit 1
  fi
  echo "==> secrets → ${REMOTE_HOST}:${REMOTE_PATH} (scp, mode 600)"
  ssh -o BatchMode=yes "$REMOTE_HOST" \
    "mkdir -p $(printf %q "$REMOTE_PATH/.secrets") && chmod 700 $(printf %q "$REMOTE_PATH/.secrets")"
  scp -o BatchMode=yes "$ROOT/.env" "${REMOTE_HOST}:${REMOTE_PATH}/.env"
  scp -o BatchMode=yes "$ROOT/.secrets/kalshi_live.pem" \
    "${REMOTE_HOST}:${REMOTE_PATH}/.secrets/kalshi_live.pem"
  # Rewrite PEM path inside remote .env to match DEST
  ssh -o BatchMode=yes "$REMOTE_HOST" bash -s -- "$REMOTE_PATH" <<'REMOTE'
set -euo pipefail
DEST="$1"
chmod 600 "$DEST/.env" "$DEST/.secrets/kalshi_live.pem"
chmod 700 "$DEST/.secrets"
# Point KALSHI_PRIVATE_KEY_PATH at the remote PEM (no hardcoded key material).
if grep -q '^KALSHI_PRIVATE_KEY_PATH=' "$DEST/.env"; then
  sed -i "s|^KALSHI_PRIVATE_KEY_PATH=.*|KALSHI_PRIVATE_KEY_PATH=${DEST}/.secrets/kalshi_live.pem|" "$DEST/.env"
else
  printf '\nKALSHI_PRIVATE_KEY_PATH=%s/.secrets/kalshi_live.pem\n' "$DEST" >>"$DEST/.env"
fi
# Strip any inline private key if someone pasted one.
sed -i '/^KALSHI_PRIVATE_KEY=/d' "$DEST/.env"
REMOTE
  echo "==> secrets landed; verify remote never prints them"
else
  echo "==> code only. On the server, place secrets separately, e.g.:"
  echo "    scp .env ${REMOTE_HOST}:${REMOTE_PATH}/.env"
  echo "    scp .secrets/kalshi_live.pem ${REMOTE_HOST}:${REMOTE_PATH}/.secrets/"
  echo "    ssh ${REMOTE_HOST} chmod 600 ${REMOTE_PATH}/.env ${REMOTE_PATH}/.secrets/kalshi_live.pem"
fi

echo "==> done"
echo "    next on remote: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
echo "    then:           ./deploy/scalperctl.sh install"
