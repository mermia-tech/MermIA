# 01 - Soft Restaurant deep dive (section A)

Research date: 2026-10-15. Labels: **verified** (read on the cited page/document), **likely** (consistent secondary evidence or inference), **unverified** (not confirmed; confirm as stated). Vendor marketing and reseller pages are marked as such. Report names in section 3 come from an official **SR 8.0 manual (2010)**, so they are a lower bound for SR 10/11/12, not a confirmed list for the pilot's version.

## Key findings

- **Installed base is real but smaller than "most of Mexico".** Vendor says 23,000+ restaurants in 2025 (13,334 subscription licences when current management started), versus 600,000+ restaurants in Mexico, so about 4% (our arithmetic; the 23k may include other countries). Vendor targets 20% of Mexico. **verified** (vendor claims) - [Infochannel 2026-03](https://infochannel.info/soft_restaurant_25_anos_digitalizando_sector_restaurantero_mano_canal_distribucion/), [Just Retail 2024](https://www.justretail.news/latam/noticias/soft-restaurant-transformacion-digital-en-el-sector-restaurantero/). The "most restaurants use SR" premise is **unverified**; no independent share data found.
- **Current product is SR 12 (launched Sept 2025), sold as a monthly/annual subscription** from MXN 799 (Lite) / 1,099 (Pro) + IVA per month (inferred monthly, see section 1). Many pilots will still be on SR 10/11 (legacy perpetual or older subscriptions), so the parser must handle several versions. **verified** - [official pricing](https://softrestaurant.com/soft-restaurant-precio), [Infochannel SR12](https://infochannel.info/soft-restaurant-12-en-mexico-revoluciona-la-gestion-gastronomica-con-analytics-avanzados/).
- **Best low-effort data path is already built into SR 12: "Corte Z" emailed automatically (SMTP) and cortes/alerts via WhatsApp Business, plus 25+ cloud reports in Analytics 3.0.** SR 12 only. The Corte Z content/format is **unverified** (official manual URL returned 404; get a sample). - [SR12 sales deck](https://softrestaurant.com/docs), [search summary of Corte Z manual](https://softrestaurant.com/recursos/manuales?download=213%3Asr12-manual-corte-z&start=15).
- **Rich per-product sales exports exist locally ("Reportes" menu with 50+ reports, destination Excel/screen/printer)**, including sales by product, by waiter, discounts, cancellations, payment methods, tips, recipes cost, consumed inputs and cost variation. Verified for SR 8.0 manual; **unverified for SR 10-12** names. Scheduling/automatic export of these reports: **not found**; only Corte de caja email/WhatsApp is automatic. - [SR 8.0 manual](https://yosoyvendedor.com/source/e73023b0f7a95d8ea360597237718f4b/Documentos/m_referencia_sr8_std.pdf).
- **Official integration surface is thin:** an ERP/PMS module that POSTs each sale as JSON to an integrator-built endpoint (per sale, or batch at daily close), a menu-only REST service (key by email), and a WhatsApp "Marketplace" module. No public developer portal or tech-partner program found. **The ERP/PMS module (JSON of sales with lines, discounts, payments, tips) is the best "official" ingestion route to explore with National Soft.** - [ERP/PMS guide](https://softrestaurant.zohodesk.com/portal/es/kb/articles/m%C3%B3dulo-de-integraci%C3%B3n-erp-y-psm), [menu API](https://api.softrestaurant.com.mx/), [integrations page](https://www.softrestaurant.com/integraciones).
- **Local DB connector is technically feasible and already done commercially** (Kavasoft SR Agent reads the local POS DB read-only as a Windows service; FactorBI "Vansync" ETL replicates SR DB to AWS). Pro edition runs SQL Server (instance name e.g. NATIONALSOFT). Legal: 2010 EULA prohibits reverse engineering, modification and merging with other programs without written authorization; no data-ownership clause found; current EULA **unverified**. Treat as medium legal/commercial risk; seek written clearance or partnership. - [Kavasoft](https://kavasoft.app/integraciones/soft-restaurant), [FactorBI](https://www.factorbi.com/reportes-soft-restaurant), [KB repair article](https://softrestaurant.zohodesk.com/portal/es/kb/articles/reparaci%C3%B3n-de-base-de-datos-sospechosa-para-soft-restaurant).
- **Recipes/costing exist and SR 12 adds CFDI XML purchase import with automatic input linking, subrecipes and yields**, but no data shows how many restaurants keep them current. One Capterra reviewer notes SR needs "a lot of detailed data loaded". Assume a minority keep costs fresh; **verify in pilot** by asking for the "Recetas" report. - [SR recipe costing blog](https://softrestaurant.com/blog-restaurantero/como-hacer-el-costeo-de-recetas-en-un-restaurante), [Capterra](https://www.capterra.com/p/200701/Soft-Restaurant/reviews/).
- **Complaint evidence is thin and mostly competitor-sourced** (dated UI, paid modules, Windows-only, support cost); vendor itself admitted early instability in cloud and card-payment launches. No Reddit/Facebook threads surfaced via search. **Unverified** beyond that; do customer interviews.

## 1. Versions, architecture, segments, pricing

### Versions and products

| Item | What we found | Label / source |
|---|---|---|
| SR 12 | Launched Sept 2025 in Mexico; Light/Classic/Dark UI, Analytics 3.0 (25+ reports), Recall KDS, tip per diner, XML purchase import, 50+ improvements; WhatsApp Business 2.0 for cortes/alerts | **verified** (vendor/press) - [Infochannel](https://infochannel.info/soft-restaurant-12-en-mexico-revoluciona-la-gestion-gastronomica-con-analytics-avanzados/) |
| SR 11 | Prior generation; Lite/Pro subscriptions via distributors; Analytics included in Pro (per reseller) | **verified** (reseller) - [Asentaa](https://asentaa.com.mx/softrestaurant/soft-restaurant-11/), [Doctor Pyme](https://softrestaurant.doctorpyme.mx/que-es-soft-restaurant) |
| SR 10 | Flagship in 2022 coverage; Lite and Professional editions; perpetual licence SKUs still sold by resellers (e.g. SR-10PRO-E 10 nodes) | **verified** - [ITSitio 2022](https://www.itsitio.com/distribucion/national-soft-cumple-20-anos-en-mexico-y-lo-celebra-con-nuevas-iniciativas-para-los-canales/), [Intcomex](https://store.intcomex.com/en-XMX/Product/Detail/375063) |
| SR 8/9.5 | Older Standard/Professional; Standard reportedly used a DBF-type database, Professional SQL | **likely** (search summary of vendor datasheet; PDF not readable) |
| SR Cloud | Official launch July 2025; SaaS POS for small operators; Lite (2 devices), Pro (5/branch), Enterprise (10/unit, unified reporting); sold only via partner portal; 150+ businesses; vendor admits early stability issues; offline mode **not covered** in article | **verified** - [eSemanal](https://esemanal.mx/2025/07/soft-restaurant-cloud-marca-el-inicio-de-una-nueva-receta-tecnologica-para-transformar-la-gestion-de-negocios/), [Infochannel](https://infochannel.info/soft_restaurant_25_anos_digitalizando_sector_restaurantero_mano_canal_distribucion/) |
| SR Móvil / Comandero Móvil | Waiter ordering on Android devices via an SR Móvil server on the POS PC; known localhost connectivity bug after Oct 2025 Windows 11 update | **verified** - [SR KB](https://softrestaurant.zohodesk.com/portal/es/kb/articles/soluci%C3%B3n-provisional-para-incidencia-de-conectividad-en-soft-restaurant-m%C3%B3vil-tras-actualizaci%C3%B3n-de-windows), [Asentaa](https://asentaa.com.mx/softrestaurant/soft-restaurant-11/) |
| SR Admin (owner app) | Free iPhone app: real-time sales, online reports for one or many branches, tickets, invoicing; PDF/Excel download since v2.0 (Sept 2024); new reports for SR 12 licences | **verified** - [App Store](https://apps.apple.com/mn/app/sr-admin/id6575394645) |
| Analytics / Reportes Web | Cloud BI add-on; "more than 20/25 reports"; multi-branch; sync mechanism not documented | **verified** (existence) / **unverified** (mechanism) - [Analytics](https://softrestaurant.com/addons/analytics) |
| Other add-ons | Production Monitor/KDS, Reservations, Order Monitor, Autofactura, Menú Digital, e-Delivery, e-Menu QR, Kiosko, Delivery Manager/Hub, Payments (own terminals T2/P5), Terminal Comandera, Enlace ERP/PMS | **verified** - [SR12 deck](https://softrestaurant.com/docs), [Asentaa](https://asentaa.com.mx/softrestaurant/soft-restaurant-11/) |
| Sister products | On The Minute, Soft Facturas, NS Hoteles, NS POS (cloud, Android) | **verified** - [nationalsoft.com.mx](https://www.nationalsoft.com.mx) |

Company rebranded National Soft to "Soft Restaurant" (site banner; legal entity National Soft de México). Support portals: softrestaurant.zohodesk.com (13 KB categories incl. "Novedades Soft Restaurant 12", "Enlace ERP-PMS", "Add ons") - **verified**.

### Architecture

| Question | Finding | Label / source |
|---|---|---|
| Local vs cloud | Legacy and SR 12: installed on the restaurant's Windows PC (server + stations; Windows 10/11 Pro Enterprise or Server 2022; ARM not supported). Cloud product is separate. | **verified** - [pricing page](https://softrestaurant.com/soft-restaurant-precio) |
| Database | Professional editions use Microsoft SQL Server. Official KB repair guide references SQL Server, `.mdf/.ldf` files and an instance "NATIONALSOFT" (as example, "or the instance you use"). A third-party doc mentions SQL Server Express 2014 firewall scripts (folder MSSQL12) for SR 8-11 installs. SQL edition for SR 12 and for Lite: **unverified**. | **verified** (SQL Server, instance example) / **likely** (Express 2014) - [KB](https://softrestaurant.zohodesk.com/portal/es/kb/articles/reparaci%C3%B3n-de-base-de-datos-sospechosa-para-soft-restaurant), [Studocu guide](https://www.studocu.com/pe/document/universidad-nacional-del-callao/sistemas-de-informacion/ilide-ayuda-para-int-slacio-n/114840540), [KB service stopped](https://faqs.nationalsoft.mx/Base-de-conocimientos/servicio-detenido-de-sql-server/) |
| Cloud sync of local SR | Analytics/SR Admin show data "in real time" from any device, implying a sync service from the local DB to National Soft's cloud (also requires licence registered and synced to Analytics 3.0). Protocol not documented. | **likely** - [Corte Z manual summary](https://softrestaurant.com/recursos/manuales?download=213%3Asr12-manual-corte-z&start=15) |
| Windows only | Client is Windows-only. | **verified** - [Tabblify (competitor)](https://www.tabblify.com/post/soft-restaurant-es-la-mejor-herramienta-para-tu-restaurante-o-bar-an%C3%A1lisis-ventajas-y-desventaja), pricing page |

### Market share, installed base, segments

| Claim | Source | Label |
|---|---|---|
| 23,000+ restaurants on the platform in 2025; 13,334 subscription licences / ~13,500 restaurants at 2022 handover (~72% growth) | [Infochannel 2026-03-06](https://infochannel.info/soft_restaurant_25_anos_digitalizando_sector_restaurantero_mano_canal_distribucion/) | **verified** (company claim) |
| "More than 42,000 businesses in 11+ (also "14+") countries" (marketing; likely includes legacy perpetual licences and non-Mexico) | [SR12 deck](https://softrestaurant.com/docs), [SR12 page](https://softrestaurant.com/soft-restaurant-12) | **verified** (claim), inconsistent with 23k |
| Mexico has 600,000+ restaurants; only 9% have internet, 11% computers (per CEO) -> implied SR share about 4% | [Just Retail](https://www.justretail.news/latam/noticias/soft-restaurant-transformacion-digital-en-el-sector-restaurantero/) | **verified** (quote) / share is **our calc** |
| Goal 20% Mexico, 10% LatAm; 250,000 restaurants by 2030 | same | **verified** (target, not data) |
| 610 active partners (distributors); 17,000+ licences served by partners; wholesalers under 2% of business; Cloud sold direct-to-partner | [Infochannel](https://infochannel.info/soft_restaurant_25_anos_digitalizando_sector_restaurantero_mano_canal_distribucion/) | **verified** |
| Payments: 550+ restaurants; Cloud: 150+ | same | **verified** |
| Segments: restaurants, bars, cafes, pizzerias, fast food, taquerias, drive-thru, delivery; Enterprise plan for multi-branch; positioned for SMBs. Share among independents vs chains: **unverified** (no data) | [ITSitio](https://www.itsitio.com/distribucion/national-soft-cumple-20-anos-en-mexico-y-lo-celebra-con-nuevas-iniciativas-para-los-canales/), [Doctor Pyme](https://softrestaurant.doctorpyme.mx/que-es-soft-restaurant) | **verified** / **unverified** |
| Piracy exists and vendor is fighting it (blog warns on pirated copies; "reinforced anti-piracy"). Cracked SR copies are widely advertised online. Share of pirated installs: **unverified** (no stat). Implication: some pilot restaurants may run unlicensed SR, with no Analytics/WhatsApp/email features. | [SR blog](https://softrestaurant.com/blog-restaurantero/6-riesgos-de-adquirir-un-software-para-restaurantes-pirata) | **verified** (exists) / **unverified** (scale) |

### Pricing and licensing (MXN)

| Offer | Price | Notes / source | Label |
|---|---|---|---|
| SR 12 Lite | 799/month + IVA (639 with Payments discount) | Official page does not state period; matches monthly store price below - [pricing](https://softrestaurant.com/soft-restaurant-precio) | **verified** price, period **likely** monthly |
| SR 12 Pro | 1,099/month + IVA (879 with discount) | same | same |
| 20% discount | If Payments active and >100,000 MXN/month card volume | [pricing](https://softrestaurant.com/soft-restaurant-precio) | **verified** |
| SR 12 Pro rental, 10 nodes (store) | 1,274.84/month; 13,386.40/year (IVA incl.) | 1,099 x 1.16 = 1,274.84, confirming monthly - [nationalsoft.store](https://www.nationalsoft.store/productos/softrestaurant-12-pro/6007?view=all&sversion=Professional) | **verified** |
| SR 11 via reseller (IVA incl.) | Lite 810.90/month, 8,920/year (2 devices); Pro 1,159/month, 12,748/year (10 devices) | [Asentaa](https://asentaa.com.mx/softrestaurant/soft-restaurant-11/); reseller prices vary | **verified** (reseller) |
| SR 10 via Intcomex | Lite annual/biennial subscriptions, Pro perpetual 10 nodes SKUs; prices not shown | [Intcomex](https://store.intcomex.com/en-XMX/Product/Detail/374886) | **verified** (existence) |
| CFDI stamps | Packs of 50/200/1000 sold separately; Enterprise includes unlimited folios (per Doctor Pyme) | [Intcomex](https://store.intcomex.com/en-XMX/Product/Detail/238242), [Doctor Pyme](https://softrestaurant.doctorpyme.mx/que-es-soft-restaurant) | **verified** (existence), prices **unverified** |
| Cloud | Launch promos, 1.95% per transaction with Payments; base prices not disclosed | [eSemanal](https://esemanal.mx/2025/07/soft-restaurant-cloud-marca-el-inicio-de-una-nueva-receta-tecnologica-para-transformar-la-gestion-de-negocios/) | **verified** / base price **unverified** |
| Installation, training, DB setup | Not included; quoted by distributor | [Asentaa](https://asentaa.com.mx/softrestaurant/soft-restaurant-11/) | **verified** |
| Licence model (2010 EULA) | Non-exclusive, non-transferable, one trade name/legal entity/physical address; monthly rent or "permanent with expiry at 24 months" | [SR 8.0 manual](https://yosoyvendedor.com/source/e73023b0f7a95d8ea360597237718f4b/Documentos/m_referencia_sr8_std.pdf) | **verified** (old version) |

Takeaway: typical SR spend per restaurant is about MXN 800-1,300 per month plus add-ons; our price must be judged against that.

## 2. Exports available for automation (what the manager can send, or what we can receive)

| Mechanism | Format | Content | Automatic? | Version | Label / source |
|---|---|---|---|---|---|
| Corte Z / Corte de caja by email | Not stated (likely PDF or text body) | Shift report: cash in/out, sales stats, cashier declaration, discounts, cancellations, shortages/surpluses | **Yes**, at shift close, via SMTP configured in Configuración > Configuración General > Corte de caja; needs licence SR 12+ registered and synced to Analytics 3.0 | SR 12 (SR 11 had "Corte de Caja por Correo" per Asentaa) | **verified** feature; format/content details **unverified** - [Asentaa SR11](https://asentaa.com.mx/softrestaurant/soft-restaurant-11/), [search on Corte Z manual](https://softrestaurant.com/recursos/manuales?download=213%3Asr12-manual-corte-z&start=15) |
| Cortes and anti-fraud alerts via WhatsApp | Message/attachment, not stated | Cortes X, alerts (cancellations, discounts, reprints) | **Yes**, via "Marketplace" setup with the restaurant's own Meta Business/WhatsApp Business account, token and webhook | SR 12 (setup guides sit under "Novedades SR 11" in KB) | **verified** existence; details **unverified** - [SR12 deck](https://softrestaurant.com/docs), [search summary of SR12 manual](https://softrestaurant.com/recursos/manuales?download=224%3Asr12-manual-mejoras-de-soft-restaurant) |
| Any "Reportes" window report | Excel (file dialog), screen, printer; the 2010 manual also notes ASCII for accounting policies | See section 3 | **No** (user runs and exports); no scheduler found | all | **verified** (SR 8) - [SR 8.0 manual](https://yosoyvendedor.com/source/e73023b0f7a95d8ea360597237718f4b/Documentos/m_referencia_sr8_std.pdf) |
| Analytics / Reportes Web | PDF or Excel download | 25+ managerial reports | On demand; no scheduled email found | SR 11 Pro / 12 | **verified** - [Analytics](https://softrestaurant.com/addons/analytics), [SR Admin](https://apps.apple.com/mn/app/sr-admin/id6575394645) |
| Exportar/Importar ventas | .ZIP in SR proprietary format (for moving sales between SR databases of the same version) | Sales records | No | SR 8 doc | **verified** (SR 8) - not parseable by us without reverse engineering |
| Exportar movimientos (admin tool) | .TXT and Excel | Inventory/warehouse movements | No | SR 8 doc | **verified** (SR 8) |
| Póliza contable | Excel / ASCII (COI, CONTPAQi, Navision, Aspel) | Accounting entries for sales and purchases | No | SR 8; SR 12 CONTPAQi guide | **verified** - SR 8 manual, [SR docs](https://softrestaurant.com/docs) |
| ERP/PMS module | JSON via HTTP POST | Per sale (see section 5) | **Yes**: on payment, daily close, or every N minutes | SR 11+ | **verified** - [ERP/PMS guide](https://softrestaurant.zohodesk.com/portal/es/kb/articles/m%C3%B3dulo-de-integraci%C3%B3n-erp-y-psm) |

Confirm in pilot: get a real SR 12 sample of (a) the emailed Corte Z, (b) "Productos vendidos" export to Excel, (c) the recipes report, (d) whether CSV/XLS columns include modifiers and branch.

## 3. Reports (name, format, content)

Source for all rows tagged SR8: official SR 8.0 reference manual, chapter "Reportes" ([PDF](https://yosoyvendedor.com/source/e73023b0f7a95d8ea360597237718f4b/Documentos/m_referencia_sr8_std.pdf)), 2010. Common controls: destination = printer / screen / Excel; filter by shift or by period; summary or detail. **Names in SR 10-12 may differ**; confirm with the pilot's menu. "SR12" rows come from the 2025-26 vendor material.

| Report (menu) | Format | Contents | Auto-send? | Label |
|---|---|---|---|---|
| Productos vendidos en general | Excel/screen/print | Products sold in shift/period (units, sales); also marketed as top-10 best and worst sellers | No | **verified** SR8 |
| Productos vendidos por mesero/repartidor | same | Product sales per waiter | No | **verified** SR8 |
| Máximos y promedios de venta por producto | same | Max/average sales per product | No | **verified** SR8 |
| Ventas por grupos de productos | same | Sales by product group | No | **verified** SR8 |
| Ventas por mesero/repartidor; Corte por mesero | same | Sales per waiter (per vendor blog: waiter, sales, tables, avg ticket, days worked) | No | **verified** SR8 + [blog](https://softrestaurant.com/blog-restaurantero/5-reportes-de-ventas-que-no-pueden-faltar-en-un-software-restaurantero) |
| Venta por mesa | same | Sales per table, guests, consumption | No | **verified** SR8 + blog |
| Ventas por servicio y área | same | Dine-in / delivery / fast / area | No | **verified** SR8 |
| Ventas por día | same | Food, beverages, other, courtesies | No | **verified** SR8 |
| Cuentas resumen / desglose | same | Check-level summary or detail | No | **verified** SR8 |
| Cuentas pagadas con tarjeta | same | Card-paid checks | No | **verified** SR8 |
| Descuentos a cuentas / a productos | same | Discounts on whole checks / items (audit: which user) | No | **verified** SR8 |
| Cancelaciones de cuentas / de productos | same | Cancelled checks / items | No | **verified** SR8 |
| Cuentas con propina; Reparto de propinas | same | Tips per check; tip distribution | No | **verified** SR8 |
| Comisiones de meseros / agentes | same | Commissions | No | **verified** SR8 |
| Cambios de precio | same | Price changes by staff | No | **verified** SR8 |
| Formas de pago por semana; Reportes semanales (ventas/cantidad por hora, grupos, subgrupos, comensales por hora) | same | Payment methods, hourly matrices, guest counts | No | **verified** SR8 |
| Acumulado de ventas mensual/anual | same | Cumulative sales | No | **verified** SR8 |
| Ventas, inventarios y utilidad | same | Sales and profit (needs accounting departments configured) | No | **verified** SR8 |
| Facturas; Notas de consumo; Libro de ventas | same | Invoices, consumption notes | No | **verified** SR8 |
| Ventas a domicilio/comedor; por zona; tiempo de repartidores; ventas por cliente; ventas a crédito | same | Delivery and customer sales | No | **verified** SR8 |
| Cortes de caja (X per shift, Z daily); Cortes por período; Retiros y depósitos | same | Cash close, withdrawals, deposits; detailed or summary | Corte by email/WhatsApp in SR 11/12 | **verified** SR8 + SR12 deck |
| Compras / órdenes de compra; Compras por insumo | same | Purchases | No | **verified** SR8 |
| Existencias; Movimientos; Traspasos; Stock máx/mín; Costo de almacenes; Saldos de insumos; Formato de inventario físico | same | Inventory | No | **verified** SR8 |
| Insumos consumidos; Costo diario/semanal; Variación de costos de insumos; Costos y consumos | same | Costing, theoretical consumption, price variation | No | **verified** SR8 |
| Recetas - Productos; Recetas - Insumos elaborados | same | Recipes with costs (average or last cost per vendor blog) | No | **verified** SR8 + [blog](https://softrestaurant.com/blog-restaurantero/como-hacer-el-costeo-de-recetas-en-un-restaurante) |
| Cuentas por pagar (saldos, pagos a proveedores); Pólizas contables | same / ASCII | Payables, accounting | No | **verified** SR8 |
| Analytics 3.0 (named): Ventas por período, Ventas diarias, Ventas anuales, Descuentos por sucursal, Productos más vendidos, Clientes/ticket/ventas promedio por hora, Popularidad por producto, Ventas por estación, Acumulado de ventas; new in 3.0: bitácora, cortes de caja, efectivo, cuentas y productos cancelados | PDF/Excel (Admin app) | Multi-branch managerial | On demand | **verified** - [Analytics](https://softrestaurant.com/addons/analytics), [Infochannel](https://infochannel.info/soft-restaurant-12-en-mexico-revoluciona-la-gestion-gastronomica-con-analytics-avanzados/) |

Not found in any source: a documented **modifiers** report (modifier sales likely appear as lines in "Cuentas desglose" or product reports - **unverified**), a **CSV** option (only Excel/PDF/ASCII/TXT are documented), and a **branch** field in local single-branch reports (branch consolidation is done in Analytics/Enterprise).

## 4. Recipe, inventory and costing modules

| Topic | Finding | Label / source |
|---|---|---|
| What is stored | Insumos catalog (with presentations, units), recipes of products (ingredients and quantities), "insumos elaborados" (sub-recipes), warehouses, purchases, purchase orders, transfers, physical counts, min/max stock; sales deduct ingredients from inventory; recipe cost report by average or last cost | **verified** - [SR blog](https://softrestaurant.com/blog-restaurantero/como-hacer-el-costeo-de-recetas-en-un-restaurante), [Doctor Pyme](https://softrestaurant.doctorpyme.mx/que-es-soft-restaurant), SR 8 manual |
| SR 12 additions | Presentations, subrecipes, yields; **purchases imported from CFDI XML with automatic linking to insumos** (new vs SR 11); "automatic cost and profit calculation" | **verified** (marketing) - [Infochannel](https://infochannel.info/soft-restaurant-12-en-mexico-revoluciona-la-gestion-gastronomica-con-analytics-avanzados/), [SR12 deck](https://softrestaurant.com/docs) |
| Setup effort | Requires full ingredient catalog and exact quantities; one Capterra reviewer: "need to load a lot of detail"; a download-guide site says complex recipes/explosions require time and precision | **verified** (single review) - [Capterra](https://www.capterra.com/p/200701/Soft-Restaurant/reviews/) |
| Access | Inventory module is in Pro (Lite scope **unverified**); inventory is also a paid add-on in older versions | **likely** |
| How many restaurants keep it up to date | **No data found.** Inference: most small restaurants run SR only as POS; costing needs weekly purchase entry that few do. | **unverified** - confirm: ask pilot for "Recetas" report and last purchase date; count recipes with cost > 0 |
| Cost freshness | Cost depends on purchases entered (average cost or last cost); stale if purchases are not captured | **likely** |

## 5. Integrations, APIs, partner program, stance on third parties

| Item | Finding | Label / source |
|---|---|---|
| Integrations page | AddOns; delivery: e-Delivery, Rappi, Didi Food, Delivery Manager, FoodBot, Uber Eats; admin: Analytics, SR Facturación, Ordatic, Deliverect, Hubster, CashDro, WhatsApp Soft Restaurant; PMS: Zavia, Cloudbeds; button "Quiero integrar mi sistema" (form) and a "Documentación" menu link | **verified** - [integrations](https://www.softrestaurant.com/integraciones) |
| ERP/PMS module (paid module, buy via distributor, SR 11+) | SR POSTs JSON to an integrator-built URL. Fields: `IdEmpresa`, `Ventas[]` with `Estacion`, `Almacen`, `FechaVenta`, `NumeroOrden`, `IdCliente`, `IdUsuario`, `Total`, `Area`, `Conceptos[]` (`IdProducto`, `Descripcion`, `Movimiento`, `Cantidad`, `PrecioUnitario`, importe, `Descuento`, `Impuestos`), `Pagos[]` (`FormaPago`, `Importe`, `Propina`). Triggers: per paid check, daily close (most common), every N minutes, cancellations. Auth: `x-api-key` header (`customerId::apiKey`). Failed sends queue as pending; log in "Bitácora de ERP". Module cost **unverified**. | **verified** - [guide](https://softrestaurant.zohodesk.com/portal/es/kb/articles/m%C3%B3dulo-de-integraci%C3%B3n-erp-y-psm) |
| Menu REST service | JSON, `AuthorizedApp` header; menu only; keys by email request (contact named on page), no terms/pricing shown | **verified** - [API](https://api.softrestaurant.com.mx/), [demo](https://demoapiaccount.nationalsoft.com.mx/Home/Api) |
| WhatsApp Marketplace | Restaurant uses its own validated Meta Business account; permanent token + webhook + templates; sends cortes and alerts. Note: the restaurant may already have a WhatsApp Business number set up through SR | **verified** (search-sourced KB topics) / details **unverified** |
| CFDI / facturación | CFDI 4.0 stamps through SR (packs), Autofactura portal | **verified** - [Doctor Pyme](https://softrestaurant.doctorpyme.mx/que-es-soft-restaurant) |
| Accounting | CONTPAQi guide (SDK) to export income/expense entries | **verified** - [SR docs](https://softrestaurant.com/docs) |
| Partner program | 610 distributors; sign-up at softrestaurant.com/alta-de-socio-comercial; "El Recetario" rules; partners get product updates first; incentives for Payments; regional "Summit". This is a reseller programme, **not** a technology-partner / developer programme. | **verified** - [Infochannel](https://infochannel.info/soft_restaurant_25_anos_digitalizando_sector_restaurantero_mano_canal_distribucion/), [nationalsoft.com.mx](https://www.nationalsoft.com.mx) |
| Marketplace | SR 12 has an in-app "Marketplace" for add-on configuration (WhatsApp). Whether third parties can list: **unverified** | **likely** |
| Stance toward third-party DB readers | No public statement found either way. Kavasoft publicly sells a DB-reading connector without National Soft's involvement and says it works "without asking your provider"; FactorBI does the same. No evidence of blocking or legal action found. Recent vendor strategy ("grow with partners") suggests they prefer channel partners; they also have their own Analytics, so they could see us as competing. | **verified** (others do it) / stance **unverified** - [Kavasoft](https://kavasoft.app/integraciones/soft-restaurant), [FactorBI](https://www.factorbi.com/reportes-soft-restaurant) |
| Data ownership | No clause found in the 2010 EULA about ownership of the restaurant's operating data; the EULA covers the software only. Mexican law (LFPDPPP) makes the restaurant the controller of its personal data. Current EULA and Analytics cloud terms: **unverified** | **unverified** - confirm with legal counsel and by requesting the current EULA from National Soft |

## 6. User complaints (with sources)

Independent review volume is very low. Treat as hypotheses to test in interviews.

| Complaint | Source | Bias / label |
|---|---|---|
| Needs a lot of detailed data entry (recipes, inputs) | [Capterra reviews](https://www.capterra.com/p/200701/Soft-Restaurant/reviews/) (2 reviews, 4.5/5) | Independent, tiny sample; **verified** |
| No free tier; recurring fee heavy for small businesses; support response could be faster | [SelectHub](https://www.selecthub.com/p/restaurant-management-software/soft-restaurant/) (2 reviews) | **verified**, tiny sample |
| Key features cost extra / separate modules; hardware tied; dated, unintuitive UI; steep learning curve; Windows only | [Tabblify](https://www.tabblify.com/post/soft-restaurant-es-la-mejor-herramienta-para-tu-restaurante-o-bar-an%C3%A1lisis-ventajas-y-desventaja), [SICAR](https://www.sicar.mx/centro-de-soluciones/comparativas/sicar-vs-soft-restaurant) | Competitors; **likely** |
| Technical support is ticket-based and some services cost extra; long waits (competitor claim) | [SR FAQ](https://softrestaurant.com/faqs-funcionamiento-sistema), competitor page | **verified** (policy) / **unverified** (waits) |
| Frequent service issues: SQL Server service stopped after forced shutdown or Windows update; terminal DBNETLIB connection errors; "suspect" databases needing repair; tablet sync errors "table could not be opened"; SR Móvil localhost break after Oct 2025 Windows 11 update | [SR KB](https://faqs.nationalsoft.mx/Base-de-conocimientos/servicio-detenido-de-sql-server/), [KB repair](https://softrestaurant.zohodesk.com/portal/es/kb/articles/reparaci%C3%B3n-de-base-de-datos-sospechosa-para-soft-restaurant), [Opravy](https://opravy.com.mx/ayuda/category/soft-restaurant/), [SR KB Móvil](https://softrestaurant.zohodesk.com/portal/es/kb/articles/soluci%C3%B3n-provisional-para-incidencia-de-conectividad-en-soft-restaurant-m%C3%B3vil-tras-actualizaci%C3%B3n-de-windows) | **verified** (vendor/repair shops) - relevant: a local connector must tolerate SQL outages |
| Cloud and card-payment launches had timing and stability problems (vendor's own admission, 2026) | [Infochannel](https://infochannel.info/soft_restaurant_25_anos_digitalizando_sector_restaurantero_mano_canal_distribucion/) | **verified** |
| Employee reviews of the company | [Computrabajo](https://mx.computrabajo.com/empresas/evaluaciones-en-national-soft-69DD4EEF81467963) | Not read; **unverified** |
| Owner visibility/insight gap (our hypothesis) | Indirectly: Analytics only offers sales-oriented dashboards; no AI/insights mentioned in any 2024-26 vendor material | **likely** |

Searches of Reddit, Facebook groups, YouTube comments and foros returned nothing usable. Suggested confirmation: 10 owner interviews, and ask 3-5 distributors (e.g. via [authorized distributors](https://softrestaurant.com/distribuidores-autorizados)) what they hear.

## 7. Technical feasibility of a local connector (public information only)

| Topic | Finding | Label / source |
|---|---|---|
| Engine | Microsoft SQL Server for Professional editions; database files `.mdf/.ldf`; admin tools via SQL Server Management Studio | **verified** - [KB repair](https://softrestaurant.zohodesk.com/portal/es/kb/articles/reparaci%C3%B3n-de-base-de-datos-sospechosa-para-soft-restaurant) |
| Instance name | Official KB uses `NATIONALSOFT` as example instance ("or the instance you use"); other installs reportedly use SQLEXPRESS (generic checks). Discover by listing services (`MSSQL$<name>`) and SQL Browser. | **verified** (example) / **likely** (SQLEXPRESS) |
| Authentication | Official KB article publishes a default `sa` login and password for the repair procedure (value deliberately not copied here). Installers/distributors may or may not have changed it; reports that it often stays default are **unverified**. We should never use `sa`: create a dedicated read-only SQL login with the restaurant's written consent. | **verified** (a default is published) - same KB article |
| Table and column names | Not documented publicly in anything we could read. A GitHub project ([Extensiones-Soft-Restaurant](https://github.com/mariosuarezDEV/Extensiones-Soft-Restaurant)) exposes "ventas (cheques)" and details via Django and does not publish schema. Do not assume `cheques`/`cheqdet`: **unverified**. Discover schema on a pilot machine (read-only, with consent) or ask National Soft. | **unverified** |
| Concurrency | Connector must be read-only, `READ UNCOMMITTED`/snapshot where possible, throttled; Kavasoft states read-only sync, one connector per branch, outbound HTTPS only, per-minute heartbeat | **verified** (competitor design) - [Kavasoft](https://kavasoft.app/integraciones/soft-restaurant) |
| Per-edition risk | Standard (older) editions used a file-based DB (DBF-type per datasheet summary) - the connector would not work there. SR Cloud has no local DB. | **likely** |
| Precedents | Kavasoft SR Agent (Windows service, read-only); FactorBI Vansync ETL to AWS QuickSight; others (e.g. FoodBot, Ordatic) integrate via other paths, **unverified** | **verified** - [Kavasoft](https://kavasoft.app/integraciones/soft-restaurant), [FactorBI](https://www.factorbi.com/reportes-soft-restaurant) |
| Windows constraints | Server PC runs Windows 10/11 Pro Enterprise or Server 2022; connector as a Windows service with outbound-only HTTPS; must survive SQL service restarts and SR upgrades (schema may change per version) | **likely** |

### Legal and licence risk

- 2010 EULA (SR 8.0) clauses 6(c) no reverse engineering/decompiling, 6(e) no modification, 6(f) no merging with another program without written authorization, and 7 (vendor not liable for "unauthorized adaptations"). Reading the database with a standard SQL client is arguably not reverse engineering of the program, but the vendor could argue clause 6(f)/(h) or a technical-support breach. **Risk: medium; unverified legal position.** - [SR 8.0 manual, EULA](https://yosoyvendedor.com/source/e73023b0f7a95d8ea360597237718f4b/Documentos/m_referencia_sr8_std.pdf)
- No data-ownership clause found; the restaurant owns its sales data (and is controller under LFPDPPP), so consent from the restaurant is essential. The current EULA (SR 12) should be obtained and reviewed by a Mexican lawyer.
- Practical mitigations: written consent from each restaurant; read-only login; no schema modification; avoid distributing SR binaries; do not depend on cracked copies; open a conversation with National Soft (ERP/PMS module is the sanctioned route, and the "Quiero integrar mi sistema" form is the entry point). Pirated installations: refuse as customers.

## 8. Implications for the MVP (for later agents)

1. Ask the pilot for: SR version/edition, whether Analytics and "Corte por correo/WhatsApp" are active, three sample exports (Corte Z, Productos vendidos, Recetas), and whether recipes have costs.
2. If pilot is SR 12 with the email feature: point the Corte Z email at a dedicated inbox (zero manager effort). If the corte has no product-level detail, still require a "Productos vendidos" export.
3. Evaluate the ERP/PMS module as the long-term official route (requires distributor purchase and a hosted endpoint); the JSON is clean and covers discounts, payments and tips, but not recipes or cancellations beyond folio cancel events.
4. The DB connector is a fallback with known commercial precedent and unresolved licence risk.

## Open items to confirm

- Exact SR 10/11/12 report menu and Excel column layouts (sample exports).
- Corte Z email format and attachment type.
- Price of the ERP/PMS module and whether National Soft will give API/DB consent or a partner arrangement (contact via the integrations form).
- SQL Server edition and instance in SR 12; schema.
- Share of installs that are SR 12, Lite vs Pro, cloud vs local, pirated.
- Current EULA text and data-ownership terms.
