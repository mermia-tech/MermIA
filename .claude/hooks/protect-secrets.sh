#!/bin/bash
# PreToolUse: block Claude from writing secret files (.env, .env.local, ...). Templates like .env.example are allowed.
set -euo pipefail

file_path=$(python3 -c 'import json, sys; print(json.load(sys.stdin).get("tool_input", {}).get("file_path") or "")')
name=$(basename "${file_path:-}")

case "$name" in
  .env.example|.env.sample|.env.template)
    exit 0
    ;;
  .env|.env.*|*.pem|*.key|service-account*.json)
    echo "Blocked: $name may hold secrets. Edit it yourself, or change .env.example instead." >&2
    exit 2
    ;;
esac

exit 0
