#!/bin/bash
# PostToolUse: run `ruff format` on a Python file Claude just edited. Never blocks the edit.
set -uo pipefail

file_path=$(python3 -c 'import json, sys; print(json.load(sys.stdin).get("tool_input", {}).get("file_path") or "")')

case "$file_path" in
  *.py|*.pyi) ;;
  *) exit 0 ;;
esac

[ -f "$file_path" ] || exit 0
cd "${CLAUDE_PROJECT_DIR:-.}" || exit 0

# Prefer the project's pinned ruff; fall back to one on PATH.
if [ -f pyproject.toml ] && command -v uv >/dev/null 2>&1 && uv run --quiet ruff --version >/dev/null 2>&1; then
  uv run --quiet ruff format --quiet "$file_path" >&2 || true
elif command -v ruff >/dev/null 2>&1; then
  ruff format --quiet "$file_path" >&2 || true
fi

exit 0
