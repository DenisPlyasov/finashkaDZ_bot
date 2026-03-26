# # #!/usr/bin/env bash
# set -euo pipefail

# DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# exec "$DIR/venv/bin/python" "$DIR/fa_bridge.py" "$@"

#!/bin/sh
set -eu

DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"

# Если хочешь задать путь вручную (самый надежный способ):
# export FA_PY="/abs/path/to/.venv/bin/python"
if [ -n "${FA_PY:-}" ]; then
  if [ ! -x "$FA_PY" ]; then
    echo "[fa_bridge] FA_PY is set but not executable: $FA_PY" >&2
    exit 1
  fi
  PY="$FA_PY"
else
  PY=""
  for up in "" "/.." "/../.." "/../../.." "/../../../.."; do
    base="$DIR$up"
    for candidate in "$base/.venv/bin/python" "$base/venv/bin/python"; do
      if [ ! -x "$candidate" ]; then
        continue
      fi
      if "$candidate" -c "import fa_api" >/dev/null 2>&1; then
        PY="$candidate"
        break 2
      fi
    fi
  done

  if [ -z "$PY" ]; then
    for candidate in python3 python; do
      if ! command -v "$candidate" >/dev/null 2>&1; then
        continue
      fi
      if "$candidate" -c "import fa_api" >/dev/null 2>&1; then
        PY="$candidate"
        break
      fi
    done
  fi

  if [ -z "$PY" ]; then
    echo "[fa_bridge] Could not find a Python with 'fa_api' installed." >&2
    echo "[fa_bridge] Searched from: $DIR and parent directories." >&2
    echo "[fa_bridge] Tip: activate your venv and run: pip show fa_api" >&2
    echo "[fa_bridge] Or set FA_PY=/abs/path/to/venv/bin/python" >&2
    exit 1
  fi
fi

echo "[fa_bridge] Using python: $PY" >&2
exec "$PY" "$DIR/fa_bridge.py" "$@"
