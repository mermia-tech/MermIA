# 03 - Data ingestion and costing (kickoff sections B and C)

Date: 2026-10-15. Labels: **verified** (source read/returned this session), **likely** (consistent with sources or standard practice, not confirmed for SR), **unverified** (not found; confirm as stated). Soft Restaurant (SR) report formats and modules are covered in `01-soft-restaurant-research.md`; not repeated here.

## Key findings & recommendations

- **MVP ingestion: manual WhatsApp upload (files; in the MVP a photo gets a request for the file, OCR comes in Phase 1b per 08) with a dedicated email inbox as a second door.** It needs zero SR changes, zero installs, no legal exposure, and fits 4 weeks. If the pilot runs SR 12, point its automatic Corte Z email (SMTP, **verified** feature, format **unverified**, see 01) at our inbox from day 1. CSV and XML are not on Meta's list of accepted WhatsApp document types (**unverified** in practice, see 04): ask for xlsx/xls/pdf on WhatsApp and send CFDI XML by email until a device test shows XML gets through.
- **Long-term: the official SR ERP/PMS module first.** It is a paid module bought through a distributor, SR 11+. SR POSTs each sale as JSON (lines, discounts, taxes, payments, tips) to an endpoint we host: per check, at daily close, or every N minutes, with `x-api-key` auth and a retry queue (**verified**, 01). The module price is **unverified**. It is sanctioned, ticket-level and needs no install by us.
- **Second long-term option: a read-only local connector on the SR SQL Server DB** (opt-in, signed, outbound-only). Use it where the module is not available, or for recipes and inventory, which the push does not carry. Professional editions run SQL Server (**verified**, 01). Kavasoft and FactorBI already sell connectors that read the SR DB, and we found no visible objection from National Soft (**verified** that they exist; National Soft's stance **unverified**). The 2010 EULA still bars reverse engineering and "merging with other programs" without written authorization, so the risk is medium and contractual, not zero. Get written customer authorization and a lawyer's read of the current EULA. Schema is **unverified**. Both options evolve to our own POS in Phase 3.
- **No public developer portal or tech-partner program found.** The official integration surface is the ERP/PMS module, a menu-only REST service and the "Quiero integrar mi sistema" form (**verified**, 01). Automatic export of regular reports: not found (**unverified**). Only Corte Z/corte de caja is sent automatically, by email or WhatsApp (SR 11/12).
- **Build the parser around a batch model from day 1**: every upload = batch ID, file hash, detected report type, status `received -> parsed -> applied | needs_review | rejected`, then `rolled_back` or `superseded` (full lifecycle in 09 §2.6). This delivers the "reviewable and reversible" rule and dedup for free.
- **Costs: do not wait for perfect recipes.** Target the top ~10 dishes by sales and the ~20 ingredients that drive most of their cost; ship with +/-10% accuracy flagged as "estimated" (heuristic; no authoritative source found - **unverified** as a numeric standard, **likely** directionally).
- **Cost sources ranked by pain/benefit:** (1) SR recipe export if present; (2) CFDI XML forwarded to the same inbox/WhatsApp (structured, free, no OCR); (3) photo of a nota with vision OCR for informal suppliers; (4) chat/spreadsheet recipe capture; (5) SNIIM benchmarks only as sanity check and for alerts on commodities (no API found).
- **Margin logic must net out IVA.** Menu prices include 16% IVA; CFDI `ValorUnitario` is pre-tax. Food cost % = ingredient cost / (menu price / 1.16) (**likely**; verify with the pilot's accountant).
- **Alerts are rules in code, not LLM**: ingredient price moves >= X% -> recompute affected dishes -> if food-cost % crosses target, propose a price change that the owner confirms (human-approval rule).

## B. Ingestion options

### B.1 Option facts

| # | Option | What is known | Status |
|---|---|---|---|
| 1 | Manual WhatsApp upload | Cloud API accepts documents (xls/xlsx/pdf/txt/doc/docx) up to 100 MB; **CSV and XML are not on Meta's supported list** (delivery **unverified**: test on iOS/Android, 04); images jpeg/png (5 MB per third parties); media IDs expire (7 days in webhooks, 30 days via API) so we must download immediately. [Meta media docs](https://developers.facebook.com/documentation/business-messaging/whatsapp/business-phone-numbers/media), [Vonage](https://api.support.vonage.com/hc/en-us/articles/10900821425308-What-file-types-and-sizes-are-supported-on-WhatsApp), [Expertflow](https://docs.expertflow.com/cx-knowledgebase/latest/meta-whatsapp-cloud-api-limitations-key-highlights) | **verified** (5 MB image cap: third-party only) |
| 2 | Email forward / dedicated inbox | Standard (inbound email webhook e.g. a parse service). **SR 12 emails the Corte Z automatically at shift close (SMTP)**, and SR 11 had "Corte de caja por correo" (01). Scheduled email of other reports: not found. Also the right door for CFDI XML (see option 1) | Corte Z email **verified** (feature), format **unverified**; other scheduled reports **unverified**; our inbox is **verified** as generic tech |
| 3 | Scheduled/automated export | SR export scheduling: no documentation found. Windows Task Scheduler cannot drive a GUI export reliably without UI automation (fragile). Possible only if SR has a CLI/auto-export or "corte" hook | **unverified**; ask SR support / distributor |
| 4 | Local connector on SR DB | Professional editions use SQL Server (official KB, instance e.g. `NATIONALSOFT`; 01). Older Standard editions used a file DB (**likely**), and SR Cloud has no local DB. If SQL Server Express: 10 GB DB cap and no SQL Agent (2014-era thread; check installed version) [MS Q&A](https://learn.microsoft.com/en-us/answers/questions/2247920/small-data-from-sql-and-connect-it-with-bi-for-gen). **Commercial precedent:** Kavasoft SR Agent (read-only Windows service, outbound HTTPS) and FactorBI Vansync (ETL to AWS) [Kavasoft](https://kavasoft.app/integraciones/soft-restaurant), [FactorBI](https://www.factorbi.com/reportes-soft-restaurant) | engine **verified** (Pro); schema **unverified**; precedent **verified** |
| 5 | Official API / partnership | No public developer portal or tech-partner program; menu-only REST service (keys by email); "Quiero integrar mi sistema" form; National Soft sells through distributors (01) [ITSitio](https://www.itsitio.com/distribucion/national-soft-cumple-20-anos-en-mexico-y-lo-celebra-con-nuevas-iniciativas-para-los-canales/) | **verified** (01); partnership terms **unverified** |
| 5b | **SR ERP/PMS module (JSON push)** | Paid module via distributor, SR 11+. SR POSTs `Ventas[]` with `Conceptos[]` (product, qty, unit price, discount, taxes) and `Pagos[]` (method, amount, tip) to our URL; triggers per paid check, daily close, every N minutes, cancellations; `x-api-key`; failed sends queue and retry. No recipes/inventory [guide](https://softrestaurant.zohodesk.com/portal/es/kb/articles/m%C3%B3dulo-de-integraci%C3%B3n-erp-y-psm) | payload **verified** (01); module price and lead time **unverified** |
| 6 | Read SR cloud / SR Admin backend | SR Admin pulls reports "online" for several branches. Using its private endpoints = reverse engineering the customer's login; high ToS risk, brittle | feasibility **unverified**; legal risk high |
| 7 | Virtual printer of corte de caja (PDF) | SR prints cortes/tickets via Windows printers (**likely**). A virtual PDF printer (or "print to file") + folder watcher could capture them without DB access | **likely** feasible, needs pilot test |
| 8 | Photo + vision OCR | Works on any report; accuracy lower and numeric errors are costly. Use only as fallback with human confirmation of totals | **likely** |
| 9 | Google Drive / OneDrive synced folder | Manager (or option 3/7 script) drops files into a synced folder; we read via Drive API. Needs OAuth consent, adds a Google dependency | **likely** |

### B.2 Scores (1 = worst, 5 = best; opinion, to be re-scored after pilot)

| Option | Reliability | Restaurant effort (5 = none) | Build cost (5 = cheap) | Legal risk (5 = safe) | 4-week MVP fit | Total /25 |
|---|---|---|---|---|---|---|
| 1 WhatsApp manual | 2 | 2 | 5 | 5 | 5 | **19** |
| 2 Email inbox | 3 | 3 | 4 | 5 | 4 | **19** |
| 3 Scheduled export (if SR allows) | 4 | 4 | 3 | 5 | 2 | 18 |
| 4 Local DB connector | 4 | 4 | 2 | 4 | 1 | 15 (legal 3 -> 4: commercial precedent, no visible objection; EULA clause unresolved) |
| 5 Official API/partnership | 5 | 5 | 3 | 5 | 1 | 19 (but not obtainable in 4 wks) |
| 5b SR ERP/PMS push | 5 | 3 (buy module, configure once) | 4 | 5 | 2 | **19** (best long-term; needs SR 11+ and module purchase) |
| 6 SR cloud scraping | 2 | 4 | 2 | 1 | 1 | 10 |
| 7 Virtual printer -> folder | 3 | 4 | 2 | 4 | 2 | 15 |
| 8 Photo OCR | 2 | 3 | 3 | 5 | 4 | 17 (fallback only) |
| 9 Drive sync | 3 | 3 | 3 | 4 | 3 | 16 |

### B.3 Legal notes (not legal advice; get a Mexican lawyer to review before connector)

- **Data ownership:** the restaurant is the controller of its business data; no data-ownership clause was found in the 2010 EULA (01). Current SR 12 terms on DB access/third-party reading were **not found** - **unverified**. Action: obtain the SR license/EULA from the pilot and have counsel read the clauses on reverse engineering, DB access and third-party tools.
- **Connector risk (revised):** the 2010 EULA bars reverse engineering, modification and "merging with other programs" without written authorization (**verified**, old version, 01). Reading the DB with a standard SQL client is arguably not reverse engineering. Kavasoft and FactorBI sell DB-reading connectors publicly, and we found no blocking or legal action (**verified** that they exist; National Soft's stance **unverified**). Net: **medium contractual/commercial risk, lower practical risk**. The risk may rise once we compete with SR Analytics. The ERP/PMS push carries no such risk.
- **Personal data:** sales reports are mostly non-personal, but CFDI to customers (RFC, name), waiter names and tips are personal data. The LFPDPPP was replaced by a new law published in the DOF on 20 March 2025, in force next day; INAI's powers moved to the Secretaria Anticorrupcion y Buen Gobierno; a reform is logged 14 Nov 2025 (content not checked). **verified** [Diputados](https://www.diputados.gob.mx/LeyesBiblio/ref/lfpdppp.htm), [EY](https://www.ey.com/es_mx/technical/tax/boletines-fiscales/nueva-ley-federal-proteccion-datos-personal-posesion-particulares). We act as "encargado" (processor) - needs a data-processing clause in our contract and a privacy notice (**likely**).
- **Minimise:** strip customer-identifying fields at parse time; store only aggregates where possible.

### B.4 Recommendation

| Stage | Choice | Why |
|---|---|---|
| MVP (week 1-4) | **1 WhatsApp upload + 2 email inbox** (same pipeline, two adapters) | no SR dependency, no legal exposure, ships in days |
| Pilot spike (week 0-4, parallel, 1 day) | On the pilot: is SR 12 Corte Z email active (point it at our inbox); SR version/edition (11+ means the ERP/PMS module is possible); ask the distributor for the module price; test CSV/XML/xlsx delivery over WhatsApp on real phones; what DB engine is installed (read-only look, with permission) | converts **unverified** items into facts |
| Long-term (first) | **5b SR ERP/PMS push** to our HTTPS endpoint (ticket-level, sanctioned) | removes the weakest link (manager discipline) with no legal question |
| Long-term (fallback) | **4 Local connector** (read-only DB user, outbound HTTPS, auto-update, kill switch) where the module is not possible, or for recipes/inventory; written customer consent + lawyer review of the current EULA; then **Phase 3 own POS** writes the same normalized schema | covers SR installs without the module |
| Migration | Same normalized schema + batch model. Push and connector emit the same "batch" records (`source=sr_erp_push` / `sr_connector`). Run in shadow mode next to manual uploads for 2-4 weeks, reconcile totals, then switch off the manual reminder | zero change for agent/dashboard |

### B.5 Parsing safety: wrong files, photos, duplicates, reversibility

| Problem | Handling |
|---|---|
| Wrong file / unknown report | Detect by file type + header fingerprint (sheet names, column titles). Unknown -> do not load; reply in Spanish "No reconoci este reporte; necesito el reporte X". Keep file in quarantine for later adapter work |
| Right report, wrong period/branch | Extract period and branch from the file; compare to expected (yesterday, known branches); mismatch -> ask manager to confirm before apply |
| Photo instead of file | Classify image (vision, cheap model); if it is a corte/ticket, OCR to a structured draft, show totals read back ("Vi ventas por $X, ¿correcto?"), store with `quality=ocr`, never mixed silently with file data |
| Duplicates | SHA-256 of file + natural key (branch, business date, report type). Same hash -> ignore with reply; same key, different hash -> treat as correction: new batch supersedes old after confirmation |
| Partial/garbled parse | Validation rules: totals equal sum of lines (tolerance), no negative qty except refunds, dates in range. Fail -> batch `rejected`, reason shown |
| Reviewable | Batch summary message (rows, sales total, date range, anomalies); full detail in dashboard later |
| Reversible | Every row carries `batch_id`; rollback = mark batch `rolled_back` and exclude it in metric views (soft delete, audit-logged, who/when). A superseded batch can be restored |
| Auth | Only registered phone numbers of the restaurant may upload; others ignored |

## C. Ingredient costs and recipes

### C.1 Case 1: recipes and costs are in SR

- Extraction: via the recipe/inventory report export (xls) if the module is populated; formats **unverified here** - see `01-soft-restaurant-research.md`. Get a sample from the pilot.
- Sync: re-import a "recetas / costos" export weekly or when the manager sends it; diff against our table and show a change list for confirmation (write rule). Our DB is system of record for history; SR is a source.
- Trust check: compare SR theoretical cost against last purchases from CFDI; flag SR costs older than N days (stale). SR 12 imports purchase CFDI XML and links it to insumos automatically (**verified** marketing claim, 01), so SR 12 costs may be fresher than older versions'.
- Risk: many restaurants leave SR costs unmaintained (rate **unverified**); ask the pilot.

### C.2 Case 2: not in SR - capture, least painful first

| Source | How | Effort | Accuracy | Notes |
|---|---|---|---|---|
| CFDI 4.0 XML of suppliers | Manager forwards XML to the inbox (WhatsApp doc only if a device test shows XML is delivered; **unverified**, 04) | Low | High | See C.3 |
| SAT descarga masiva | Owner/accountant authorizes download of received CFDI with e.firma | One-time setup, high trust | High, complete | Needs FIEL/e.firma; vendor sources say up to 200k XML or 1M metadata records per request and up to 72 h wait - **unverified** vs SAT docs. [Edifact](https://www.edifact.com.mx/masinfo/cfdi-descarga-masiva), [El Contribuyente](https://www.elcontribuyente.mx/2022/03/el-sat-actualizo-la-documentacion-de-la-descarga-masiva-de-los-cfdi/). Phase 2+ (e.firma handling is a security burden) |
| Notas from informal suppliers (Central de Abasto) | Photo -> vision model extracts supplier, date, items, qty, unit, price -> user confirms | Medium | Medium; handwritten is poor | Always confirm; store image |
| Recipe by chat | Agent asks per top dish: "¿Qué lleva? ¿cuánto de cada uno?" -> draft -> confirm | Medium | Medium | Do top 10 dishes first |
| Recipe by spreadsheet template | Prefilled with menu from SR sales report; owner fills grams | Medium-high | Medium-high | Good for owners who like Excel |
| Photo of recipe card | Vision OCR to draft | Low | Low-medium | Confirm |
| SNIIM | Wholesale reference prices | None | Benchmark only | See C.4 |

### C.3 CFDI 4.0 XML parsing

Official spec: SAT Anexo 20 (get XSD from sat.gob.mx; secondary summary: [Edifact](https://www.edifact.com.mx/masinfo/anexo-20-cfdi-4.0.html)). Field names below come from the spec as known and were only partly confirmed by search (**likely**; validate against the XSD):

| Node/attribute | Use |
|---|---|
| `cfdi:Comprobante` (Fecha, Moneda, TipoDeComprobante=I, Total, SubTotal) | invoice date, currency; accept only type I (ingreso) from suppliers |
| `cfdi:Emisor` (Rfc, Nombre) | supplier identity |
| `cfdi:Receptor` (Rfc) | must match restaurant RFC (reject otherwise) |
| `cfdi:Conceptos/cfdi:Concepto`: `ClaveProdServ`, `ClaveUnidad`, `Unidad`, `Cantidad`, `Descripcion`, `ValorUnitario`, `Importe`, `Descuento`, `ObjetoImp` | one price observation per line: ingredient candidate, qty, unit, unit price pre-IVA ([guide](https://siemprealdia.co/mexico/fiscal/anexo-20-sat-cfdi-4-0/)) |
| `cfdi:Complemento/tfd:TimbreFiscalDigital@UUID` | dedup key (UUID globally unique) |

- ClaveUnidad uses SAT catalog codes (e.g. KGM kilogram, LTR litre, H87 piece - **likely**); map to our base units. ClaveProdServ is a catalog code (food mostly in the 50xxxxxx family - **likely**) useful for category, not for exact ingredient.
- Descriptions are free text and inconsistent: map `(supplier RFC, description)` -> ingredient with a learned alias table; first time, ask the owner once (confirmation), then automatic. Pack sizes hide in text ("CAJA 12 PZ 500G") - parse with rules, LLM only for unresolved lines.
- Many market/Central de Abasto suppliers issue no CFDI; do not assume coverage.
- Forwarding: manager forwards email with XML to the inbox (preferred); attaching XML in WhatsApp may not work because XML is not on Meta's supported document list (**unverified**, 04). Test it; a zipped XML is not a fix either (zip is also unlisted). PDF without XML is not enough (ask for XML). Also verify UUID status with SAT (optional, later).

### C.4 Public price benchmarks

| Source | Findings | Status |
|---|---|---|
| SNIIM (Secretaria de Economia) | Free wholesale prices: fruits/vegetables, grains, livestock, poultry/eggs, fisheries (La Nueva Viga), "Precios del dia", historical series. No API/download mentioned on the home map; update schedule not stated on the page (see its "Periodicidad" page). URL fetched: `http://www.economia-sniim.gob.mx/nuevo/mapa.asp` ([site](http://www.economia-sniim.gob.mx/)). **verified** content; frequency/API **unverified**. Third-party datasets exist (Alphacast daily series ending Apr 2025; Vesper added 205 series in Jan 2026) [Alphacast](https://www.alphacast.io/datasets/activity-production-mexico-sniim-wholesale-prices-of-fruits-vegetables-new-format-41926), [Vesper](https://vespertool.com/release-notes/205-new-mexico-price-series-from-sniim/). A 2021 gov report noted COVID-era suspension of collection, so check current continuity. Likely needs scraping of ASP pages: check terms and cache politely |
| PROFECO Quien es Quien en los Precios | Retail prices, 1,800+ stores incl. some Central de Abasto stalls; portal qqp.profeco.gob.mx; open-data JSON/CSV listing last updated July 2019 [DataMX](https://datamx.io/dataset/quien-es-quien-en-los-precios). Retail/consumer basket, weak for restaurant ingredients. **verified** exists; API currency **unverified** |

Use: benchmark "your tomate price vs Central de Abasto reference" and spot invoice outliers; never as the cost of record.

### C.5 Accuracy that is good enough

- Practical rule (**likely**): cost the top ~10 dishes by sales (and ~20 ingredients by spend) first; extend later. Software vendors say variance concentrates in a few high-volume lines and that yield loss is the largest unexplained driver [Supy](https://supy.io/blog/learn-theoretical-vs-actual-food-cost-variance), [Supy yield](https://supy.io/blog/learn-restaurant-yield-costing). No authoritative "80/20" study was found, so state it to customers as a rule of thumb.
- Show every dish cost with a confidence tag: `confirmed` (CFDI price < 30 days + owner-confirmed recipe), `estimated` (older price / benchmark / chat recipe), `missing`. Never show a margin without its tag.
- Variance bands used by vendors: <2 pts good, 2-3 acceptable, 3-5 improvable, >5 systemic (vendor blog heuristics, not a standard) [Supy](https://supy.io/blog/learn-theoretical-vs-actual-food-cost-variance).

### C.6 Units, yield (merma)

- Store every ingredient with a **base unit** (g, ml, pza) and conversions (kg->1000 g, L->1000 ml, "caja 12 pza", density only where required).
- **Yield %** per ingredient (edible portion / purchased): e.g. trimming meat, peeling, shrink. Cost per usable unit = price / yield. Default yields from a seed table flagged `default`; replace via a simple yield test (weigh before/after) for the top proteins.
- Recipe line = ingredient, qty in base unit, optional yield override; sub-recipes (salsas, bases) cost per output unit.
- Recipes list modifiers/extras as separate lines (needs SR sales report with modifiers; see doc 01).

## Price tracking -> margin alerts -> price suggestions

### Methods

- **Kasavana-Smith menu engineering** (1982): classify each item by popularity (share of units vs. threshold, commonly 70% of the equal share) and contribution margin (price - food cost) vs. the menu's weighted average: Star (high/high), Plowhorse (high pop, low margin), Puzzle (low pop, high margin), Dog (low/low). Sources: [FIU paper](https://digitalcommons.fiu.edu/record/17973/files/V13n195e.pdf), [BCcampus textbook](https://opentextbc.ca/basickitchenandfoodservicemanagement/chapter/describe-the-principles-of-menu-engineering/). The 70% rule: **likely** (textbook standard, not checked in the fetched text). Actions: Stars protect; Plowhorses raise price or cut cost slightly; Puzzles promote/reposition; Dogs rework or remove.
- **Food cost % targets:** vendor sources cluster at 28-35% for full service (30% common), 25-40% across concepts; one cites US Foods 28%/32% (second-hand). Textbook warns that blanket 30% is often chosen without calculating what the menu needs [Resy](https://resy.com/join/resources/restaurant-menu-pricing/), [SevenRooms](https://sevenrooms.com/blog/restaurant-menu-pricing-strategy/), [BCcampus](https://opentextbc.ca/basickitchenandfoodservicemanagement/chapter/describe-the-principles-of-menu-engineering/). **likely** as US-centric rule of thumb; no Mexican benchmark found - ask the pilot, default 30-35% for MX independents (**unverified**), configurable per restaurant/category.
- **Theoretical vs actual cost:** theoretical = sum(units sold x recipe cost); actual = opening stock + purchases - closing stock. Needs inventory counts, so **Phase 1 reports theoretical only**; actual is Phase 2 when counts/purchases exist.

### Alert thresholds (proposed defaults, configurable)

| Alert | Trigger |
|---|---|
| Ingredient price jump | unit price change >= 8% vs 30-day average, or >= 15% vs last price (only for ingredients in top-20 spend) |
| Dish margin breach | dish food cost % > target + 3 pts |
| Stale cost | ingredient price older than 45 days |
| Mix shift | top-5 dish share changes > 20% week over week |
| Price suggestion eligibility | breach persists after 2 observations (avoid noise) |

All numbers are our design defaults (opinion), to calibrate in the pilot. Cadence: daily silent computation; message the owner weekly summary plus immediate message only for severe breaches (also minimises template cost - see doc 04).

### Price-suggestion formula

```
net_price_target   = dish_cost / target_food_cost_pct          # pre-IVA
menu_price_raw     = net_price_target * 1.16                   # IVA 16% included in menu price
menu_price_sugg    = round_to_price_point(menu_price_raw)      # round UP to the next point
guardrails         = max change +/- 10% per step; never below current price if cost rose
```

- Rounding: to the next $5 for items under ~$250, next $10 above (design choice; Mexican menu price-point norms **unverified** - check with pilot menu). Show impact: new margin, expected food cost %, "lo que cambia" for confirmation.
- Menu-engineering aware: for Plowhorses suggest the full increase; for Dogs/Puzzles suggest cost or portion review before price; never auto-apply (human approval, audit log).
- Contribution-margin variant: for Stars do not increase; for items where price is capped by competitors, suggest ingredient or portion change.

### Data model needs (normalized, POS-independent)

Sketch only; the canonical table names are in 09 §2 (`import_batch`, `item_sales_agg`, `menu_item`, `tenant_id` instead of `restaurant_id`).

| Entity | Key fields |
|---|---|
| `ingredient` | id, restaurant_id, name, base_unit, category, default_yield_pct |
| `ingredient_alias` | supplier_rfc/name, source_text, ingredient_id |
| `ingredient_price` | id, ingredient_id, unit_price_net, base_unit, currency, **effective_from**, **effective_to**, **source** (cfdi/ocr_note/manual/sr_import/benchmark), source_ref (UUID/file), batch_id, confidence, created_by |
| `unit_conversion` | ingredient_id, from_unit, to_unit, factor |
| `recipe` / `recipe_line` | dish_id, version, effective_from/to, ingredient_id or sub_recipe_id, qty_base, yield_override |
| `dish_cost_snapshot` | dish_id, date, cost, price, food_cost_pct, confidence |
| `menu_item_sales` | restaurant, branch, date, item, units, gross, discounts, batch_id |
| `ingestion_batch` | id, source, file_hash, report_type, period, status, approver, rolled_back_at |
| `alert` / `price_suggestion` / `pending_change` / `audit_log` | rule, value, status, approved_by, timestamps |

Price history is append-only with effective dates so any past margin can be recomputed; the "cost of record" for a date = latest price effective on that date by source priority (cfdi > confirmed note > sr_import > manual > benchmark).

## What we still need from the pilot (verify)

1. Sample exports of every SR report and the recipe/cost export; SR version (the SR Admin app mentions "licencias SR 12").
2. Whether SR 12 Corte Z email is active; SR version/edition (ERP/PMS module needs SR 11+) and the module price from the distributor; DB engine and install path (with permission).
2b. Real-phone test: does an SR export or CFDI XML sent as CSV/XML reach our webhook?
3. SR license text; whether the owner keeps recipes in SR.
4. Pilot's supplier mix (share with CFDI vs notas), real food cost %, menu price points.
