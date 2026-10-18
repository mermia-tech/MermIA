#!/bin/bash
# Installs Python dependencies in Claude Code cloud sessions so checks and tests can run.
# Local sessions are skipped: run `uv sync` yourself.
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "${CLAUDE_PROJECT_DIR:-.}"

# No Python project yet (pre MR-9): nothing to install.
if [ ! -f pyproject.toml ]; then
  exit 0
fi

if ! command -v uv >/dev/null 2>&1; then
  echo "session-start: uv not found, skipping dependency install" >&2
  exit 0
fi

# `uv sync` (not --frozen) so a missing lockfile does not fail the session; the container caches the result.
uv sync --all-packages --all-groups >&2
