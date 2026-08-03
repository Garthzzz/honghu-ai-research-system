PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS financial_schema_meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL,
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS financial_security (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  research_company_id INTEGER,
  canonical_name TEXT NOT NULL,
  name_en TEXT,
  ticker TEXT,
  market TEXT,
  listing_status TEXT,
  reporting_currency TEXT,
  fiscal_year_end TEXT,
  identity_status TEXT NOT NULL DEFAULT 'verified'
    CHECK(identity_status IN ('verified','needs_review','external_only')),
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_financial_security_research_company
  ON financial_security(research_company_id) WHERE research_company_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_financial_security_market_ticker
  ON financial_security(market,ticker) WHERE ticker IS NOT NULL AND trim(ticker)<>'';
CREATE INDEX IF NOT EXISTS idx_financial_security_name ON financial_security(canonical_name);

CREATE TABLE IF NOT EXISTS financial_security_company_link (
  research_company_id INTEGER PRIMARY KEY,
  security_id INTEGER NOT NULL,
  link_role TEXT NOT NULL DEFAULT 'canonical_or_alias'
    CHECK(link_role IN ('canonical','alias','canonical_or_alias')),
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY(security_id) REFERENCES financial_security(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_financial_security_company_link_security
  ON financial_security_company_link(security_id);
INSERT OR IGNORE INTO financial_security_company_link(research_company_id,security_id,link_role)
SELECT research_company_id,id,'canonical' FROM financial_security WHERE research_company_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS financial_source_snapshot (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  provider TEXT NOT NULL,
  source_channel TEXT NOT NULL
    CHECK(source_channel IN ('structured_api','report','web','internal_calculation','legacy_compat')),
  source_ref TEXT NOT NULL,
  title TEXT NOT NULL,
  publisher TEXT,
  as_of_date TEXT,
  fetched_at TEXT,
  content_hash TEXT,
  raw_snapshot_path TEXT,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE(provider,source_ref,as_of_date,content_hash)
);
CREATE INDEX IF NOT EXISTS idx_financial_source_provider_asof
  ON financial_source_snapshot(provider,as_of_date);

CREATE TABLE IF NOT EXISTS financial_observation (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  observation_key TEXT NOT NULL UNIQUE,
  security_id INTEGER NOT NULL,
  metric_name TEXT NOT NULL,
  value_num REAL,
  value_text TEXT,
  unit TEXT NOT NULL,
  currency TEXT,
  period_start TEXT,
  period_end TEXT,
  fiscal_year INTEGER,
  fiscal_period TEXT,
  frequency TEXT NOT NULL,
  fact_type TEXT NOT NULL
    CHECK(fact_type IN ('actual','market','consensus','guidance','internal_estimate','implied')),
  as_of_date TEXT NOT NULL,
  announcement_date TEXT,
  provider TEXT NOT NULL,
  raw_feature_name TEXT,
  source_snapshot_id INTEGER,
  formula TEXT,
  input_refs_json TEXT NOT NULL DEFAULT '[]',
  quality_status TEXT NOT NULL DEFAULT 'usable'
    CHECK(quality_status IN ('usable','limited','not_applicable','superseded','needs_review')),
  scenario_name TEXT NOT NULL DEFAULT 'reported',
  model_run_id INTEGER,
  legacy_ref TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY(security_id) REFERENCES financial_security(id) ON DELETE CASCADE,
  FOREIGN KEY(source_snapshot_id) REFERENCES financial_source_snapshot(id),
  FOREIGN KEY(model_run_id) REFERENCES financial_model_run(id)
);
CREATE INDEX IF NOT EXISTS idx_financial_observation_lookup
  ON financial_observation(security_id,metric_name,fact_type,as_of_date,period_end);
CREATE INDEX IF NOT EXISTS idx_financial_observation_period
  ON financial_observation(security_id,fiscal_year,fiscal_period,metric_name);

CREATE TABLE IF NOT EXISTS financial_observation_revision (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  observation_id INTEGER NOT NULL,
  previous_payload_json TEXT NOT NULL,
  replacement_payload_json TEXT NOT NULL,
  revision_reason TEXT NOT NULL,
  revised_at TEXT NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY(observation_id) REFERENCES financial_observation(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_financial_observation_revision_observation
  ON financial_observation_revision(observation_id,revised_at);

CREATE TABLE IF NOT EXISTS financial_model_run (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_key TEXT NOT NULL UNIQUE,
  security_id INTEGER,
  research_run_ref TEXT,
  skill_name TEXT NOT NULL
    CHECK(skill_name IN ('company_financial_modeling','company_valuation_modeling','industry_supply_demand_modeling','probability_scenario_modeling')),
  model_name TEXT NOT NULL,
  model_role TEXT NOT NULL
    CHECK(model_role IN ('primary','validation','core','reference','diagnostic','not_applicable')),
  status TEXT NOT NULL DEFAULT 'draft'
    CHECK(status IN ('draft','frozen_independent','reconciled','reviewed','superseded')),
  forecast_start TEXT,
  forecast_end TEXT,
  valuation_date TEXT,
  independent_before_consensus INTEGER NOT NULL DEFAULT 0 CHECK(independent_before_consensus IN (0,1)),
  assumptions_json TEXT NOT NULL DEFAULT '{}',
  limitations TEXT,
  input_hash TEXT,
  output_hash TEXT,
  frozen_at TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY(security_id) REFERENCES financial_security(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_financial_model_security ON financial_model_run(security_id,skill_name,status);

CREATE TABLE IF NOT EXISTS financial_model_input (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  model_run_id INTEGER NOT NULL,
  input_name TEXT NOT NULL,
  value_num REAL,
  value_text TEXT,
  range_low REAL,
  range_high REAL,
  unit TEXT NOT NULL,
  period_or_as_of_date TEXT NOT NULL,
  source_ref TEXT NOT NULL,
  input_type TEXT NOT NULL
    CHECK(input_type IN ('direct_fact','derived_fact','external_consensus','company_guidance','expert_assumption','objectively_unavailable')),
  formula_or_method TEXT,
  sensitivity_note TEXT,
  limitation_note TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY(model_run_id) REFERENCES financial_model_run(id) ON DELETE CASCADE,
  UNIQUE(model_run_id,input_name,period_or_as_of_date,source_ref)
);

CREATE TABLE IF NOT EXISTS financial_model_output (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  model_run_id INTEGER NOT NULL,
  output_name TEXT NOT NULL,
  value_num REAL,
  value_text TEXT,
  range_low REAL,
  range_high REAL,
  unit TEXT NOT NULL,
  period_or_as_of_date TEXT NOT NULL,
  formula TEXT NOT NULL,
  substitution TEXT NOT NULL,
  dependency_group TEXT,
  conclusion TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY(model_run_id) REFERENCES financial_model_run(id) ON DELETE CASCADE,
  UNIQUE(model_run_id,output_name,period_or_as_of_date)
);

CREATE TABLE IF NOT EXISTS financial_reconciliation (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  model_run_id INTEGER NOT NULL,
  benchmark_type TEXT NOT NULL CHECK(benchmark_type IN ('consensus','guidance','market_implied','peer','historical')),
  benchmark_source_ref TEXT NOT NULL,
  metric_name TEXT NOT NULL,
  period TEXT NOT NULL,
  independent_value REAL,
  benchmark_value REAL,
  unit TEXT NOT NULL,
  difference_value REAL,
  difference_pct REAL,
  decomposition_json TEXT NOT NULL DEFAULT '{}',
  conclusion TEXT NOT NULL,
  reconciled_at TEXT NOT NULL DEFAULT (datetime('now')),
  FOREIGN KEY(model_run_id) REFERENCES financial_model_run(id) ON DELETE CASCADE,
  UNIQUE(model_run_id,benchmark_type,benchmark_source_ref,metric_name,period)
);

INSERT INTO financial_schema_meta(key,value)
VALUES ('schema_version','financial.schema.v1')
ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=datetime('now');
