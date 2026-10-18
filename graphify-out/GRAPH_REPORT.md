# Graph Report - MermIA  (2026-10-18)

## Corpus Check
- 86 files · ~100,145 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 7 file(s) not represented in the graph (top: (none) 4, .typed 1, .lock 1)

## Summary
- 940 nodes · 1885 edges · 47 communities (26 shown, 21 thin omitted)
- Extraction: 92% EXTRACTED · 8% INFERRED · 0% AMBIGUOUS · INFERRED: 146 edges (avg confidence: 0.8)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- MR-10 Implementation Plan
- Business Model & Pricing
- Architecture & Components
- Data Ingestion & Costing
- NormalizedBatch Contract
- Generated Row Models
- Product Features vs SR/Toast
- Model Generator Tool
- Competitive Landscape
- Batch Input Types
- Repo Conventions & Skeptic Review
- Soft Restaurant Research
- WhatsApp Platform
- Overrides & Import Models
- REST Exposure Tests
- Package Init & Batch DB Tests
- Generated Enums
- Feedback & Alternatives
- MVP Plan & Contracts C1-C8
- Roadmap & Milestones
- Ticket Guide
- Phase 1b Hardening
- Phase 1 Pilot & Go-Live
- Claude Hooks Settings
- Phase 2 & Data Sources
- check.sh Script
- format-python Hook
- protect-secrets Hook
- session-start Hook
- Check Skill
- Row model: audit_log
- Row model: conversation
- Row model: daily_location_metrics
- Row model: import_issue
- Row model: item_sales_agg
- Row model: llm_usage
- Row model: membership
- Row model: price_suggestion
- Row model: recipe_line
- Row model: report_run
- Row model: sale_ticket
- Row model: source
- Row model: staff
- Fact Labels Legend
- Package Name

## God Nodes (most connected - your core abstractions)
1. `MR-10 Design: database schema and NormalizedBatch contract` - 63 edges
2. `RowModel` - 44 edges
3. `Data ingestion and costing (kickoff B and C)` - 42 edges
4. `Competitive Landscape (section D)` - 41 edges
5. `09 Architecture` - 40 edges
6. `Soft Restaurant deep dive (section A)` - 34 edges
7. `10 - Business model` - 32 edges
8. `13 LLM selection and token strategy` - 31 edges
9. `WhatsApp Business Platform (kickoff E)` - 30 edges
10. `08 MVP 4-week plan` - 29 edges

## Surprising Connections (you probably didn't know these)
- `Wire format: snake_case JSON, Decimal, centavos int, tz-aware` --references--> `Money units and rounding (D6, 5.4)`  [INFERRED]
  packages/contracts/README.md → docs/superpowers/specs/2026-10-18-mr-10-contracts-schema-design.md
- `test_optional_fields_accept_none_and_omission()` --uses--> `DailySalesIn`  [INFERRED]
  packages/contracts/tests/test_batch_types.py → packages/contracts/src/mermia_contracts/batch.py
- `db.models generated row models` --implements--> `gen_db_models generator and staleness checks (10.2)`  [EXTRACTED]
  packages/contracts/README.md → docs/superpowers/specs/2026-10-18-mr-10-contracts-schema-design.md
- `db.overrides jsonb shapes` --references--> `gen_db_models generator and staleness checks (10.2)`  [EXTRACTED]
  packages/contracts/README.md → docs/superpowers/specs/2026-10-18-mr-10-contracts-schema-design.md
