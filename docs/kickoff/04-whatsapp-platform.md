# 04 - WhatsApp Business Platform (section E)

Researched 2026-10-15. Labels: **verified** = read on a current Meta/vendor primary page this session; **likely** = consistent secondary evidence or inference from verified facts; **unverified** = could not confirm, test before relying on it.

Primary sources (Meta):
- Pricing page (updated 30 Sep 2026; USD/MXN rate cards effective 1 Oct 2026): https://developers.facebook.com/docs/whatsapp/pricing
- Media: https://developers.facebook.com/documentation/business-messaging/whatsapp/business-phone-numbers/media.md
- Service messages and 24h window: https://developers.facebook.com/documentation/business-messaging/whatsapp/messages/send-messages.md
- Template categorization: https://developers.facebook.com/documentation/business-messaging/whatsapp/templates/template-categorization.md
- Messaging limits: https://developers.facebook.com/documentation/business-messaging/whatsapp/messaging-limits.md
- Terms (section 4.7 AI Providers; last updated 23 Sep 2026): https://www.facebook.com/legal/Meta-Terms-for-WhatsApp-Business-Platform
- AI Providers pricing policy: https://developers.facebook.com/documentation/business-messaging/whatsapp/pricing/ai-providers.md

## Key findings

1. **Biggest change since the brief: service messages are billable again since 1 Oct 2026.** Free-form replies inside the 24h window were free; now each business phone number gets 1,000 free service messages/month, then USD 0.0085 (MXN 0.1565) each in Mexico. Without a payment method on file, delivery stops after the free tier. **verified**
2. **Utility templates sent inside an open 24h window are still free**, and do not count toward volume tiers. Mexico utility = USD 0.0085 outside the window. Marketing = USD 0.0397 (4.7x). **verified**
3. **Our WhatsApp cost is dominated by the agent's free-form answers**, not by the reports: about USD 0.81 to 1.43 (MXN 15 to 26) per restaurant per month in the model below. Daily vs weekly reports differ by only about USD 0.22 (MXN 4). Marketing misclassification of daily reports would add about USD 0.95 (MXN 17.5) per restaurant. Decide daily vs weekly on product value, not WhatsApp cost.
4. **Recommendation: Cloud API direct from Meta** (free API access, no markup, On-Premises API is dead) with one MermIA business number and our own webhook. BSP only if we want a ready inbox/support UI; then YCloud (USD 0 plan, "zero mark-up") or 360dialog (EUR 49/number/month, no markup). **Avoid Twilio** (USD 0.005 per message, inbound and outbound, on top of Meta): roughly doubles our cost. **verified** (pricing), **likely** (recommendation)
5. **Document intake: xlsx, xls, pdf, txt, docx accepted up to 100 MB; CSV and XML are not on Meta's supported list.** Test real Soft Restaurant exports on a real phone in week 1. Media URL lives 5 minutes, webhook media ID 7 days: download immediately. **verified** (list), **unverified** (CSV/XML delivery)
6. **AI policy: our use case is very likely compliant** (business-specific analytics assistant over the customer's own data), but Meta bans AI whose *primary* functionality is a general-purpose assistant, decided at Meta's discretion, and bans using WhatsApp platform data to train AI models (own fine-tuning allowed). Keep the agent scoped to restaurant data. **verified** (terms), **likely** (our compliance)
7. **Go-live is fast, verification is the long pole.** Cloud API + test number same day; templates reviewed in up to 24h; new portfolio starts at 250 unique users/24h outside the window (enough for a pilot); Business Verification (RFC + proof of address) takes days to weeks, start day 1. **verified** (limits, template review), **likely** (verification timing)
8. **Design rules:** send every proactive report and confirmation prompt as a *utility* template with neutral wording (no recommendations in the template body); put the detail and price suggestions in the free-form follow-up after the owner taps a quick-reply button; use reply buttons (max 3) for confirm/reject, no Flows in the MVP.

## 1. Cloud API direct vs BSPs

| Option | Cost on top of Meta's fees | Fit for 2 devs / 4 weeks | Status |
|---|---|---|---|
| **Cloud API direct** | None. API access is free; Meta bills messages only | Best: one webhook + Graph API calls, no vendor lock-in, same API a BSP wraps | **verified** (pricing page) |
| YCloud | Free plan USD 0 (1 user, 2 channels); Growth USD 39/mo; Pro USD 89/mo; "zero mark-up" on messages; wallet top-up | Good if we want inbox, webhooks relay, templates UI | **verified**: https://www.ycloud.com/pricing (does not state pass-through explicitly) |
| 360dialog | EUR 49/number/mo (Regular), 99 (Premium); "no markup on Meta fees" | Good, developer-oriented, thin layer over Cloud API | **verified**: https://360dialog.com/pricing |
| Twilio | USD 0.005 per message, inbound or outbound | Easy SDK, but fee scales with chat volume (see section 8) | **verified**: https://www.twilio.com/en-us/whatsapp/pricing |
| Gupshup | Platform fee not published; +6% on marketing fee from 1 Jan 2026 | Enterprise-leaning; no benefit for us | **verified** (6%): https://support.gupshup.io/hc/en-us/articles/53700207494169 ; platform fee **unverified** |
| Wati | Subscription; third-party review says about USD 119-149/mo | Shared-inbox product, not an API fit | **unverified** (third-party only) |
| Infobip | No public markup found | Enterprise sales cycle | **unverified** |

- **On-Premises API is retired.** Last client version expired 23 Oct 2025; Cloud API is the only option. **verified** (Meta sunset page via search: https://developers.facebook.com/docs/whatsapp/on-premises/sunset)
- Account model is changing (H2 2026 to 2028): a separate "Messaging Account" per partner, phone-number-first Embedded Signup. Existing integrations keep working; only matters if we later become a Tech Provider (Phase 3, one number per restaurant). **verified**: https://developers.facebook.com/documentation/business-messaging/whatsapp/account-model-evolution/onboarding.md
- Our setup: **one WABA, one MermIA number, many restaurants as users** (owners and managers opt in). No per-restaurant WABA needed in Phase 1. **likely**
- Fee/FX note: the billing currency (USD vs MXN) is chosen when the messaging account is created and cannot be changed later, except via migration APIs. Pick it deliberately. **verified**

## 2. Onboarding and verification

| Item | What Meta says | Label |
|---|---|---|
| Messaging limit (new portfolio) | 250 unique users per rolling 24h, only for messages sent *outside* a customer service window. Shared across all numbers in the portfolio (since 7 Oct 2025) | **verified** |
| Raising it | To 2,000 by Business Verification, partner verification, or 2,000 delivered out-of-window messages in 30 days with high-quality templates. Then automatic: 10K, 100K, unlimited; needs high quality and use of at least half the limit in 7 days; upgrade within 6 hours | **verified** |
| Display name | Required at registration. Verification runs automatically when you reach a higher limit; shows at top of chats only if approved. Up to 10 changes per 30 days | **verified** |
| Quality | Template quality: GREEN / YELLOW / RED / UNKNOWN, based on feedback and read rates; low quality leads to pacing, pausing, disabling. Phone-number "Flagged" state no longer exists; limits are not downgraded on quality drops | **verified** |
| Template review | Automatic, up to 24h; max 100 templates created/hour; 250 templates per WABA unverified portfolio, up to 6,000 when verified with an approved display name | **verified** |
| Business Verification | Mexico: tax ID document (RFC constancia) plus proof of address matching the legal name exactly. Reports range 1-5 business days to 30 days; max 3 attempts per portfolio | **likely** (vendor sources, no official SLA) |
| Phone number | Dedicated +52 number able to receive the registration code, not already active in the consumer WhatsApp app; set two-step verification PIN | **likely** (number rules), **verified** (two-step page exists) |
| Opt-in | Required before messaging; can be collected outside WhatsApp (in person, paper, web, phone). Record who opted in, when, and for which message types | **verified**: https://developers.facebook.com/documentation/business-messaging/whatsapp/getting-opt-in.md |

Suggested timeline: day 1 create portfolio and start Business Verification; day 1-2 developer app, WABA, number, webhook, submit templates; days 3-7 pilot on the 250 limit while verification completes.

## 3. Pricing for Mexico (Meta rate card effective 1 Oct 2026)

Source: "Tarifas en USD / MXN" and volume-tier files linked from https://developers.facebook.com/docs/whatsapp/pricing. **verified**. Charged per delivered message; user-to-business messages are free. Rate changes only on 1 Jan / 1 Apr / 1 Jul / 1 Oct with at least 1 month notice. **verified**

| Category | USD | MXN | Notes |
|---|---|---|---|
| Marketing | 0.0397 | 0.7298 | Lowered 1 Oct 2025; no volume tiers |
| Utility | 0.0085 | 0.1565 | Free inside an open service window; volume tiers apply |
| Authentication | 0.0085 | 0.1565 | Not needed by us |
| Service (free-form, non-template) | 0.0085 | 0.1565 | Only inside the 24h window. **First 1,000/month per business phone number free**, then charged (from 1 Oct 2026) |
| Meta Business Agent (Meta's own AI) | USD 2.00 per 1M tokens | n/a | Not used; our agent runs on our own LLM |

Implied FX in Meta's own cards: 0.1565 / 0.0085 = about 18.41 MXN per USD (used below).

**Volume tiers (Mexico, utility)**, monthly, aggregated per portfolio, billed messages only:

| Monthly utility messages | USD per message | vs list |
|---|---|---|
| 0 to 1,000,000 | 0.0085 | list |
| 1,000,001 to 5,000,000 | 0.0081 | -5% |
| 5,000,001 to 10,000,000 | 0.0077 | -10% |
| 10,000,001 to 20,000,000 | 0.0072 | -15% |
| 20,000,001 to 40,000,000 | 0.0068 | -20% |
| above 40,000,000 | 0.0064 | -25% |

Irrelevant at our scale (one restaurant is about 30-130 billed messages/month).

**Free windows**
- Customer service window (CSW): 24h, opened and reset by every user message. Free-form messages allowed; utility templates sent while open are free; marketing templates are always charged. **verified**
- Free entry point (Click-to-WhatsApp ad): replying to the user inside the CSW with any template/service message opens a free window. The Oct 2026 pricing page says it can stay open **up to 7 days** (the earlier 72h figure is outdated or conflicting). Not relevant to us unless we run CTWA ads for acquisition. **verified** (7 days), conflict noted
- Government/nonprofit service messages stay free beyond the tier until 31 Dec 2027; not us. **verified**

## 4. Template categories and where our messages fall

Meta rules (verified): utility must be non-promotional **and** either specific to/requested by the user or essential/critical. Mixed utility+marketing content, or unclear content, is marketing. Since 9 Apr 2025 a template submitted as utility that Meta judges to be marketing is **approved as marketing** (no rejection); you can request review within 60 days. Utility examples include "Daily update for account ending in X: your available balance is Y". Marketing includes recommendations, upsell, and anything "intended to drive sales or renewals".

| Our message | Category | Risk | Guidance |
|---|---|---|---|
| Daily/weekly report notice with the owner's own numbers ("Tu resumen de ventas del {{fecha}}: ventas {{monto}}, ticket promedio {{monto}}") | Utility | Low-medium: closest to "account update specific to a subscribed service" | Facts about their account only, no tips, no CTAs to buy or upgrade |
| Report with "suggested price changes" or "best sellers to promote" | Likely marketing | **High**: recommendation language | Keep the suggestions out of the template; send them as free-form after the owner taps a button |
| "Falta el reporte de hoy" reminder to manager | Utility | Low | Neutral, tied to the manager's own daily task |
| Pending-change confirmation with quick-reply buttons ("Cambio pendiente: precio de {{platillo}} de {{a}} a {{b}}. Confirma o rechaza") | Utility | Low-medium (user-requested transaction) | Include the specific change; no persuasion |
| Receipt of upload ("Recibimos tu reporte del {{fecha}}") | Utility | Low | Only needed outside window; inside the window it is free |
| Onboarding welcome / re-engagement ("te extrañamos") | Marketing | Certain | Avoid; use the owner's own message to reopen the window |

**unverified**: how strictly Meta reviews a daily report notice in practice. Submit 2-3 phrasings early and check the category Meta assigns; track recategorization via the `message_template_status_update` webhook. Cost of being wrong: daily report 30.4 x USD 0.0397 = USD 1.21 (MXN 22.2) per restaurant per month instead of USD 0.26 (MXN 4.8).

## 5. Receiving media (reports, CFDI XML invoices, receipt photos)

| Item | Value | Label |
|---|---|---|
| Documents accepted | .txt, .xls, .xlsx, .doc, .docx, .ppt, .pptx, .pdf, max 100 MB | **verified** |
| CSV / XML (CFDI) | Not in Meta's table. Users can usually attach any file in the app, but Meta's webhook behavior (type document? mime `text/csv`/`application/xml`? dropped?) is undocumented | **unverified**: test on iOS and Android with real files; fallback: ask for xlsx/pdf, or forward CFDI by email |
| Images | JPEG/PNG, 5 MB max (receipt photos) | **verified** |
| Audio / video | 16 MB each | **verified** |
| Over-size file | Webhook error 131052 "Media file size too big... 100MB" | **verified** |
| Webhook payload (`type: document`) | `id`, `filename`, `mime_type`, `sha256`, `caption`; same shape for CTWA | **verified**: https://developers.facebook.com/documentation/business-messaging/whatsapp/webhooks/reference/messages/document.md |
| Expiry | Media ID from webhook: 7 days; media URL: 5 minutes (re-query the ID); uploaded media: 30 days | **verified** |
| Download flow | 1) `GET /{MEDIA_ID}` returns `url`, `mime_type`, `sha256`, `file_size`; 2) `GET url` with `Authorization: Bearer <token>`; 3) store the bytes in our storage, verify sha256; on 404 re-fetch URL, then refresh token | **verified** |

