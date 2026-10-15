# Research notes: Phase 3 POS, Mexican data protection, stack costs

Date: 2026-10-15. Labels: **verified** = read on a primary/vendor page this session; **likely** = consistent secondary sources or standard practice; **unverified** = single/third-party source or from memory. Prices are USD unless MXN is stated. Not legal advice; every legal point needs a Mexican lawyer/contador before launch.

## Key findings

1. **LFPDPPP was replaced.** New law published in the DOF 20 Mar 2025, in force 21 Mar 2025; the INAI is gone and the **Secretaría Anticorrupción y Buen Gobierno** is now the authority (**verified** via Garrigues; Hogan Lovells/HLC). Principles, ARCO rights and notice duties are largely the same as 2010 (**likely**, Basham). A 2026 legal compendium still shows the old text, so do not rely on aggregator sites; read the DOF text.
2. **Treat MermIA as responsable-or-encargado per data type.** Owner/sales data is the restaurant's; WhatsApp user phone numbers and chats are MermIA's own (MermIA is the responsable). Sign a data-processing clause (encargado contract) in the ToS and publish an aviso de privacidad before the pilot.
3. **Transfer to US LLM/cloud providers:** the 2025 law dropped the duty to disclose transfers in the aviso, but the Reglamento still has it, so disclose anyway (**verified**, Garrigues). Sub-processor use by an encargado is generally contract-based, not consent-based (**likely**). Sign DPAs with the LLM, Supabase, Meta; keep PII (names, phones) out of prompts.
4. **Reading Soft Restaurant's local SQL Server DB is a legal gray area, not a clear yes.** Copyright law reserves decompilation/reverse engineering to the owner (LFDA art. 106, **verified**); CPF art. 211 bis 1 punishes unauthorized access to secured systems (**verified**, but it covers a system the user has no right to access; the restaurant owns its data and its machine). Get written customer authorization and read the actual SR EULA before building a connector. MVP file exports avoid this entirely.
5. **CFDI is cheap to buy, hard to get right.** Facturapi: MXN 299/month + MXN 0.60 per timbre (**verified**). Facturama API: MXN 1,650/yr + MXN 0.50 per folio (**verified**, page undated). Do not build your own stamping; use a PAC API from day one of Phase 3.
6. **Delivery apps are partner-gated.** Rappi API needs approval (**unverified**, third-party directory); Uber Eats says access may require written approval and a custom POS integration takes months (**verified**); Deliverect lists Rappi and DiDi Food (**verified**). Plan to integrate through an aggregator, not directly.
7. **Payments: Mercado Pago Point has a public POS API** (Orders API, Point Smart terminals, Mexico docs, **verified**). Clip has a developer portal with PinPad API and a Terminal SDK per third-party directories (**unverified**, could not reach developer.clip.mx).
8. **Offline-first is the hardest Phase 3 piece.** Realistic Phase 3 estimate: 4-6 months for 2 devs for a minimal restaurant POS, of which offline sync + printing + CFDI + payments are about two thirds (**unverified** estimate, my judgement).
9. **Stack for the MVP: Supabase Pro (US$25, includes US$10 Micro credit) is enough** (**verified**). Hosting is roughly US$2-5 per restaurant per month at 10-200 restaurants (estimate below); LLM and WhatsApp costs dominate.
10. **Build now for Phase 3:** POS-agnostic schema with `source` + `external_id`, UUID PKs, cents-as-integers + currency, tax/CFDI fields, immutable event/audit log, modifiers/tips/payments tables, `updated_at`/version columns, tenant_id + RLS from day one.

## 1. Phase 3 POS requirements (Mexico)

### 1.1 CFDI 4.0 via PAC

| Provider | Model | Price | Label / source |
|---|---|---|---|
| Facturapi | Subscription + per-timbre | API plan MXN 299/mo; timbre MXN 0.60; E-Receipt (autofactura) plan MXN 599/mo per org + MXN 0.40/receipt; extra user MXN 99; custom pricing for volume; 14-day trial | **verified** https://www.facturapi.io/pricing |
| Facturama | Annual API module + folio packs | API module MXN 1,650/yr; folios MXN 0.50 (1-10k), 0.45 (10k-50k), 0.40 (>50k), 1-yr validity, IVA incl.; 30-day trial, 15 folios; Facturama works with PACs rather than being one | **verified** (page undated) https://facturama.mx/planes-facturacion |
| SW Sapien | Per-stamp packs | not found | **unverified**; request quote |
| Finkok | Per-stamp packs | not found; generic blog range MXN 0.30-2 per invoice, packs MXN 1-3 extra | **unverified** |
| EdiFactMx | Packs | e.g. 150 stamps MXN 450 | **unverified** (third-party snippet) https://www.edifact.com.mx/cfdi-40 |

