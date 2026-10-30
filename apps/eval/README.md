# mermia-eval

Asks the same question to several LLMs through [Agno](https://docs.agno.com), with the 12 C4 tools running against the Mock RPC, and prints three scores per model (tool, args, numbers) plus tokens, latency and cost. Each run is a Langfuse trace with the scores attached. Design: `docs/superpowers/specs/2026-10-19-mr-18-eval-harness-design.md`.

```bash
uv run --env-file .env mermia-eval                                   # all models, 1 run each
uv run --env-file .env mermia-eval --runs 3 --models openai:gpt-5.6-luna,google:gemini-3.8-flash
uv run --env-file .env mermia-eval --mock-url http://localhost:8000  # a running mock instead of in-process
```

Environment (in `.env`): `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_BASE_URL`. A missing provider key makes that model's runs `err` (the others still run), and the first error of each model is printed on stderr with secrets hidden; `--runs` must be at least 1; missing Langfuse variables turn tracing off with a warning.

Scores are 0 or 1 per run and are averaged over the runs that did not error. `-` means every run of that model errored. Cost is `n/a` when the model has no price in `config.py`. Langfuse also computes a cost per trace and can price models the local table lacks; use it to cross-check, the harness does not read it.

The numbers score wants each figure as the tool shows it: a rounded or shortened figure ("67%" for 67.16%, "$184 mil") counts as invented and scores 0. The tool's dates may be quoted in ISO or Spanish form ("del 5 al 11 de octubre", "12/10/2026").

- **`--mock-url` and real data:** the tool answers become part of each Langfuse trace. Pointed at a real backend, `--mock-url` sends that real data to Langfuse; use it only with the mock.
- **Add a model:** one line in `MODELS` (`config.py`), with its price if known.
- **Add a case:** a JSON file in `cases/` (`question`, `expected_tool`, `expected_args`, optional `accepted_args`, `must_contain`). `must_contain` figures must appear in the mock's answer; a test checks it.
- **Tests:** `uv run pytest apps/eval` (offline).
