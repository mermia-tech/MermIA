"""POST /rpc/{name}[?variant=]: the request is checked with the RPC's C3 args model and the answer
with its C3 envelope; the answer is one fixed response per RPC (see rpcs.py)."""

import json
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import FastAPI, HTTPException, Request, Response
from pydantic import TypeAdapter, ValidationError

from mermia_contracts.rpc import RPCS, RpcEnvelope
from mermia_mock_rpc import rpcs

app = FastAPI(title="MermIA mock RPC")


def _json(value: Any) -> Any:
    """What json.dumps cannot do alone. A Decimal is a JSON number (pydantic would write a string):
    the C3 examples use numbers; four decimals at most, so a float prints it exactly."""
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    return str(value) if isinstance(value, UUID) else value.isoformat()


@app.post("/rpc/{name}")
async def call(name: str, request: Request, variant: str | None = None) -> Response:
    if name not in RPCS:
        raise HTTPException(404, f"unknown RPC {name!r}")
    if variant is not None and variant not in rpcs.VARIANTS[name]:
        raise HTTPException(422, f"variant must be one of {list(rpcs.VARIANTS[name])}")
    try:
        RPCS[name].args.model_validate_json(await request.body() or b"{}")
    except ValidationError as e:
        raise HTTPException(422, json.loads(e.json(include_url=False))) from e
    adapter: TypeAdapter[Any] = TypeAdapter(RpcEnvelope[RPCS[name].data])  # type: ignore[misc,arg-type]
    answer = adapter.validate_python(rpcs.build(name, variant))
    body = json.dumps(adapter.dump_python(answer, by_alias=True), default=_json)
    return Response(body, media_type="application/json")
