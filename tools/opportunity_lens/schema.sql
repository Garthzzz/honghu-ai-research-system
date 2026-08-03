PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS opportunity_schema_meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL,
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS opportunity_run (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  question TEXT NOT NULL,
  research_question TEXT NOT NULL DEFAULT '',
  display_title TEXT,
  run_mode TEXT NOT NULL CHECK (run_mode IN ('c_open','c_open_with_seed','c_paper','c_hybrid','c_paper_scoring_ready','needs_problem_rewrite')),
  run_status TEXT NOT NULL CHECK (run_status IN ('created','intake_validated','searching','screening','extracting','mapping_entities','scoring','report_drafting','under_review','completed','blocked','failed','cancelled','archived')),
  run_readiness_status TEXT NOT NULL DEFAULT 'draft' CHECK (run_readiness_status IN ('draft','reviewable','published','blocked','archived')),
  requested_by TEXT,
  problem_statement TEXT,
  evidence_policy TEXT NOT NULL DEFAULT 'balanced' CHECK (evidence_policy IN ('freshness_first','balanced','accuracy_first')),
  seed_description TEXT,
  data_cutoff_at TEXT,
  schema_version TEXT NOT NULL,
  api_contract_version TEXT NOT NULL,
  score_rule_version TEXT NOT NULL,
  source_tier_version TEXT NOT NULL,
  search_protocol_version TEXT NOT NULL,
  report_template_version TEXT NOT NULL,
  pdf_export_version TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now')),
  completed_at TEXT
);

