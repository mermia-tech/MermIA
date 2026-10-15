# Kickoff Prompt — Restaurant Intelligence for Mexico

> Paste everything below the line into the kickoff agent. It works best with an agent that can search the web and write files (e.g. Claude Code in this repo).

---

## Your role

You are the founding product strategist, market researcher and technical architect for a new startup. Your job in this session is **research, critique and planning — not writing production code**. We want you to be honest with us: we are **not married to our current plan**. If you find a better approach, a cheaper path, a fatal flaw or a missing piece, tell us directly and explain why.

Today's date is 2026-10-15. Treat anything you know from before that date as possibly out of date, and verify it.

## The business

We are building a software company for **restaurants in Mexico**. The core problem: **owners have very little visibility into their business.** Ingredient prices change often, so dishes that used to be profitable quietly stop being profitable, and owners only notice a month later when they're already losing money.

Most Mexican restaurants use **Soft Restaurant** (by National Soft) as their point of sale (POS). Our view is that it is outdated, gives owners little insight, and has no AI features. Getting data out of it is hard, but it can **export reports**.

We plan to build in three phases. **Everything built in one phase must be reused in the next.**

### Phase 1 — WhatsApp agent (MVP)
1. Every day, the restaurant manager exports a report from Soft Restaurant and sends it to **our WhatsApp number** (the data entry point).
2. We parse the report, pull out the data, and load it into our database.
3. The owner talks to **our AI agent on WhatsApp** and can ask things like: sales, cost of each ingredient, cost of each dish, high- and low-margin dishes, week-over-week changes, and so on.
4. The agent also **sends reports on its own** (daily or weekly — your research should decide which): best sellers, lowest-margin dishes, and **suggested price changes** when ingredient costs move.

### Phase 2 — Mobile-first dashboard
- A summary of the key numbers (best sellers, sales, costs, margins) that each owner can customize.
- It won't be live. It will be as fresh as the data we receive (probably daily).

### Phase 3 — Our own POS ("the operating system for the restaurant")
- Works on any device (iPad, Mac, Windows, etc.), so we never sell hardware.
- Modern, cloud-first, with near-real-time sync so owners can watch their restaurants live. **It must keep working when the internet goes down** and sync once it's back.
- We provide everything: the POS, the database, AI agents running on top of it, and visibility.
- A known competitor doing something similar in Mexico City: **Polotab**.

## Decisions already made
- **Target customers:** independent owners and small chains (roughly 2–10 locations).
- **Team and timeline:** we build it ourselves — **a team of 2 developers** who want to work **in parallel** with as little blocking as possible. **Phase 1 MVP live with a pilot restaurant in 4 weeks at most.**
- **Language:** code, technical docs and anything aimed at developers are in **English**. Everything customers see — WhatsApp messages, the agent's replies, reports, dashboard text, marketing — is in **Mexican Spanish**, in a natural, friendly tone for restaurant owners and managers.
- **Recipe and cost data:** some restaurants keep their recipes and ingredient costs in Soft Restaurant and some don't. **Design a solution for both cases.**
- **Proven models, adapted to Mexico — not inventions.** We don't want to bet on something new built from scratch. We want to bring products and business models that already work elsewhere (e.g. **ToastIQ** from Toast in the USA) to Mexico, adapt them to the local market, and improve them where we can. Every feature and pricing idea you recommend should point to who already does it and the evidence that it works.
- **A human approves every change to the database.** Reading data is free, but any action that creates, edits or deletes data (recipes, ingredient costs, prices, corrected sales, settings) needs **explicit manual confirmation from an authorized owner, manager or admin** before it's applied. The agent proposes the change and shows what will change; a person confirms it. Uploading a report is the one exception, but the data it loads must be reviewable and reversible.
- **Token costs must stay low.** We'll pay for an LLM API per token, which gets expensive fast. The agent must be lean: our backend does the heavy lifting and the agent acts mostly as a broker between the user and our functions.

## Things we already suspect (verify them, don't assume them)
- The daily manual upload is our weakest link: managers will forget, send the wrong report, or send a photo instead of the file.
- Soft Restaurant reportedly runs on a local SQL Server database. A small local connector that reads it could replace the manual step. Check whether that's technically possible and legal (license terms, data ownership).
- Sales reports don't include ingredient costs. Possible sources: Soft Restaurant's recipe and inventory module, supplier e-invoices (CFDI XML) forwarded the same way as reports, photos of cash receipts and notes from suppliers who don't issue invoices (common for markets and Central de Abasto), public wholesale price data (e.g. SNIIM), and recipe capture done by chatting with the agent.
- WhatsApp rules affect the product: messages we start must use templates approved in advance, each message has a cost, there is a 24-hour customer-service window, and Meta has policies on AI chatbots in the WhatsApp Business Platform. Check what's current.

## Research to do

