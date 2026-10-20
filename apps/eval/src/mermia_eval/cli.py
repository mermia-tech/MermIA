"""`uv run --env-file .env mermia-eval`: every model answers every case; print the scores."""

import argparse
import logging
import os
import sys
from collections.abc import Mapping, Sequence
from statistics import fmean
from typing import Any
from urllib.parse import quote

from agno.utils.log import configure_agno_logging

from mermia_eval.cases import Case, load_cases
from mermia_eval.config import MODELS, Price
from mermia_eval.run import RunResult, cost_usd, run_case
from mermia_eval.score import score_args, score_numbers, score_tool
from mermia_eval.tools import build_tools, make_rpc_caller
from mermia_eval.tracing import post_scores, setup_tracing


def _scores(case: Case, r: RunResult) -> dict[str, float]:
    return {
        "tool": score_tool(case, r.calls),
        "args": score_args(case, r.calls),
        "numbers": score_numbers(case, r.text, r.tool_results),
    }


def summarize(
    results: Sequence[RunResult], case: Case, prices: Mapping[str, Price | None]
) -> list[dict[str, Any]]:
    """One row per model: means over the runs that did not error."""
    rows = []
    for model in dict.fromkeys(r.model for r in results):
        mine = [r for r in results if r.model == model]
        ok = [r for r in mine if r.error is None]
        scores = [_scores(case, r) for r in ok]
        costs = [cost_usd(r, prices.get(model)) for r in ok]
        rows.append(
            {
                "case": case.id,
                "model": model,
                **{
                    k: fmean(s[k] for s in scores) if ok else None
                    for k in ("tool", "args", "numbers")
                },
                "tokens_in": fmean(r.input_tokens for r in ok) if ok else 0,
                "tokens_out": fmean(r.output_tokens for r in ok) if ok else 0,
                "seconds": fmean(r.seconds for r in ok) if ok else 0,
                "cost": fmean(c for c in costs if c is not None)
                if ok and None not in costs
                else None,
                "runs": len(mine),
                "errors": len(mine) - len(ok),
            }
        )
    return rows


def _score(v: float | None) -> str:
    return "-" if v is None else f"{v:.2f}"


def format_header() -> str:
    return (
        f"{'case':<18}{'model':<32}{'tool':>5}{'args':>6}{'nums':>6}"
        f"{'in':>8}{'out':>7}{'sec':>7}{'usd':>10}{'runs':>5}{'err':>4}"
    )


def format_row(r: Mapping[str, Any]) -> str:
    cost = "n/a" if r["cost"] is None else f"{r['cost']:.5f}"
    return (
        f"{r['case']:<18}{r['model']:<32}{_score(r['tool']):>5}{_score(r['args']):>6}"
        f"{_score(r['numbers']):>6}{r['tokens_in']:>8.0f}{r['tokens_out']:>7.0f}"
        f"{r['seconds']:>7.1f}{cost:>10}{r['runs']:>5}{r['errors']:>4}"
    )


def format_table(rows: Sequence[Mapping[str, Any]]) -> str:
    return "\n".join([format_header(), *(format_row(r) for r in rows)])


_SECRET_NAMES = ("KEY", "SECRET", "TOKEN", "PASSWORD", "AUTH", "CREDENTIAL")


def redact(text: str, env: Mapping[str, str]) -> str:
    """Hide the value (and its URL-encoded form) of every secret-looking environment variable."""
    for name, value in env.items():
        if len(value) >= 8 and any(k in name.upper() for k in _SECRET_NAMES):
            for form in (value, quote(value, safe="")):
                text = text.replace(form, "***")
    return text


class _Redacting(logging.Filter):
    def __init__(self, env: Mapping[str, str]) -> None:
        super().__init__()
        self._env = env

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg, record.args = redact(record.getMessage(), self._env), None
        return True


def route_agno_logs(env: Mapping[str, str]) -> None:
    """Agno logs provider errors to stdout, next to the table; send them to stderr instead,
    with secrets hidden."""
    log = logging.Logger("mermia_eval.agno", logging.INFO)  # not registered: no handler piles up
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(levelname)-7s %(message)s"))
    handler.addFilter(_Redacting(env))
    log.addHandler(handler)
    configure_agno_logging(
        custom_default_logger=log,
        custom_agent_logger=log,
        custom_team_logger=log,
        custom_workflow_logger=log,
    )


def _positive_int(text: str) -> int:
    value = int(text)  # argparse reports a ValueError as "invalid ... value"
    if value < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return value


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mermia-eval", description=__doc__)
    parser.add_argument("--runs", type=_positive_int, default=1, help="runs per model and case")
    parser.add_argument("--models", help="comma-separated provider:model ids (default: all)")
    parser.add_argument("--mock-url", help="a running Mock RPC (default: in-process)")
    args = parser.parse_args(argv)

    known = {m.id for m in MODELS}
    models = [m.id for m in MODELS]
    if args.models is not None:
        models = [m.strip() for m in args.models.split(",")]
        if "" in models:
            parser.error("--models has an empty id")
    if unknown := [m for m in models if m not in known]:
        parser.error(f"unknown model(s): {', '.join(unknown)}")

    cases = load_cases()
    if not cases:
        parser.error("no cases found in apps/eval/cases")

    env = os.environ
    route_agno_logs(env)
    provider = setup_tracing(env)
    if provider is None:
        print("warning: LANGFUSE_* not set, runs are not traced", file=sys.stderr)
    backend = make_rpc_caller(args.mock_url)
    tools = build_tools(backend)
    prices = {m.id: m.price for m in MODELS}

    every_run_errored = True
    first_error: dict[str, str] = {}
    print(format_header(), flush=True)
    try:
        for case in cases:
            for model in models:
                results = []
                for _ in range(args.runs):
                    backend.failures.clear()
                    r = run_case(model, case, tools, failures=backend.failures)
                    results.append(r)
                    if r.error is not None:
                        first_error.setdefault(model, r.error)
                    if r.error is None:
                        every_run_errored = False
                        # spans export in the background; the scores need the trace to be there
                        if provider is not None:
                            provider.force_flush()
                        post_scores(env, r.trace_id, _scores(case, r))
                print(format_row(summarize(results, case, prices)[0]), flush=True)
    finally:
        if provider is not None:
            provider.force_flush()
        for model, error in first_error.items():  # the table only counts errors; say what they were
            print(f"{model}: {' '.join(redact(error, env).split())[:300]}", file=sys.stderr)
    return 1 if every_run_errored else 0


if __name__ == "__main__":
    raise SystemExit(main())