- `Security model: RLS, JWT claims tenant_id/app_role/location_ids` --conceptually_related_to--> `Tenant isolation check (RLS, pgTAP, SECURITY INVOKER)`  [INFERRED]
  README.md → .claude/agents/skeptic-reviewer.md

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Week 0 to pilot live flow** — docs_kickoff_07_roadmap_m0, docs_kickoff_07_roadmap_m1, docs_kickoff_07_roadmap_m2, docs_kickoff_07_roadmap_m5, docs_kickoff_07_roadmap_m7 [EXTRACTED 1.00]
- **Day-2 frozen contract set** — docs_kickoff_08_mvp_4_week_plan_c1, docs_kickoff_08_mvp_4_week_plan_c2, docs_kickoff_08_mvp_4_week_plan_c3, docs_kickoff_08_mvp_4_week_plan_c4, docs_kickoff_08_mvp_4_week_plan_c5, docs_kickoff_08_mvp_4_week_plan_c6, docs_kickoff_08_mvp_4_week_plan_c7, docs_kickoff_08_mvp_4_week_plan_c8 [EXTRACTED 1.00]
- **Phase 3 gate decision chain** — docs_kickoff_06_feedback_and_alternatives_phase3_pos_risk, docs_kickoff_06_feedback_and_alternatives_phase3_gate, docs_kickoff_07_roadmap_phase3_spikes, docs_kickoff_07_roadmap_phase3_gate [INFERRED 0.85]
- **Human-approved write flow** — docs_kickoff_09_architecture_d7, docs_kickoff_09_architecture_propose_change, docs_kickoff_09_architecture_pending_change, docs_kickoff_09_architecture_confirmation_service, docs_kickoff_09_architecture_apply_pending_change, docs_kickoff_09_architecture_audit_log [EXTRACTED 1.00]
- **Ingestion pipeline transport to batch** — docs_kickoff_09_architecture_transport, docs_kickoff_09_architecture_parser_registry, docs_kickoff_09_architecture_normalized_batch, docs_kickoff_09_architecture_batch_loader, docs_kickoff_09_architecture_import_batch [EXTRACTED 1.00]
- **Lean low-token agent design** — docs_kickoff_13_llm_and_token_strategy_intent_router, docs_kickoff_13_llm_and_token_strategy_prompt_caching, docs_kickoff_13_llm_and_token_strategy_numbers_never_llm, docs_kickoff_13_llm_and_token_strategy_routing_rules, docs_kickoff_13_llm_and_token_strategy_tenant_budgets [INFERRED 0.85]
- **Pricing plan ladder** — docs_kickoff_10_business_model_plan_piloto, docs_kickoff_10_business_model_plan_compras, docs_kickoff_10_business_model_plan_margenes, docs_kickoff_10_business_model_plan_cadena [EXTRACTED 0.95]
- **Confirm-before-write flow** — docs_kickoff_12_sample_agent_messages_pending_change, docs_kickoff_12_sample_agent_messages_confirm_flow, docs_kickoff_12_sample_agent_messages_undo, docs_kickoff_12_sample_agent_messages_approval_audit [EXTRACTED 0.85]
- **Manager report upload loop** — docs_kickoff_12_sample_agent_messages_onboarding_manager, docs_kickoff_12_sample_agent_messages_upload_instructions, docs_kickoff_12_sample_agent_messages_report_validation, docs_kickoff_12_sample_agent_messages_reminders [EXTRACTED 0.85]
- **Phase 3 POS build blocks** — docs_kickoff_research_pos_legal_stack_notes_offline_first_sync, docs_kickoff_research_pos_legal_stack_notes_cfdi_pac, docs_kickoff_research_pos_legal_stack_notes_printers_kds, docs_kickoff_research_pos_legal_stack_notes_payment_terminals, docs_kickoff_research_pos_legal_stack_notes_delivery_integrations [EXTRACTED 0.95]
- **Compras plan paid price-capture features** — docs_kickoff_14_product_features_cfdi_xml_capture, docs_kickoff_14_product_features_nota_photo_ocr, docs_kickoff_14_product_features_price_shock_alerts, docs_kickoff_14_product_features_sniim_benchmark, docs_kickoff_14_product_features_plan_compras [EXTRACTED 0.95]
- **MR-n naming across issue, branch, commit, PR** — docs_process_ticket_guide_mr_indicator, docs_process_ticket_guide_branch_rules, docs_process_ticket_guide_labels [INFERRED 0.75]
- **Fail-closed null-claim trust chain** — docs_superpowers_specs_2026_10_18_mr_10_contracts_schema_design_membership_all_locations, docs_superpowers_specs_2026_10_18_mr_10_contracts_schema_design_null_claim_issuance, docs_superpowers_specs_2026_10_18_mr_10_contracts_schema_design_fn_can_see_location, docs_superpowers_specs_2026_10_18_mr_10_contracts_schema_design_trust_boundary [INFERRED 0.85]
- **SQL migrations to generated models to NormalizedBatch** — docs_superpowers_specs_2026_10_18_mr_10_contracts_schema_design_supabase_root, docs_superpowers_specs_2026_10_18_mr_10_contracts_schema_design_enums_24, docs_superpowers_specs_2026_10_18_mr_10_contracts_schema_design_generator, docs_superpowers_specs_2026_10_18_mr_10_contracts_schema_design_normalized_batch, packages_contracts_readme_models_generated [INFERRED 0.85]
- **Indirect exposure defence and tests** — docs_superpowers_specs_2026_10_18_mr_10_contracts_schema_design_indirect_exposure, packages_contracts_tests_test_rest_exposure, docs_superpowers_specs_2026_10_18_mr_10_contracts_schema_design_pgtap_suite, docs_superpowers_plans_2026_10_18_mr_10_contracts_schema_task13 [INFERRED 0.75]
- **Review workflow agents and skills** — claude_skills_review_skill, claude_agents_skeptic_reviewer, claude_skills_check_skill [INFERRED 0.75]
- **Ticket lifecycle** — github_issue_template_ticket, claude_skills_start_ticket_skill, claude_skills_review_skill [INFERRED 0.75]
- **Soft Restaurant data ingestion routes** — docs_kickoff_01_soft_restaurant_research_corte_z, docs_kickoff_01_soft_restaurant_research_erp_pms, docs_kickoff_01_soft_restaurant_research_local_connector, docs_kickoff_01_soft_restaurant_research_reportes_menu [INFERRED 0.85]
- **MX cloud POS challengers** — docs_kickoff_02_competitive_landscape_polotab, docs_kickoff_02_competitive_landscape_parrot, docs_kickoff_02_competitive_landscape_fudo, docs_kickoff_02_competitive_landscape_mercadopago [INFERRED 0.85]
- **SR DB connector precedents** — docs_kickoff_01_soft_restaurant_research_kavasoft, docs_kickoff_01_soft_restaurant_research_factorbi, docs_kickoff_01_soft_restaurant_research_local_connector [EXTRACTED 0.95]
- **Ingestion options compared for the MVP-to-long-term path** — docs_kickoff_03_data_ingestion_and_costing_opt_whatsapp_upload, docs_kickoff_03_data_ingestion_and_costing_opt_email_inbox, docs_kickoff_03_data_ingestion_and_costing_opt_erp_pms_push, docs_kickoff_03_data_ingestion_and_costing_opt_local_connector, docs_kickoff_03_data_ingestion_and_costing_ingestion_scores [EXTRACTED 1.00]
- **WhatsApp per-restaurant cost model** — docs_kickoff_04_whatsapp_platform_service_billable, docs_kickoff_04_whatsapp_platform_mexico_rate_card, docs_kickoff_04_whatsapp_platform_csw_24h, docs_kickoff_04_whatsapp_platform_template_categories, docs_kickoff_04_whatsapp_platform_cost_per_restaurant [EXTRACTED 1.00]
- **Top 5 risks and their mitigations** — docs_kickoff_05_risks_and_friction_r01, docs_kickoff_05_risks_and_friction_r05, docs_kickoff_05_risks_and_friction_r08, docs_kickoff_05_risks_and_friction_r06, docs_kickoff_05_risks_and_friction_r16, docs_kickoff_05_risks_and_friction_top5_notes [EXTRACTED 1.00]

