# # #!/usr/bin/env bash
# set -euo pipefail

# DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# exec "$DIR/venv/bin/python" "$DIR/fa_bridge.py" "$@"

#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Если хочешь задать путь вручную (самый надежный способ):
# export FA_PY="/abs/path/to/.venv/bin/python"
if [[ -n "${FA_PY:-}" ]]; then
  if [[ ! -x "$FA_PY" ]]; then
    echo "[fa_bridge] FA_PY is set but not executable: $FA_PY" >&2
    exit 1
  fi
  PY="$FA_PY"
else
  # Собираем кандидатов: в этой папке и на 1-4 уровня выше
  candidates=()
  for up in "" "/.." "/../.." "/../../.." "/../../../.."; do
    base="$DIR$up"
    candidates+=("$base/.venv/bin/python" "$base/venv/bin/python")
  done

  # как последний шанс — системный python3 (иногда `fa_api` ставили глобально)
  candidates+=("python3" "python")

  PY=""
  for c in "${candidates[@]}"; do
    if [[ "$c" == "python3" || "$c" == "python" ]]; then
      if ! command -v "$c" >/dev/null 2>&1; then
        continue
      fi
      test_py="$c"
    else
      if [[ ! -x "$c" ]]; then
        continue
      fi
      test_py="$c"
    fi

    # Ключ: выбираем интерпретатор, где реально есть fa_api
    if "$test_py" -c "import fa_api" >/dev/null 2>&1; then
      PY="$test_py"
      break
    fi
  done

  if [[ -z "$PY" ]]; then
    echo "[fa_bridge] Could not find a Python with 'fa_api' installed." >&2
    echo "[fa_bridge] Searched from: $DIR (and parents). Candidates:" >&2
    for c in "${candidates[@]}"; do echo "  - $c" >&2; done
    echo "[fa_bridge] Tip: activate your venv and run: pip show fa_api" >&2
    echo "[fa_bridge] Or set FA_PY=/abs/path/to/venv/bin/python" >&2
    exit 1
  fi
fi

echo "[fa_bridge] Using python: $PY" >&2
exec "$PY" "$DIR/fa_bridge.py" "$@"