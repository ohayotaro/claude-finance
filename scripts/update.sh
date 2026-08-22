#!/usr/bin/env bash
# Delegate the stable shell entry point to the single Python updater.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd -P)"
UPDATER="$SCRIPT_DIR/update.py"

if [[ ! -f "$UPDATER" || -L "$UPDATER" ]]; then
  printf 'ERROR: Python updater is missing or unsafe: %s\n' "$UPDATER" >&2
  exit 1
fi

is_supported_python() {
  "$1" -c 'import sys; raise SystemExit(sys.version_info < (3, 11))' \
    >/dev/null 2>&1
}

resolve_python() {
  local candidate

  if [[ -n "${UPDATER_PYTHON:-}" ]] && is_supported_python "$UPDATER_PYTHON"; then
    printf '%s\n' "$UPDATER_PYTHON"
    return 0
  fi

  for candidate in python3 python python3.14 python3.13 python3.12 python3.11; do
    if command -v "$candidate" >/dev/null 2>&1; then
      candidate="$(command -v "$candidate")"
      if is_supported_python "$candidate"; then
        printf '%s\n' "$candidate"
        return 0
      fi
    fi
  done

  if command -v uv >/dev/null 2>&1; then
    candidate="$(uv python find '>=3.11' 2>/dev/null || true)"
    if [[ -n "$candidate" ]] && is_supported_python "$candidate"; then
      printf '%s\n' "$candidate"
      return 0
    fi
  fi

  return 1
}

if PYTHON="$(resolve_python)"; then
  exec "$PYTHON" "$UPDATER" "$@"
fi

printf '%s\n' \
  'ERROR: scripts/update.sh requires Python 3.11 or newer.' \
  'Set UPDATER_PYTHON, install a supported interpreter, or ensure uv can find one.' >&2
exit 1