## Communities (47 total, 21 thin omitted)

### Community 0 - "MR-10 Implementation Plan"
Cohesion: 0.05
Nodes (85): MR-10 Implementation Plan, Global constraints, Review focus items, Task 1: Project scaffolds, Task 10: Complete pgTAP suite, Task 11: Generator and models, Task 12: NormalizedBatch, Task 13: REST exposure test (+77 more)

### Community 1 - "Business Model & Pricing"
Cohesion: 0.05
Nodes (77): 10 - Business model, Annual prepay: pay 10 get 12, Assumptions to replace first, Break-even ~270 paying locations, CAC and payback assumptions, Channel: accountants (contadores) referral, Channel: CANIRAC and state delegations, Channel: Click-to-WhatsApp ads (+69 more)

### Community 2 - "Architecture & Components"
Cohesion: 0.06
Nodes (72): 09 Architecture, Agent core (router, templates, LLM broker, validator), AgentRequest/AgentResponse channel-agnostic interface, apply_pending_change() SQL function, audit_log table (append-only), Batch loader (validate, stage, apply), CFDI 4.0 XML parser, Confirmation service (+64 more)

### Community 3 - "Data Ingestion & Costing"
Cohesion: 0.07
Nodes (65): Data ingestion and costing (kickoff B and C), Accuracy rule: cost top ~10 dishes and ~20 ingredients first (+/-10%), Alert thresholds: price jump 8%/15%, margin breach +3 pts, stale 45 days, mix shift 20%, Append-only price history with source priority (cfdi > note > sr_import > manual > benchmark), Import batch model and lifecycle (received to applied/rolled_back/superseded), Case 1: recipes and costs in SR (weekly re-import, stale check), CFDI fields: Comprobante, Emisor, Receptor, Concepto, ValorUnitario, ClaveUnidad, ClaveProdServ, CFDI TimbreFiscalDigital UUID as dedup key (+57 more)

