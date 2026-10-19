"""C6: the channel-agnostic agent interface (09 section 4.3).

The TypeScript sketch in 09 uses camelCase; the wire format here is snake_case like every
other contract. WhatsApp turns `choices` into buttons (up to 3, 20-character labels) or a
list; that limit belongs to the channel adapter, not to this contract.
"""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import AfterValidator, AwareDatetime, Field, JsonValue

from mermia_contracts.batch import Model, Text
from mermia_contracts.db.models import Channel
from mermia_contracts.rpc import RPCS

AgentRoute = Literal["handler", "template", "haiku", "sonnet", "fallback"]
"""LlmRoute plus `handler` (button taps are answered without a template or a model)."""

PENDING_VERBS = ("approve", "reject", "detail")


class PendingAction(Model):
    change_id: UUID
    verb: Literal["approve", "reject", "detail"]


def parse_pending_action(action_id: str) -> PendingAction | None:
    """`pc:<uuid>:<verb>` -> PendingAction; any other id is opaque and gives None.

    The id is only a lookup key: the confirmation service re-checks it against the database.
    """
    if not action_id.startswith("pc:"):
        return None
    parts = action_id.split(":")
    if len(parts) != 3 or parts[2] not in PENDING_VERBS:
        raise ValueError("a pc: action id must be pc:<uuid>:approve|reject|detail")
    try:
        change_id = UUID(parts[1])
    except ValueError:
        raise ValueError("a pc: action id must carry a valid UUID") from None
    if str(change_id) != parts[1]:
        raise ValueError("a pc: action id must carry a lowercase hyphenated UUID")
    return PendingAction(change_id=change_id, verb=parts[2])  # type: ignore[arg-type]


def _check_action_id(action_id: str) -> str:
    parse_pending_action(action_id)
    return action_id


ActionId = Annotated[str, Field(min_length=1, max_length=256), AfterValidator(_check_action_id)]
"""A button or list-row id (256: WhatsApp limit). `pc:` ids are validated; others are opaque."""


class TextInput(Model):
    type: Literal["text"]
    text: Text


class ActionInput(Model):
    type: Literal["action"]
    action_id: ActionId


class MediaInput(Model):
    type: Literal["media"]
    raw_file_id: UUID


AgentInput = Annotated[TextInput | ActionInput | MediaInput, Field(discriminator="type")]


class AgentRequest(Model):
    tenant_id: UUID
    user_id: UUID
    location_ids: list[UUID]
    channel: Channel
    conversation_id: UUID
    input: AgentInput
    window_open_until: AwareDatetime | None = None
    """WhatsApp only: end of the 24-hour free-form window; null on other channels."""


class TextMsg(Model):
    kind: Literal["text"]
    text: Text


class Choice(Model):
    id: ActionId
    label: Annotated[Text, Field(max_length=24)]


class ChoicesMsg(Model):
    kind: Literal["choices"]
    text: Text
    options: Annotated[list[Choice], Field(min_length=1, max_length=10)]


def _known_rpc(name: str) -> str:
    if name not in RPCS:
        raise ValueError(f"unknown rpc {name!r}")
    return name


class MetricCardMsg(Model):
    kind: Literal["metric_card"]
    rpc: Annotated[str, AfterValidator(_known_rpc)]
    data: JsonValue
    """The RPC's `data` as returned; web and POS render it, WhatsApp flattens it to text."""


AgentMessage = Annotated[TextMsg | ChoicesMsg | MetricCardMsg, Field(discriminator="kind")]


class AgentResponse(Model):
    messages: Annotated[list[AgentMessage], Field(min_length=1)]
    route: AgentRoute
    usage_id: UUID | None = None
