# 07 - Roadmap (Phases 1 to 3)

Date: 2026-10-15. Durations are **opinion** for a team of 2 devs. Facts point to 01, 03, 04, 13 and `research/pos-legal-stack-notes.md`. Architecture: `09-architecture.md`. First 4 weeks in detail: `08-mvp-4-week-plan.md`.

## Overview

| Phase | Window (from kickoff) | Goal | Reuses |
|---|---|---|---|
| 1 MVP | Weeks 0-4 | One pilot restaurant live on WhatsApp | - |
| 1b Harden | Weeks 5-12 | 5-10 paying restaurants; less manual upload | Everything from Phase 1 |
| 2 Dashboard | Months 3-6 | Mobile-first dashboard; automatic ingestion; Phase 3 spikes | Schema, metric RPCs, `pending_change`, auth/RLS, agent core, contracts |
| 3 POS (gated) | **Decision gate at about month 9** (06 §4). If it passes: about 5-8 months of build (**unverified** estimate, notes 1.7), so roughly months 9-17 | Own offline-first POS writing to the same model; if the gate fails, intelligence across POSes plus purchasing (06 §4) | All of the above, plus the dashboard UI components |

## Phase 1: WhatsApp agent MVP (weeks 0-4)

| # | Milestone | When | Done when |
|---|---|---|---|
| M0 | Long-lead items started | Day 1 | Meta Business Verification submitted; number registered; pilot samples requested; templates submitted; ERP/PMS module quote requested (08, week 0) |
| M1 | Contracts frozen | Day 2 | Schema, `NormalizedBatch`, RPC interfaces, tool definitions, `PendingChange`, fixtures merged (08) |
| **M2** | **LLM selection (section H)** | **Day 5** | 40-question eval run 3× on at least 4 models against mock tools. Pass thresholds from 13 H3: tool selection ≥95%, args ≥95%, **numeric fidelity 100%**, tone ≥4/5, p95 ≤8 s. Primary, escalation and fallback chosen; decision memo written. **Gate: no agent code merges before M2** |
| **M3** | **Token-cost design (section I) validated** | **Day 5** | Real token counts of the Spanish prefix measured (`count_tokens`); prefix ≤3k tokens and byte-identical across tenants; cost per Haiku-routed question ≤US$0.003 measured from `usage`; per-tenant caps and `llm_usage` schema merged |
| M4 | First real parse | Day 5 | A pilot SR export becomes an applied batch and matches the SR totals |
| M5 | Integration | Day 10 | Agent runs on real RPCs; eval re-run with no regression |
| M6 | Dress rehearsal | Day 15 | Manual test script passes (08) |
| M7 | Pilot live | Day 16 | Manager uploads daily; owner gets answers and the weekly report |

**Exit criteria (to start Phase 1b):** pilot success criteria in 08 met over 4 weeks, or the failures understood and fixed. Also: zero confirmed wrong numbers; LLM cost ≤US$1 per restaurant per month; WhatsApp cost reconciled with Meta's invoice within 5%; owner willing to pay.

## Phase 1b: harden and reach 5-10 restaurants (weeks 5-12)

