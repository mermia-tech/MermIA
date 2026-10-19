"""C5: the five PendingChange kinds and the typed proposal the confirmation service stores.

`pending_change.kind` stays `text` in the database (MR-10 decision C7); this module is where
the allowed values live. Only the five kinds of 08 C5 exist: `ingredient_alias.confirm` and
`settings.update` (09 section 5.1) are out of scope.

The `apply_pending_change` contract (arguments, result codes, approver roles) is not here yet:
it waits for a decision on the authorization model, see the MR-11 report.
"""

import datetime as dt
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field

from mermia_contracts.batch import Cents, Model, Quantity, RecipeLineIn, Text, UnitPrice
from mermia_contracts.db.models import IngredientPriceSource


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