Cite sources with URLs. Label each claim as **verified**, **likely** or **unverified**. If you can't confirm something (for example, an exact report format), say so and tell us how to confirm it (e.g. "get a sample export from the pilot restaurant").

### A. Soft Restaurant deep dive
- Versions currently in use and how it's built (local vs cloud, database, its cloud or mobile add-ons).
- Market share and installed base in Mexico; who uses it (independents vs chains); pricing and licensing.
- **Every report that can be exported**: names, formats (Excel/PDF/CSV/XML), what each one contains (sales per dish, modifiers, discounts, cancellations, payment types, waiters, shifts, branches), and whether they can be scheduled or emailed automatically.
- The recipe, inventory and costing modules: what they hold and how many restaurants actually keep them up to date.
- Official APIs, integrations, partner program, marketplace, and how they've reacted to third-party tools.
- What users complain about (reviews, forums, Facebook groups, Reddit, YouTube, distributors).

### B. Ways to get the data in
Compare at least these, scored on reliability, effort for the restaurant, cost to build, legal risk and fit with the 4-week MVP:
manual WhatsApp upload · email forwarding or a dedicated inbox · scheduled or automated exports · local connector reading the SR database · official SR API or partnership · any better idea you find.
Recommend **one for the MVP** and **one to aim for long-term**, plus how to move from the first to the second.

### C. Ingredient costs and recipes (both cases)
- **Case 1 — recipes and costs are in SR:** how we extract and keep them in sync.
- **Case 2 — they aren't:** the least painful way to capture recipes and costs (chat with the agent, spreadsheet template, photos, CFDI parsing, price benchmarks), and how much accuracy is "good enough" to be useful.
- How to track ingredient price changes over time and turn them into margin alerts and price suggestions. Use standard menu-engineering methods (e.g. the Kasavana–Smith matrix, food-cost % targets, theoretical vs actual cost).