| Milestone | Content |
|---|---|
| Less manual upload | Corte Z email to our inbox for every SR 12 customer (the pilot's goes live in week 3 if it runs SR 12, per 03 and 08); **SR ERP/PMS push adapter** (ticket-level JSON to our endpoint) for restaurants on SR 11+ that buy the module; shadow mode next to manual uploads, reconcile totals, then turn off reminders |
| Cost capture | CFDI XML parser (email first; WhatsApp XML only if the M0 test passed); nota photo OCR with `needs_review`; recipe capture by chat for the top 10 dishes |
| Product | Daily report opt-in; multi-location comparisons; more templates from unanswered questions |
| Ops | Admin onboarding script and runbook; per-tenant cost dashboard (Metabase); monthly invoice reconciliation |
| Legal | Aviso de privacidad, encargado clause and pilot contract reviewed by a lawyer; SR EULA read (connector decision input) |

**Exit criteria:** ≥5 paying restaurants; ≥90% of business days with data; ≥30% of data arriving without the manager sending a file (email or push); cost per restaurant within the 09 section 8 table; churn 0 after 1 month.

## Phase 2: mobile-first dashboard (months 3-6)

| Milestone | Content |
|---|---|
| Dashboard v1 | React + Vite PWA, Supabase Auth (phone OTP or magic link), the same 11 RPCs as cards; owner-chosen KPIs saved in `tenant.settings` |
| Approvals in web | `pending_change` inbox, diff view, bulk approve for import change sets, audit view |
| Agent in web | The same agent core via `AgentResponse` (`metric_card` rendered natively) |
| Ingestion | Local connector only where the ERP push is not possible, or for recipes and inventory, after legal review and written customer consent (03 B.3) |
| Actual vs theoretical cost | Purchases from CFDI plus inventory counts (simple weekly count for the top 20 ingredients) |
| Phase 3 spikes | PowerSync (or similar) on one non-critical table; ESC/POS LAN printer test; PAC sandbox (Facturapi); Mercado Pago Point sandbox |

**Exit criteria:** ≥50% of owners open the dashboard weekly; Phase 3 gate inputs collected (POS-switch demand asked in every account review); ≥20 paying restaurants; spikes answer "web-only PWA or native shell" and "which sync engine"; positive unit economics at the current price (`10-business-model.md`).

## Phase 3: decision gate (about month 9), then own POS only if it passes

**Gate (06 §4):** at least 150 paying locations, monthly churn under 3%, at least 30% of owners asking for a POS switch, and funding for at least 2 more engineers. Until the gate: no public POS plans (they would turn SR and its distributors, our data source and best channel, into rivals); only the cheap Phase 2 spikes and the POS-ready schema. **If the gate fails:** Phase 3 becomes intelligence across POSes (a second POS as a source, Tenzo model) plus purchasing and supplier features (MarketMan/xtraCHEF model, 02).

If the gate passes, the build (about 5-8 months for 2 devs, **unverified**):

| Milestone | Content (notes section 1) |
|---|---|
| Core POS | Menu, tables, orders, checks, split bills, tips, roles (cashier, waiter); writes `sale_ticket` / `sale_line` / `payment` as `source = mermia_pos` |
| Offline-first | Event-sourced orders, device UUIDs, sync engine from the Phase 2 spike, server-side total recomputation |
| Hardware | ESC/POS printers via print relay or native shell; drawer; KDS screen |
| Fiscal | CFDI via PAC, factura global, autofactura portal |
| Payments, delivery | Mercado Pago Point first, then Clip; delivery via an aggregator |
| Migration path | Restaurant runs our POS alongside SR for 1-2 weeks; history stays because both are sources in the same model |

**Exit criteria (first sellable version):** 3 restaurants run a full service week on our POS with zero lost orders during a forced 2-hour offline test; every CFDI stamped correctly; the agent and dashboard show POS data with no changes to the metrics code.

## What each phase reuses

| Built in | Reused by Phase 2 | Reused by Phase 3 |
|---|---|---|
| Normalized schema (ticket + aggregate grains, `source`, `external_id`, UUIDv7, centavos) | Dashboard reads it | POS writes it |
| Metric RPCs | Dashboard cards | POS reports and in-POS agent |
| `pending_change`, `audit_log`, role matrix | Web approvals | Manager overrides (PIN), audit trail |
| Agent core and the `AgentRequest`/`AgentResponse` contract | Web chat | POS assistant |
| Ingestion batches and adapters | Connector and ERP push are new adapters | POS migration keeps SR history |
| Contracts, fixtures, eval harness, CI | Same | Same |
| Cost metering | Same, plus dashboard hosting | Plus PAC and sync-engine costs |

## Key metrics per phase

| Metric | Phase 1 | Phase 1b | Phase 2 | Phase 3 (if gate passes) |
|---|---|---|---|---|
| Data coverage (business days with data) | ≥85% | ≥90% | ≥95% | 100% (live) |
| Automatic ingestion share | 0% | ≥30% | ≥60% | 100% |
| Owner weekly active (WhatsApp or web) | pilot yes | ≥70% | ≥70% | ≥80% |
| Confirmed wrong numbers | 0 | 0 | 0 | 0 |
| Changes confirmed through `pending_change` per restaurant per month | ≥1 | ≥2 | ≥4 | n/a (operational) |
| Paying restaurants | 0-1 | 5-10 | ≥20 | ≥3 on POS |
| LLM cost per restaurant per month (typical) | ≤US$1 | ≤US$1 | ≤US$1 | ≤US$1.5 |
| WhatsApp cost per restaurant per month | ≤US$1.5 | ≤US$1.5 | ≤US$1.5 | ≤US$1.5 |
| Total variable cost as % of price | track | <15% | <15% | <20% (incl. PAC, sync) |

## Cost tracking in every phase

| Phase | What is tracked | Alert or review |
|---|---|---|
| 1 | `llm_usage` per call (tokens, cache, route, cost); `message_log` with Meta pricing category; caps per tenant | Daily review in week 4; alerts from 13 I4 (3× average, cache hit <60%, validator rejects >2%) |
| 1b | + monthly reconciliation with the Anthropic Console and Meta invoice; Metabase cost per tenant | Monthly; difference >5% means a bug in the price table |
| 2 | + hosting allocated per tenant; dashboard egress | Monthly cost review vs price |
| 3 | + PAC stamps, sync engine, payment-terminal fees | Monthly; per-location unit economics |

Re-run the eval (and re-check prices) on every model release and every prompt or tool change. Haiku 5.5 is 8 days old (13), so a better or cheaper model may change routing within months.
