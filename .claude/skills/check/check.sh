#!/bin/bash
# Runs the repo's fast checks: ruff lint, ruff format, mypy, pytest, pgTAP.
# Each check runs only once the project has what it needs, so this works before and after MR-9.
# Usage: check.sh [--fix]   (--fix applies ruff fixes and formatting instead of only reporting)
set -uo pipefail

cd "${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel)}" || exit 1

fix=0
[ "${1:-}" = "--fix" ] && fix=1

passed=()
failed=()
skipped=()

run() {
  local label=$1
  shift
  echo "::: $label: $*"
  if "$@"; then
    passed+=("$label")
  else
    failed+=("$label")
  fi
}

has_tool() {
  uv run --quiet "$1" --version >/dev/null 2>&1
}

if [ -f pyproject.toml ] && command -v uv >/dev/null 2>&1; then
  if has_tool ruff; then
    if [ "$fix" = 1 ]; then
      run "ruff lint" uv run ruff check --fix .
      run "ruff format" uv run ruff format .
    else
      run "ruff lint" uv run ruff check .
      run "ruff format" uv run ruff format --check .
    fi
  else
    skipped+=("ruff (not a dev dependency yet)")
  fi

  if has_tool mypy; then
    run "mypy" uv run mypy .
  else
    skipped+=("mypy (not a dev dependency yet)")
  fi

  if has_tool pytest; then
    echo "::: pytest: uv run pytest -q"
    uv run pytest -q
    code=$?
    # Exit code 5 means no tests were collected.
    if [ "$code" = 0 ]; then
      passed+=("pytest")
    elif [ "$code" = 5 ]; then
      skipped+=("pytest (no tests yet)")
    else
      failed+=("pytest")
    fi
  else
    skipped+=("pytest (not a dev dependency yet)")
  fi
else
  skipped+=("python checks (no pyproject.toml yet, see MR-9)")
fi

if find . -path ./node_modules -prune -o -path '*/supabase/tests/*.sql' -print -quit 2>/dev/null | grep -q .; then
  if command -v supabase >/dev/null 2>&1; then
    run "pgTAP" supabase test db
  else
    skipped+=("pgTAP (supabase CLI not installed)")
  fi
else
  skipped+=("pgTAP (no supabase/tests yet)")
fi

echo
echo "=== check summary ==="
for p in "${passed[@]+"${passed[@]}"}"; do echo "PASS  $p"; done
for f in "${failed[@]+"${failed[@]}"}"; do echo "FAIL  $f"; done
for s in "${skipped[@]+"${skipped[@]}"}"; do echo "SKIP  $s"; done

[ "${#failed[@]}" = 0 ]
