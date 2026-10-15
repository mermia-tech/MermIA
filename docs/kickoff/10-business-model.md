# 10 - Business model

Date: 2026-10-15. Prices are MXN per location per month **before IVA** unless stated. Facts carry a label and source doc (01 SR, 02 competitors, 04 WhatsApp, 13 LLM, PL = `research/pos-legal-stack-notes.md`). Rows marked **A** are assumptions to replace with pilot data. FX: **1 USD = 18 MXN (A)**; Meta's own rate card implies 18.41 [04], doc 13 used 17.5.

## Key points

- **Price the main plan (Márgenes) at MXN 899 per location**, between SR Lite (799) and SR Pro (1,099), far below USD-priced costing tools (MarketMan about MXN 3,600+). Test 449 vs 899 in the pilot.
- **Never charge for what SR gives away.** Sales Q&A, the weekly report and per-event cancellation/discount alerts are covered by SR Admin, Analytics and SR 12 WhatsApp alerts (**verified**, 01, [14](14-product-features.md)). They are included in every plan, not sold. The old 449 "Ventas" plan is replaced by **Compras** (449): price capture from CFDI and notas plus price-shock alerts, which SR does not push.
- **Charge a setup fee (MXN 2,500)** that pays for concierge recipe capture of the top-10 dishes, as MarketMan and Restaurant365 do.
- **Software cost is small (MXN 54-115 per location); human support is the real cost.** Gross margin is about 50-73% for a single independent and 63-80% for a 4-location chain.
- **Small chains pay back CAC in about 2 months, independents in 4-6** (assumption-driven). Lead with chains and sell through SR distributors.

## 1. Price anchors (what owners already pay)