### Community 4 - "NormalizedBatch Contract"
Cohesion: 0.07
Nodes (35): Grain, ItemSalesIn, NormalizedBatch, db_url(), make(), test_batches_are_immutable(), test_contract_version_is_pinned_to_one(), test_database_enums_are_reused_not_redefined() (+27 more)

### Community 5 - "Generated Row Models"
Cohesion: 0.04
Nodes (26): AlertRow, AppUserRow, ChannelIdentityRow, ConsentLogRow, DailySalesAggRow, DishCostSnapshotRow, ExternalRefRow, IngredientAliasRow (+18 more)

### Community 6 - "Product Features vs SR/Toast"
Cohesion: 0.07
Nodes (51): Product features: Soft Restaurant vs Toast vs MermIA, Branch ranking of margin, food cost and leaks, CFDI XML purchase capture via forwarded inbox, Menu-engineering matrix (Kasavana-Smith), NCR Aloha Restaurant Guard exception reporting, Nory, MarketMan, Apicbase, R365 (proven-model references), Photo OCR of informal supplier notas, Confirmed writes: pending_change with diff, 24h expiry, audit log (+43 more)

### Community 7 - "Model Generator Tool"
Cohesion: 0.09
Nodes (21): Column, compute_migrations_hash(), element_type(), EnumType, generate(), import_line(), introspect(), main() (+13 more)

### Community 8 - "Competitive Landscape"
Cohesion: 0.10
Nodes (41): Competitive Landscape (section D), Agiliza360.ai (WhatsApp AI ordering), NCR Voyix Aloha, Apicbase, CFDI XML invoice-to-cost capture, Clip, Features and models to copy, Cost-side margin alert and price suggestion wedge (+33 more)

### Community 9 - "Batch Input Types"
Cohesion: 0.08
Nodes (21): DailySalesIn, IssueIn, MenuItemIn, Model, PaymentIn, Period, PurchaseIn, PurchaseLineIn (+13 more)

