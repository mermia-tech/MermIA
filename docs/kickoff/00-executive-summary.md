# 00 - Executive summary

Date: 2026-10-15. One page. Facts carry a label (**verified** / **likely** / **unverified**) and point to the detail file; everything under "We recommend" and "Where we disagree" is opinion.

## We recommend

Build Phase 1 in the shape you planned: a WhatsApp agent, a POS-agnostic data model, a lean broker agent and human-approved writes. Five changes:

1. **Sell margins and leaks, not sales Q&A.** Recipe costing, margin and price-shock alerts, price suggestions, and waiter-level leak patterns in pesos are the paid value. Sales Q&A and per-event cancellation/discount alerts are free in SR 12, so we include Q&A in every plan and skip the per-event alerts. Feature-by-feature view vs SR and Toast: [14](14-product-features.md) ([06](06-feedback-and-alternatives.md), [10](10-business-model.md)).
2. **Ingestion:** for the MVP, WhatsApp upload plus an email inbox, which also receives the automatic Corte Z email from SR 12. **Target:** the official SR ERP/PMS JSON push, from Phase 1b. **Fallback:** a local DB connector, only after legal review ([03](03-data-ingestion-and-costing.md) B.4, [09](09-architecture.md) §10).
3. **Reports and model:** a weekly report by default, with daily as an opt-in. Claude Haiku 5.5 as the primary model and Sonnet 5.5 for escalation, both gated by a 40-question eval on day 5 ([13](13-llm-and-token-strategy.md) H4).
4. **Pricing and go-to-market:** Márgenes at **MXN 899** per location per month (+IVA). Cadena at 799, or 699 from 5 locations. Compras at 449 (price capture and price-shock alerts, no recipes) replaces the old sales-only plan. A setup fee of MXN 2,500. Test 449 against 899 in the pilot. Lead with chains of 2-5 locations, sold through SR distributors ([10](10-business-model.md)).
5. **Phase 3 POS is a decision gate at about month 9**, not a commitment ([06](06-feedback-and-alternatives.md) §4, [07](07-roadmap.md)).

**Timeline:** contracts frozen on day 2, LLM eval gate on day 5, integration on day 10, dress rehearsal on day 15, and the **pilot live on day 16** ([08](08-mvp-4-week-plan.md)).

## The 5 most important findings

| # | Finding | Label / source |
|---|---|---|
| 1 | **SR already has sanctioned automatic data paths.** The ERP/PMS module POSTs every sale as JSON: lines, discounts, payments and tips (SR 11+, paid module, price **unverified**). SR 12 also emails the Corte Z automatically (format **unverified**). The daily manual upload doesn't have to be the backbone | **verified** [01](01-soft-restaurant-research.md) §2, §5 |
| 2 | **SR is about 4% of the market, not "most restaurants."** The vendor claims 23,000+ restaurants against 600,000+ in Mexico. No independent share data exists, so the brief's premise is **unverified**. SR is a good wedge, but a small market | **verified** (vendor claim) [01](01-soft-restaurant-research.md), [06](06-feedback-and-alternatives.md) #1 |
| 3 | **SR already gives sales insight away free**: the SR Admin app, Analytics 3.0, WhatsApp cortes and anti-fraud alerts. Kavasoft sells an AI assistant over SR data ("CatIA"), but it is focused on wine cellars. We found nobody selling cost and margin intelligence on WhatsApp for SR users | **verified** [01](01-soft-restaurant-research.md), [02](02-competitive-landscape.md); the gap is **likely** |
| 4 | **Software costs per restaurant per month are small:** about US$0.66 for the LLM (**likely**, design model), US$0.81-1.43 for WhatsApp (**verified** rates; service messages are billable since 2026-10-01, with 1,000 free per number) and US$1.4-4 for hosting (**unverified**). Human support is the real cost. Gross margin is 50-80% | [13](13-llm-and-token-strategy.md) I3, [04](04-whatsapp-platform.md) §9, [09](09-architecture.md) §8, [10](10-business-model.md) §3 |
| 5 | **Toast IQ proves the model works.** Over 50% of Toast locations used it within about 4 months. The money comes from paid action agents, not the chat. Its pricing agent is still in early access, so the cost-side niche is open | **verified** [02](02-competitive-landscape.md) |