Design: download and persist on webhook receipt (queue job), keep the original file and sha256 for audit and re-parsing; reject with a friendly reply if the mime/filename does not match a known Soft Restaurant report type; reply to photos asking for the file.

## 6. Interactive messages (confirm/reject pending changes)

| Type | Limits | Use for us |
|---|---|---|
| Reply buttons | Up to 3 buttons; label max 20 chars, unique; button id max 256 chars; body max 1024; footer max 60 | **Primary**: "Confirmar / Rechazar / Ver detalle". Put the pending-change ID in the button id. **verified**: https://developers.facebook.com/documentation/business-messaging/whatsapp/messages/interactive-reply-buttons-messages.md |
| List message | 1 menu button (20 chars), up to 10 sections / 10 rows total, row title 24, description 72, body 4096 | Choosing among several pending changes or restaurants. **verified** |
| Quick-reply buttons inside a template | Allowed on templates; a tap is a user message and opens the window | Needed for proactive prompts outside the window. **likely** (standard template feature, not re-read this session) |
| Flows | Multi-screen forms; static or dynamic via our encrypted endpoint; can be sent in templates or user-initiated interactive messages | Overkill for MVP. Consider later for recipe capture. **unverified** in detail (third-party docs only; Meta Flows guide: https://developers.facebook.com/documentation/business-messaging/whatsapp/flows/guides) |

Authorization pattern (our side): map the sender's `wa_id` to a user and role, verify the pending-change ID belongs to their restaurant and is not expired/already resolved, apply idempotently, write the audit row, reply. Never trust the button payload alone. Taps on old buttons are valid user messages: handle "already resolved/expired" gracefully.

## 7. 24-hour window mechanics and design

- Window starts on a user message (or call) and resets on every new one; 24h after the user's last message it closes. It is tracked per user/business-number pair. After it closes only approved templates can be sent. **verified**
- Free-form answers to owners: always inside the window the owner just opened (they asked a question). Billed as service message after the pooled 1,000/month/number.
- **The manager's daily upload opens the *manager's* window, not the owner's.** Use it for the instant acknowledgement and validation errors to the manager. Owner windows open only when the owner writes.
- Owner reports: send as a **utility template**. If the owner's window is open it is free; otherwise USD 0.0085. Encourage a cheap daily "ping" from the owner (tap on a quick-reply button at the end of each report, e.g. "Ver detalle") so the next report lands inside an open window. **likely** (follows from verified pricing rules; effect depends on owner behavior)
- If no window is open, the button tap on the template reopens it, and then the detailed answer (including price suggestions) goes out as free-form.
- Missing upload: reminder to manager is a template (window usually closed or about to close); escalate to the owner only after N days.
- Scheduling: send reports at a fixed morning time; if the last owner message was less than 24h ago the template is free, so jitter is unnecessary.
- Webhook reliability: Meta notes a rare known issue where a reply to a user message inside the window may fail; retry and fall back to a template. **verified**

## 8. AI chatbot policy

- Meta's Business Solution Terms, updated 15 Jan 2026 (current copy "last updated 23 Sep 2026"), section 4.7: AI Providers (developers of LLMs, generative AI platforms, general-purpose assistants) are prohibited from using the WhatsApp Business Platform when the AI technology is the *primary*, not incidental or auxiliary, functionality offered; Meta decides. The same section prohibits using WhatsApp Business Platform data, even anonymized or aggregated, to train or improve AI/ML models; fine-tuning a model for your exclusive use is allowed. **verified** (via page summary of the Spanish terms)
- Meta's statement at launch: businesses using AI to serve their customers (e.g. a travel company's support bot) are not affected. **verified** (secondary reporting: https://tech.yahoo.com/ai/meta-ai/articles/whatssapp-changes-terms-bar-general-141214399.html) ; Meta's AI Providers pricing page says it does not change how other businesses are charged: https://developers.facebook.com/documentation/business-messaging/whatsapp/pricing/ai-providers.md
- Mexico is not among the listed markets where AI Providers are charged for service messages (Brazil from 11 Mar 2026; EU countries until 12 May 2026). Irrelevant if we are not classed as an AI Provider. **verified**

**Does MermIA comply? Likely yes**, with some residual discretionary risk:
- Our messages are business-specific: reports, answers about *the customer's own restaurant data*, confirmations. The agent is not offered as a general chatbot.
- Risk: our product *is* an AI agent on WhatsApp. Mitigations: scope the system prompt and tools to restaurant data only; decline off-topic requests; present MermIA as a restaurant-intelligence service (report ingestion, alerts, confirmations), keep a human support contact; do not market it as "ChatGPT on WhatsApp"; keep the dashboard (Phase 2) as a second channel.
- Do **not** use WhatsApp message content to train or improve shared/third-party models; confirm our LLM vendor contract is zero-retention/no-training for API data (see the LLM selection doc). Own-use fine-tuning would be allowed.
- Monitor: Meta can change terms; keep the agent channel-agnostic (already in the architecture), so a ban only removes the channel.

## 9. Cost per restaurant per month (Mexico, rates of 1 Oct 2026)

Assumptions (labelled; change them as data arrives): 1 owner + 1 manager; 30.4 days/month; 52/12 = 4.33 weeks/month.
- Owner questions: 20/week = 86.7/month, one free-form reply each (86.7 service messages; long answers sent as one message).
- Pending-change flows: 2/week = 8.7 prompts + 8.7 acknowledgements per month.
- Manager: 30.4 uploads/month, one acknowledgement each; 4 missed-upload reminders/month, assumed outside the window (worst case).
- Report: daily = 30.4 templates/month; weekly = 4.33 templates/month; worst case = owner window closed so each is billed at utility rate.
- Rates: utility = service = USD 0.0085 = MXN 0.1565; 18.41 MXN/USD. Pooled 1,000 free service messages per number ignored (see below).

Two sending strategies:
- **Optimized**: prompts, acknowledgements and manager acks are sent as utility templates; inside an open window they are free. Only the 86.7 AI answers are billed service messages. **likely** (rests on "utility templates in an open CSW are free" **verified** plus Meta approving those templates as utility)
- **Conservative**: everything inside the window is a free-form service message (billed).

| Line | Count/mo | USD | MXN |
|---|---|---|---|
| Owner answers (service) | 86.7 | 86.7 x 0.0085 = 0.737 | 86.7 x 0.1565 = 13.56 |
| Prompts + acks (conservative only) | 17.3 | 0.147 | 2.71 |
| Manager acks (conservative only) | 30.4 | 0.258 | 4.76 |
| Missed-upload reminders (utility, outside window) | 4 | 0.034 | 0.63 |
| Weekly report, worst case | 4.33 | 0.037 | 0.68 |
| Daily report, worst case | 30.4 | 0.259 | 4.76 |

| Scenario | USD / month | MXN / month |
|---|---|---|
| Optimized + weekly report (worst case) | 0.737 + 0.034 + 0.037 = **0.81** | 13.56 + 0.63 + 0.68 = **14.9** |
| Optimized + daily report (worst case) | 0.737 + 0.034 + 0.259 = **1.03** | 13.56 + 0.63 + 4.76 = **19.0** |
| Conservative + weekly report | 0.737 + 0.147 + 0.258 + 0.034 + 0.037 = **1.21** | 13.56 + 2.71 + 4.76 + 0.63 + 0.68 = **22.3** |
| Conservative + daily report | 0.737 + 0.147 + 0.258 + 0.034 + 0.259 = **1.43** | 13.56 + 2.71 + 4.76 + 0.63 + 4.76 = **26.4** |
| Best case (daily report always lands in an open window, optimized) | 0.737 + 0.034 = **0.77** | **14.2** |
| Daily report misclassified as marketing (optimized) | 0.737 + 0.034 + 30.4 x 0.0397 (1.208) = **1.98** | 13.56 + 0.63 + 22.2 = **36.4** |

Pooled free tier: 1,000 service messages per business number per month are shared by all restaurants on our one number. In the optimized model that covers about 11 restaurants' answers (1,000 / 86.7); at 5 restaurants the answer cost is zero, at 50 restaurants the average answer cost is (4,335 - 1,000) / 50 x 0.0085 = USD 0.57 per restaurant. Whether a second number resets the free tier (and whether Meta tolerates it) is **unverified**; do not rely on it.

BSP overlay (illustrative, assumes about 126 inbound + about 150 outbound messages per restaurant per month): Twilio adds 276 x USD 0.005 = about **USD 1.38 (MXN 25)** per restaurant per month, more than the entire Meta bill. 360dialog adds EUR 49 per number per month flat (EUR 4.9 per restaurant at 10 restaurants; not converted, FX not sourced). YCloud Free adds USD 0.

Compare with tokens: a Meta-hosted AI agent (not our design) would cost USD 0.04 to 0.05 per message; our own LLM spend is covered in the LLM/token documents.

## 10. Design implications and to-do

1. Start Business Verification and number registration on day 1; take payment method setup seriously (without one, service messages stop after the first 1,000 per month).
2. Cloud API direct; webhook returns 200 immediately, enqueue processing; idempotent on message id; download media within the 5-minute URL window.
3. Template set v1 (all in es_MX, utility): `reporte_diario`, `reporte_semanal`, `recordatorio_reporte`, `cambio_pendiente` (3 quick-reply buttons), `reporte_recibido`, `cambio_resuelto`. Submit variants day 2; check assigned category; no promotional words.
4. Daily vs weekly: WhatsApp cost is not the deciding factor (USD 0.22 / MXN 4 difference). Default to **weekly report + on-demand answers**, and offer the daily as opt-in; revisit with pilot engagement data.
5. Keep answers compact (one message per question) because each billed message costs the same regardless of length; avoid chatty multi-message replies and separate "typing" acknowledgements.
6. Test early on real devices: CSV/XML delivery, report names, large xlsx, forwarded files, photos instead of files.
7. Log the Meta pricing object on each status webhook (category, type `regular` vs `free_customer_service`) so we can reconcile real cost per restaurant against this model after the first invoice (service charging started only 15 days ago).
8. Keep a second channel path (dashboard, Phase 2) as insurance against Meta policy shifts.