### Community 10 - "Repo Conventions & Skeptic Review"
Cohesion: 0.07
Nodes (29): Job 1: challenge reviewer findings (CONFIRMED/REJECTED/UNSURE), Contracts check (packages/contracts, 125-token tool schemas), Human approval for writes (pending_change, apply_pending_change, audit_log), Ingestion safety (idempotent apply_batch, rollback_batch), Money and numbers check (bigint centavos, no float), Tenant isolation check (RLS, pgTAP, SECURITY INVOKER), Conventions: English code, Mexican Spanish customer text, 2 devs, human approval, lean agent, Current direction: cost-side value, POS is month-9 gate (+21 more)

### Community 11 - "Soft Restaurant Research"
Cohesion: 0.12
Nodes (36): Soft Restaurant deep dive (section A), Analytics 3.0 / Reportes Web (25+ reports), SR 12 CFDI XML purchase import with auto input linking, User complaints (thin evidence, competitor-sourced), Corte Z / Corte de caja email (SMTP, SR 12), Data ownership / LFPDPPP controller is the restaurant, 610 distributor partners (reseller programme, not tech-partner), ERP/PMS module (JSON HTTP POST per sale, x-api-key) (+28 more)

### Community 12 - "WhatsApp Platform"
Cohesion: 0.11
Nodes (35): WhatsApp Business Platform (kickoff E), One WABA, one MermIA number, many restaurants as users, MermIA likely compliant: scoped to restaurant data, Meta AI Providers policy (Terms section 4.7), BSP options: YCloud, 360dialog, Twilio, Gupshup, Wati, Infobip, Meta Business Verification (RFC constancia plus proof of address), Button authorization: map wa_id to role, verify pending change, idempotent, Recommendation: Cloud API direct from Meta (+27 more)

### Community 13 - "Overrides & Import Models"
Cohesion: 0.08
Nodes (9): ImportBatchRow, TenantRow, ImportBatchStats, TenantSettings, enums(), rows(), test_documented_jsonb_columns_are_typed_and_the_rest_are_open(), test_forty_rows_and_twenty_four_enums() (+1 more)

### Community 14 - "REST Exposure Tests"
Cohesion: 0.17
Nodes (20): b64(), call(), env(), fixtures(), mint(), test_a_self_referencing_composite_foreign_key_embeds(), test_backend_only_tables_are_refused(), test_embedding_backend_only_or_hidden_data_is_refused() (+12 more)

### Community 15 - "Package Init & Batch DB Tests"
Cohesion: 0.12
Nodes (11): enum_of(), optional(), test_input_fields_map_to_columns(), unit(), input_types(), test_every_input_type_exists(), test_exactly_the_documented_types_are_provisional(), allows_none() (+3 more)

### Community 16 - "Generated Enums"
Cohesion: 0.16
Nodes (20): ActorKind, BaseUnit, BatchQuality, BatchStatus, Channel, CostConfidence, IngredientPriceSource, IssueSeverity (+12 more)

### Community 17 - "Feedback & Alternatives"
Cohesion: 0.13
Nodes (22): 06 Feedback and alternatives, Approve per batch, alias once, Charge from month 2 of pilot, Concierge costing of top-10 dishes, Customer discovery before code, Sell through SR distributors, Weekly per-waiter leak ranking in pesos, Legal basics: aviso de privacidad, Meta verification (+14 more)

### Community 18 - "MVP Plan & Contracts C1-C8"
Cohesion: 0.18
Nodes (22): What each phase reuses, 08 MVP 4-week plan, C1 Normalized schema v1, C2 NormalizedBatch v1, C3 Metric RPC interfaces (11 RPCs), C4 Agent tool definitions (12 tools), C5 PendingChange kinds, C6 AgentRequest/AgentResponse (+14 more)