### D. Competitors
- Soft Restaurant's direct competitors in Mexico (POS), including Polotab, Mexican and Latin American players, and global entrants. Verify each name and look for others.
- Analytics, back-office and inventory/costing tools sold to restaurants in Mexico and Latin America, and any AI or WhatsApp-based restaurant assistants.
- For each: what it offers, price, target segment, strengths and weaknesses, funding and traction. Then: **where is the gap we can own?**
- **Proven models to replicate.** Study what already works in mature markets, starting with **ToastIQ** (Toast, USA), then other restaurant AI, analytics and costing products in the US, Europe and Latin America (find and verify the relevant ones). For each: the features, the business model (pricing, bundling, how it's sold), and evidence it works (adoption, revenue, reviews). Then list which features and models we should copy for Mexico, what needs adapting (WhatsApp instead of apps, Soft Restaurant data, CFDI, informal suppliers, price sensitivity), and where we can do better.

### E. WhatsApp Business Platform
- Cloud API vs BSPs (Business Solution Providers), onboarding and verification, pricing per message type in Mexico, template categories, media limits for receiving documents, the 24-hour window, current AI-chatbot policies, and how these affect our design (proactive reports, receiving reports, cost per customer per month).

### F. Friction and risks
Adoption and habit building, manager discipline, data quality, multiple branches, owner trust in the AI's numbers, willingness to pay, how Soft Restaurant might react (blocking us, copying us), Mexican data-protection law (current LFPDPPP), and the AI giving wrong numbers. For each risk, give a mitigation.

### G. Phase 3 POS requirements (high level only)
What a POS needs in Mexico: CFDI 4.0 invoicing through a PAC (authorized invoicing provider), ticket printers and cash drawers, kitchen display or order printers, waiter devices (comanderas), tips, splitting bills, payment terminals (e.g. Clip, Mercado Pago), delivery-app integrations (Rappi, Uber Eats, DiDi Food), and offline-first sync methods. How hard and expensive is this, and what should Phases 1–2 build now so Phase 3 is easier later?

### H. LLM selection
We need evidence behind which model(s) power the agent: **cost-effective, but with great results for our tasks.**
- Compare current models from the main providers (Anthropic, OpenAI, Google) and strong open-weight options served by hosting providers. Verify current models and prices; don't rely on memory.
- Criteria: quality in Mexican Spanish, tool/function-calling reliability, accuracy with numbers, latency on WhatsApp, price per million input/output tokens, prompt caching and batch discounts, rate limits, data privacy and retention terms.
- Propose a small evaluation set we can run ourselves (e.g. 30–50 realistic owner questions with expected answers and tool calls) and how to score it.
- Recommend a primary model, a fallback, and whether to route by task (a cheap model for simple questions and classification, a stronger one only when needed).

### I. Token cost and a lean agent
- Research how other companies building LLM agents on per-token APIs keep costs down, and which techniques fit us.
- Starting point to validate or challenge: **the agent is a thin broker.** It works out what the user wants, calls our backend functions (RPCs / metric tools) that do the real work — queries, calculations, report building — and phrases the result. It never loads raw data into its context.
- Cover at least: small tool definitions and system prompts, prompt caching, short conversation memory (summaries instead of full history), answering common questions with templates and no LLM call at all, generating proactive reports in code (LLM only for wording, or not at all), batch APIs for scheduled jobs, model routing, and per-restaurant token budgets and limits.
- Estimate tokens per typical interaction and the **monthly LLM cost per restaurant**, with a target budget and how we'll measure it in production.

## Architecture direction (challenge it if you disagree)
- **A data model that isn't tied to any POS.** Soft Restaurant is just the first data source. Our own POS should later write into the same model.
- **One adapter per data source** (SR report parser, CFDI parser, local connector, later our POS), all producing the same normalized data.
- Built for many restaurants and branches from day one (multi-tenant, multi-location).
- **A shared metrics layer** (margin, food cost %, sales mix, week-over-week change) that the agent, the dashboard and the POS all use. The agent calls trusted metric tools instead of writing raw SQL, so its numbers stay correct.
- **A lean agent that acts as a broker** (see section I): backend RPCs do the heavy lifting and return small, ready-to-use results, so the agent uses few tokens.
- **Write actions go through a confirmation step:** roles and permissions (owner, manager, admin), a pending-change record the agent creates, explicit approval by an authorized person (e.g. a WhatsApp confirm button), and an audit log of who approved what and when. Show how this works on WhatsApp now and in the dashboard and POS later.
- **An agent that isn't tied to one channel:** WhatsApp now, then the dashboard and the POS.
- **Built for 2 devs working in parallel:** clear module boundaries and agreed contracts (normalized data schema, metric/RPC interfaces, agent tool definitions) defined first, so each dev can build against mocks or sample data without waiting on the other.
- Propose a concrete stack that suits a team of 2 shipping in 4 weeks, with justification and estimated monthly cost per restaurant (LLM, WhatsApp, hosting).

## Deliverables

Write these as Markdown files under `docs/kickoff/`, in English:

1. `00-executive-summary.md` — one page: what you recommend, the 5 most important findings, the biggest risks, and **where you disagree with our plan**.
2. `01-soft-restaurant-research.md` — section A, with sources.
3. `02-competitive-landscape.md` — section D, with a comparison table, the gap we can own, and a table of proven features and business models to replicate (who does it, evidence it works, how we adapt it to Mexico).
4. `03-data-ingestion-and-costing.md` — sections B and C, with your recommendations.
5. `04-whatsapp-platform.md` — section E.
6. `05-risks-and-friction.md` — section F as a table: risk, likelihood, impact, mitigation.
7. `06-feedback-and-alternatives.md` — your honest critique: what we're missing, what's wrong, better alternatives, what you'd do differently.
8. `07-roadmap.md` — Phases 1→3 with milestones, exit criteria for each phase (what must be true before moving on), key metrics, and what each phase reuses from the one before. Include **LLM selection (section H)** and **token-cost research (section I)** as early Phase 1 milestones, finished before the agent is built, plus ongoing cost tracking in every phase.
9. `08-mvp-4-week-plan.md` — a week-by-week plan to reach a live pilot, the smallest feature set, what's explicitly out of scope, and how we'll know the pilot worked. **Split the work into two parallel tracks (Dev A / Dev B)**: what each owns, the contracts to agree on in the first days, the dependencies and sync points between tracks, and how to avoid blocking each other (mocks, sample exports, branching and review flow).
10. `09-architecture.md` — the architecture, data model (main entities), stack, the confirmation flow for write actions, and the Phase 3 considerations from section G.
11. `10-business-model.md` — pricing ideas (in MXN) based on models proven elsewhere and adapted to Mexico, go-to-market for independents and small chains, how to find pilot customers, unit economics (including LLM cost per restaurant from section I).
12. `11-open-questions.md` — what you need from us or from a pilot restaurant to move forward.
13. `12-sample-agent-messages.md` — **in Mexican Spanish**: an example daily or weekly proactive report, three example owner questions with answers, an example change that asks the owner to confirm before it's saved, and the onboarding messages for the manager who uploads reports.
14. `13-llm-and-token-strategy.md` — sections H and I: model comparison table, evaluation plan, recommended model(s) and routing, cost-saving techniques, and estimated monthly LLM cost per restaurant.

## How to work
- If anything is unclear and blocks you, **ask us up to 5 questions at the start**. Otherwise, go ahead, write down your assumptions, and continue.
- Keep facts separate from your opinions. Never make up details about Soft Restaurant, a competitor or a price. If you can't verify something, say so.
- Be concise and use tables where they help. We're a small, technical team that needs to act fast.
- When you finish, reply with a short summary: your top 3 recommendations, the top 3 risks, and the 3 things we must do this week.
