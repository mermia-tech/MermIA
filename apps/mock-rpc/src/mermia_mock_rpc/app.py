"""POST /rpc/{name}[?variant=]: the request is checked with the RPC's C3 args model and the answer
with its C3 envelope; the answer is one fixed response per RPC (see rpcs.py)."""

import json
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response
from pydantic import TypeAdapter, ValidationError

from mermia_contracts.rpc import RPCS, RpcEnvelope
from mermia_mock_rpc import rpcs

app = FastAPI(title="MermIA mock RPC")


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
    answer = rpcs.build(name, variant)
    adapter.validate_python(answer)  # the answer is sent as it is: it is already plain JSON
    return Response(json.dumps(answer), media_type="application/json")