CREATE TABLE IF NOT EXISTS opportunity_run_manifest (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id INTEGER NOT NULL,
  manifest_type TEXT NOT NULL,
  manifest_json TEXT NOT NULL,
  manifest_hash TEXT,
  intake_contract_version TEXT,
  evidence_policy_version TEXT,
  early_signal_rule_version TEXT,
  workflow_contract_version TEXT,
  pack_schema_version TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY(run_id) REFERENCES opportunity_run(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS opportunity_intake_contract (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id INTEGER NOT NULL UNIQUE,
  research_question TEXT NOT NULL,
  available_materials_choice TEXT NOT NULL DEFAULT 'A' CHECK (available_materials_choice IN ('A','B','C')),
  intake_material_type TEXT NOT NULL DEFAULT 'none' CHECK (intake_material_type IN ('none','papers_folder','research_db_reference')),
  papers_or_report_folder TEXT,
  materials_delivery_note TEXT,
  reference_industry_in_research_db TEXT,
  evidence_policy TEXT NOT NULL DEFAULT 'balanced' CHECK (evidence_policy IN ('freshness_first','balanced','accuracy_first')),
  time_window_json TEXT NOT NULL DEFAULT '{}',
  research_scope_json TEXT NOT NULL DEFAULT '{}',
  special_constraints_json TEXT NOT NULL DEFAULT '{}',
  field_origin_json TEXT NOT NULL DEFAULT '{}',
  default_accepted_json TEXT NOT NULL DEFAULT '{}',
  parsed_intake_json TEXT NOT NULL DEFAULT '{}',
  validation_issue_json TEXT NOT NULL DEFAULT '[]',
  raw_intake_text TEXT,
  raw_payload_json TEXT,
  intake_contract_version TEXT NOT NULL,
  evidence_policy_version TEXT NOT NULL,
  early_signal_rule_version TEXT NOT NULL,
  intake_contract_hash TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY(run_id) REFERENCES opportunity_run(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS opportunity_run_stats (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id INTEGER NOT NULL UNIQUE,
  source_count INTEGER NOT NULL DEFAULT 0,
  independent_source_count INTEGER NOT NULL DEFAULT 0,
  candidate_count INTEGER NOT NULL DEFAULT 0,
  canonical_entity_count INTEGER NOT NULL DEFAULT 0,
  scored_entity_count INTEGER NOT NULL DEFAULT 0,
  open_p0_count INTEGER NOT NULL DEFAULT 0,
  open_p1_count INTEGER NOT NULL DEFAULT 0,
  supplement_open_count INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY(run_id) REFERENCES opportunity_run(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS opportunity_search_plan (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id INTEGER NOT NULL,
  plan_name TEXT NOT NULL,
  search_axes_json TEXT NOT NULL,
  source_groups_json TEXT NOT NULL,
  search_protocol_version TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY(run_id) REFERENCES opportunity_run(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS opportunity_search_task (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id INTEGER NOT NULL,
  search_plan_id INTEGER NOT NULL,
  axis_key TEXT NOT NULL,
  source_group TEXT NOT NULL,
  source_channel TEXT NOT NULL DEFAULT 'legacy_unspecified'
    CHECK(source_channel IN ('report','web','legacy_unspecified')),
  query_text TEXT,
  search_task_status TEXT NOT NULL DEFAULT 'planned' CHECK (search_task_status IN ('planned','running','completed','skipped_not_applicable','failed','cancelled','blocked')),
  planned_at TEXT NOT NULL DEFAULT (datetime('now')),
  started_at TEXT,
  completed_at TEXT,
  result_count INTEGER NOT NULL DEFAULT 0,
  included_count INTEGER NOT NULL DEFAULT 0,
  rejection_reason TEXT,
  failure_reason TEXT,
  FOREIGN KEY(run_id) REFERENCES opportunity_run(id) ON DELETE CASCADE,
  FOREIGN KEY(search_plan_id) REFERENCES opportunity_search_plan(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS opportunity_search_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id INTEGER NOT NULL,
  search_task_id INTEGER,
  source_channel TEXT NOT NULL DEFAULT 'legacy_unspecified'
    CHECK(source_channel IN ('report','web','legacy_unspecified')),
  search_log_decision TEXT NOT NULL CHECK (search_log_decision IN ('identified','screened','included','excluded','duplicate','paywalled','unreachable','not_applicable')),
  title TEXT,
  url TEXT,
  publisher TEXT,
  reason TEXT,
  evidence_ref_uri TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY(run_id) REFERENCES opportunity_run(id) ON DELETE CASCADE,
  FOREIGN KEY(search_task_id) REFERENCES opportunity_search_task(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS opportunity_source_cluster (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id INTEGER NOT NULL,
  cluster_key TEXT NOT NULL,
  cluster_label TEXT,
  independence_rationale TEXT,
  confidence REAL NOT NULL DEFAULT 0.5 CHECK (confidence >= 0 AND confidence <= 1),
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE(run_id, cluster_key),
  FOREIGN KEY(run_id) REFERENCES opportunity_run(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS opportunity_source_discovery (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id INTEGER NOT NULL,
  search_task_id INTEGER,
  source_cluster_id INTEGER,
  source_channel TEXT NOT NULL DEFAULT 'legacy_unspecified'
    CHECK(source_channel IN ('report','web','legacy_unspecified')),
  title TEXT NOT NULL,
  url TEXT,
  publisher TEXT,
  discovered_at TEXT NOT NULL DEFAULT (datetime('now')),
  screen_decision TEXT CHECK (screen_decision IS NULL OR screen_decision IN ('identified','screened','included','excluded','duplicate','paywalled','unreachable','not_applicable')),
  screen_reason TEXT,
  policy_evidence_role TEXT NOT NULL DEFAULT 'needs_review' CHECK (policy_evidence_role IN ('core_evidence','early_signal_candidate','reference_only','needs_review','rejected')),
  policy_gate_verdict TEXT NOT NULL DEFAULT 'needs_review' CHECK (policy_gate_verdict IN ('pass_core','pass_early_signal','pass_reference','needs_review','blocked','rejected')),
  scoring_eligibility TEXT NOT NULL DEFAULT 'reference_only' CHECK (scoring_eligibility IN ('core_eligible','early_signal_only','reference_only','blocked_by_conflict','rejected')),
  FOREIGN KEY(run_id) REFERENCES opportunity_run(id) ON DELETE CASCADE,
  FOREIGN KEY(search_task_id) REFERENCES opportunity_search_task(id) ON DELETE SET NULL,
  FOREIGN KEY(source_cluster_id) REFERENCES opportunity_source_cluster(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS opportunity_source (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id INTEGER NOT NULL,
  source_cluster_id INTEGER,
  source_channel TEXT NOT NULL DEFAULT 'legacy_unspecified'
    CHECK(source_channel IN ('report','web','legacy_unspecified')),
  title TEXT NOT NULL,
  source_tier TEXT NOT NULL DEFAULT 'unknown' CHECK (source_tier IN ('S','A','B','C','D','unknown')),
  source_review_status TEXT NOT NULL DEFAULT 'pending' CHECK (source_review_status IN ('pending','pass','pass_with_note','weak_source_only','duplicate','paywalled','stale','conflict','reject')),
  title_zh TEXT,
  publisher TEXT,
  author TEXT,
  publish_date TEXT,
  event_date TEXT,
  fetch_date TEXT,
  url TEXT,
  local_path TEXT,
  local_locator TEXT,
  content_hash TEXT,
  excerpt TEXT,
  excerpt_zh TEXT,
  language TEXT,
  evidence_ref_uri TEXT,
  policy_evidence_role TEXT NOT NULL DEFAULT 'core_evidence' CHECK (policy_evidence_role IN ('core_evidence','early_signal_candidate','reference_only','needs_review','rejected')),
  policy_gate_verdict TEXT NOT NULL DEFAULT 'pass_core' CHECK (policy_gate_verdict IN ('pass_core','pass_early_signal','pass_reference','needs_review','blocked','rejected')),
  scoring_eligibility TEXT NOT NULL DEFAULT 'core_eligible' CHECK (scoring_eligibility IN ('core_eligible','early_signal_only','reference_only','blocked_by_conflict','rejected')),
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY(run_id) REFERENCES opportunity_run(id) ON DELETE CASCADE,
  FOREIGN KEY(source_cluster_id) REFERENCES opportunity_source_cluster(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_opportunity_source_channel
  ON opportunity_source(run_id,source_channel);
CREATE INDEX IF NOT EXISTS idx_opportunity_search_task_channel
  ON opportunity_search_task(run_id,source_channel);

CREATE TABLE IF NOT EXISTS opportunity_entity (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  entity_type TEXT NOT NULL CHECK (entity_type IN ('theme','industry','segment','product_material','process_step','application','customer','company','security','geography')),
  taxonomy_level TEXT NOT NULL CHECK (taxonomy_level IN ('theme','industry','segment','product_material','process_step','application','customer','company','security','geography')),
  canonical_name TEXT NOT NULL,
  display_name TEXT,
  description TEXT,
  parent_entity_id INTEGER,
  external_ref_type TEXT,
  external_ref_id TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE(entity_type, canonical_name),
  FOREIGN KEY(parent_entity_id) REFERENCES opportunity_entity(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS opportunity_score_batch (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id INTEGER NOT NULL,
  score_rule_version TEXT NOT NULL,
  score_batch_status TEXT NOT NULL DEFAULT 'draft' CHECK (score_batch_status IN ('draft','completed','failed','superseded','replayed')),
  is_current INTEGER NOT NULL DEFAULT 0 CHECK (is_current IN (0,1)),
  input_manifest_json TEXT,
  input_manifest_hash TEXT,
  source_manifest_hash TEXT,
  factor_manifest_hash TEXT,
  rule_manifest_hash TEXT,
  supersedes_batch_id INTEGER,
  superseded_by_batch_id INTEGER,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  completed_at TEXT,
  failure_reason TEXT,
  FOREIGN KEY(run_id) REFERENCES opportunity_run(id) ON DELETE CASCADE,
  FOREIGN KEY(supersedes_batch_id) REFERENCES opportunity_score_batch(id) ON DELETE SET NULL,
  FOREIGN KEY(superseded_by_batch_id) REFERENCES opportunity_score_batch(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS opportunity_entity_maturation (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id INTEGER NOT NULL,
  entity_id INTEGER NOT NULL,
  maturation_status TEXT NOT NULL CHECK (maturation_status IN ('seed','evidence_supported','scoring_ready','scoring_limited','research_only','scored','review_ready','published','blocked','superseded','rejected','archived')),
  readiness_score REAL CHECK (readiness_score IS NULL OR (readiness_score >= 0 AND readiness_score <= 1)),
  readiness_reason TEXT,
  evidence_ref_uri TEXT,
  score_batch_id INTEGER,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE(run_id, entity_id),
  FOREIGN KEY(run_id) REFERENCES opportunity_run(id) ON DELETE CASCADE,
  FOREIGN KEY(entity_id) REFERENCES opportunity_entity(id) ON DELETE CASCADE,
  FOREIGN KEY(score_batch_id) REFERENCES opportunity_score_batch(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS opportunity_entity_research_profile (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id INTEGER NOT NULL,
  entity_id INTEGER NOT NULL,
  entity_research_mode TEXT NOT NULL DEFAULT 'market_linked' CHECK (entity_research_mode IN ('market_linked','theory_research')),
  research_depth_status TEXT NOT NULL DEFAULT 'complete' CHECK (research_depth_status IN ('draft','in_progress','complete','needs_more_sources','blocked')),
  research_question TEXT NOT NULL,
  research_scope TEXT,
  methodology_note TEXT,
  literature_review_markdown TEXT NOT NULL,
  data_collection_markdown TEXT,
  analysis_markdown TEXT NOT NULL,
  answer_markdown TEXT NOT NULL,
  conclusion_markdown TEXT NOT NULL,
  limitations_markdown TEXT,
  evidence_ref_uri_list_json TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE(run_id, entity_id),
  FOREIGN KEY(run_id) REFERENCES opportunity_run(id) ON DELETE CASCADE,
  FOREIGN KEY(entity_id) REFERENCES opportunity_entity(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS opportunity_research_data_point (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id INTEGER NOT NULL,
  entity_id INTEGER NOT NULL,
  source_id INTEGER,
  data_point_title TEXT NOT NULL,
  research_category TEXT NOT NULL,
  metric TEXT NOT NULL,
  period TEXT,
  as_of_date TEXT,
  value_num REAL,
  value_text TEXT,
  unit TEXT,
  source_excerpt TEXT NOT NULL,
  source_excerpt_zh TEXT,
  source_context TEXT,
  interpretation TEXT NOT NULL,
  research_use TEXT NOT NULL,
  limitations TEXT,
  evidence_ref_uri TEXT NOT NULL,
  sort_order INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  CHECK ((period IS NOT NULL AND period <> '') OR (as_of_date IS NOT NULL AND as_of_date <> '')),
  CHECK (value_num IS NOT NULL OR (value_text IS NOT NULL AND value_text <> '')),
  FOREIGN KEY(run_id) REFERENCES opportunity_run(id) ON DELETE CASCADE,
  FOREIGN KEY(entity_id) REFERENCES opportunity_entity(id) ON DELETE CASCADE,
  FOREIGN KEY(source_id) REFERENCES opportunity_source(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS opportunity_candidate_entity (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id INTEGER NOT NULL,
  candidate_stage TEXT NOT NULL CHECK (candidate_stage IN ('discovered','long_list','candidate','shortlist','scoring_ready','research_only','rejected','duplicate','out_of_scope','merged_to_entity')),
  name TEXT NOT NULL,
  entity_type_hint TEXT,
  entity_id INTEGER,
  parent_candidate_id INTEGER,
  preliminary_research_priority_label TEXT CHECK (preliminary_research_priority_label IS NULL OR preliminary_research_priority_label IN ('high_priority_for_scoring','medium_priority_for_followup','low_priority_watch','research_only_insufficient_data','research_only_literature_review_complete','reject_or_out_of_scope')),
  source_count INTEGER NOT NULL DEFAULT 0,
  independent_source_count INTEGER NOT NULL DEFAULT 0,
  reason TEXT,
  evidence_ref_uri TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY(run_id) REFERENCES opportunity_run(id) ON DELETE CASCADE,
  FOREIGN KEY(entity_id) REFERENCES opportunity_entity(id) ON DELETE SET NULL,
  FOREIGN KEY(parent_candidate_id) REFERENCES opportunity_candidate_entity(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS opportunity_entity_mapping (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id INTEGER NOT NULL,
  source_entity_id INTEGER NOT NULL,
  target_entity_id INTEGER NOT NULL,
  mapping_type TEXT NOT NULL CHECK (mapping_type IN ('direct_mass_supply','direct_small_batch','qualified_testing','indirect_supply','upstream_raw_material','downstream_customer_link','global_peer','theme_mapping_only','unverified','not_applicable')),
  relationship_status TEXT NOT NULL DEFAULT 'unknown_pending_review' CHECK (relationship_status IN ('verified','probable','weak','rejected','not_applicable','unknown_pending_review')),
  review_status TEXT NOT NULL DEFAULT 'pending' CHECK (review_status IN ('pending','in_review','approved','rejected','resolved','waived','reopened','not_required')),
  evidence_ref_uri TEXT,
  rationale TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY(run_id) REFERENCES opportunity_run(id) ON DELETE CASCADE,
  FOREIGN KEY(source_entity_id) REFERENCES opportunity_entity(id) ON DELETE CASCADE,
  FOREIGN KEY(target_entity_id) REFERENCES opportunity_entity(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS opportunity_claim_evidence (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id INTEGER NOT NULL,
  entity_id INTEGER,
  candidate_id INTEGER,
  source_id INTEGER NOT NULL,
  claim_type TEXT NOT NULL,
  claim_text TEXT NOT NULL,
  source_excerpt TEXT,
  source_excerpt_zh TEXT,
  claim_evidence_status TEXT NOT NULL CHECK (claim_evidence_status IN ('extracted','verified','needs_review','weak_source_only','conflict','rejected','superseded','not_applicable')),
  claim_next_action TEXT CHECK (claim_next_action IS NULL OR claim_next_action IN ('route_to_data_point','route_to_event','route_to_forecast_overlay','route_to_supplement_request','use_as_background','reject','no_action')),
  support_status TEXT NOT NULL DEFAULT 'supported' CHECK (support_status IN ('supported','partially_supported','derived','forecast','weak','unsupported','conflict','not_applicable')),
  evidence_ref_uri TEXT,
  policy_evidence_role TEXT NOT NULL DEFAULT 'core_evidence' CHECK (policy_evidence_role IN ('core_evidence','early_signal_candidate','reference_only','needs_review','rejected')),
  policy_gate_verdict TEXT NOT NULL DEFAULT 'pass_core' CHECK (policy_gate_verdict IN ('pass_core','pass_early_signal','pass_reference','needs_review','blocked','rejected')),
  scoring_eligibility TEXT NOT NULL DEFAULT 'core_eligible' CHECK (scoring_eligibility IN ('core_eligible','early_signal_only','reference_only','blocked_by_conflict','rejected')),
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY(run_id) REFERENCES opportunity_run(id) ON DELETE CASCADE,
  FOREIGN KEY(entity_id) REFERENCES opportunity_entity(id) ON DELETE SET NULL,
  FOREIGN KEY(candidate_id) REFERENCES opportunity_candidate_entity(id) ON DELETE SET NULL,
  FOREIGN KEY(source_id) REFERENCES opportunity_source(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS opportunity_data_point (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id INTEGER NOT NULL,
  entity_id INTEGER,
  source_id INTEGER NOT NULL,
  metric TEXT NOT NULL,
  period TEXT,
  as_of_date TEXT,
  value_num REAL,
  value_text TEXT,
  unit TEXT NOT NULL,
  source_excerpt TEXT NOT NULL,
  source_excerpt_zh TEXT,
  value_status TEXT NOT NULL CHECK (value_status IN ('available','available_with_grade_unknown','available_text_only','calculated','stale_but_usable','not_disclosed_with_source','not_found_after_search','weak_source_only','stale_only','conflict_unresolved','unsupported','rejected','not_applicable')),
  calculation_review_status TEXT NOT NULL DEFAULT 'pending' CHECK (calculation_review_status IN ('pending','pass','warning','fail','not_applicable')),
  extraction_method TEXT,
  evidence_ref_uri TEXT NOT NULL,
  policy_evidence_role TEXT NOT NULL DEFAULT 'core_evidence' CHECK (policy_evidence_role IN ('core_evidence','early_signal_candidate','reference_only','needs_review','rejected')),
  policy_gate_verdict TEXT NOT NULL DEFAULT 'pass_core' CHECK (policy_gate_verdict IN ('pass_core','pass_early_signal','pass_reference','needs_review','blocked','rejected')),
  scoring_eligibility TEXT NOT NULL DEFAULT 'core_eligible' CHECK (scoring_eligibility IN ('core_eligible','early_signal_only','reference_only','blocked_by_conflict','rejected')),
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  CHECK ((period IS NOT NULL AND period <> '') OR (as_of_date IS NOT NULL AND as_of_date <> '')),
  CHECK (value_num IS NOT NULL OR (value_text IS NOT NULL AND value_text <> '')),
  FOREIGN KEY(run_id) REFERENCES opportunity_run(id) ON DELETE CASCADE,
  FOREIGN KEY(entity_id) REFERENCES opportunity_entity(id) ON DELETE SET NULL,
  FOREIGN KEY(source_id) REFERENCES opportunity_source(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS opportunity_ab_reference_link (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id INTEGER NOT NULL,
  local_object_type TEXT NOT NULL,
  local_object_id INTEGER NOT NULL,
  evidence_ref_uri TEXT NOT NULL,
  ab_reference_usage TEXT NOT NULL CHECK (ab_reference_usage IN ('seed','supporting','stale_reference','market_reference','sentiment_reference','rejected')),
  ab_snapshot_at TEXT NOT NULL,
  ab_reference_freshness_days INTEGER,
  rationale TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE(run_id, local_object_type, local_object_id, evidence_ref_uri),
  FOREIGN KEY(run_id) REFERENCES opportunity_run(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS opportunity_factor_readiness (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id INTEGER NOT NULL,
  entity_id INTEGER NOT NULL,
  factor_code TEXT NOT NULL,
  factor_readiness_status TEXT NOT NULL CHECK (factor_readiness_status IN ('ready','limited','reference_only','missing','conflict_blocked','not_applicable')),
  coverage REAL NOT NULL DEFAULT 0 CHECK (coverage >= 0 AND coverage <= 1),
  confidence REAL NOT NULL DEFAULT 0 CHECK (confidence >= 0 AND confidence <= 1),
  missing_reason TEXT,
  evidence_ref_uri_list_json TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE(run_id, entity_id, factor_code),
  FOREIGN KEY(run_id) REFERENCES opportunity_run(id) ON DELETE CASCADE,
  FOREIGN KEY(entity_id) REFERENCES opportunity_entity(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS opportunity_metric_slot (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id INTEGER NOT NULL,
  entity_id INTEGER NOT NULL,
  factor_code TEXT NOT NULL,
  slot_key TEXT NOT NULL,
  slot_label TEXT,
  metric_name TEXT,
  metric_slot_status TEXT NOT NULL CHECK (metric_slot_status IN ('not_started','candidate','accepted','weak_source_only','stale_only','conflict_unresolved','not_applicable','rejected','used_in_factor')),
  value_status TEXT NOT NULL CHECK (value_status IN ('available','available_with_grade_unknown','available_text_only','calculated','stale_but_usable','not_disclosed_with_source','not_found_after_search','weak_source_only','stale_only','conflict_unresolved','unsupported','rejected','not_applicable')),
  slot_weight REAL NOT NULL DEFAULT 1,
  slot_score REAL CHECK (slot_score IS NULL OR (slot_score >= 0 AND slot_score <= 100)),
  slot_confidence REAL NOT NULL DEFAULT 0 CHECK (slot_confidence >= 0 AND slot_confidence <= 1),
  unit TEXT,
  period TEXT,
  as_of_date TEXT,
  selected_data_point_id INTEGER,
  evidence_ref_uri TEXT,
  policy_evidence_role TEXT NOT NULL DEFAULT 'core_evidence' CHECK (policy_evidence_role IN ('core_evidence','early_signal_candidate','reference_only','needs_review','rejected')),
  policy_gate_verdict TEXT NOT NULL DEFAULT 'pass_core' CHECK (policy_gate_verdict IN ('pass_core','pass_early_signal','pass_reference','needs_review','blocked','rejected')),
  scoring_eligibility TEXT NOT NULL DEFAULT 'core_eligible' CHECK (scoring_eligibility IN ('core_eligible','early_signal_only','reference_only','blocked_by_conflict','rejected')),
  notes TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE(run_id, entity_id, factor_code, slot_key),
  FOREIGN KEY(run_id) REFERENCES opportunity_run(id) ON DELETE CASCADE,
  FOREIGN KEY(entity_id) REFERENCES opportunity_entity(id) ON DELETE CASCADE,
  FOREIGN KEY(selected_data_point_id) REFERENCES opportunity_data_point(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS opportunity_slot_data_point_link (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  slot_id INTEGER NOT NULL,
  data_point_id INTEGER,
  claim_id INTEGER,
  link_role TEXT NOT NULL DEFAULT 'selected',
  evidence_ref_uri TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY(slot_id) REFERENCES opportunity_metric_slot(id) ON DELETE CASCADE,
  FOREIGN KEY(data_point_id) REFERENCES opportunity_data_point(id) ON DELETE SET NULL,
  FOREIGN KEY(claim_id) REFERENCES opportunity_claim_evidence(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS opportunity_factor_score (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id INTEGER NOT NULL,
  score_batch_id INTEGER NOT NULL,
  entity_id INTEGER NOT NULL,
  factor_code TEXT NOT NULL,
  score_status TEXT NOT NULL CHECK (score_status IN ('complete','insufficient_evidence','blocked','not_applicable','superseded','failed')),
  score_raw REAL,
  score_adjusted REAL,
  coverage REAL NOT NULL DEFAULT 0,
  confidence REAL NOT NULL DEFAULT 0,
  coverage_multiplier REAL NOT NULL DEFAULT 0,
  confidence_multiplier REAL NOT NULL DEFAULT 0,
  audit_multiplier REAL NOT NULL DEFAULT 1,
  reliability_multiplier REAL NOT NULL DEFAULT 0,
  factor_trace_json TEXT NOT NULL,
  evidence_ref_uri_list_json TEXT,
  is_current INTEGER NOT NULL DEFAULT 0 CHECK (is_current IN (0,1)),
  supersedes_factor_score_id INTEGER,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE(score_batch_id, entity_id, factor_code),
  FOREIGN KEY(run_id) REFERENCES opportunity_run(id) ON DELETE CASCADE,
  FOREIGN KEY(score_batch_id) REFERENCES opportunity_score_batch(id) ON DELETE CASCADE,
  FOREIGN KEY(entity_id) REFERENCES opportunity_entity(id) ON DELETE CASCADE,
  FOREIGN KEY(supersedes_factor_score_id) REFERENCES opportunity_factor_score(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS opportunity_composite_score (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id INTEGER NOT NULL,
  score_batch_id INTEGER NOT NULL,
  entity_id INTEGER NOT NULL,
  score_status TEXT NOT NULL CHECK (score_status IN ('complete','insufficient_evidence','blocked','not_applicable','superseded','failed')),
  score_grade TEXT CHECK (score_grade IS NULL OR score_grade IN ('S','A','B','C','D','F','unrated')),
  rating_status TEXT NOT NULL CHECK (rating_status IN ('valid','review_required','blocked','superseded','not_applicable','unrated_insufficient_evidence')),
  score_quality_label TEXT NOT NULL CHECK (score_quality_label IN ('high_confidence','medium_confidence','provisional','unrated_insufficient_evidence','review_required')),
  score_point REAL,
  score_band_low REAL,
  score_band_high REAL,
  band_method TEXT,
  band_reason TEXT,
  coverage REAL NOT NULL DEFAULT 0,
  confidence REAL NOT NULL DEFAULT 0,
  audit_multiplier REAL NOT NULL DEFAULT 1,
  composite_trace_json TEXT NOT NULL,
  evidence_ref_uri_list_json TEXT,
  research_bias_label TEXT CHECK (research_bias_label IS NULL OR research_bias_label IN ('strong_positive_research','positive_research','neutral_watch','negative_watch','avoid_or_reject','unrated_insufficient_evidence')),
  is_current INTEGER NOT NULL DEFAULT 0 CHECK (is_current IN (0,1)),
  supersedes_composite_score_id INTEGER,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE(score_batch_id, entity_id),
  FOREIGN KEY(run_id) REFERENCES opportunity_run(id) ON DELETE CASCADE,
  FOREIGN KEY(score_batch_id) REFERENCES opportunity_score_batch(id) ON DELETE CASCADE,
  FOREIGN KEY(entity_id) REFERENCES opportunity_entity(id) ON DELETE CASCADE,
  FOREIGN KEY(supersedes_composite_score_id) REFERENCES opportunity_composite_score(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS opportunity_early_signal_aggregate (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id INTEGER NOT NULL,
  entity_id INTEGER NOT NULL,
  early_signal_rule_version TEXT NOT NULL,
  evidence_policy TEXT NOT NULL CHECK (evidence_policy IN ('freshness_first','balanced','accuracy_first')),
  early_signal_score REAL CHECK (early_signal_score IS NULL OR (early_signal_score >= 0 AND early_signal_score <= 100)),
  early_signal_strength_label TEXT NOT NULL DEFAULT 'not_applicable' CHECK (early_signal_strength_label IN ('strong','medium','weak','noise','not_applicable')),
  research_priority_score REAL CHECK (research_priority_score IS NULL OR (research_priority_score >= 0 AND research_priority_score <= 100)),
  research_priority_label TEXT,
  source_count INTEGER NOT NULL DEFAULT 0,
  independent_source_count INTEGER NOT NULL DEFAULT 0,
  verification_debt_count INTEGER NOT NULL DEFAULT 0,
  core_score_snapshot REAL,
  core_score_changed_by_overlay INTEGER NOT NULL DEFAULT 0 CHECK (core_score_changed_by_overlay=0),
  evidence_ref_uri_list_json TEXT NOT NULL DEFAULT '[]',
  excluded_from_core_reason TEXT NOT NULL,
  aggregate_trace_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE(run_id, entity_id, early_signal_rule_version),
  FOREIGN KEY(run_id) REFERENCES opportunity_run(id) ON DELETE CASCADE,
  FOREIGN KEY(entity_id) REFERENCES opportunity_entity(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS opportunity_event_ledger (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id INTEGER NOT NULL,
  entity_id INTEGER,
  event_scope TEXT NOT NULL DEFAULT 'business' CHECK (event_scope IN ('business','system_provenance')),
  event_type TEXT CHECK (event_type IS NULL OR event_type IN ('price_revision','capacity_change','supply_disruption','policy_control','customer_validation','long_term_contract','customer_substitution_or_cut','guidance_or_analyst_revision','accounting_impairment','clarification_denial','market_reaction','customs_trade_signal','other')),
  system_event_type TEXT CHECK (system_event_type IS NULL OR system_event_type IN ('run_state_transition','search_task_status','source_screening_decision','entity_promotion','score_batch_completed','audit_issue_status_change','supplement_request_status_change','export_status_change','replay_result','human_review_decision','other_system')),
  event_category TEXT CHECK (event_category IS NULL OR event_category IN ('fundamental','market','risk','forecast_overlay','reference_only','veto_candidate')),
  event_direction TEXT NOT NULL CHECK (event_direction IN ('positive','negative','neutral','mixed','unknown','not_applicable')),
  event_title TEXT NOT NULL,
  event_summary TEXT,
  event_date TEXT,
  dedupe_key TEXT,
  confidence REAL NOT NULL DEFAULT 0.5 CHECK (confidence >= 0 AND confidence <= 1),
  score_effect TEXT NOT NULL DEFAULT 'none' CHECK (score_effect IN ('none','mapped_only','factor_delta_small','factor_delta_medium','factor_delta_large','veto_candidate','forecast_overlay','market_only','reference_only')),
  official_confirmation_status TEXT DEFAULT 'unknown' CHECK (official_confirmation_status IN ('official_confirmed','official_denied','media_reported','multi_source_reported','single_source_reported','rumor_unconfirmed','not_applicable','unknown')),
  evidence_ref_uri TEXT,
  evidence_ref_uri_list_json TEXT,
  event_payload_json TEXT,
  policy_evidence_role TEXT NOT NULL DEFAULT 'reference_only' CHECK (policy_evidence_role IN ('core_evidence','early_signal_candidate','reference_only','needs_review','rejected')),
  policy_gate_verdict TEXT NOT NULL DEFAULT 'pass_reference' CHECK (policy_gate_verdict IN ('pass_core','pass_early_signal','pass_reference','needs_review','blocked','rejected')),
  scoring_eligibility TEXT NOT NULL DEFAULT 'reference_only' CHECK (scoring_eligibility IN ('core_eligible','early_signal_only','reference_only','blocked_by_conflict','rejected')),
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  CHECK ((event_scope='business' AND event_type IS NOT NULL AND event_category IS NOT NULL)
      OR (event_scope='system_provenance' AND system_event_type IS NOT NULL AND event_direction='not_applicable')),
  FOREIGN KEY(run_id) REFERENCES opportunity_run(id) ON DELETE CASCADE,
  FOREIGN KEY(entity_id) REFERENCES opportunity_entity(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS opportunity_audit_issue (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id INTEGER NOT NULL,
  entity_id INTEGER,
  affected_uri TEXT NOT NULL,
  audit_issue_type TEXT NOT NULL CHECK (audit_issue_type IN ('source_missing','source_rejected','source_conflict','official_vs_media_conflict','calculation_error','unit_conversion_error','period_conflict','geo_scope_conflict','capacity_definition_conflict','supplier_count_definition_conflict','duplicate_event_score','stale_data','low_coverage','low_confidence','ai_inference_only','unsupported_claim','theme_mapping_only','forecast_as_fact','cross_db_reference_stale','replay_not_reproducible','policy_gate_violation','weak_signal_core_leak','insufficient_independent_confirmation')),
  audit_severity TEXT NOT NULL CHECK (audit_severity IN ('p0','p1','p2','p3')),
  audit_issue_status TEXT NOT NULL DEFAULT 'open' CHECK (audit_issue_status IN ('open','in_review','resolved','waived','reopened')),
  issue_title TEXT NOT NULL,
  issue_detail TEXT,
  evidence_ref_uri TEXT,
  evidence_ref_uri_list_json TEXT,
  reviewer TEXT,
  waiver_reason TEXT,
  resolved_at TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY(run_id) REFERENCES opportunity_run(id) ON DELETE CASCADE,
  FOREIGN KEY(entity_id) REFERENCES opportunity_entity(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS opportunity_veto_status (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id INTEGER NOT NULL,
  entity_id INTEGER NOT NULL,
  score_batch_id INTEGER NOT NULL,
  composite_score_id INTEGER,
  veto_code TEXT NOT NULL CHECK (veto_code IN ('veto.tech_substitution','veto.capacity_flood','veto.imbalance_too_short','veto.customer_backup_selfdev','veto.policy_market_shutdown')),
  veto_status TEXT NOT NULL CHECK (veto_status IN ('safe','unknown','warning','triggered','not_applicable')),
  veto_reason TEXT,
  evidence_ref_uri TEXT,
  evidence_ref_uri_list_json TEXT,
  source_event_id INTEGER,
  audit_issue_id INTEGER,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE(run_id, entity_id, score_batch_id, veto_code),
  FOREIGN KEY(run_id) REFERENCES opportunity_run(id) ON DELETE CASCADE,
  FOREIGN KEY(entity_id) REFERENCES opportunity_entity(id) ON DELETE CASCADE,
  FOREIGN KEY(score_batch_id) REFERENCES opportunity_score_batch(id) ON DELETE CASCADE,
  FOREIGN KEY(composite_score_id) REFERENCES opportunity_composite_score(id) ON DELETE SET NULL,
  FOREIGN KEY(source_event_id) REFERENCES opportunity_event_ledger(id) ON DELETE SET NULL,
  FOREIGN KEY(audit_issue_id) REFERENCES opportunity_audit_issue(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS opportunity_market_reaction (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id INTEGER NOT NULL,
  entity_id INTEGER NOT NULL,
  composite_score_id INTEGER,
  market_reflection_state TEXT NOT NULL CHECK (market_reflection_state IN ('unnoticed','early_reaction','recognized','crowded','overheated','post_hype_reset','market_data_missing','not_applicable')),
  benchmark_region TEXT NOT NULL DEFAULT 'unknown' CHECK (benchmark_region IN ('CN_A','HK','US','JP','KR','proxy','not_applicable','unknown')),
  direct_security_ref TEXT,
  proxy_entity_id INTEGER,
  proxy_mapping_status TEXT NOT NULL DEFAULT 'not_required' CHECK (proxy_mapping_status IN ('not_required','evidence_supported','insufficient_evidence','not_applicable','rejected')),
  proxy_reason TEXT,
  proxy_evidence_ref_uri TEXT,
  reaction_multiplier REAL NOT NULL DEFAULT 1,
  evidence_ref_uri TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY(run_id) REFERENCES opportunity_run(id) ON DELETE CASCADE,
  FOREIGN KEY(entity_id) REFERENCES opportunity_entity(id) ON DELETE CASCADE,
  FOREIGN KEY(proxy_entity_id) REFERENCES opportunity_entity(id) ON DELETE SET NULL,
  FOREIGN KEY(composite_score_id) REFERENCES opportunity_composite_score(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS opportunity_entity_investment_target (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id INTEGER NOT NULL,
  entity_id INTEGER NOT NULL,
  target_name TEXT NOT NULL,
  ticker TEXT,
  market TEXT,
  target_type TEXT NOT NULL CHECK (target_type IN ('company','security','etf','futures_contract','spread','basket','external_watch')),
  company_id INTEGER,
  target_url TEXT,
  exposure_rationale TEXT NOT NULL,
  evidence_ref_uri TEXT,
  research_action TEXT NOT NULL,
  investment_view TEXT NOT NULL,
  risk_note TEXT NOT NULL,
  target_priority TEXT,
  target_quality_label TEXT,
  relative_preference TEXT,
  confirmed_scenario_action TEXT,
  falsified_scenario_action TEXT,
  target_profile_markdown TEXT,
  target_deep_research_markdown TEXT,
  entity_relation_markdown TEXT,
  parent_research_relation_markdown TEXT,
  conditional_investment_recommendation TEXT,
  financial_data_status TEXT,
  link_status TEXT NOT NULL DEFAULT 'linked' CHECK (link_status IN ('linked','external_only','needs_company_profile','needs_evidence','not_applicable')),
  support_status TEXT NOT NULL DEFAULT 'partially_supported' CHECK (support_status IN ('supported','partially_supported','weak','not_applicable')),
  sort_order INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY(run_id) REFERENCES opportunity_run(id) ON DELETE CASCADE,
  FOREIGN KEY(entity_id) REFERENCES opportunity_entity(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS opportunity_target_data_point (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id INTEGER NOT NULL,
  entity_id INTEGER NOT NULL,
  target_id INTEGER NOT NULL,
  metric_name TEXT NOT NULL,
  metric_category TEXT NOT NULL,
  period TEXT,
  as_of_date TEXT,
  value_num REAL,
  value_text TEXT,
  unit TEXT,
  source_title TEXT,
  source_title_zh TEXT,
  source_publisher TEXT,
  source_url TEXT,
  source_excerpt TEXT,
  source_excerpt_zh TEXT,
  source_language TEXT,
  evidence_ref_uri TEXT,
  data_quality_label TEXT,
  direction TEXT NOT NULL DEFAULT 'neutral' CHECK (direction IN ('positive','negative','mixed','neutral')),
  credibility_weight REAL NOT NULL DEFAULT 0.5,
  numeric_weight REAL NOT NULL DEFAULT 0.7,
  direction_score REAL NOT NULL DEFAULT 0,
  weighted_contribution REAL NOT NULL DEFAULT 0,
  sort_order INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  CHECK (value_num IS NOT NULL OR (value_text IS NOT NULL AND value_text <> '')),
  FOREIGN KEY(run_id) REFERENCES opportunity_run(id) ON DELETE CASCADE,
  FOREIGN KEY(entity_id) REFERENCES opportunity_entity(id) ON DELETE CASCADE,
  FOREIGN KEY(target_id) REFERENCES opportunity_entity_investment_target(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS opportunity_review_queue (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id INTEGER NOT NULL,
  entity_id INTEGER,
  audit_issue_id INTEGER,
  object_uri TEXT NOT NULL,
  review_status TEXT NOT NULL DEFAULT 'pending' CHECK (review_status IN ('pending','in_review','approved','rejected','resolved','waived','reopened','not_required')),
  review_decision TEXT NOT NULL DEFAULT 'no_decision' CHECK (review_decision IN ('approve','reject','request_revision','waive','resolve','reopen','no_decision')),
  reviewer TEXT,
  reviewer_note TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY(run_id) REFERENCES opportunity_run(id) ON DELETE CASCADE,
  FOREIGN KEY(entity_id) REFERENCES opportunity_entity(id) ON DELETE SET NULL,
  FOREIGN KEY(audit_issue_id) REFERENCES opportunity_audit_issue(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS opportunity_agent_review_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id INTEGER NOT NULL,
  review_round INTEGER NOT NULL,
  reviewer_role TEXT NOT NULL,
  review_verdict TEXT NOT NULL CHECK (review_verdict IN ('GREEN','YELLOW','RED')),
  reconciliation_status TEXT NOT NULL CHECK (reconciliation_status IN ('pending','resolved','deferred_to_user','blocked','not_applicable')),
  findings_json TEXT,
  review_stage TEXT NOT NULL DEFAULT 'unspecified',
  reviewer_id TEXT,
  review_kind TEXT NOT NULL DEFAULT 'legacy' CHECK (review_kind IN ('deterministic','independent','human','legacy')),
  input_artifact_hash TEXT,
  output_artifact_hash TEXT,
  findings_hash TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY(run_id) REFERENCES opportunity_run(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS opportunity_quality_gate_result (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id INTEGER NOT NULL,
  gate_name TEXT NOT NULL,
  gate_verdict TEXT NOT NULL CHECK (gate_verdict IN ('GREEN','YELLOW','RED')),
  findings_json TEXT NOT NULL DEFAULT '[]',
  artifact_ref_json TEXT NOT NULL DEFAULT '[]',
  gate_version TEXT NOT NULL,
  result_hash TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY(run_id) REFERENCES opportunity_run(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS opportunity_supplement_request (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id INTEGER NOT NULL,
  entity_id INTEGER,
  request_title TEXT NOT NULL,
  request_detail TEXT,
  priority TEXT NOT NULL CHECK (priority IN ('p0','p1','p2','p3')),
  blocking_status TEXT NOT NULL CHECK (blocking_status IN ('blocks_scoring','limits_scoring','blocks_publication','non_blocking','unknown_pending_review')),
  review_status TEXT NOT NULL DEFAULT 'pending' CHECK (review_status IN ('pending','in_review','approved','rejected','resolved','waived','reopened','not_required')),
  evidence_ref_uri TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY(run_id) REFERENCES opportunity_run(id) ON DELETE CASCADE,
  FOREIGN KEY(entity_id) REFERENCES opportunity_entity(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS opportunity_handoff_package (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id INTEGER NOT NULL,
  handoff_status TEXT NOT NULL CHECK (handoff_status IN ('draft','research_pack_ready','scoring_ready','scoring_limited','research_only','blocked','superseded')),
  package_json TEXT NOT NULL,
  gap_summary TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY(run_id) REFERENCES opportunity_run(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS opportunity_report_section (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id INTEGER NOT NULL,
  entity_id INTEGER,
  section_key TEXT NOT NULL,
  section_title TEXT NOT NULL,
  body_markdown TEXT NOT NULL,
  support_status TEXT NOT NULL CHECK (support_status IN ('supported','partially_supported','derived','forecast','weak','unsupported','conflict','not_applicable')),
  red_flag_level TEXT NOT NULL DEFAULT 'none' CHECK (red_flag_level IN ('none','yellow','red')),
  flag_derivation_source TEXT NOT NULL DEFAULT 'system' CHECK (flag_derivation_source IN ('system','human_override','system_with_human_override')),
  flag_reason_json TEXT,
  review_status TEXT NOT NULL DEFAULT 'pending' CHECK (review_status IN ('pending','in_review','approved','rejected','resolved','waived','reopened','not_required')),
  evidence_ref_uri_list_json TEXT,
  sort_order INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY(run_id) REFERENCES opportunity_run(id) ON DELETE CASCADE,
  FOREIGN KEY(entity_id) REFERENCES opportunity_entity(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS opportunity_section_evidence_link (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  section_id INTEGER NOT NULL,
  evidence_ref_uri TEXT NOT NULL,
  link_role TEXT NOT NULL DEFAULT 'supports',
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE(section_id, evidence_ref_uri, link_role),
  FOREIGN KEY(section_id) REFERENCES opportunity_report_section(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS opportunity_visual_block (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id INTEGER NOT NULL,
  entity_id INTEGER,
  section_id INTEGER,
  block_key TEXT NOT NULL,
  block_type TEXT NOT NULL,
  title TEXT NOT NULL,
  subtitle TEXT,
  data_json TEXT,
  print_fallback_json TEXT,
  evidence_ref_uri_list_json TEXT NOT NULL,
  support_status TEXT NOT NULL CHECK (support_status IN ('supported','partially_supported','derived','forecast','weak','unsupported','conflict','not_applicable')),
  red_flag_level TEXT NOT NULL DEFAULT 'none' CHECK (red_flag_level IN ('none','yellow','red')),
  empty_state_reason TEXT,
  sort_order INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE(run_id, block_key),
  FOREIGN KEY(run_id) REFERENCES opportunity_run(id) ON DELETE CASCADE,
  FOREIGN KEY(entity_id) REFERENCES opportunity_entity(id) ON DELETE SET NULL,
  FOREIGN KEY(section_id) REFERENCES opportunity_report_section(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS opportunity_visual_evidence_link (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  visual_block_id INTEGER NOT NULL,
  evidence_ref_uri TEXT NOT NULL,
  source_id INTEGER,
  data_point_id INTEGER,
  metric_slot_id INTEGER,
  factor_score_id INTEGER,
  composite_score_id INTEGER,
  event_id INTEGER,
  audit_issue_id INTEGER,
  supplement_request_id INTEGER,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE(visual_block_id, evidence_ref_uri),
  FOREIGN KEY(visual_block_id) REFERENCES opportunity_visual_block(id) ON DELETE CASCADE,
  FOREIGN KEY(source_id) REFERENCES opportunity_source(id) ON DELETE SET NULL,
  FOREIGN KEY(data_point_id) REFERENCES opportunity_data_point(id) ON DELETE SET NULL,
  FOREIGN KEY(metric_slot_id) REFERENCES opportunity_metric_slot(id) ON DELETE SET NULL,
  FOREIGN KEY(factor_score_id) REFERENCES opportunity_factor_score(id) ON DELETE SET NULL,
  FOREIGN KEY(composite_score_id) REFERENCES opportunity_composite_score(id) ON DELETE SET NULL,
  FOREIGN KEY(event_id) REFERENCES opportunity_event_ledger(id) ON DELETE SET NULL,
  FOREIGN KEY(audit_issue_id) REFERENCES opportunity_audit_issue(id) ON DELETE SET NULL,
  FOREIGN KEY(supplement_request_id) REFERENCES opportunity_supplement_request(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS opportunity_navigation_index (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id INTEGER NOT NULL,
  entity_id INTEGER,
  section_id INTEGER,
  nav_key TEXT NOT NULL,
  label TEXT NOT NULL,
  href TEXT NOT NULL,
  sort_order INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY(run_id) REFERENCES opportunity_run(id) ON DELETE CASCADE,
  FOREIGN KEY(entity_id) REFERENCES opportunity_entity(id) ON DELETE SET NULL,
  FOREIGN KEY(section_id) REFERENCES opportunity_report_section(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS opportunity_export_job (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id INTEGER NOT NULL,
  score_batch_id INTEGER,
  export_type TEXT NOT NULL DEFAULT 'pdf' CHECK (export_type IN ('pdf','html_snapshot','artifact_manifest')),
  export_scope TEXT NOT NULL DEFAULT 'run_report' CHECK (export_scope IN ('run_report','entity_lens','audit_appendix','full_package')),
  export_status TEXT NOT NULL CHECK (export_status IN ('queued','rendering_html','rendering_assets','rendering_pdf','completed','failed','cancelled','expired')),
  requested_by TEXT,
  artifact_dir TEXT,
  html_snapshot_path TEXT,
  pdf_path TEXT,
  manifest_path TEXT,
  export_manifest_json TEXT,
  error_message TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now')),
  completed_at TEXT,
  FOREIGN KEY(run_id) REFERENCES opportunity_run(id) ON DELETE CASCADE,
  FOREIGN KEY(score_batch_id) REFERENCES opportunity_score_batch(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS opportunity_state_transition (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id INTEGER NOT NULL,
  object_type TEXT NOT NULL,
  object_id INTEGER NOT NULL,
  from_status TEXT,
  to_status TEXT NOT NULL,
  transition_reason TEXT,
  evidence_ref_uri TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY(run_id) REFERENCES opportunity_run(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS opportunity_score_replay_record (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id INTEGER NOT NULL,
  entity_id INTEGER,
  score_batch_id INTEGER,
  composite_score_id INTEGER,
  replay_level TEXT NOT NULL,
  replay_status TEXT NOT NULL CHECK (replay_status IN ('pending','passed','failed','not_applicable')),
  input_manifest_hash TEXT,
  factor_manifest_hash TEXT,
  source_manifest_hash TEXT,
  rule_manifest_hash TEXT,
  result_hash TEXT,
  replay_detail_json TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY(run_id) REFERENCES opportunity_run(id) ON DELETE CASCADE,
  FOREIGN KEY(entity_id) REFERENCES opportunity_entity(id) ON DELETE SET NULL,
  FOREIGN KEY(score_batch_id) REFERENCES opportunity_score_batch(id) ON DELETE SET NULL,
  FOREIGN KEY(composite_score_id) REFERENCES opportunity_composite_score(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_opp_run_status ON opportunity_run(run_status, run_readiness_status);
CREATE INDEX IF NOT EXISTS idx_opp_intake_run ON opportunity_intake_contract(run_id);
CREATE INDEX IF NOT EXISTS idx_opp_run_stats_run ON opportunity_run_stats(run_id);
CREATE INDEX IF NOT EXISTS idx_opp_search_log_run_task ON opportunity_search_log(run_id, search_task_id);
CREATE INDEX IF NOT EXISTS idx_opp_entity_type_name ON opportunity_entity(entity_type, canonical_name);
CREATE INDEX IF NOT EXISTS idx_opp_entity_maturation_run ON opportunity_entity_maturation(run_id, maturation_status, entity_id);
CREATE INDEX IF NOT EXISTS idx_opp_entity_research_profile_run ON opportunity_entity_research_profile(run_id, entity_research_mode, entity_id);
CREATE INDEX IF NOT EXISTS idx_opp_research_dp_entity ON opportunity_research_data_point(run_id, entity_id, research_category, sort_order);
CREATE INDEX IF NOT EXISTS idx_opp_candidate_run_stage ON opportunity_candidate_entity(run_id, candidate_stage);
CREATE INDEX IF NOT EXISTS idx_opp_source_cluster_run ON opportunity_source_cluster(run_id, cluster_key);
CREATE INDEX IF NOT EXISTS idx_opp_source_tier_date ON opportunity_source(source_tier, publish_date);
CREATE INDEX IF NOT EXISTS idx_opp_source_cluster ON opportunity_source(source_cluster_id);
CREATE INDEX IF NOT EXISTS idx_opp_source_evidence_ref ON opportunity_source(evidence_ref_uri);
CREATE INDEX IF NOT EXISTS idx_opp_source_policy ON opportunity_source(run_id, policy_gate_verdict, scoring_eligibility);
CREATE INDEX IF NOT EXISTS idx_opp_claim_run_entity ON opportunity_claim_evidence(run_id, entity_id, claim_type);
CREATE INDEX IF NOT EXISTS idx_opp_claim_policy ON opportunity_claim_evidence(run_id, policy_gate_verdict, scoring_eligibility);
CREATE INDEX IF NOT EXISTS idx_opp_dp_entity_metric ON opportunity_data_point(entity_id, metric, period, as_of_date);
CREATE INDEX IF NOT EXISTS idx_opp_dp_evidence_ref ON opportunity_data_point(evidence_ref_uri);
CREATE INDEX IF NOT EXISTS idx_opp_dp_policy ON opportunity_data_point(run_id, policy_gate_verdict, scoring_eligibility);
CREATE INDEX IF NOT EXISTS idx_opp_slot_run_entity_factor ON opportunity_metric_slot(run_id, entity_id, factor_code);
CREATE INDEX IF NOT EXISTS idx_opp_slot_policy ON opportunity_metric_slot(run_id, entity_id, scoring_eligibility);
CREATE INDEX IF NOT EXISTS idx_opp_score_batch_run_current ON opportunity_score_batch(run_id, is_current, score_batch_status);
CREATE INDEX IF NOT EXISTS idx_opp_factor_run_entity ON opportunity_factor_score(run_id, entity_id, score_batch_id, is_current);
CREATE INDEX IF NOT EXISTS idx_opp_composite_run_entity ON opportunity_composite_score(run_id, entity_id, score_batch_id, is_current);
CREATE INDEX IF NOT EXISTS idx_opp_early_signal_run_entity ON opportunity_early_signal_aggregate(run_id, entity_id, research_priority_score);
CREATE INDEX IF NOT EXISTS idx_opp_veto_run_entity ON opportunity_veto_status(run_id, entity_id, veto_code, veto_status);
CREATE INDEX IF NOT EXISTS idx_opp_market_run_entity ON opportunity_market_reaction(run_id, entity_id, market_reflection_state);
CREATE INDEX IF NOT EXISTS idx_opp_entity_target_entity ON opportunity_entity_investment_target(entity_id, sort_order);
CREATE INDEX IF NOT EXISTS idx_opp_entity_target_run ON opportunity_entity_investment_target(run_id, entity_id);
CREATE INDEX IF NOT EXISTS idx_opp_target_dp_target ON opportunity_target_data_point(target_id, sort_order);
CREATE INDEX IF NOT EXISTS idx_opp_target_dp_run_entity ON opportunity_target_data_point(run_id, entity_id, target_id);
CREATE INDEX IF NOT EXISTS idx_opp_event_run_entity_type ON opportunity_event_ledger(run_id, entity_id, event_scope, event_type, system_event_type);
CREATE INDEX IF NOT EXISTS idx_opp_event_policy ON opportunity_event_ledger(run_id, policy_gate_verdict, scoring_eligibility);
CREATE INDEX IF NOT EXISTS idx_opp_event_dedupe ON opportunity_event_ledger(run_id, dedupe_key);
CREATE INDEX IF NOT EXISTS idx_opp_audit_run_severity ON opportunity_audit_issue(run_id, audit_severity, audit_issue_status);
CREATE INDEX IF NOT EXISTS idx_opp_quality_gate_run ON opportunity_quality_gate_result(run_id, gate_name, created_at);
CREATE INDEX IF NOT EXISTS idx_opp_agent_review_stage ON opportunity_agent_review_log(run_id, review_stage, review_round);
CREATE INDEX IF NOT EXISTS idx_opp_supp_run_priority ON opportunity_supplement_request(run_id, priority, blocking_status);
CREATE INDEX IF NOT EXISTS idx_opp_agent_review_run ON opportunity_agent_review_log(run_id, review_round, review_verdict);
CREATE INDEX IF NOT EXISTS idx_opp_visual_evidence_block ON opportunity_visual_evidence_link(visual_block_id, evidence_ref_uri);
CREATE INDEX IF NOT EXISTS idx_opp_export_run_status ON opportunity_export_job(run_id, export_status);
