#!/bin/bash
# SessionStart для облачных сессий Claude Code: venv + зависимости TechStudio, чтобы make test/lint работали сразу.
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "${CLAUDE_PROJECT_DIR:-$(pwd)}"

PY=".venv/bin/python"
if [ ! -x "$PY" ]; then
  if command -v uv >/dev/null; then
    uv venv --python 3.13 .venv || uv venv .venv
  else
    python3 -m venv .venv
  fi
fi

if command -v uv >/dev/null; then
  uv pip install --python "$PY" -e ".[dev]"
else
  "$PY" -m pip install -q -e ".[dev]"
fi

# в тестах реальных API нет; фейковые бэкенды по умолчанию для ручных прогонов в облаке
if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
  {
    echo "export PATH=\"$PWD/.venv/bin:\$PATH\""
  } >> "$CLAUDE_ENV_FILE"
fi
