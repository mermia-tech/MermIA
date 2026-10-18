---
name: check
description: Run MermIA's fast local checks (ruff lint and format, mypy, pytest, pgTAP) and report what passed, failed or was skipped. Use before committing, before opening a PR, or when asked to "run checks", "lint" or "run the tests".
argument-hint: "[--fix]"
---

# check

Run the same fast checks CI runs, from the repo root:

```bash
"$CLAUDE_PROJECT_DIR"/.claude/skills/check/check.sh $ARGUMENTS
```

- `--fix` applies ruff fixes and formatting. Without it, nothing is changed.
- A check is skipped (not failed) when the project does not have it yet, for example no `pyproject.toml` before MR-9 or no `supabase/tests` before MR-14.

## After it runs

1. Show the summary block as it is.
2. For each FAIL, quote the first error lines and name the file and line.
3. Fix only failures in code this branch changed. For a failure elsewhere, say what fails and why it is not this branch's, and do not fix it unasked.
4. Never skip, delete or mark a test as expected-to-fail to make it pass.
5. Re-run the script after a fix, and report the final summary.
