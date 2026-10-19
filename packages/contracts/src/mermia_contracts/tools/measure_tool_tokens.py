"""Measure what each agent tool adds to a request, with the Anthropic count_tokens API.

    ANTHROPIC_API_KEY=... python -m mermia_contracts.tools.measure_tool_tokens [--model M] [--check]

Metric: marginal cost M(t) = count([B, t]) - count([B]), where B is a fixed baseline tool. The
API adds fixed tool-use scaffolding once per request; subtracting the baseline count cancels it
and leaves the tokens the tool's own definition adds (08 C4 / 13 H budget 125 per tool).
Also records total = count([B] + all tools) - count([B]) and overhead = count([B]).

Without `--check` it writes schemas/tool_tokens.json. With `--check` it re-measures and fails if a
count differs from the snapshot by more than TOLERANCE, or exceeds TOKEN_LIMIT.
"""

import argparse
import datetime as dt
import json
import sys
from collections.abc import Callable, Sequence
from importlib.metadata import version
from typing import Any

from mermia_contracts.agent_tools import TOKEN_LIMIT, ToolDef, tool_definitions, tools_sha256
from mermia_contracts.tools.export_schemas import DEFAULT_OUTPUT

MODEL = "claude-haiku-5-5"
TOLERANCE = 2
SNAPSHOT = DEFAULT_OUTPUT / "tool_tokens.json"
BASELINE: ToolDef = {
    "name": "noop",
    "description": "noop",
    "input_schema": {"type": "object", "properties": {}},
}

Counter = Callable[[Sequence[ToolDef]], int]


def measure(count: Counter, model: str, sdk_version: str) -> dict[str, Any]:
    tools = tool_definitions()
    base = count([BASELINE])
    return {
        "model": model,
        "sdk_version": sdk_version,
        "measured_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "baseline_tool": BASELINE,
        "limit": TOKEN_LIMIT,
        "tools_sha256": tools_sha256(),
        "per_tool": {t["name"]: count([BASELINE, t]) - base for t in tools},
        "total": count([BASELINE, *tools]) - base,
        "overhead": base,
    }


def api_counter(model: str) -> Counter:
    import anthropic

    client = anthropic.Anthropic()

    def count(tools: Sequence[ToolDef]) -> int:
        result = client.messages.count_tokens(
            model=model,
            messages=[{"role": "user", "content": "x"}],
            tools=list(tools),  # type: ignore[arg-type]
        )
        return result.input_tokens

    return count


def problems(fresh: dict[str, Any], saved: dict[str, Any]) -> list[str]:
    out = [
        f"{n}: {m} tokens > {TOKEN_LIMIT}" for n, m in fresh["per_tool"].items() if m > TOKEN_LIMIT
    ]
    for name, m in fresh["per_tool"].items():
        was = saved["per_tool"].get(name)
        if was is None or abs(was - m) > TOLERANCE:
            out.append(f"{name}: measured {m}, snapshot {was}")
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--model", default=MODEL)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)

    fresh = measure(api_counter(args.model), args.model, version("anthropic"))
    for name, m in fresh["per_tool"].items():
        print(f"{name:24} {m:4} {'OVER' if m > TOKEN_LIMIT else 'ok'}")
    print(f"total {fresh['total']}  overhead {fresh['overhead']}  limit {TOKEN_LIMIT} per tool")
    if args.check:
        bad = problems(fresh, json.loads(SNAPSHOT.read_text()))
        for line in bad:
            print(line, file=sys.stderr)
        return 1 if bad else 0
    SNAPSHOT.write_text(json.dumps(fresh, indent=2, sort_keys=True) + "\n")
    print(f"wrote {SNAPSHOT}")
    return 1 if any(m > TOKEN_LIMIT for m in fresh["per_tool"].values()) else 0


if __name__ == "__main__":
    raise SystemExit(main())
