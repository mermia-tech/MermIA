"""C6: request and response models, and the action id rule."""

import json
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from pydantic import ValidationError

from mermia_contracts.agent import AgentRequest, AgentResponse, parse_pending_action

EXAMPLES = Path(__file__).parent / "examples" / "agent"
CHANGE = "0f7a1c52-3b6e-7c1a-9d33-000000000001"
OPAQUE_IDS = ["undo_batch", "more_detail", "pcx:1", "PC:abc", "a" * 256]


def _doc(name: str) -> dict[str, Any]:
    doc: dict[str, Any] = json.loads((EXAMPLES / f"{name}.json").read_text())
    return doc


@pytest.mark.parametrize("name", ["request_text", "request_action", "request_media"])
def test_requests_round_trip(name: str) -> None:
    parsed = AgentRequest.model_validate(_doc(name))
    assert AgentRequest.model_validate_json(parsed.model_dump_json()) == parsed


@pytest.mark.parametrize("name", ["response_choices", "response_metric_card"])
def test_responses_round_trip(name: str) -> None:
    parsed = AgentResponse.model_validate(_doc(name))
    assert AgentResponse.model_validate_json(parsed.model_dump_json()) == parsed


@pytest.mark.parametrize(
    "action_id",
    [f"pc:{CHANGE}:{v}" for v in ("approve", "reject", "detail")] + OPAQUE_IDS,
)
def test_valid_action_ids(action_id: str) -> None:
    request = {**_doc("request_text"), "input": {"type": "action", "action_id": action_id}}
    assert AgentRequest.model_validate(request).input.action_id == action_id  # type: ignore[union-attr]


@pytest.mark.parametrize(
    "action_id",
    [
        "pc:not-a-uuid:approve",
        f"pc:{CHANGE.upper()}:approve",
        "pc:{" + CHANGE + "}:approve",
        f"pc:{CHANGE.replace('-', '')}:approve",
        f"pc:{CHANGE}:delete",
        f"pc:{CHANGE}",
        f"pc:{CHANGE}:approve:x",
        "pc:",
        "",
        "a" * 257,
    ],
)
def test_invalid_action_ids(action_id: str) -> None:
    request = {**_doc("request_text"), "input": {"type": "action", "action_id": action_id}}
    with pytest.raises(ValidationError):
        AgentRequest.model_validate(request)


def test_choice_ids_follow_the_same_rule() -> None:
    doc = _doc("response_choices")
    doc["messages"][1]["options"][0]["id"] = "pc:oops:approve"
    with pytest.raises(ValidationError):
        AgentResponse.model_validate(doc)


def test_parse_pending_action() -> None:
    action = parse_pending_action(f"pc:{CHANGE}:reject")
    assert action is not None
    assert (action.change_id, action.verb) == (UUID(CHANGE), "reject")
    assert parse_pending_action("undo_batch") is None


@pytest.mark.parametrize(
    "patch",
    [
        {"channel": "sms"},
        {"input": {"type": "voice", "text": "x"}},
        {"input": {"type": "text", "text": " "}},
        {"input": {"type": "text", "text": "hola", "extra": 1}},
        {"window_open_until": "2026-10-20T08:00:00"},  # no time zone
        {"tenant_id": "tenant-1"},
    ],
)
def test_bad_requests_are_rejected(patch: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        AgentRequest.model_validate({**_doc("request_text"), **patch})


def _choices(options: list[dict[str, str]]) -> dict[str, Any]:
    return {
        "messages": [{"kind": "choices", "text": "x", "options": options}],
        "route": "handler",
    }


@pytest.mark.parametrize(
    "doc",
    [
        _choices([]),
        _choices([{"id": "a", "label": "x" * 25}]),
        _choices([{"id": "a", "label": "x"}] * 11),
        {"messages": [], "route": "handler"},
        {"messages": [{"kind": "text", "text": "x"}], "route": "gpt"},
        {
            "messages": [{"kind": "metric_card", "rpc": "drop_table", "data": {}}],
            "route": "template",
        },
    ],
    ids=["no-options", "long-label", "eleven-options", "no-messages", "bad-route", "unknown-rpc"],
)
def test_bad_responses_are_rejected(doc: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        AgentResponse.model_validate(doc)


def test_handler_route_is_accepted() -> None:
    assert AgentResponse.model_validate(_choices([{"id": "a", "label": "x"}])).route == "handler"