## Biggest risks

| Risk | Mitigation | Detail |
|---|---|---|
| The manager stops uploading, and with no data there is no product | Point the SR 12 Corte Z email at our inbox from week 3. Add the ERP/PMS push in Phase 1b. Until then: reminders, friendly replies to wrong files, and the owner alerted after 2 missed days | [05](05-risks-and-friction.md) #1 |
| Cost data is missing or stale, and margins are the paid value | We capture the top-10 dishes ourselves (concierge), paid for by the setup fee. Use CFDI XML for prices. Every margin carries a confidence tag | [05](05-risks-and-friction.md) #5, [03](03-data-ingestion-and-costing.md) C |
| Willingness to pay is low (SR Admin is free; Mercado Pago POS costs MXN 149) | Sell "pesos found." Charge from month 2 of the pilot. Test two price points | [05](05-risks-and-friction.md) #8, [10](10-business-model.md) |
| One wrong number kills the owner's trust | Code produces every number and a validator rejects any number the tools didn't return. 100% numeric fidelity is a release gate. Haiku 5.5 is 8 days old and unproven | [05](05-risks-and-friction.md) #6, #7, #15, [13](13-llm-and-token-strategy.md) H3 |
| 2 devs can't build and also run the pilots | One founder owns customers from week 1. Cut the MVP scope hard | [05](05-risks-and-friction.md) #16 |

## Where we disagree with your plan

| Your plan | We recommend | Detail |
|---|---|---|
| "Most restaurants use SR" | Treat SR (about 4%) as the wedge. Keep a second source on the roadmap: Excel/CFDI-only restaurants, then a POS with an API | [06](06-feedback-and-alternatives.md) #1 |
| The daily manual upload is the data entry point | Use it as the onboarding path and the fallback. Move to Corte Z email and the ERP/PMS push. Build the local connector only if the push isn't possible | [03](03-data-ingestion-and-costing.md), [09](09-architecture.md) §10 |
| Sales Q&A as the core product | Margins, price suggestions and waiter-level leak patterns ([14](14-product-features.md)) | [06](06-feedback-and-alternatives.md) #3 |
| Phase 3 POS is the plan | Make it a gate at month 9: 150+ paying locations, churn under 3%, 30%+ of owners asking for a POS, funding for 2+ more engineers. If the gate fails, build intelligence across POSes plus purchasing. Building our own POS would turn SR and its 610 distributors, our data source and our best channel, into rivals | [06](06-feedback-and-alternatives.md) §4, [07](07-roadmap.md) |
| A human approves every change | Keep the rule, but approve per batch (one CFDI = one tap). Clean uploads auto-apply with a "Deshacer" button. Routine POS orders aren't gated | [06](06-feedback-and-alternatives.md) #6, [09](09-architecture.md) §10 |
| A thin broker agent | The broker is necessary but not enough. Add a router with zero-token templates in front of it and a number validator behind it | [09](09-architecture.md) D6, [13](13-llm-and-token-strategy.md) I1 |
| No customer discovery step | 10 owner interviews in week 1, with a price question | [06](06-feedback-and-alternatives.md) §2 |

Decisions we need from you: Phase 3 gate (F7), pricing test (F8), weekly default (F12), who owns customers (F6). Full list in [11](11-open-questions.md).

## This week

1. **Lock the pilot.** Do 10 owner interviews (5 chains, 5 independents) and pick a pilot on SR 11/12 Pro with 2-5 locations. Get 2-4 weeks of sample exports. Test sending those files, plus a CFDI XML, from the manager's phone to a test WhatsApp number.
2. **Start the long-lead items on day 1:** Meta Business Verification (RFC plus proof of address with the exact legal name), the +52 number, template submissions, the National Soft "Quiero integrar mi sistema" form, a distributor quote for the ERP/PMS module, and a lawyer for the aviso de privacidad.
3. **Freeze the contracts by day 2 and run the 40-question LLM eval on days 4-5.** No agent code merges until it passes.
