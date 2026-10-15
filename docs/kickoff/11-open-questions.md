# 11 - Open questions

Date: 2026-10-15. What we need to move forward, and the assumptions made across the kickoff docs (01-04, 05, 06, 10, 13, PL = `research/pos-legal-stack-notes.md`). "Blocks" = what stops if we do not get it.

## 1. From the founders

| # | Question / item | Why | Blocks | Needed by |
|---|---|---|---|---|
| F1 | Legal entity: name, RFC, constancia de situación fiscal, proof of address with the exact legal name | Meta Business Verification; billing; contracts [04 §2] | Leaving the 250 users/24h limit; invoicing customers | Day 1 |
| F2 | Dedicated +52 phone number not on consumer WhatsApp; who holds the SIM | WhatsApp Cloud API registration [04] | Any WhatsApp testing | Day 1 |
| F3 | WhatsApp display name and brand ("MermIA"?) | Display name approval [04] | Template submission | Day 2 |
| F4 | Payment method for Meta and for the LLM provider; billing currency USD or MXN (cannot change later) | Service messages stop after 1,000/month without one [04] | Pilot beyond the free tier | Week 1 |
| F5 | Who is the pilot restaurant (or shortlist), and how do we reach the owner | Everything in §2 | Parsers, report design | Week 1 |
| F6 | Which founder owns customers (onboarding, recipe capture, support) during the 4 weeks | Capacity risk [05 #16] | Pilot onboarding | Week 1 |
| F7 | Do you accept deferring the Phase 3 POS to a gated decision at month 9? | Distributor channel and SR relationship [06 §4] | GTM message, distributor talks | Week 2 |
| F8 | Pricing appetite: OK to test MXN 449 vs 899 and charge from month 2 of the pilot? | Willingness to pay [10] | Pilot offer | Week 1 |
| F9 | Lawyer and contador: who, budget | Aviso de privacidad, terms, SR EULA review, IVA on menu prices, tip treatment [PL] | Pilot go-live (aviso), connector | Week 2 |
| F10 | Any existing contact at National Soft or an SR distributor | ERP/PMS module price; partner stance [01 §5] | Long-term ingestion decision | Week 2 |
| F11 | Budget per month for tools and acquisition (Supabase, worker, LLM, ads) | Unit economics and break-even [10] | Stack sign-up | Week 1 |
| F12 | Weekly report as default with daily opt-in: agree? | Habit and cost [04, 06] | Template set | Day 2 |
| F13 | Who may approve DB changes: owner only, or managers too, per change type? Per-batch approval for CFDI OK? | Confirmation rule [06 §1 #6] | Pending-change design | Week 1 |

## 2. From the pilot restaurant

### 2.1 Software and licences

| # | Item | How to get it |
|---|---|---|
| P1 | SR version and edition (10/11/12, Lite/Pro, local or SR Cloud) | Screenshot of "Acerca de" or the licence screen |
| P2 | Licence is legitimate (subscription or perpetual) and current EULA text | Distributor invoice; EULA from the install or distributor [01 §7] |
| P3 | Modules licensed: Analytics, Inventario/Recetas, Enlace ERP/PMS, WhatsApp Marketplace, Corte por correo, Payments, e-Delivery | Distributor or the SR config screens |
| P4 | Is the restaurant already using a WhatsApp Business number through SR? | Ask the owner [01 §5] |
| P5 | Number of branches, one SR install per branch or Enterprise | Owner |
| P6 | Server PC: Windows version, always-on?, internet quality | Visit or photo |

### 2.2 Sample exports (one real file each, from the same business day)

| # | Report | Why |
|---|---|---|
| E1 | Productos vendidos en general (Excel) | Core sales per dish [01 §3] |
| E2 | Corte Z / corte de caja (the emailed version if SR 12) | Totals to reconcile; possible zero-effort ingestion [01 §2] |
| E3 | Cancelaciones de productos / de cuentas | Leak alerts [06] |
| E4 | Descuentos a cuentas / a productos | Leak alerts |
| E5 | Formas de pago / Cuentas pagadas con tarjeta | Payment mix |
| E6 | Ventas por mesero | Staff view (personal data, minimise) |
| E7 | Recetas - Productos and Recetas - Insumos elaborados | Case 1 costing [03 C.1] |
| E8 | Costo de insumos / Variación de costos de insumos | Cost freshness |
| E9 | Same E1 from a second branch (if a chain) | Branch field and layout |
| E10 | The same report sent by WhatsApp from the manager's phone and from WhatsApp Desktop | Real media handling, CSV/XML behaviour [04 §5] |

### 2.3 Costs and operations

| # | Question |
|---|---|
| O1 | Are recipes and costs in SR? How many dishes have cost > 0? When was the last purchase entered? |
| O2 | Supplier mix: share of purchases with CFDI XML vs notas/cash (Central de Abasto) |
| O3 | Can the owner or accountant forward supplier CFDI XML to us? Who receives them today? |
| O4 | Target food cost % (overall and per category); current menu with prices (IVA included?) |
| O5 | Price-point habits (round to $5, $9 endings?) |
| O6 | Top 10 dishes by sales and who can tell us their recipes (chef, owner) |
| O7 | When is the daily close (corte Z) done and by whom? |
| O8 | Who exports reports today, from which PC, and how comfortable are they with Excel and WhatsApp Desktop |

### 2.4 People and consent

| # | Item |
|---|---|
| C1 | Owner and manager names, roles and WhatsApp numbers (one uploader per branch) |
| C2 | Who may approve changes (owner, manager, admin) per change type |
| C3 | Signed consent: aviso de privacidad accepted; data-processing terms; written authorisation if we ever read the SR database [PL §2] |
| C4 | Consent to keep sample files as test fixtures (anonymised) |
| C5 | Willingness to try the ERP/PMS module (and who pays for it) |

## 3. From third parties

| # | Who | Question |
|---|---|---|
| T1 | National Soft (integration form) | Partner terms for the ERP/PMS module; position on third-party DB reads; current EULA [01 §5] |
| T2 | 2-3 SR distributors | ERP/PMS module price; share of SR 12 vs older; share of clients with recipes loaded; interest in resale and revenue share |
| T3 | Meta | Category assigned to our template variants [04 §4] |
| T4 | Anthropic | Standard retention period; ZDR for the pilot [13 I5] |
| T5 | Lawyer | Reglamento status under the 2025 law; transfer wording; SR EULA reading [PL §2] |
| T6 | Contador | Margin math net of IVA; tip treatment [03, PL §1.3] |

## 4. Assumptions made across the kickoff docs

| # | Assumption | Doc | Label | How to confirm |
|---|---|---|---|---|
| A1 | SR report names and layouts in SR 10-12 match the SR 8.0 manual | 01 | unverified | Sample exports E1-E8 |
| A2 | Corte Z email has too little product detail to replace E1 | 01, 06 | unverified | Sample E2 |
| A3 | ERP/PMS module is affordable and pilots can enable it | 01, 06 | unverified | T1, T2 |
| A4 | Most SR restaurants do not keep recipe costs current | 01, 03 | unverified | O1, T2 |
| A5 | Owners will forward supplier CFDI XML | 03 | unverified | O3 |
| A6 | Top-10 dishes and top-20 ingredients are "good enough" (about +/-10%) | 03 | likely (heuristic) | Pilot feedback |
| A7 | Food cost target 30-35% for MX independents | 03 | unverified | O4 |
| A8 | Margin math uses menu price / 1.16 | 03 | likely | T6 |
| A9 | Alert thresholds (8% price jump, +3 pts food cost) | 03 | opinion | Pilot calibration |
| A10 | Owner asks about 20 questions/week; 1 owner + 1 manager per restaurant | 04, 13 | assumption | Pilot logs |
| A11 | Report templates will be approved as utility | 04 | unverified | T3 |
| A12 | WhatsApp delivers CSV/XML attachments to the webhook | 04 | unverified | E10 |
| A13 | 35% of questions answered by templates without the LLM | 13 | unverified | Pilot logs |
| A14 | Haiku 5.5 passes the eval (tools, Spanish, numbers) | 13 | unverified | Eval [13 H3] |
| A15 | FX 17.5-18.4 MXN/USD | 04, 10, 13 | likely | Re-check on pricing day |
| A16 | Hosting US$1.4-4 per restaurant | PL | unverified | First invoices |
| A17 | MermIA is encargado for restaurant data, responsable for WhatsApp user data | PL | likely | T5 |
| A18 | Toast and Square are not in Mexico | 02 | likely | Periodic check |
| A19 | No WhatsApp + SR analytics agent exists in MX (Kavasoft's CatIA is the closest, cellar-focused) | 02, 05 | likely | Watch competitors quarterly |
| A20 | Willingness to pay MXN 899/location; support 0.5-1 h/month; churn 3-5%; CAC figures | 10 | assumption | Pilot and first 20 customers |
| A21 | Distributors accept 20% recurring revenue share | 10 | assumption | T2 |
| A22 | Phase 3 POS takes 5-8 months for 2 devs | PL, 06 | unverified | Only if the Phase 3 gate passes |
