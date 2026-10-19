# 04 - Glossary and open questions

See `00-overview-and-prompting.md` for pack tags and snapshot date.

## Business glossary

| Term | Meaning |
|---|---|
| SR / Soft Restaurant | POS by National Soft (versions 8-12; SR 12 has Analytics 3.0, SR Admin app, Corte Z email). The first data source |
| Corte Z / corte de caja | End-of-shift cash/sales close report. SR 12 can email it automatically; its contents are **unverified** |
| Productos vendidos (en general) | SR export of units/sales per product; core MVP report; columns **unverified** for SR 10-12 |
| ERP/PMS module (Enlace ERP/PMS) | Paid SR module that POSTs each sale as JSON to a third-party endpoint; MermIA's target ingestion; price **unverified** |
| CFDI | Mexican electronic invoice (XML, version 4.0); used to capture supplier prices. SAT = tax authority; PAC = authorised stamping provider |
| RFC | Mexican taxpayer id (a company's or a supplier's) |
| IVA | VAT, 16% (`tax_rate` 0.1600 as a fraction) |
| Receta / insumo / platillo | Recipe / ingredient / dish |
| Food cost % | Theoretical ingredient cost / net price, stored as percent points (34.1 = 34.1%) |
| Margen, "pesos found" | The paid value: margin leaks and price suggestions expressed in pesos |
| Menu engineering (Kasavana-Smith) | Quadrant classification of items by popularity and margin |
| Concierge costing | Founders capture the top-10 dishes' recipes during onboarding |
| Aviso de privacidad / LFPDPPP | Privacy notice / Mexican data-protection law (2025 version); MermIA = *encargado* for restaurant data, *responsable* for WhatsApp user data (likely, `11` A17) |
| Mesero / gerente / dueño | Waiter / manager / owner |
| Deshacer | "Undo" button after an upload (rolls back the batch) |
| "Ver detalle" | Button on the weekly report to get suggestions/details |
| Márgenes, Cadena, Compras | Proposed plans (MXN 899 / 799-699 / 449 per location per month) - a pricing hypothesis |
| Pilot | First live restaurant (not yet identified in the repo) |
| Meta Business Verification, +52 number, templates (utility/marketing), 24-hour window | WhatsApp Cloud API prerequisites and messaging rules (`04`) |

## System glossary

| Term | Meaning |
|---|---|
| Tenant / location / membership | Customer company / its restaurant / user's role and location scope |
| Slice (`slice_key`) | Unit a batch covers, e.g. location + report type + period; one `applied` batch per slice |
| `NormalizedBatch` | Pydantic parser output; grain in `ticket, item_daily, daily, purchase, catalog` |
| Grain | Whether rows are tickets or aggregates |
| Batch states | `received, rejected, parsed, needs_review, applied, rolled_back, superseded` |
| `pending_change` / `apply_pending_change` | Proposed write awaiting human approval / the function that applies it (not yet written) |
| Access class T/L/F/LP/X | RLS class of a table (see `01`) |
| Claims | JWT fields `tenant_id`, `app_role`, `location_ids` read by RLS |
| `app` schema | Non-exposed schema with helpers and enums; `public` = domain tables only |
| `finish_table` | SQL helper every table migration must call |
| Broker agent / router / validator | Lean LLM design: templates first, LLM with 12 tools, numbers checked in code |
| Haiku 5.5 / Sonnet 5.5 / GPT-6 Luna | Primary / escalation / fallback LLMs proposed in `13` |
| Dev A / Dev B | Data owner / conversation owner |
| C1..C8 | Contract names in `08` (schema, NormalizedBatch, RPC interfaces, tools, PendingChange kinds, AgentRequest/Response, fixtures, SR samples) |
| Provisional type | Contract type whose source report format is unverified (docstring starts `PROVISIONAL:`) |
| V1..V34, A1..A24, AMB-1..7, O2'..O7 | Evidence ids, owner-review items and open items in the MR-10 spec |
| MR-n | Ticket id = GitHub issue number |

