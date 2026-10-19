"""C5: the five PendingChange kinds and the typed proposal the confirmation service stores.

`pending_change.kind` stays `text` in the database (MR-10 decision C7); this module is where
the allowed values live. Only the five kinds of 08 C5 exist: `ingredient_alias.confirm` and
`settings.update` (09 section 5.1) are out of scope.

`apply_pending_change(id, user_id)` follows MR-10 spec 7.5.7: `EXECUTE` for `service_role` only, the
backend resolves `user_id` (an `app_user.id`) from the channel identity, and the database
verifies everything else. This module defines only the call and its result. Who may approve is
read from `pending_change.required_role` and `membership.can_approve` (09 section 5.1), so there
is deliberately no role table here. The SQL body and its pgTAP tests are MR-32.
"""

import datetime as dt
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, model_validator

from mermia_contracts.batch import Cents, Model, Quantity, RecipeLineIn, Text, UnitPrice
from mermia_contracts.db.models import IngredientPriceSource, PendingChangeStatus


class PendingKind(StrEnum):
    ingredient_price_set = "ingredient_price.set"
    recipe_upsert = "recipe.upsert"
    menu_item_price_set = "menu_item_price.set"
    import_batch_approve = "import_batch.approve"
    import_batch_rollback = "import_batch.rollback"


TARGET_TYPE: dict[PendingKind, str] = {
    PendingKind.ingredient_price_set: "ingredient",
    PendingKind.recipe_upsert: "menu_item",
    PendingKind.menu_item_price_set: "menu_item",
    PendingKind.import_batch_approve: "import_batch",
    PendingKind.import_batch_rollback: "import_batch",
}
"""`pending_change.target_type` for each kind; `target_id` is that table's id."""


class IngredientPriceSet(Model):
    unit_price: UnitPrice
    effective_from: dt.date
    source: IngredientPriceSource = IngredientPriceSource.manual


class RecipeUpsert(Model):
    """PROVISIONAL like RecipeLineIn: the lines mirror the "Recetas" import."""

    yield_qty: Quantity
    lines: Annotated[list[RecipeLineIn], Field(min_length=1)]


class MenuItemPriceSet(Model):
    price_gross: Cents
    effective_from: dt.date


class NoPayload(Model):
    """Approve and rollback act on the batch the target points to; the why is `reason`."""


class _Proposal(Model):
    target_id: UUID
    reason: Text | None = None


class IngredientPriceSetProposal(_Proposal):
    kind: Literal[PendingKind.ingredient_price_set]
    values: IngredientPriceSet


class RecipeUpsertProposal(_Proposal):
    kind: Literal[PendingKind.recipe_upsert]
    values: RecipeUpsert


class MenuItemPriceSetProposal(_Proposal):
    kind: Literal[PendingKind.menu_item_price_set]
    values: MenuItemPriceSet


class ImportBatchApproveProposal(_Proposal):
    kind: Literal[PendingKind.import_batch_approve]
    values: NoPayload = NoPayload()


class ImportBatchRollbackProposal(_Proposal):
    kind: Literal[PendingKind.import_batch_rollback]
    values: NoPayload = NoPayload()


ChangeProposal = Annotated[
    IngredientPriceSetProposal
    | RecipeUpsertProposal
    | MenuItemPriceSetProposal
    | ImportBatchApproveProposal
    | ImportBatchRollbackProposal,
    Field(discriminator="kind"),
]
"""What propose_change becomes once validated: the payload is checked against its kind."""


class ApplyCode(StrEnum):
    """Outcomes of apply_pending_change. Business outcomes are returned, never raised."""

    applied = "applied"
    already_applied = "already_applied"  # idempotent: a second tap changes nothing
    not_found = "not_found"  # no such change, or the user is not a member of its tenant
    forbidden_role = "forbidden_role"  # required_role, can_approve or location authorization
    not_pending = "not_pending"
    expired = "expired"
    conflict = "conflict"  # the target changed since the proposal (version != base_version)
    failed = "failed"  # the write itself failed and was rolled back


class ApplyPendingChangeArgs(Model):
    """`user_id` is the approver's `app_user.id`, resolved by the backend (a service_role call)."""

    id: UUID
    user_id: UUID


_STATUS_FOR_CODE: dict[ApplyCode, set[PendingChangeStatus] | None] = {
    ApplyCode.applied: {PendingChangeStatus.applied},
    ApplyCode.already_applied: {PendingChangeStatus.applied},
    ApplyCode.expired: {PendingChangeStatus.expired},
    ApplyCode.conflict: {PendingChangeStatus.conflict},
    ApplyCode.failed: {PendingChangeStatus.failed},
    ApplyCode.not_pending: set(PendingChangeStatus)
    - {PendingChangeStatus.pending, PendingChangeStatus.applied},
    ApplyCode.forbidden_role: set(PendingChangeStatus),  # the row was readable: current status
    ApplyCode.not_found: None,  # nothing about the row is revealed
}


class ApplyResult(Model):
    """What the confirmation service gets back. `status` is the row's status after the call.

    Persisted effects per code (the SQL is MR-32): `applied` commits the write, the status and
    the audit rows together; `expired`, `conflict` and `failed` set that status and audit it
    without touching the target (`failed` rolls the write back first); every other code
    changes nothing. A state change happens only after the authorization check passed.
    """

    code: ApplyCode
    pending_change_id: UUID
    status: PendingChangeStatus | None = None
    message: str | None = None

    @property
    def ok(self) -> bool:
        return self.code in (ApplyCode.applied, ApplyCode.already_applied)

    @model_validator(mode="after")
    def _status_fits_code(self) -> "ApplyResult":
        allowed = _STATUS_FOR_CODE[self.code]
        if allowed is None:
            if self.status is not None or self.message is not None:
                raise ValueError(f"{self.code} reveals nothing: no status, no message")
        elif self.status not in allowed:
            raise ValueError(f"status {self.status} does not fit code {self.code}")
        return self
