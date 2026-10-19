# mermia-contracts

Contracts shared by the MermIA backend and its tests.

- `mermia_contracts.db.models`: row models **generated** from the migrated database
  (`python -m mermia_contracts.tools.gen_db_models`). Never edit by hand.
- `mermia_contracts.batch`: the `NormalizedBatch` parser output and its input types.
- `mermia_contracts.db.overrides`: typed shapes for the jsonb columns the architecture documents.

Types marked `PROVISIONAL:` in their docstring depend on report formats that are not verified
yet (Corte Z, "Productos vendidos", "Recetas"): `MenuItemIn`, `ItemSalesIn`, `DailySalesIn`,
`RecipeIn` and `RecipeLineIn`. They may change until the first real parser lands (MR-15,
MR-23). `TicketIn` follows the verified ERP/PMS payload but its adapter is Phase 1b, and
`PurchaseIn` follows CFDI 4.0 fields that are still to validate against the SAT XSD.

Wire format is JSON with snake_case names. Money is integer centavos (`int`, never float or
string), quantities and unit prices are `Decimal` (JSON numbers are read exactly), instants must
carry a time zone and unknown fields are rejected. See the repository `README.md` for commands
and units, and `docs/superpowers/specs/2026-10-18-mr-10-contracts-schema-design.md` for the design.