## Contradictions and drift found while building this pack

| # | Finding | Evidence |
|---|---|---|
| 1 | MR-10 branch lacks MR-9; merge conflicts in `.gitignore` and `README.md`; contracts has its own Python pin and lockfile while main has a uv workspace and mypy `files = ["apps"]` | `git merge-tree`; `origin/main:pyproject.toml` |
| 2 | Spec calls the SQL helper `app.secure_table`; code and README use `app.finish_table` | spec 5.1, 6.1, A16 vs `foundations.sql:157` |
| 3 | Spec header says branch "not yet created" and "implemented" in the same line | spec line 3 |
| 4 | Ticket #10 body and `08`'s original text placed migrations in `packages/contracts`; owner chose root `supabase/`. Issue bodies #10, #11, #13, #14 may still say the old path | spec C1, §11, O5 |
| 5 | `pending_change.kind`: 5 kinds in `08` C5 vs 7 in `09` §5.1 | spec C7; kept as `text` |
| 6 | Issue #14 ("migrations, RLS and security tests") overlaps heavily with what MR-10 already delivered | issue list vs migrations/tests |
| 7 | Issue #9 open though PR #48 merged | `gh` |
| 8 | Spec says external docs forbid a minted JWT in the `apikey` header; the local stack accepted it | V17, C13 |
| 9 | `09` says "money is bigint centavos" but unit prices are per base unit (needs decimals) | resolved by D6 |
| 10 | Kickoff says weekly report default; template/day-of-week and who decides remain F12 | `11` |

## Open questions needing human confirmation

**Product / business** (kickoff `11` F1-F13 are the authoritative list; still open unless a ticket shows otherwise)
1. Who is the pilot restaurant, which SR version/edition, are recipes/costs in SR? (F5, P1-P6, O1)
2. Real sample exports E1-E10 (Productos vendidos, Corte Z, cancelaciones, descuentos, formas de pago, ventas por mesero, recetas, costos, WhatsApp-delivered files). All parsers depend on them.
3. Pricing test MXN 449 vs 899, charge from month 2? Which founder owns customers? Defer Phase 3 POS to a gate? Weekly default? (F6-F8, F12)
4. Who may approve DB changes per kind, and is per-batch approval OK? (F13, C2)
5. Legal: entity/RFC/proof of address for Meta; aviso de privacidad; SR EULA; Anthropic data retention/ZDR; IVA and tip treatment in margin math. (F1, F9, T4-T6)
6. Is the 4-week calendar from `08` still the plan, and is the 2-dev split unchanged?

**Technical**
7. Which service issues JWT claims (Supabase auth hook vs backend-minted), where is the signing key kept, what does `sub` carry for WhatsApp-only users? (spec O2', O3)
8. Should `pg_graphql` be disabled on the hosted project? (A24, O7)
9. Have the owner's pending reviews A19-A24 been approved? (spec §16.3)
10. How and when does `packages/contracts` join the root workspace (lock, Python pin, mypy/ruff config)? Who resolves the merge conflicts?
11. Should CI set `MERMIA_DB_URL`/REST variables so model-freshness and exposure tests run?
12. Are ticket-level facts to be deduplicated by `(tenant_id, source_id, external_id)`? Needs a decision in MR-16.
13. Agent tool contract (12 tools), RPC envelope, `PendingChange` kind list (ticket #11).
14. Do range exports exist for "Productos vendidos" (period columns) or only daily? Is cancellation granularity amount, count or both? (spec A2, A11)
15. Is the Phase 2 TypeScript type-generation pipeline viable? (`09` D9: untested)

**Unknown / possibly outdated**
- All pricing, hosting, WhatsApp and LLM cost numbers and model names in `docs/kickoff/` are dated 2026-10-15 and labelled verified/likely/unverified there; recheck before use.
- Competitor and market claims (SR ~4% share, Toast IQ adoption) come from vendor statements.
