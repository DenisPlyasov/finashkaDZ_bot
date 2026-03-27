#!/bin/sh
set -eu

cd /app

write_if_set() {
  value="${1:-}"
  target="${2:-}"
  if [ -n "$value" ]; then
    printf '%s' "$value" > "$target"
  fi
}

write_if_set "${REQUIRED_CHANNEL_LINK:-}" "required_chanel_link.txt"
write_if_set "${REQUIRED_CHANNEL_ID:-}" "required_chaned_id.txt"
write_if_set "${MAIL_PASSWORD:-}" "password_mail.txt"

if [ -n "${GOOGLE_CREDS_JSON_B64:-}" ]; then
  printf '%s' "$GOOGLE_CREDS_JSON_B64" | base64 -d > "finashkadzbot-d8415e20cc18.json"
fi

mkdir -p data

if [ ! -s /app/token.txt ]; then
  echo "Missing /app/token.txt. Put the Telegram token into token.txt before starting the container." >&2
  exit 1
fi

if [ "${ENABLE_WEBAPP:-1}" = "1" ] && [ -z "${REQUIRED_CHANNEL:-}" ]; then
  echo "Missing REQUIRED_CHANNEL. Set it in .env before starting the container." >&2
  exit 1
fi

if [ "${ENABLE_BOT:-1}" = "1" ] && [ -z "${REQUIRED_CHANNEL_LINK:-}" ]; then
  echo "Missing REQUIRED_CHANNEL_LINK. Set it in .env before starting the container." >&2
  exit 1
fi

if [ "${ENABLE_BOT:-1}" = "1" ] && [ -z "${REQUIRED_CHANNEL_ID:-}" ]; then
  echo "Missing REQUIRED_CHANNEL_ID. Set it in .env before starting the container." >&2
  exit 1
fi

if [ ! -f /app/data/favorites.json ]; then
  printf '{}\n' > /app/data/favorites.json
fi

if [ ! -f /app/data/mail_accounts.json ]; then
  printf '{}\n' > /app/data/mail_accounts.json
fi

touch /app/data/miniapp.sqlite
mkdir -p /app/data/webapp-cache /app/data/webapp-uploads

ln -sfn /app/data/favorites.json /app/favorites.json
ln -sfn /app/data/mail_accounts.json /app/mail_accounts.json
ln -sfn /app/data/miniapp.sqlite /app/webapp/backend/miniapp.sqlite

rm -rf /app/webapp/backend/.cache /app/webapp/backend/uploads
ln -sfn /app/data/webapp-cache /app/webapp/backend/.cache
ln -sfn /app/data/webapp-uploads /app/webapp/backend/uploads

shutdown() {
  for pid in $PIDS; do
    kill "$pid" 2>/dev/null || true
  done
  for pid in $PIDS; do
    wait "$pid" 2>/dev/null || true
  done
}

trap 'shutdown; exit 143' INT TERM

PIDS=""

if [ "${ENABLE_WEBAPP:-1}" = "1" ]; then
  (
    cd /app/webapp/backend
    node server.js
  ) &
  PIDS="$PIDS $!"
fi

if [ "${ENABLE_BOT:-1}" = "1" ]; then
  python3 /app/main.py &
  PIDS="$PIDS $!"
fi

if [ -z "${PIDS# }" ]; then
  echo "Nothing to run: both ENABLE_WEBAPP and ENABLE_BOT are disabled" >&2
  exit 1
fi

while :; do
  for pid in $PIDS; do
    if ! kill -0 "$pid" 2>/dev/null; then
      wait "$pid" || status=$?
      shutdown
      exit "${status:-0}"
    fi
  done
  sleep 2
done
