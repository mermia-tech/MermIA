# mermia-eval

Asks the same question to several LLMs through [Agno](https://docs.agno.com), with the 12 C4 tools running against the Mock RPC, and prints three scores per model (tool, args, numbers) plus tokens, latency and cost. Each run is a Langfuse trace with the scores attached. Design: `docs/superpowers/specs/2026-10-19-mr-18-eval-harness-design.md`.

```bash
uv run --env-file .env mermia-eval                                   # all models, 1 run each
uv run --env-file .env mermia-eval --runs 3 --models openai:gpt-5.6-luna,google:gemini-3.8-flash
uv run --env-file .env mermia-eval --mock-url http://localhost:8000  # a running mock instead of in-process
uv run --env-file .env mermia-eval --judge                           # also score tone (paid judge calls)
uv run python -m mermia_eval.gate apps/eval/out/a.json apps/eval/out/b.json  # gate report from dumps
uv run python -m mermia_eval.sample apps/eval/out/a.json             # 10 replies for the human tone check
```

Environment (in `.env`): `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_BASE_URL`. A missing provider key makes that model's runs `err` (the others still run), and the first error of each model is printed on stderr with secrets hidden; `--runs` must be at least 1; missing Langfuse variables turn tracing off with a warning.

Scores are 0 or 1 per run and are averaged over the runs that did not error. `-` means every run of that model errored. Cost is `n/a` when the model has no price in `config.py`. Langfuse also computes a cost per trace and can price models the local table lacks; use it to cross-check, the harness does not read it.

The numbers score wants each figure as the tool shows it: a rounded or shortened figure ("67%" for 67.16%, "$184 mil") counts as invented and scores 0. The tool's dates may be quoted in ISO or Spanish form ("del 5 al 11 de octubre", "12/10/2026").

- **Gate report (MR-20):** after the per-case table, one row per model (`all`) and per category with tool, args, numbers, tone, p50 / p95 seconds, mean cost and errors, checked against `docs/kickoff/13` §H3 (`THRESHOLDS` in `gate.py`): `PASS` or `fail: <checks>`.
- **Run dump:** every run (question, reply, calls, scores, tone, seconds, cost, error) goes to `--out` or `apps/eval/out/<UTC time>.json` (git-ignored), even after a crash or Ctrl-C. `mermia_eval.gate` merges dumps; a model in a later dump replaces its earlier runs, so rerun a flaky model alone.
- **Tone (`--judge`):** `JUDGE` in `judge.py` scores each reply 1-5 on Mexican register, tú / usted, concision, anglicisms and emoji; `CROSS_JUDGE` re-judges replies from the judge's own vendor and the gate takes the lower score. Off by default: it costs one or two calls per run.
- **Paused models:** `PAUSED` in `config.py` (GPT-6.1 Sol, Claude Sonnet 5.5) are rejected by `--models` to keep spend low; move a line back to `MODELS` to run one.
- **`--mock-url` and real data:** the tool answers become part of each Langfuse trace. Pointed at a real backend, `--mock-url` sends that real data to Langfuse; use it only with the mock.
- **Add a model:** one line in `MODELS` (`config.py`), with its price if known.
- **Add a case:** a JSON file in `cases/` (`question`, `expected_tool`, `expected_args`, optional `accepted_args`, `must_contain`). `must_contain` figures must appear in the mock's answer; a test checks it.
- **Review the figures:** `uv run python -m mermia_eval.review` prints every case with the source of each expected figure (`pending` = the mock cannot return it).
- **More case fields:** `category`, `expected_tool` (may be `null`: answer without a tool), `must_not_contain`, `expected_figures` (documentation only).
- **Tests:** `uv run pytest apps/eval` (offline).
