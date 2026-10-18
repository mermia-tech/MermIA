# MermIA

Restaurant intelligence for Mexico. See `CLAUDE.md` and `docs/kickoff/00-executive-summary.md`.

## Development

Requires [uv](https://docs.astral.sh/uv/). Python 3.12 is installed by uv from `.python-version`.

```bash
uv sync --all-packages --all-groups   # install every workspace member and dev tools
uv run ruff check . && uv run ruff format --check .
uv run mypy
uv run pytest
uv run uvicorn mermia_api.main:app --reload   # local API at http://127.0.0.1:8000/health
```

Or run all checks at once: `.claude/skills/check/check.sh` (`/check` in Claude Code).

Layout (a `uv` workspace, see `docs/kickoff/09-architecture.md` §1):
- `apps/api`: the one FastAPI service.
- `packages/*`: shared code, starting with `packages/contracts` (MR-10) and `packages/db` (MR-14).

CI (`.github/workflows/ci.yml`) runs ruff, mypy and pytest on every PR, plus pgTAP once a `supabase/` project exists.