### Community 19 - "Roadmap & Milestones"
Cohesion: 0.22
Nodes (16): Fallback Phase 3: intelligence across POSes + purchasing, 07 Roadmap (Phases 1 to 3), Cost tracking in every phase, M0 Long-lead items started, M1 Contracts frozen, M2 LLM selection gate, M3 Token-cost design validated, M4 First real parse (+8 more)

### Community 20 - "Ticket Guide"
Cohesion: 0.31
Nodes (11): Ticket guide, Branch rules: 1-day branches, PR to main, squash, <400 lines, Contracts first: packages/contracts changes need both devs, Rules for good tickets (one owner, 1-2 days, checkable done), Issue template .github/ISSUE_TEMPLATE/ticket.md, Labels: sprint, owner, week (one of each), MR-<n> indicator format (issue, branch, commit, PR), Owners dev-a (data), dev-b (conversation), both, founders (+3 more)

### Community 21 - "Phase 1b Hardening"
Cohesion: 0.29
Nodes (8): SR 12 Corte Z email to inbox, ERP/PMS JSON push as target ingestion, Cost capture: CFDI XML parser, nota OCR, Dashboard v1 React+Vite PWA, Phase 1b Harden (weeks 5-12), Phase 1b exit criteria, ERP/PMS shadow mode next to uploads, MVP scope: out

### Community 22 - "Phase 1 Pilot & Go-Live"
Cohesion: 0.29
Nodes (7): Pilot success metric, WhatsApp first, channel-agnostic agent, Phase 1 WhatsApp agent MVP (weeks 0-4), Phase 1 exit criteria, Day 15 dress rehearsal and go/no-go, Go-live day 16, Pilot success criteria (4 weeks)

### Community 23 - "Claude Hooks Settings"
Cohesion: 0.33
Nodes (5): hooks, PostToolUse, PreToolUse, SessionStart, $schema

### Community 24 - "Phase 2 & Data Sources"
Cohesion: 0.40
Nodes (5): Local DB connector (Kavasoft, FactorBI), Pricing test MXN 449 vs 899 per location, Second data source (Excel/CFDI-only), Phase 2 Mobile-first dashboard (months 3-6), Phase 2 exit criteria

### Community 25 - "check.sh Script"
Cohesion: 0.83
Nodes (3): has_tool(), run(), check.sh script

## Knowledge Gaps
- **22 isolated node(s):** `mermia-contracts`, `Plan error: most restaurants use SR`, `Sales Q&A is not a paid product`, `Lead with small chains (2-5 locations)`, `Partner with a POS instead of building one` (+17 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 136 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **21 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `MR-10 Design: database schema and NormalizedBatch contract` connect `MR-10 Implementation Plan` to `REST Exposure Tests`?**
  _High betweenness centrality (0.058) - this node is a cross-community bridge._
- **What connects `mermia-contracts`, `Plan error: most restaurants use SR`, `Sales Q&A is not a paid product` to the rest of the system?**
  _22 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `MR-10 Implementation Plan` be split into smaller, more focused modules?**
  _Cohesion score 0.0546218487394958 - nodes in this community are weakly interconnected._
- **Why does `POS-agnostic schema built in Phases 1-2` connect `Product Features vs SR/Toast` to `Ticket Guide`?**
  _High betweenness centrality (0.046) - this node is a cross-community bridge._
- **Should `Business Model & Pricing` be split into smaller, more focused modules?**
  _Cohesion score 0.05365686944634313 - nodes in this community are weakly interconnected._
- **Why does `Product features: Soft Restaurant vs Toast vs MermIA` connect `Product Features vs SR/Toast` to `Business Model & Pricing`?**
  _High betweenness centrality (0.046) - this node is a cross-community bridge._
- **Should `Architecture & Components` be split into smaller, more focused modules?**
  _Cohesion score 0.06025039123630673 - nodes in this community are weakly interconnected._