- Authorized PAC list is published by SAT; verify any chosen PAC is on it (**likely**).
- **Factura global (público en general):** receptor RFC XAXX010101000, name "PÚBLICO EN GENERAL", régimen 616, uso S01; groups the period's unbilled sales by tax rate (**likely**, https://praxiumconsultores.com/blog/como-emitir-la-factura-global-al-publico-en-general). One blog says the issue deadline is 24 h after period close from 2026 (RMF 2026 rule 2.7.1.21) versus 72 h before: **unverified**, check the RMF.
- **Late invoice requests:** global must be replaced/cancelled to avoid double counting (**likely**). Design: ticket -> `invoice_status` (none / customer-requested / in-global) per sale.
- **Self-invoicing portal:** a page where the diner enters ticket id + RFC. Facturapi sells this as "E-Receipts + Autofactura" (**verified** above). Cheaper than building; ticket needs QR/URL + folio.
- **Customer-deductible restaurant CFDI:** pay method must be card/electronic for deduction; cash not deductible in general (**likely**, praxium blog).
- Difficulty: medium. Cost: ~MXN 0.5-0.6 per CFDI + MXN 299/mo, cancellation/complementos need testing. Effort: 2-3 weeks including sandbox testing and tax-regime edge cases.

### 1.2 Printers, drawers, KDS, comanderas (mostly **likely**/standard practice, not verified this session)

| Item | Notes |
|---|---|
| Thermal ticket printers | ESC/POS (Epson, Star, generic 58/80 mm). Network (LAN) printers are the reliable path from a web app/iPad: raw TCP 9100 or a local print agent. USB and Bluetooth from browsers are limited (WebUSB/WebBluetooth not on iOS Safari). |
| Cash drawer | Opens via the printer's RJ11 kick pulse (ESC/POS command), so no separate integration. |
| Kitchen printer vs KDS | Kitchen printer = same ESC/POS over LAN, routed per station; KDS = a web screen subscribed to orders. KDS is easier than printers for a cloud product; keep printers as fallback because kitchens are loud/greasy and Mexican restaurants expect paper. |
| Comandera (waiter device) | Phone/tablet PWA ordering; sends comandas to stations. Needs offline queue on LAN. |
| Print architecture | Browser cannot print raw to LAN printers. Options: native iPad/Android shell app, a tiny local print-relay on a mini-PC, or vendor SDKs. Pick this early; it decides "web only" vs "native shell". |

Difficulty: medium-high (hardware variance is the hidden cost). Estimate 3-5 weeks for 2-3 printer models + routing (**unverified**).

