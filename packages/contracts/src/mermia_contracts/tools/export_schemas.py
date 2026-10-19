"""Export the C3-C6 contracts as JSON Schema files for the Phase 2 frontend types.

    python -m mermia_contracts.tools.export_schemas [--output DIR] [--check]

One file per RPC (`rpc.<name>.args.json`, `rpc.<name>.response.json`), plus `agent.tools.json`,
`pending.change_proposal.json`, `pending.apply_args.json`, `pending.apply_result.json`, `agent.request.json` and `agent.response.json`. Schemas describe
what the models accept (validation mode). `--check` fails if the committed files differ.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter

from mermia_contracts.agent import AgentRequest, AgentResponse
from mermia_contracts.agent_tools import tool_definitions
from mermia_contracts.pending import ApplyPendingChangeArgs, ApplyResult, ChangeProposal
from mermia_contracts.rpc import RPCS, RpcEnvelope

PACKAGE_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUTPUT = PACKAGE_ROOT / "schemas"


def all_schemas() -> dict[str, Any]:
    schemas: dict[str, Any] = {}
    for name, spec in RPCS.items():
        schemas[f"rpc.{name}.args"] = spec.args.model_json_schema()
        schemas[f"rpc.{name}.response"] = TypeAdapter(RpcEnvelope[spec.data]).json_schema()  # type: ignore[name-defined]
    schemas["agent.tools"] = tool_definitions()
    schemas["pending.change_proposal"] = TypeAdapter(ChangeProposal).json_schema()
    schemas["pending.apply_args"] = ApplyPendingChangeArgs.model_json_schema()
    schemas["pending.apply_result"] = ApplyResult.model_json_schema()
    schemas["agent.request"] = AgentRequest.model_json_schema()
    schemas["agent.response"] = AgentResponse.model_json_schema()
    return schemas


def render(schema: Any) -> str:
    return json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def stale_files(output: Path) -> list[str]:
    """Names of files that are missing, different or no longer produced."""
    wanted = {f"{name}.json": render(s) for name, s in all_schemas().items()}
    stale = [
        n
        for n, text in wanted.items()
        if not (output / n).exists() or (output / n).read_text() != text
    ]
    stale += [
        p.name
        for p in output.glob("*.json")
        if p.name not in wanted and p.name != "tool_tokens.json"
    ]
    return sorted(stale)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)

    if args.check:
        stale = stale_files(args.output)
        if stale:
            print(f"stale schemas, run export_schemas: {', '.join(stale)}", file=sys.stderr)
            return 1
        print(f"{args.output} is up to date.")
        return 0
    args.output.mkdir(exist_ok=True)
    for name, schema in all_schemas().items():
        (args.output / f"{name}.json").write_text(render(schema))
    print(f"wrote {len(all_schemas())} schemas to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
