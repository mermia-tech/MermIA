# 06 - Feedback and alternatives

Date: 2026-10-15. Honest critique of the kickoff plan. Facts carry a label and a source doc (01-04, 13, PL = `research/pos-legal-stack-notes.md`); everything under "Opinion" is my judgement.

## Summary

The core idea (cost-side intelligence for Mexican restaurants on WhatsApp, POS-agnostic, human-approved writes, lean agent) is sound and has a proven analogue in Toast IQ. Four things in the plan are wrong or risky: the daily manual upload as the backbone, the assumption that "most restaurants use SR", selling sales Q&A that SR already gives away, and committing now to a Phase 3 POS against funded rivals. Fix those and the plan gets cheaper and faster.

## 1. What the plan gets wrong

| # | Plan says | Facts | Opinion: what to do instead |
|---|---|---|---|
| 1 | "Most Mexican restaurants use Soft Restaurant" | Vendor claims ~23,000 restaurants (2025) vs 600,000+ in Mexico, about 4%. **verified** (vendor claims) [01] | SR is the best wedge, not the market. At 10% of SR's base (2,300 locations) x MXN 899/month we reach about MXN 24.8M/year (about US$1.4M ARR at 18 MXN/USD, **assumption**). Good business, small venture. Keep the second data source on the roadmap from day 1 |
| 2 | Getting data out of SR is hard; manager exports daily | SR has an **ERP/PMS module that POSTs every sale as JSON** (lines, discounts, payments, tips) to a third-party endpoint, per check or at daily close; SR 12 emails the Corte Z automatically. **verified** [01 §2, §5] | Make the ERP/PMS push the target ingestion for paying customers from month 2, and test it with the pilot in week 1. Manual upload is the fallback and the onboarding path, not the product |
| 3 | SR "has no AI features" and gives owners little insight | SR 12 ships Analytics 3.0 (25+ reports, multi-branch), the free SR Admin app with real-time sales, WhatsApp cortes and anti-fraud alerts. **verified** [01]. Kavasoft sells an AI assistant ("CatIA") that answers questions with SR connected. **verified** 2026-10-15 ([Kavasoft](https://kavasoft.app/integraciones/soft-restaurant)) | "Ask your sales on WhatsApp" is not a product people will pay for: SR Admin shows sales free. Our paid value is costs, margins, price suggestions and leak patterns per waiter in pesos. SR 12 already sends per-event cancellation/discount alerts, so we skip those (14) |
| 4 | Phase 3: build our own POS | Parrot ($11.7M raised), Polotab (YC W23, 700-800+ venues), Fudo ($7.5M seed), SR Cloud, Mercado Pago POS at MXN 149/month. **verified** [02]. 2 devs need about 5-8 months for a sellable POS. **unverified** estimate [PL §1.7] | Do not commit to Phase 3 now. A POS turns SR (our data source) and its 610 distributors (our best channel) into enemies, and drops us into a crowded fight. Re-decide at month 9 with evidence (see §4) |
| 5 | Daily proactive report (or weekly, to decide) | WhatsApp cost difference daily vs weekly is about US$0.22/restaurant/month. **verified** [04 §9] | Weekly by default, daily opt-in, plus immediate alerts only for real margin breaches. Decide on habit and value, not cost |
| 6 | "Every DB change needs explicit confirmation" | Rule from the brief | Good rule, but per-row approval of CFDI lines will drown the owner. Approve per batch (one invoice = one confirmation), and confirm an ingredient alias once, then auto-map |

## 2. What is missing

| Missing piece | Why it matters | Suggestion |
|---|---|---|
| **Customer discovery before code** | No interviews in the plan; willingness to pay is untested (risk 8 in 05) | 10 owner interviews in week 1 (5 independents, 5 small chains), with a price question and a "would you forward your supplier invoices?" question |
| **Someone who owns customers** | Pilots need onboarding, recipe capture, reminders, support | One founder spends at least half of the 4 weeks on the pilot, not the code |
| **Concierge costing** | Most restaurants will not have recipes or costs (likely [01 §4]); margins are the paid value | We capture the top-10 dishes ourselves in onboarding (by chat, sheet or visit) and charge a setup fee |
| **Leak patterns** (cancellations, discounts, price changes by staff, per waiter) | Needs no cost data; SR reports cover it [01 §3]; SR 12 already sends per-event anti-fraud alerts, so owners care but won't pay for a copy | Add a weekly per-waiter ranking in pesos to the MVP report, not per-event pings; proven by NCR Restaurant Guard (14) |
| **Pricing and billing** | No price, no way to collect | See 10: test MXN 449 vs 899 per location for Márgenes, Compras (449) as fallback; card or SPEI monthly |
| **Legal basics** | Aviso de privacidad, terms with encargado clauses, Meta Business Verification need an RFC and legal name [04, PL] | Start on day 1; one lawyer review |
| **Partner conversation with National Soft** | ERP/PMS is the sanctioned route; their reaction is the biggest strategic unknown [01 §5] | Submit the "Quiero integrar mi sistema" form in week 1; ask a distributor for the ERP/PMS module price |
| **Success metric for the pilot** | Without it every pilot "works" | E.g. owner opens 3 of 4 weekly reports, asks at least 2 questions/week, accepts at least 1 price or cost change, agrees to pay from month 2 |
| **A second data source** | SR-only caps the market at about 23k restaurants | Excel/CFDI-only restaurants (no POS needed for costing) are a cheap second segment; later another POS with an API |

## 3. Better alternatives

| Alternative | Facts | Opinion: verdict |
|---|---|---|
| **ERP/PMS push from day 1** instead of manual uploads | Clean JSON per sale with discounts, payments, tips; queues failed sends; paid module bought via distributor, price **unverified**; covers sales, not recipes. **verified** [01 §5] | **Yes, for paying customers.** MVP keeps manual upload so the pilot is not blocked by a purchase; build the JSON endpoint in Phase 1b (weeks 5-12, per 07 and 08) and run it in shadow mode next to uploads, if the pilot can enable the module. The endpoint is trivial next to an Excel parser |
| **Local DB connector** (like Kavasoft, FactorBI) | Two companies already sell it, read-only, as a Windows service. **verified** [01 §7]. EULA and LFDA risk medium. **verified** / legal position **unverified** | **Later, only if ERP/PMS fails.** It also gives recipes and inventory, which ERP/PMS does not. Needs a lawyer and written owner consent |
| **SR 12 Corte Z email to our inbox** | Automatic at shift close; content and format **unverified** [01] | **Yes, test in week 1.** Zero manager effort if it carries enough detail; likely totals only, so still need product-level data |
| **Sell through SR distributors** | 610 active partners; 17,000+ licences served by partners; they charge for installation and training. **verified** [01] | **Yes, as the main channel.** They already visit our customers. Offer recurring revenue share and let them install the ERP/PMS module. Conflicts with Phase 3 POS, which is another reason to defer it |
| **Start with small chains (2-5 locations)** | Brief targets 2-10; branch consolidation is a paid SR add-on (Analytics/Enterprise). **verified** [01] | **Yes, lead with 2-5 location owners.** The owner is not on site, branch comparison and leak patterns matter more, they pay more per account, and each sale is several locations. Independents come through distributors and referrals later |
| **Partner with a POS instead of building one** | Polotab/Parrot have no AI layer we could find. **unverified** [02] | Worth a call in Phase 2: the same metrics layer and agent can read a second POS (Tenzo model: analytics across 100+ integrations [02]) |
| **Dashboard first, WhatsApp second** | Meta can change rules or prices at will [04] | **No.** WhatsApp is right for the habit. Keep the agent channel-agnostic as planned |

## 4. Phase 3 POS: is it wise?

**Facts.** Funded cloud POS rivals already operate in Mexico (Parrot, Polotab, Fudo), SR has its own cloud product, and Mercado Pago sells a POS at MXN 149/month [02]. A minimal restaurant POS needs offline sync, printers, CFDI via a PAC, payment terminals and delivery integrations, estimated at 5-8 months for 2 devs (**unverified** [PL §1.7]). We found no evidence that analytics buyers convert into POS buyers [02 §3].

**Opinion.** Not now. Phases 1-2 can succeed without it, and announcing it costs us the SR relationship and the distributor channel. Gate Phase 3 on: at least 150 paying locations, monthly churn under 3%, at least 30% of owners asking for a POS switch, and funding for at least 2 more engineers. If the gate fails, the better Phase 3 is "intelligence across POSes" plus purchasing and supplier features (MarketMan/xtraCHEF model [02]). Keep the POS-ready schema work from PL §1.8: it is cheap and keeps the option open.

## 5. What I would do differently

1. **Week 1: sell before building.** 10 interviews, pick the pilot (SR 11/12 Pro, 2-5 locations, owner who answers WhatsApp), get sample exports, submit the National Soft integration form, start Meta Business Verification.
2. **MVP scope:** manual upload of 2 reports (Productos vendidos, Cancelaciones/Descuentos), weekly report, 5-6 templated questions, top-10 dish costing done by us, margin alerts and price suggestions with confirm buttons. Free-form LLM Q&A comes second.
3. **Sell margins and leaks, not sales Q&A.** Sales Q&A is the hook, included in every plan; margin and price-shock alerts, price suggestions and leak patterns are the paid tiers (10, 14).
4. **ERP/PMS endpoint as the first integration**, then connector only if needed.
5. **Charge from month 2 of the pilot**, even a discounted price, to test willingness to pay.
6. **Distributors as the channel**, with a revenue share; this means no public POS ambitions for now.
7. **Small chains first.**
8. **Phase 3 is a gated decision**, not a plan.
