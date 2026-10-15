# MermIA

Restaurant intelligence for Mexico. Phase 1: WhatsApp agent fed by Soft Restaurant report exports. Phase 2: mobile-first dashboard. Phase 3: cloud POS that keeps working offline and runs on any device. Each phase reuses the one before. Kickoff brief: `docs/kickoff-prompt.md`.

## Key docs
- Kickoff research and plan: `docs/kickoff/` — start with `00-executive-summary.md`; architecture `09`, 4-week plan (Dev A / Dev B) `08`, features vs Soft Restaurant and Toast IQ `14`, LLM and token strategy `13`.
- Current direction (from kickoff, 2026-10-15): sell cost-side value (margin alerts, price suggestions, CFDI/receipt price capture), not sales Q&A that SR already gives free; MVP ingestion = WhatsApp upload + email inbox, target = SR ERP/PMS JSON push; Phase 3 POS is a decision gate at ~month 9, not a commitment.

## Conventions
- **Language:** code, technical docs and dev communication in English. Everything customers see (agent replies, WhatsApp messages, reports, UI text, marketing) in Mexican Spanish.
- **Target customers:** independent owners and small chains (2–10 locations). Phase 1 MVP goal: live pilot within 4 weeks.
- **Team:** 2 devs working in parallel; agree on contracts (schema, RPC/tool interfaces) first and build against mocks to avoid blocking.
- **Proven models first:** replicate and adapt features and business models that already work elsewhere (e.g. ToastIQ); don't invent from scratch.
- **DB writes need human approval:** any create/edit/delete the agent triggers needs explicit confirmation from an owner, manager or admin, and is audit-logged.
- **Lean agent:** backend RPCs do the heavy lifting; the LLM acts as a broker to keep token cost low.