| Product | Price (MXN/month unless noted) | What it is | Label / source |
|---|---|---|---|
| Soft Restaurant 12 Lite / Pro | 799 / 1,099 + IVA; annual Pro 13,386.40 IVA incl. (12.5% off monthly) | Incumbent POS | **verified** [01] |
| Mercado Pago POS restaurantes | 149, or 1,430/year (20% off) | Basic POS | **verified** [02] |
| Polotab | From 990 (period unstated) | Cloud POS | **unverified** [02] |
| Parrot | 1,800 / 2,100 / 2,800 + IVA | Cloud POS | **unverified** (competitor blog) [02] |
| Fudo | USD 35-45 (about MXN 630-810) | Cloud POS | **likely** [02] |
| Kavasoft (wine-cellar mgmt with SR connector and "CatIA" AI assistant) | From 17,999 + IVA per year (about 1,500/month) | Niche SR add-on | **verified** 2026-10-15 ([Kavasoft](https://kavasoft.app/integraciones/soft-restaurant)) |
| FactorBI (SR dashboards via DB replication) | No public price, demo only | BI on SR data | **verified** 2026-10-15 ([FactorBI](https://www.factorbi.com/reportes-soft-restaurant)) |
| MarketMan | USD 199-249 per location (about MXN 3,600-4,500) + USD 500 setup | Inventory and costing | **likely** [02] |
| Restaurant365 | USD 469-499 per location, about USD 5k setup | Back office, US | **unverified** [02] |
| Toast IQ | Assistant bundled; paid agents: Grow from USD 699/month, Team USD 60 + 9/employee | Free hook, paid action agents | **verified** [02] |
| Facturapi | 299 + 0.60 per timbre | MX SMB SaaS reference | **verified** [PL] |

## 2. Proposed plans

| Plan | Price | Includes | Proven model behind it |
|---|---|---|---|
| **Piloto** | MXN 0 for 30 days, then the paid plan at 50% for months 2-3 | Everything in Márgenes, setup fee waived | Free trials: Mercado Pago 15 days, Facturapi 14 days [02, PL] |
| **Included in every plan** (not sold alone) | - | WhatsApp Q&A on sales, weekly report, data ingestion (upload, Corte Z email, ERP/PMS push), confirmations and Deshacer | Toast IQ gives the assistant to all US customers as the hook [02]; SR Admin and SR 12 WhatsApp alerts already give sales and per-event alerts free [01], so charging for them fails |
| **Compras** (low-touch, from Phase 1b) | 449 | CFDI XML and nota-photo price capture, supplier price history, ingredient price-shock alerts, SNIIM benchmark (Phase 2), 1 uploader. No recipes, no setup fee | xtraCHEF sells invoice capture + price alerts as its own product [14]; SR 12 imports XML only on the PC and pushes no alert [01]. Must stay self-serve: at 449 any human support wipes out margin (§3.2). Natural upgrade to Márgenes: price history is already there |
| **Márgenes** (main plan) | **899** | Compras + recipe costing (top-10 dishes done for us), per-dish margins, menu-engineering matrix, price suggestions with confirmation, waiter-level leak patterns in pesos, cash-shortage patterns, daily report opt-in | Toast puts revenue in action agents, not chat [02]; leak patterns: NCR Restaurant Guard [14]; priced below SR Pro and at about 25% of MarketMan |
| **Cadena** (2-10 locations) | 799 per location (min. 2); 699 per location from 5 | Márgenes + branch ranking of margin, food cost and leaks, per-branch freshness, one owner view | Per-location pricing: MarketMan, R365, Toast [02]; SR sells multi-branch as a paid Enterprise/Analytics add-on [01] |
| **Setup fee** (Márgenes, Cadena; none on Compras) | 2,500 first location; 1,000 each extra; waived on annual prepay | Concierge capture of top-10 dishes, SR export setup (or ERP/PMS push), uploader training | MarketMan USD 500 setup, R365 about USD 5k [02]; SR distributors charge installation separately [01] |
| **Annual prepay** | Pay 10 months, get 12 (about 17% off) | Same | SR 12.5% off annual, Mercado Pago 20% off annual [01, 02] |

**Value check (A):** a restaurant selling MXN 400,000/month (IVA incl.) has about MXN 344,800 net sales; at 32% food cost that is about MXN 110,300 of ingredients. One food-cost point is about MXN 3,450/month, about 3.8x the Márgenes price. The pitch is "te encontramos más de lo que cuesta".

**Pricing test in the pilot (opinion):** quote 899 to half of the interviewees and 449 to the other half for the same Márgenes features; record yes/no/maybe. Show Compras (449) only as the fallback for owners who say no to Márgenes, and record how many take it. Do not launch a permanent free tier: SR Admin already gives sales free, so a free tier competes with a free incumbent and still costs us about MXN 54-115/month in software.

## 3. Unit economics per location per month

### 3.1 Cost of service

| Line | USD | MXN | Label / source |
|---|---|---|---|
| LLM, typical (about 15 questions/day, 35% templated, Haiku + 15% Sonnet) | 0.66 | 11.9 | **likely** model [13 I3] |
| LLM, heavy (40/day, multi-location) | 1.77 | 31.9 | **likely** model [13 I3] |
| WhatsApp (optimized weekly to conservative daily) | 0.81-1.43 | 14.9-26.4 | **verified** rates, **likely** model [04 §9]; about 0 below 11 restaurants thanks to the 1,000 free service messages per number |
| Hosting (Supabase Pro + worker + observability; 200 to 10 restaurants) | 1.4-4.0 | 25-72 | **unverified** estimate [PL §3] |
| Vision/OCR for photos of notas and receipts | 0.10-0.30 | 2-5 | **A** |
| **Software subtotal (typical usage)** | **3.0-6.4** | **54-115** | sum |
| Card/SPEI collection fees (about 3.6% + MXN 3, on 899) | - | about 35 | **A** (processor not chosen; rate **unverified**) |
| Human support (0.5-1 h/month at MXN 300/h) | - | 150-300 | **A** |
| **Total cost of service, Márgenes, 1 location** | - | **239-450** | sum |

### 3.2 Gross margin

| Case | Revenue | Cost | Gross profit | Gross margin |
|---|---|---|---|---|
| Márgenes, independent, best | 899 | 54 + 35 + 150 = 239 | 660 | 73% |
| Márgenes, independent, worst | 899 | 115 + 35 + 300 = 450 | 449 | 50% |
| Márgenes, software only (no support) | 899 | 54-115 | 784-845 | 87-94% |
| Compras, independent, best / worst (no setup fee) | 449 | 54 + 19 + 150 = 223 / 115 + 19 + 300 = 434 | 226 / 15 | 50% / 3% |
| Cadena, 4 locations x 799 = 3,196, best (support 1 h/account) | 3,196 | 216 + 118 + 300 = 634 | 2,562 | 80% |
| Cadena, 4 locations, worst (support 2 h/account) | 3,196 | 460 + 118 + 600 = 1,178 | 2,018 | 63% |

Takeaways: (1) software cost is not the problem, support time is; (2) Compras at 449 only works with zero human support, which is why it has no recipe work and no setup fee; (3) chains carry far better margins because support is per account, not per location. LLM cost stays under 5% of price in every case, inside the target in 13 I4.

### 3.3 Acquisition cost and payback (all **A**)

| Channel | CAC per account | Basis |
|---|---|---|
| Founder-led, independent | 3,500 | 6 h of founder time at MXN 500/h + MXN 500 travel |
| Founder-led, small chain (4 locations) | 6,000 | 10 h + MXN 1,000 travel |
| SR distributor | 0 upfront; 20% revenue share for 12 months (about 2,160 per location) | Typical reseller share; not quoted by any distributor yet |
| Accountant referral | 899 one-off bounty | One month of fees |
| Click-to-WhatsApp ads | 1,500-8,000 | CPL MXN 150-400, 5-10% close; both **unverified**; CTWA opens a free 7-day window [04] |

| Case | Net setup (fee minus our onboarding cost) | Monthly GP | Payback = (CAC - net setup) / GP |
|---|---|---|---|
| Independent, direct | 2,500 - 1,500 (5 h) = 1,000 | 449-660 | 2,500 / 660 = **3.8** to 2,500 / 449 = **5.6 months** |
| Chain 4 locations, direct | 5,500 - 3,300 (11 h) = 2,200 | 2,018-2,562 | 3,800 / 2,562 = **1.5** to 3,800 / 2,018 = **1.9 months** |

**LTV (A: monthly churn 3-5%, so 20-33 months life):** independent MXN 9,000-21,800 (LTV/CAC 2.6-6.2); 4-location chain MXN 40,400-84,500 (LTV/CAC 6.7-14).

**Break-even (A: burn MXN 150,000/month for 2 founders and tools):** about 270 paying locations at an average GP of about MXN 550, roughly 1.2% of SR's claimed base [01].

## 4. Go-to-market

### 4.1 Segments, in order (opinion)

1. **Small chains, 2-5 locations, on SR 11/12 Pro.** Owner is off-site, branch comparison and leak patterns matter, best payback (§3.3).
2. **Busy independents with SR Pro and some recipes loaded**, via distributors and referrals.
3. **Later:** restaurants without SR (Excel/CFDI only) and 6-10 location chains (need the dashboard).

### 4.2 Channels

| Channel | Why it can work | Facts | How to start |
|---|---|---|---|
| **SR distributors** | They install, train and support SR, so they already visit our buyers and can enable the ERP/PMS module | 610 active partners serve 17,000+ licences. **verified** [01]. Distributor list is public | Call 5 distributors in CDMX/Monterrey/Guadalajara/Mérida; offer 20% recurring for 12 months and a white-glove setup they can bill. Ask the ERP/PMS module price |
| **Accountants (contadores)** | They receive the restaurant's CFDI XML every month and talk to owners about margins and taxes | Restaurants need CFDI for purchases (**likely** [03]); no data on accountant-led SaaS sales in MX (**unverified**) | Referral bounty; a monthly cost report they can forward to clients |
| **CANIRAC and state delegations** | Industry chamber; events and member newsletters reach owners | Programmes and sponsorship terms **unverified** | Ask the local delegation for a talk slot or member discount; demo at an event |
| **Owner WhatsApp and Facebook groups** | Where owners already talk; free | Groups exist (**likely**); none checked | Founders join and share a free "¿cuánto te cuesta tu platillo?" check, not ads |
| **Food suppliers and distributors** | They know price moves and want loyal customers | **unverified** | Phase 2: co-branded price-change alerts |
| **Click-to-WhatsApp ads** | Lands owners directly in our chat; free 7-day window | **verified** pricing rule [04] | Small test after the pilot (MXN 5,000 budget) |

### 4.3 Finding pilot customers (weeks 1-2)

| Step | Detail |
|---|---|
| Criteria | SR 11 or 12 **Pro**, licensed (not pirated), 1-5 locations, owner answers WhatsApp, manager willing to send one file a day, ideally some recipes in SR and suppliers that issue CFDI |
| Sources | Founders' own network first; then 2-3 SR distributors; then CANIRAC delegation |
| Offer | 30 days free, setup waived, 50% off months 2-3, direct WhatsApp line to a founder, in exchange for sample exports, weekly 15-minute feedback and a testimonial if it works |
| Target | 10 interviews, 3 pilots (1 chain + 2 independents), 1 live by week 4 |
| Exit test | At least 2 of 3 pilots agree to pay in month 2 (opinion; see 06 for pilot success metrics) |

## 5. Assumptions to replace first

1. Willingness to pay at 449 vs 899 for Márgenes, and Compras take-up as the fallback (pilot interviews).
2. Support hours per location per month (log every minute in the pilot).
3. Onboarding hours for top-10 dish costing.
4. Distributor revenue share they will accept.
5. Monthly churn (only measurable after 3-6 months).
6. Payment processor and its fees in MXN.
