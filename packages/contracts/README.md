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

## MR-11 contracts (C3-C6)

- `rpc.py` (C3): the 11 read RPCs, their arguments and the `{ok, data, error, flags, meta}` envelope.
  `Figure.raw` follows `METRIC_UNIT` (money in centavos, counts, percent points); `Pct` is a calculated
  percentage (not a column); `compare_periods` carries `period_a` and `period_b`; `get_dish_margin`
  is on the net price (without IVA), the adopted definition. See `docs/superpowers/specs/2026-10-18-mr-11-contracts-rpc-tools-design.md` section 7.
  `ok=true` needs `data` and no `error`; `ok=false` needs `error` and no `data`.
- `agent_tools.py` (C4): the 12 agent tools, derived from C3 plus `propose_change`, whose `values` is typed
  per kind (price in the user's unit: `g`, `kg`, `ml`, `l`, `pza`; the confirmation service converts, not this package).
- `pending.py` (C5): the five `PendingChange` kinds and the typed proposal. `apply_pending_change`
  is the call and its result only (service_role model of MR-10 spec 7.5.7; SQL is MR-32).
- `agent.py` (C6): `AgentRequest` / `AgentResponse`. `pc:<uuid>:approve|reject|detail` action ids
  are validated; any other id is opaque.

```bash
uv run python -m mermia_contracts.tools.export_schemas           # write schemas/*.json (Phase 2 types)
uv run python -m mermia_contracts.tools.export_schemas --check   # fail if they are stale
ANTHROPIC_API_KEY=... uv run python -m mermia_contracts.tools.measure_tool_tokens          # later, MR-20: write schemas/tool_tokens.json
ANTHROPIC_API_KEY=... uv run python -m mermia_contracts.tools.measure_tool_tokens --check  # re-measure and compare
```

**Token budget: NOT MEASURED YET (deferred to MR-20; not met by MR-11, and not a closing requirement of it).** Each tool may add at most 125 tokens (`agent_tools.TOKEN_LIMIT`,
08 C4); nobody has checked that the current tools fit, and a rough size estimate suggests some do
not. The measurement is deferred to the LLM eval ticket (proposed: MR-20, the day-5 gate and the
M3 milestone in `docs/kickoff/07-roadmap.md`). The cost of a tool is `count([B, t]) - count([B])`
with the Anthropic `count_tokens` API and a fixed baseline tool `B`: the API adds tool-use
scaffolding once per request, and the difference cancels it.
Typed `propose_change.values` (spec section 7, D15) grew that tool's schema from 519 to 2397
characters (both as compact JSON, `separators=(",", ":")`; the same schemas are 563 and 2594 with
the default separators). That is a size guard in a test, not a token measurement.

To run it later: set `ANTHROPIC_API_KEY`, run `measure_tool_tokens` (above; the SDK is a dev
dependency of this package), review `schemas/tool_tokens.json`, then run `uv run pytest`: the budget tests, skipped while the
snapshot is absent, start running (and `-m tokens` re-measures live).
The snapshot stores the hash of the tool definitions, so changing a tool afterwards needs a new
measurement. If a tool is over 125, decide then how to cut it; the limit itself is not changed
without the owner's approval.

**Owners.** `.github/CODEOWNERS` requests a review from `@p0sin` and `@campolloram` for this
package. Owners on one line are alternatives: either one satisfies code-owner review, and `main`
has no branch protection that requires it.
