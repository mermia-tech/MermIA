"""Column types used by the generated row models.

Units follow spec 5.4: ledger amounts are integer centavos, unit prices are pesos per
unit, percentages are percent points (34.1 means 34.1 %), tax rates are fractions.
Row models read what the database returns, so they validate in lax mode; the stricter
parser-side variants live in batch.py.
"""

from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

Cents = Annotated[int, Field(description="unit=centavos")]
Bytes = Annotated[int, Field(ge=0, description="unit=bytes")]
Quantity = Annotated[Decimal, Field(max_digits=18, decimal_places=6, description="unit=quantity")]
Factor = Annotated[Decimal, Field(max_digits=20, decimal_places=10, description="unit=quantity")]
UnitPricePesosPerBaseUnit = Annotated[
    Decimal,
    Field(max_digits=20, decimal_places=6, description="unit=pesos_per_base_unit"),
]
UnitPricePesosPerPurchaseUnit = Annotated[
    Decimal,
    Field(max_digits=20, decimal_places=6, description="unit=pesos_per_purchase_unit"),
]
PercentPoints = Annotated[
    Decimal, Field(max_digits=7, decimal_places=4, description="unit=percent_points")
]
Fraction = Annotated[Decimal, Field(max_digits=5, decimal_places=4, description="unit=fraction")]
Usd = Annotated[Decimal, Field(max_digits=12, decimal_places=6, description="unit=usd")]


class RowModel(BaseModel):
    """Base of every generated row model: unknown columns are an error."""

    model_config = ConfigDict(extra="forbid", frozen=True)
