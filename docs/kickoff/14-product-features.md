# 14 - Product features: Soft Restaurant vs Toast vs MermIA

Date: 2026-10-15. One table: per feature, what Soft Restaurant (SR) already offers, what Toast IQ (or the wider Toast suite) does, and what we recommend. Facts reuse 01 (SR) and 02 (competitors) where already verified; gaps were checked by web search on 2026-10-15. Recommendations, phases and plans are **opinion**. Plans follow the redesign in [10](10-business-model.md) §2 (Compras 449, Márgenes 899, Cadena 799/699).

Toast is a reference model, not a competitor in Mexico (no MX launch found, **likely**, 02). Toast IQ is US-only.

**Legend.** ✅ has it · 🟡 partial or limited (the cell says why) · ❌ no · ❓ unverified (not found either way).
**Origin tag** (in the Feature cell): *Toast has, SR doesn't* · *Both have* · *SR has* · *New (neither)*.
**Phases** (07): MVP = weeks 0-4 · 1b = weeks 5-12 · 2 = months 3-6 (dashboard) · 3 = gated POS (month 9+). "—" = not built.
**Proven-model rule:** every Build row names who proves the model works, in the recommendation or evidence cell.

## Key findings

- **SR already gives away sales visibility and per-event fraud alerts.** SR Admin is free; Analytics ("más de 20 reportes", goals, multi-branch) is described as "incluido en tu licencia" (**verified** 2026-10-15, [SR Analytics](https://softrestaurant.com/addons/analytics)); SR 12 sends cortes and cancellation/discount/reprint alerts on WhatsApp (**verified**, 01). We must not charge for either.
- **SR has no AI, no price suggestions, no pushed cost alerts and no OCR** in any 2024-26 vendor material we found (**likely**). Its recipe/inventory/XML-purchase modules exist but are PC-bound and DIY.
- **Toast's Oct 2026 line-up** (**verified**, [NRN 2026-10-07](https://www.nrn.com/restaurant-technology/toast-unveils-an-array-of-new-ai-agents-for-restaurants)): assistant with "For you" feed and chat actions; Grow (Marketing, SEO, Reviews, Offers agents, from US$699/mo); Team (Scheduling Agent, AI sales forecasts, Team Performance contests, US$60 + 9/employee); **early access only**: Menu Agent (descriptions + price recommendations), Answering Agent (phone), Configurable Agents (e.g. unusual voids, missed clock-outs, prep forecasts). Toast IQ agents can "alert you within the hour when voids or discounts look unusual" but are in early access ([Toast support](https://support.toasttab.com/en/article/Toast-IQ-Agents-Overview)).
- **Toast's cost side is xtraCHEF:** invoice photos/scans/email/EDI, line-item price tracking, configurable price alerts, recipe costs updated per invoice, actual vs theoretical (**verified**, [Toast xtraCHEF](https://pos.toasttab.com/products/restaurant-invoice-processing), [partner page](https://pos.toasttab.com/partners/directory/xtrachef)). Native Toast Recipes is still **beta in Canada/Ireland/UK only** (**verified**, [Toast support, Apr 2026](https://support.toasttab.com/en/article/Get-Started-With-Recipes)).
- **Why price-shock alerts matter in Mexico now:** jitomate inflation peaked at 152% in March 2026 (INEGI via press, **verified**, [El Financiero](https://www.elfinanciero.com.mx/economia/2026/06/08/precio-del-jitomate-baja-a-30-pesos-en-centros-comerciales-y-central-de-abasto/)); the same article cites SNIIM Central de Abasto prices, so the benchmark source is live.

## Main table

### 1. Visibility & Q&A

| Feature | Soft Restaurant (version; how good) | Toast IQ / Toast | Our recommendation | Phase | Plan | Evidence |
|---|---|---|---|---|---|---|
| Sales reports and dashboards (product, waiter, hour, branch) · *Both have* | ✅ SR 8-12: 50+ local reports to Excel; SR Admin app free (real-time, multi-branch, PDF/Excel); Analytics 3.0, 20-25+ reports, included in licence. Good, but screens, not answers | ✅ Toast Web / Toast Now reports | **Skip** as a product; use SR reports as our data source. No dashboard before Phase 2 | — | — | [SR Admin](https://apps.apple.com/mn/app/sr-admin/id6575394645), [SR Analytics](https://softrestaurant.com/addons/analytics), 01 §3 |
| Plain-language Q&A on own numbers · *Toast has, SR doesn't* | ❌ No AI found (01, 02). Kavasoft "CatIA" is a third-party wine-cellar add-on | ✅ Toast IQ assistant, all US customers; >50% of locations in ~4 months; 40k WAU, 21M+ threads Q1 2026 | **Build better:** on WhatsApp, Mexican Spanish, zero-token templates for top questions, tools return every number, validator blocks invented numbers. **Not charged**: SR shows the same sales free | MVP | All plans (included) | [RTN](https://restauranttechnologynews.com/2025/10/toast-launches-conversational-ai-assistant-to-help-restaurant-operators-work-faster-and-smarter/), [Toast blog](https://pos.toasttab.com/blog/on-the-line/toast-iq), 13 |
| Proactive feed / scheduled report · *Both have* | 🟡 SR 11/12: Corte X/Z by WhatsApp or email at shift close; totals, no interpretation | ✅ "For you" feed: proactive insights on sales, labor, menu | **Build better:** weekly "pesos encontrados" report (3 actions, each in MXN), daily opt-in; immediate message only for severe breaches. Proven by Toast feed | MVP | All plans (content grows with plan) | [Toast news](https://pos.toasttab.com/news/toast-expands-toast-iq-smart-ai-assistant), 01 §2, 04 §9 |
| Sales goals and progress · *SR has* | ✅ Analytics: daily/monthly/annual goals, % achieved | ❓ Not found as a feature | **Skip** as a feature; answer "¿cómo voy vs meta?" in Q&A if the owner gives a target | 1b | All plans | [SR Analytics](https://softrestaurant.com/addons/analytics) |

### 2. Costs, recipes & margins

| Feature | Soft Restaurant (version; how good) | Toast IQ / Toast | Our recommendation | Phase | Plan | Evidence |
|---|---|---|---|---|---|---|
| Recipe costing (insumos, sub-recipes, yields) · *Both have* | 🟡 SR Pro; SR 12 adds presentations, sub-recipes, yields. Works only if the full catalogue is loaded on the PC; reviewers call it data-heavy; share of restaurants keeping it current **unverified** | 🟡 Native Recipes beta in CA/IE/UK only; ✅ in the US via xtraCHEF (setup "tedious" per a user review) | **Build better:** import SR recipes when present; otherwise we capture the top-10 dishes (concierge, paid by setup fee) or by chat; every cost tagged confirmed / estimated / missing. Proven: xtraCHEF, MarketMan, Apicbase | MVP | Márgenes | [SR blog](https://softrestaurant.com/blog-restaurantero/como-hacer-el-costeo-de-recetas-en-un-restaurante), [Capterra](https://www.capterra.com/p/200701/Soft-Restaurant/reviews/), [Toast Recipes](https://support.toasttab.com/en/article/Get-Started-With-Recipes), 03 C |
| Dish margin and food-cost %, net of 16% IVA · *Both have* | 🟡 SR 12 markets "cálculo automático de costos y utilidad"; "Ventas, inventarios y utilidad" report needs accounting setup; no per-dish answer on the phone | ✅ xtraCHEF COGS vs budget with Toast sales; Recipes shows margin per recipe (beta) | **Build better:** per-dish margin pre-IVA with confidence tag, asked on WhatsApp ("¿cuánto le gano a la birria?"). Proven: xtraCHEF | MVP | Márgenes | [Infochannel SR12](https://infochannel.info/soft-restaurant-12-en-mexico-revoluciona-la-gestion-gastronomica-con-analytics-avanzados/), [xtraCHEF](https://pos.toasttab.com/products/restaurant-invoice-processing), 03 |
| Auto-recost when an ingredient price changes · *Both have* | 🟡 Recipe cost follows average or last purchase cost, only if purchases are entered in SR | ✅ xtraCHEF: "pricing data updated with each new invoice" | **Build:** recompute affected dishes on every new price (chat in MVP; CFDI / photo in 1b). Proven: xtraCHEF, Apicbase | MVP (chat) / 1b | Márgenes | [xtraCHEF](https://pos.toasttab.com/products/restaurant-invoice-processing), 03 |
| Theoretical vs actual cost (variance) · *Both have* | 🟡 SR 8+: insumos consumidos, costos y consumos, physical counts. Needs full inventory discipline | ✅ xtraCHEF / Toast inventory variance reporting | **Build later:** weekly count of top-20 ingredients only. Proven: xtraCHEF; variance bands from Supy | 2 | Márgenes | 01 §3-4, [Supy](https://supy.io/blog/learn-theoretical-vs-actual-food-cost-variance), 07 Phase 2 |

### 3. Menu pricing & engineering

| Feature | Soft Restaurant (version; how good) | Toast IQ / Toast | Our recommendation | Phase | Plan | Evidence |
|---|---|---|---|---|---|---|
| Menu-engineering matrix (Star / Plowhorse / Puzzle / Dog) · *Toast has (partial), SR doesn't* | 🟡 Analytics "Popularidad por producto" and top/worst sellers; no margin x popularity matrix found (❓) | 🟡 Free worksheet resource; Menu Agent (early access) improves content and prices | **Build:** monthly Kasavana-Smith matrix in plain words ("sube el precio de X, promueve Y"). Proven: Kasavana-Smith (1982), menu-engineering reports in Apicbase/MarketMan (**likely**) | MVP (RPC) / 1b (report) | Márgenes | [FIU paper](https://digitalcommons.fiu.edu/record/17973/files/V13n195e.pdf), [Toast worksheet](https://pos.toasttab.com/es-us/resources/menu-engineering-worksheet-restaurants), 08 |
| Price suggestions with the math, approved by the owner · *Toast has (early access), SR doesn't* | ❌ None found | 🟡 Menu Agent "recommending prices", early access Oct 2026; method not public | **Build better:** cost-driven, IVA-aware, rounded to MX price points, max ±10% per step, menu-engineering aware, math shown, never auto-applied. Proven: Toast is investing here; formula from 03 | MVP | Márgenes | [NRN](https://www.nrn.com/restaurant-technology/toast-unveils-an-array-of-new-ai-agents-for-restaurants), 03 |
| Apply a price change in the POS · *Both have* | ✅ Manager edits prices in SR (its own POS); "Cambios de precio" report audits it | ✅ Adjust pricing or 86 items from the chat | **Skip** writing into SR (no write path we can rely on; 08 Out). Send a "lista de cambios" the manager types into SR. Revisit only with our own POS | 3 | — | [Toast blog](https://pos.toasttab.com/blog/on-the-line/toast-iq), 01 §5, 08 |

### 4. Leak / fraud control

| Feature | Soft Restaurant (version; how good) | Toast IQ / Toast | Our recommendation | Phase | Plan | Evidence |
|---|---|---|---|---|---|---|
| Per-event alerts (cancellation, discount, reprint, courtesy) · *Both have* | ✅ SR 12 WhatsApp anti-fraud alerts (cancellations, discounts, reprints) via its Marketplace setup; "Alertas de seguridad" in SR training | 🟡 Toast IQ agents alert "within the hour" on unusual voids/discounts; early access | **Skip:** SR 12 already does it free; duplicating it is noise and sells nothing | — | — | 01 §2, [SR course syllabus](https://apicvaservices.grupocva.com/api/v2/pdf_service/descarga_ficha/10422592), [Toast support](https://support.toasttab.com/en/article/Toast-IQ-Agents-Overview) |
| Waiter/cashier-level leak patterns in pesos (weekly ranking vs peers and weekday baseline: cancellations after print, discount concentration, staff price changes, courtesies) · *New (neither)* | 🟡 Raw reports exist (cancelaciones, descuentos with user, cambios de precio, ventas por mesero) but no pattern detection | 🟡 Configurable Agents "flagging unusual voids" (early access); no per-employee pattern product found | **Build:** the weekly "fugas" section: who, how much in MXN, vs the median waiter and the same weekday; trend over 4 weeks. Proven: NCR Aloha Restaurant Guard (scam-pattern detection since 2010), exception reporting per employee (Solink) | MVP (basic) / 1b | Márgenes | [NCR Restaurant Guard](https://www.ncrvoyix.com/restaurant/restaurant-guard), 01 §3, 06 §5 |
| Cash shortage/surplus pattern per cashier · *New (neither)* | 🟡 Corte Z shows faltantes/sobrantes per shift; no trend | ❓ Not found | **Build:** from the emailed Corte Z, flag repeated shortages by cashier. Proven: Restaurant Guard-style exception reporting (**likely**) | 1b | Márgenes | 01 §2, [NCR Restaurant Guard](https://www.ncrvoyix.com/restaurant/restaurant-guard) |

### 5. Purchasing & inventory

| Feature | Soft Restaurant (version; how good) | Toast IQ / Toast | Our recommendation | Phase | Plan | Evidence |
|---|---|---|---|---|---|---|
| CFDI XML purchase capture · *Both have (different form)* | ✅ SR 12 imports purchase CFDI XML and links lines to insumos automatically (marketing claim); done on the SR PC, needs the inventory module | ✅ xtraCHEF takes invoices by email, photo, scan or EDI (US, no CFDI) | **Build better:** forward the XML to our inbox (WhatsApp only if the device test passes), learn `(RFC, descripción) → insumo` once, approve per invoice, no PC. Proven: xtraCHEF email-in; SR 12 proves owners use XML | 1b (MVP stretch) | Compras | [Infochannel SR12](https://infochannel.info/soft-restaurant-12-en-mexico-revoluciona-la-gestion-gastronomica-con-analytics-avanzados/), [xtraCHEF](https://pos.toasttab.com/products/restaurant-invoice-processing), 03 C.3 |
| Photo of a nota from informal suppliers (Central de Abasto) · *Toast has, SR doesn't* | ❌ No OCR found | ✅ xtraCHEF accepts photos and scans | **Build:** vision OCR, read totals back, owner confirms, stored as `quality=ocr`. Proven: xtraCHEF, MarketMan invoice scanning | 1b | Compras | [xtraCHEF](https://pos.toasttab.com/products/restaurant-invoice-processing), 02 §2, 03 C.2 |
| Ingredient price-shock alert pushed before the margin drops · *Toast has, SR doesn't* | 🟡 "Variación de costos de insumos" report (SR 8), on demand, no push | ✅ xtraCHEF configurable price alerts on "outsized price fluctuations, vendor errors, or contract pricing variances" | **Build better:** alert names the dishes hit and the MXN per month at risk, with a proposed fix (price, portion, supplier). Thresholds from 03. Proven: xtraCHEF alerts; jitomate +152% (Mar 2026) shows the need | 1b (MVP via chat prices) | Compras (alert) / Márgenes (dish impact) | [xtraCHEF partner page](https://pos.toasttab.com/partners/directory/xtrachef), [El Financiero](https://www.elfinanciero.com.mx/economia/2026/06/08/precio-del-jitomate-baja-a-30-pesos-en-centros-comerciales-y-central-de-abasto/), 03 |
| Market benchmark: "tu jitomate está 20% arriba de la Central de Abasto" (SNIIM; PROFECO as weak retail check) · *New (neither)* | ❌ | ❌ Not found (❓) | **Build:** weekly SNIIM wholesale prices for the top-20 commodities only; benchmark, never cost of record. Proven: xtraCHEF contract-price variance alerts (benchmark against a reference price); consumer price trackers (Google Flights, GasBuddy) in other industries (**likely**) | 2 | Compras | [SNIIM](http://www.economia-sniim.gob.mx/), [PROFECO QQP](https://datamx.io/dataset/quien-es-quien-en-los-precios), [xtraCHEF partner page](https://pos.toasttab.com/partners/directory/xtrachef), 03 C.4 |
| Supplier price history and cross-supplier comparison · *Both have* | 🟡 Compras por insumo / por proveedor reports, on the PC, only if purchases are entered | ✅ xtraCHEF tracks price changes over time and across locations | **Build:** "¿quién me vende más barata la cebolla?" from CFDI and notas. Proven: xtraCHEF, MarketMan | 1b | Compras | 01 §3, [xtraCHEF partner page](https://pos.toasttab.com/partners/directory/xtrachef) |
| Inventory counts, min/max stock, purchase orders, transfers · *Both have* | ✅ SR Pro inventory module (warehouses, counts, POs, transfers) | ✅ Toast inventory / xtraCHEF | **Skip:** SR does it; we read counts only for variance (Phase 2) | — | — | 01 §4 |
| SAT descarga masiva of received CFDI · *New (neither)* | ❌ Not found (❓) | n/a (US) | **Build later:** full purchase history with the owner's e.firma, no forwarding. Proven: MX vendors already sell it (Edifact; **unverified** limits). Security burden, so Phase 2+ | 2 | Compras | 03 C.2 |
| Accounting export (pólizas, CONTPAQi) · *Both have* | ✅ Pólizas to COI/CONTPAQi/Aspel; CONTPAQi guide | ✅ xtraCHEF GL coding and accounting sync | **Skip** | — | — | 01 §2, [SR docs](https://softrestaurant.com/docs) |

### 6. Labor

| Feature | Soft Restaurant (version; how good) | Toast IQ / Toast | Our recommendation | Phase | Plan | Evidence |
|---|---|---|---|---|---|---|
| Shift scheduling · *Toast has, SR doesn't* | ❌ Only attendance registry and sales shifts | ✅ Scheduling Agent (beta): 41% fewer overtime hours per employee (company claim); Team from US$60 + 9/employee | **Skip:** small MX restaurants schedule informally and SR exports carry no labour cost. Revisit with own POS | 3 | — | [NRN](https://www.nrn.com/restaurant-technology/toast-unveils-an-array-of-new-ai-agents-for-restaurants), [SR course syllabus](https://apicvaservices.grupocva.com/api/v2/pdf_service/descarga_ficha/10422592) |
| Attendance / clock-in · *Both have* | 🟡 "Registro de asistencia" (SR training); fingerprint device sheet; reports **unverified** | ✅ Toast time clock (**likely**) | **Skip** | — | — | [SR docs](https://softrestaurant.com/docs) |
| Waiter performance scorecard and contests · *Both have* | 🟡 Ventas por mesero (sales, tables, avg ticket), commissions; reports only | ✅ Team Performance: menu-item contests with live leaderboard (MyToast app) | **Build (light):** weekly scorecard per waiter (avg ticket, target-dish attach rate) inside the report; no contests app. Proven: Toast Team Performance | 1b | Márgenes | 01 §3, [NRN](https://www.nrn.com/restaurant-technology/toast-unveils-an-array-of-new-ai-agents-for-restaurants) |
| Tip distribution · *Both have* | ✅ Reparto de propinas; tip per diner in SR 12 | ✅ (**likely**) | **Skip** | — | — | 01 §1, §3 |

### 7. Guests, marketing & reviews

| Feature | Soft Restaurant (version; how good) | Toast IQ / Toast | Our recommendation | Phase | Plan | Evidence |
|---|---|---|---|---|---|---|
| Marketing campaigns and offers (win-back, new guests) · *Toast has, SR doesn't* | ❌ No CRM/marketing module found; only "ventas por cliente" for delivery/credit | ✅ Grow: Marketing Agent (runs campaigns with operator approval, human marketer) and Offers Agent; from US$699/mo; "fastest-growing new product ever" | **Skip:** SR exports carry almost no guest identity (cash, dine-in); WhatsApp marketing templates cost money; Meta Business AI covers SMB messaging in MX. Revisit with own POS | 3 | — | [NRN](https://www.nrn.com/restaurant-technology/toast-unveils-an-array-of-new-ai-agents-for-restaurants), [Xataka MX](https://www.xataka.com.mx/aplicaciones/asistentes-ia-llegan-a-whatsapp-business-mexico-asi-nueva-herramienta-pymes-automaticen-sus-ventas) |
| Review monitoring and summary · *Toast has, SR doesn't* | ❌ | ✅ Reviews Agent: prompts reviews, routes unhappy guests, summarises trends | **Build later, only if pilots ask:** weekly digest of Google reviews linked to dishes ("3 quejas de birria fría"). Proven: Toast Reviews Agent | 2 | Márgenes | [NRN](https://www.nrn.com/restaurant-technology/toast-unveils-an-array-of-new-ai-agents-for-restaurants) |
| SEO / online presence · *Toast has, SR doesn't* | ❌ | ✅ SEO Agent | **Skip** (not our job) | — | — | [NRN](https://www.nrn.com/restaurant-technology/toast-unveils-an-array-of-new-ai-agents-for-restaurants) |
| Loyalty programme · *Toast has, SR doesn't* | ❓ No native module found | ✅ Toast Loyalty (**likely**) | **Skip** | — | — | search 2026-10-15 |
| Phone answering agent · *Toast has, SR doesn't* | ❌ | 🟡 Answering Agent, early access; partners Loman AI (GA on Toast, July 2026) and Maple | **Skip:** guest-facing, crowded, and Meta Business AI covers WhatsApp in MX | — | — | [NRN](https://www.nrn.com/restaurant-technology/toast-unveils-an-array-of-new-ai-agents-for-restaurants), [Loman on BusinessWire](https://www.businesswire.com/news/home/20260720599451/en/) |
| Online ordering, delivery hub, QR menu, kiosk, KDS, reservations · *Both have* | ✅ SR add-ons: e-Delivery, Menú digital, Kiosko, Recall KDS, Delivery Manager/Hub, Reservaciones; Rappi/DiDi/Uber integrations | ✅ Toast suite | **Skip:** POS features; only relevant if Phase 3 passes | 3 | — | [SR 12 page](https://softrestaurant.com/soft-restaurant-12), [SR integrations](https://www.softrestaurant.com/integraciones) |
| Dish margin per channel after delivery-app commission · *New (neither)* | 🟡 Sales by service/station (dine-in vs delivery); no margin | ❓ Not found | **Build later (candidate):** margin per dish on Rappi/DiDi/Uber net of a 20-30% commission. Proven only by small vendors (Fooderise order-profitability tool) and commission data, so **likely** at best; validate demand in interviews | 2 | Márgenes | [Stuart](https://blog.stuart.com/en/last-mile-delivery/most-profitable-sales-channels-in-the-restaurant-industry), [Fooderise](https://www.fooderise.com/en/order-profitability) |

### 8. Forecasting

| Feature | Soft Restaurant (version; how good) | Toast IQ / Toast | Our recommendation | Phase | Plan | Evidence |
|---|---|---|---|---|---|---|
| Sales forecast · *Both have* | 🟡 Analytics "Acumulado de ventas" with projection and % vs prior year | ✅ AI sales forecasts (Team) | **Build (light):** next-week sales and top-dish units by weekday, inside the weekly report. Proven: Toast, Nory | 2 | Márgenes | [SR Analytics](https://softrestaurant.com/addons/analytics), [NRN](https://www.nrn.com/restaurant-technology/toast-unveils-an-array-of-new-ai-agents-for-restaurants) |
| Prep / purchase quantities ("compra 18 kg de jitomate") · *Toast has (early access), SR doesn't* | ❌ Only min/max stock | 🟡 Configurable Agent "forecasting food prep" (early access) | **Build later:** forecast x recipes once both exist. Proven: Nory (US$62.6M raised, procurement + forecasting) | 2 | Márgenes | [Nory](https://www.nory.ai/blog/nory-series-b-funding-to-revolutionise-restaurant-operations), [NRN](https://www.nrn.com/restaurant-technology/toast-unveils-an-array-of-new-ai-agents-for-restaurants) |

### 9. Multi-location

| Feature | Soft Restaurant (version; how good) | Toast IQ / Toast | Our recommendation | Phase | Plan | Evidence |
|---|---|---|---|---|---|---|
| Consolidated multi-branch sales · *Both have* | ✅ Analytics and SR Admin show one or many branches; Enterprise / SR Cloud unified reporting | ✅ (**likely**) | **Skip** as a feature; Q&A across branches is included in Cadena | — | Cadena (Q&A) | [SR Analytics](https://softrestaurant.com/addons/analytics), 01 §1 |
| Branch comparison of margin, food cost and leaks ("Centro pierde $X en descuentos vs Norte") · *New (neither, at margin/leak level)* | 🟡 Discounts by branch and sales by branch; no margin or leak ranking | ❓ Not found as a feature | **Build better:** weekly branch ranking in MXN with per-branch data freshness. Proven: R365, Tenzo, Nory multi-site analytics | 1b | Cadena | 02 §2, 07 Phase 1b |

### 10. Agent actions with confirmation

| Feature | Soft Restaurant (version; how good) | Toast IQ / Toast | Our recommendation | Phase | Plan | Evidence |
|---|---|---|---|---|---|---|
| Change data from chat (ingredient price, recipe, menu price in our model) · *Toast has, SR doesn't* | ❌ | ✅ Chat actions: adjust pricing, mark items out of stock, update menu; approval step not documented (❓) | **Build better:** every write is a `pending_change` with a diff, Confirmar/Rechazar buttons, 24 h expiry and audit log (project rule) | MVP | All plans | [Toast blog](https://pos.toasttab.com/blog/on-the-line/toast-iq), 09 §5 |
| WhatsApp-native approvals per batch (one CFDI = one tap; clean uploads auto-apply with "Deshacer") · *New (neither)* | ❌ | 🟡 Grow runs campaigns "with operator approval" (app/web, not WhatsApp) | **Build:** approvals live in the chat the owner already uses. Proven: Toast Grow approval flow; WhatsApp interactive buttons (04); chat-based spend approvals (Ramp/Expensify in Slack, **likely**) | MVP | All plans | [NRN](https://www.nrn.com/restaurant-technology/toast-unveils-an-array-of-new-ai-agents-for-restaurants), 04, 06 #6 |
| Owner-set alert rules ("avísame si el aguacate pasa $60/kg") · *Toast has (early access), SR doesn't* | ❌ | 🟡 Configurable Agents from templates (early access); xtraCHEF configurable price alerts | **Build (light):** owner edits thresholds on our coded rules; no free-form agents | 1b | Márgenes | [NRN](https://www.nrn.com/restaurant-technology/toast-unveils-an-array-of-new-ai-agents-for-restaurants), [xtraCHEF partner page](https://pos.toasttab.com/partners/directory/xtrachef) |

### 11. Mexico-specific

| Feature | Soft Restaurant (version; how good) | Toast IQ / Toast | Our recommendation | Phase | Plan | Evidence |
|---|---|---|---|---|---|---|
| Automatic Corte Z email as a data feed · *SR has* | ✅ SR 12 emails Corte Z at shift close (format **unverified**) | n/a | **Build (consume):** point it at our inbox; zero manager effort | MVP (if pilot is SR 12) | All plans | 01 §2, 03 B |
| ERP/PMS JSON push as a data feed · *SR has* | ✅ SR 11+, paid module (price **unverified**): every sale as JSON | n/a | **Build (consume):** HTTPS endpoint, shadow mode, then default | 1b | All plans | [ERP/PMS guide](https://softrestaurant.zohodesk.com/portal/es/kb/articles/m%C3%B3dulo-de-integraci%C3%B3n-erp-y-psm), 03 B.4 |
| Two-way WhatsApp in Mexican Spanish, no app install · *New (neither, as two-way)* | 🟡 SR 12 WhatsApp is outbound only (cortes, alerts) | ❌ Toast IQ lives in Toast Now app and Toast Web | **Build:** core channel. Proven: SR itself chose WhatsApp for alerts; Toast IQ adoption proves the chat format | MVP | All plans | 01 §2, 04 |
| CFDI-aware costing (pre-IVA ValorUnitario, SAT ClaveUnidad mapping, menu prices with IVA) · *New (neither)* | 🟡 SR 12 imports XML into inventory; no margin math on it | n/a | **Build:** inside costing rows above | MVP / 1b | Márgenes / Compras | 03 C.3 |

## What we charge for

Only things SR does not already give away. Sales Q&A, the weekly report, data ingestion (upload, Corte Z email, ERP/PMS push) and approvals are in every plan and never priced on their own ([10](10-business-model.md) §2).

| Plan (10 §2) | Paid features (from the table) | Why SR doesn't cover it |
|---|---|---|
| **Compras** (449) | CFDI XML and nota-photo price capture without a PC; supplier price history; price-shock alerts; SNIIM benchmark (Phase 2) | SR 12 imports XML only on the PC into inventory; no push alerts, no OCR, no market benchmark |
| **Márgenes** (899) | Compras + done-for-you recipe costing (setup fee) and per-dish margins on WhatsApp; menu-engineering matrix; price suggestions with approval; waiter-level leak patterns; cash-shortage patterns; owner-set alert rules; waiter scorecard; Phase 2: forecasts, variance, review digest | SR has a DIY recipe module but no price suggestions, no matrix, no pattern detection, no AI. We charge for the outcome (margin found), not for SR's costing maths |
| **Cadena** (799 / 699) | Márgenes + branch ranking of margin, food cost and leaks | SR Analytics compares branch sales and discounts, not margins or leak patterns |

## What we skip and why

| Skipped | Why |
|---|---|
| Sales dashboards, goals, consolidated branch sales | SR Admin and Analytics give them free or in the licence; we read them as data |
| Per-event cancellation/discount/reprint alerts | SR 12 sends them on WhatsApp; we only add the weekly pattern in pesos |
| Inventory counts, POs, transfers, accounting pólizas, tip distribution | SR Pro already does them; duplicating them makes us a second POS back office |
| Writing prices or 86s into SR | No reliable write path; would raise EULA risk; Phase 3 only |
| Scheduling, attendance | No labour cost in SR exports; informal scheduling in MX independents; Toast-scale feature for a POS owner |
| Marketing, offers, SEO, loyalty, phone answering | Need guest identity SR exports don't carry; Meta Business AI and partners cover guest messaging; not our wedge |
| Ordering, delivery hub, KDS, kiosk, reservations | POS features; gated behind Phase 3 |

## Top 5 differentiators

1. **Cost-driven price suggestions with the math shown, IVA-aware, approved by one tap.** SR has none; Toast's Menu Agent is early access and US-only.
2. **Price capture with zero data entry:** forward the CFDI XML or photograph the Central de Abasto nota; price-shock alerts arrive with the dishes hit and the pesos at risk.
3. **Market benchmark:** "tu jitomate está 20% arriba de la Central de Abasto" from SNIIM. Neither SR nor Toast has it.
4. **Leak patterns per waiter and cashier, in pesos, weekly,** instead of the per-event pings SR 12 already sends.
5. **Two-way WhatsApp agent in Mexican Spanish on the POS they already have,** with every write confirmed and audit-logged, at MXN 449-899 (vs US$699 for Toast Grow or US$199+ for MarketMan).

## Still to verify

- SR 12 WhatsApp alert event list and whether SR 10/11 have it (official manual URL failed; 01).
- Whether SR Analytics is included in Lite as well as Pro ("incluido en tu licencia" does not say which).
- Toast IQ chat actions: is there an approval step before a price change? Toast Loyalty and time-clock details (marked **likely**).
- Demand for delivery-channel margin and review digests: ask in the 10 owner interviews.