### 1.3 Tips, split bills
- Tips (propina) are customer-voluntary and normally not part of the sale price; sources disagree on CFDI treatment (not part of invoice vs "no objeto de impuesto", 01), so confirm with a contador (**unverified**, conflicting blogs: https://www.contadigital.mx/posts/tratamiento-fiscal-de-las-propinas).
- Model: tip as a separate line on payment, per-waiter attribution, card tips reported separately; pooled-tip rules by restaurant config.
- Split bills: by item, by seat, by equal share, partial payments; each split produces its own ticket and optionally its own CFDI. Model order -> checks -> payments from day one. Medium difficulty (UI-heavy, tax rounding).

### 1.4 Payment terminals

| Provider | Integration | Label / source |
|---|---|---|
| Mercado Pago Point | Orders API to push amounts to Point Smart terminals (Mexico docs); needs branch + register per terminal; cards, contactless | **verified** https://www.mercadopago.com.mx/developers/en/docs/mp-point/overview |
| Clip | Developer portal: Checkout, Transactions, Refunds, PinPad API, Terminal SDK; Clip PinPad launched Nov 2025 with POS API | **unverified/likely** (press: https://www.payclip.com/press-releases-list/clip-introduces-pin-pad-fixed-terminal-for-high-volume-businesses; endpoints via third party) |
| Getnet, BBVA, Zettle, others | Not researched | **unverified** |

Strategy: integrate 1-2 terminals via a `payment_provider` interface; allow "manual card payment" (cashier keys amount) as universal fallback, which is what most POS do first. Terminal APIs need a connectivity path; with the internet down, card payments usually also fail, so offline mode = cash + manual-card.

### 1.5 Delivery integrations

| Channel | Finding | Label |
|---|---|---|
| Rappi | Partner developer portal, OAuth2, menus/orders/webhooks; not self-serve | **unverified** (apis.io directory) |
| Uber Eats | Marketplace APIs (stores, menus, orders); access may need written approval; US page says 2-3 months for custom integration | **verified** https://developer.uber.com/docs/eats/introduction |
| DiDi Food | No developer program found; Deliverect lists it | **unverified** / Deliverect **verified** |
| Deliverect | Two-way integrations with Rappi and DiDi Food; requires subscriptions to both | **verified** https://www.deliverect.com/en/integrations/rappi |
| Otter, Ordatic | Not found in search | **unverified** |

Recommendation: do not build direct integrations for Phase 3 v1; become a Deliverect (or similar) POS partner, or offer a "delivery orders entered manually/tablet" fallback. Phases 1-2 can already ingest delivery-channel sales as `channel` on sales.

### 1.6 Offline-first sync options

| Option | Fit | Notes |
|---|---|---|
| PowerSync | Postgres <-> SQLite on device, good for Supabase | Free tier 2 GB synced/500 MB hosted; Pro from US$49/mo (**unverified**, aggregator https://toolradar.com/tools/powersync/pricing). FSL source-available license (**likely**). Writes go through your own backend, which suits order rules. |
| ElectricSQL | Read-path sync (Electric "next"); write path is the app's job | **unverified** (competitor claim) |
| Zero (Rocicorp) / Replicache | Query-based sync, optimistic mutators | Not verified this session |
| RxDB | JS local-first DB, Apache 2.0 core, many storage adapters | **unverified** (vendor page https://rxdb.info) |
| CouchDB/PouchDB | Mature multi-master replication; heavier ops, weaker relational reporting | **likely** |
| CRDTs (Automerge/Yjs) | Fit for text/docs; poor fit for inventory/payment invariants | **likely** |

Conflict rules for orders (design opinion): orders are append-only event logs created on a device with a device-generated UUID and per-device sequence; items added = union; item void/discount = event requiring a role; table close/payment is a single-writer state machine (first valid close wins, a late conflicting close creates a review flag); totals always recomputed server-side from events; ticket folio numbering per device-prefix to avoid duplicate fiscal folios; CFDI stamping is online-only and queued. Inventory deduction is derived, never synced directly.

Difficulty: high. Prefer a sync engine over a custom one. Prototype in Phase 2 on a small non-critical table to learn.

### 1.7 Difficulty and cost summary (all **unverified** estimates)

| Block | Effort (2 devs) | Recurring cost |
|---|---|---|
| Core POS (menu, tables, orders, split, tips, roles) | 6-8 wks | - |
| Offline sync + conflict handling | 4-8 wks | PowerSync-like ~US$49-599/mo or self-host |
| CFDI (PAC, global, autofactura, cancel) | 2-4 wks | ~MXN 0.5-0.6/CFDI + MXN 299/mo |
| Printers/drawer/KDS | 3-5 wks | hardware by customer |
| Payment terminals (1-2) | 2-4 wks each | per-transaction fees paid by merchant |
| Delivery via aggregator | 2-4 wks + partnership time | aggregator fees |
| Total to a sellable POS | roughly 5-8 months | |

### 1.8 What Phases 1-2 should build now
- POS-agnostic schema: `restaurant`, `location`, `menu_item`, `modifier`, `order`, `order_item`, `payment`, `tip`, `discount`, `void`, `channel` (dine-in, delivery app, takeout), `staff`, `shift`, `cfdi_status`; each row with `tenant_id`, `source`, `external_id`, `created_at`, `updated_at`.
- UUID primary keys generated client-side-safe; money as integer centavos + currency; tax breakdown per line; timezone stored per location.
- Append-only audit log and pending-change/approval tables (already required by the brief); reuse them as the POS audit trail.
- A metrics layer in SQL views/RPCs fed only from the normalized model, so the POS later writes the same tables.
- Adapter interface per source; mark sales with `fiscal_status`.
- RBAC roles (owner, manager, admin, cashier, waiter) now.
- Ingredient/recipe tables with unit conversion and cost history (needed for POS stock deduction).
- Avoid: building any sync engine in Phases 1-2; do one PowerSync/RxDB spike at the end of Phase 2.

## 2. Mexican data protection

### 2.1 The law (as of 2026-10-15)

| Point | Finding | Label / source |
|---|---|---|
| Law | New LFPDPPP published 20 Mar 2025, in force 21 Mar 2025, replaces 2010 law | **verified** https://www.garrigues.com/es_ES/noticia/mexico-nueva-ley-federal-proteccion-datos-personales-posesion-particulares-introduce |
| Authority | INAI extinguished after Dec 2024 constitutional reform; Secretaría Anticorrupción y Buen Gobierno enforces; takes INAI resources | **verified** (Garrigues; https://www.hlc.com/es/publications/mexicos-new-federal-data-protection-law-what-it-means-for-companies) |
| Changes | "Responsable" definition now covers encargados too; consent express or tacit (tacit valid once the notice is available, unless law requires express); new purpose = new consent; consent exceptions changed; new infraction for mishandling ARCO requests; cancellation/opposition scope clarified; fines in UMA; amparo replaces nullity suit; data blocked before deletion; confidentiality duty extends to processors/employees; right to object to automated processing with adverse effects | **verified** (Garrigues, HLC) |
| Transfers | Duty to state transfers in the aviso removed from the law but remains in the regulations, so include it | **verified** (Garrigues) |
| Definitions | One summary says "personal data" no longer limited to natural persons; Garrigues text says "persona identificada o identificable" | conflicting; **unverified** |
| Reglamento / lineamientos | Whether the 2011 Reglamento and 2013 aviso lineamientos still apply, and whether new secondary rules are out, was not confirmed | **unverified**: ask a lawyer |
| Fine amounts, breach notification, ARCO deadlines | Not found in fetched sources | **unverified** |
| Old text still on sites | A compendium says "no reforms after 20 May 2024" (stale) | warning: https://sdv.com.mx/compendio/ley-proteccion-datos-personales/articulo-36/ |

### 2.2 Aviso de privacidad (for MermIA's own users: owners, managers, staff phone numbers)
- Integral notice must list data processed, flag sensitive data, state purposes separating those needing consent (**verified**, Garrigues/HLC). Simplified notice for electronic channels: controller identity/address, data, purposes, how to limit use, link to integral notice (**verified**, HLC).
- On WhatsApp: first message includes the short notice + link and an "Acepto" button (design opinion; tacit consent is valid when the notice is made available, but express consent via button is cleaner evidence).
- Notice in Mexican Spanish; keep a consent log (timestamp, wa_id, notice version).
- Sensitive data: avoid collecting any. Staff names/sales per waiter are personal data of employees; notify the restaurant that it must inform its staff (likely).

### 2.3 MermIA as encargado of restaurant data
- Restaurant (a persona moral or physical person) decides the purposes -> responsable; MermIA processes on its behalf -> encargado. Mostly business data (sales, costs); personal data is limited to staff/waiter names, sometimes customer names/phones/RFC from CFDI or delivery orders (**likely**).
- Needed: contract clauses (process only on instructions, confidentiality, security measures, sub-processor list/approval, return/deletion at end, assist with ARCO) (**likely**, standard under the regime; HLC recommends reviewing provider contracts to define roles clearly).
- If MermIA uses data for its own purposes (benchmarks across restaurants, model improvement), it becomes a responsable for that use: use anonymized/aggregated data and say so in the contract.
- Operational: deletion/export per tenant, data retention policy, blocking before deletion, access logs.

### 2.4 Cross-border transfer (OpenAI/Anthropic/Google, Supabase region, Meta)
- Under the 2010 regime, transfers to third parties required aviso + consent unless an exception applied; remisiones to an encargado did not need consent (**likely**). Generic template cites art. 36 and Reglamento arts. 68-74 (**unverified**, https://forms-legal.com/es/mexico/business/policies/acuerdo-transferencia-datos-transfronteriza-mexico). Re-check against the 2025 text.
- Practice: DPAs with each vendor, zero-retention / no-training API terms (check per vendor in the LLM research), list sub-processors in the aviso, pseudonymize before sending to the LLM (send aggregates and item names, not names/phones/RFC).
- Region: Supabase hosting in US East is the common choice; Mexico-region options not verified.

### 2.5 WhatsApp user data
- Meta is itself a controller of WhatsApp data; MermIA is responsable for the phone numbers, message content and media it stores. Keep minimal: store parsed data, discard raw media after parsing/retention window; store report files for audit with a retention limit (e.g. 90 days; opinion).
- Photos of receipts/invoices may include third-party personal data (RFC, names): same retention rules.

### 2.6 POS data ownership and reading SR's local DB
| Point | Finding | Label |
|---|---|---|
| Data ownership | No Mexican statute found that gives a POS vendor ownership of a restaurant's transaction data; the restaurant is the business owner of its records (plus fiscal duty to keep accounting records) | **likely**; confirm with lawyer |
| Reverse engineering | LFDA art. 106 reserves decompilation / reverse-engineering of a program to the right holder | **verified** https://mley.mx/LFDA/articulo/106/ |
| Backup copies | Art. 105: legitimate user may make only copies authorized by the licence or one backup copy | **verified** https://mley.mx/LFDA/articulo/105/ |
| Unauthorized access | CPF art. 211 bis 1 punishes modifying/destroying (6 mo-2 yrs) or only copying (3 mo-1 yr) information in secured systems without authorization; reform to 3-10 yrs proposed, not confirmed passed | **verified** text https://mley.mx/CPF/articulo/211-bis%201/ |
| Interoperability exception | Not found | **unverified** |
| SR EULA language | Not retrieved; typical EULAs ban reverse engineering, sublicensing and third-party access to the database or schema (**unverified**, from general practice) | **unverified**: get the SR licence text from the pilot restaurant |

Practical stance: (a) MVP via user-initiated exports carries minimal risk; (b) a connector should only read data the owner authorizes in writing, read-only, with no schema reverse-engineering of the program binary, preferably using SR's own export/report functions or a documented DB view; (c) have a lawyer review the SR EULA before shipping the connector.

## 3. Stack cost data (2-dev team, 4 weeks)

| Service | Plan / price | Key limits | Label / source |
|---|---|---|---|
| Supabase | Free US$0: 500 MB DB, 1 GB storage, 500k edge invocations, pauses after 1 week inactivity, 2 projects, 1-day logs | not for production | **verified** https://supabase.com/pricing.md |
| | Pro from US$25/mo per org: 8 GB disk per project (then US$0.125/GB), 250 GB egress, 100 GB storage (US$0.0213/GB over), 2M edge invocations (US$2/M over), 100k MAU, 7-day logs, no pausing, US$10/mo compute credit (covers one Micro), spend cap on by default, PITR US$100/mo per 7 days | | **verified** same |
| | Compute add-ons: Micro US$10 (1 GB), Small US$15 (2 GB), Medium US$60 (4 GB), Large US$110 (8 GB), XL US$210 (16 GB) | | **verified** same |
| Neon | Launch US$0.106/CU-hr, Scale US$0.222/CU-hr, storage ~US$0.35/GB-mo, usage-based, no minimum | no built-in auth/storage/RLS tooling like Supabase | **verified (compute)** https://neon.com/pricing; storage **unverified** |
| Render | Starter US$7/mo (512 MB, 0.5 vCPU), Standard US$25/mo (2 GB, 1 vCPU) | | **unverified** (blog https://findstack.com/resources/railway-vs-render-vs-fly-io) |
| Railway | US$5/mo Hobby incl. US$5 credit, usage-based; ~US$15/mo for 512 MB service 24/7 | | **unverified** |
| Fly.io | per-second; shared-cpu-1x 512 MB ~US$3.19/mo, IPv4 ~US$2 | | **unverified** |
| Vercel | Pro US$20/user/mo incl. US$20 usage credit | per-seat cost for 2 devs = US$40 | **unverified** (https://makerkit.dev/blog/saas/vercel-cost) |
| Cloudflare Workers | Paid US$5/mo min; overages differ by source; R2 storage ~US$0.015/GB-mo, no egress fees | | **unverified** (sources conflict) |
| AWS Lambda | free tier 1M requests + 400k GB-s monthly; paid per request/GB-s | not re-checked this session | **unverified** |
| Sentry | Developer free: 1 user, 5k errors, 30-day retention; Team US$26/mo (annual), 50k errors, unlimited users | | **verified** https://sentry.io/pricing/ |
| Langfuse | Hobby free: 50k units/mo, 30 days, 2 users; Core US$29/mo: 100k units, then US$8/100k, 90 days; Pro US$199 reported | | **verified** (Hobby/Core) https://langfuse.com/pricing.md; Pro **unverified** |
| Helicone | Not checked | | **unverified** |

### Supabase features relevant to MermIA
| Feature | Use | Limit / caution |
|---|---|---|
| Postgres | normalized model, metrics views/RPC | 8 GB disk on Pro is ample (daily summaries); sales line items at 200 restaurants could reach GBs/year |
| RLS | multi-tenant isolation (`tenant_id` policy) | test RLS in CI; service-role key bypasses RLS (agent backend must never expose it); RLS adds query cost on big scans |
| Edge Functions | WhatsApp webhook, parsers | 2M invocations on Pro (enough); short execution/CPU limits make heavy Excel parsing better in a worker (limit values not verified) |
| Cron (pg_cron) / queues | daily/weekly report jobs | verify exact availability on your plan |
| Storage | raw report files, receipt photos | 100 GB included on Pro |
| Auth | dashboard login (Phase 2), 100k MAU | WhatsApp identity is a phone number; map wa_id to user |
| Backups | daily backups on Pro (**likely**), PITR extra US$100/mo | |
| Realtime | Phase 2/3 live dashboard | |

Suggested MVP stack (opinion): Supabase Pro (Postgres, RLS, Storage, Edge Functions, cron) + one small always-on worker (Fly.io/Render, ~US$7) for report parsing and LLM calls + Sentry free + Langfuse Hobby. Cloudflare/Vercel only if the Phase 2 dashboard needs hosting (Vercel per-seat cost vs Cloudflare Pages).

### Hosting cost per restaurant per month (estimate; excludes LLM, WhatsApp, PAC)
Assumptions: one Supabase project, daily report ingestion, <10 GB data at 200 restaurants, one worker, observability upgraded as needed. Prices from the table above (Supabase **verified**, worker/Langfuse/Sentry as noted). Calculation is mine; **unverified** as a forecast.

| Scale | Components | Monthly total (US$) | Per restaurant |
|---|---|---|---|
| 10 | Supabase Pro 25 (Micro covered by credit) + worker 7 + Sentry/Langfuse free | ~32-40 | ~US$3.2-4.0 |
| 50 | Pro 25 + Small compute 15-10 credit + worker 7-15 + Langfuse Core 29 + Sentry Team 26 | ~100-130 | ~US$2.0-2.6 |
| 200 | Pro 25 + Medium/Large 60-110 (credit -10) + PITR 100 + worker(s) 25-50 + Langfuse Core/Pro 29-199 + Sentry Team 26 + storage/egress overage ~10-30 | ~270-540 | ~US$1.4-2.7 |

Hosting is under about US$4 (roughly MXN 70-80) per restaurant per month at all three sizes, so it is small next to WhatsApp message fees and LLM tokens; FX conversion not verified.

## Open items for follow-up
- Get SR EULA text and a sample export from the pilot restaurant.
- Lawyer review: aviso de privacidad, DPA template, 2025 law secondary rules, cross-border clauses, connector legality.
- Confirm: SW Sapien and Finkok prices; Clip developer docs (developer.clip.mx); DiDi Food/Rappi partner programs; factura global deadline in the current RMF; tip CFDI treatment (ask a contador).
- Re-check pricing pages before quoting: Neon storage, Render, Railway, Fly, Vercel, Cloudflare, AWS Lambda, PowerSync, Zero, Helicone.
