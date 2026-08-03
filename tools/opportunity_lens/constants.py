from __future__ import annotations

from pathlib import Path

from tools.research_core.config import contract_version, resolve_track_config
from tools.runtime_paths import resolve_runtime_layout

MODULE_NAME = "opportunity_lens"
PROJECT_NAME = "Opportunity Lens"
ROUTE_PREFIX = "/opportunity-lens"
API_PREFIX = "/api/opportunity-lens"

ROOT = Path(__file__).resolve().parents[2]
RUNTIME_LAYOUT = resolve_runtime_layout(ROOT)
DATA_DIR = RUNTIME_LAYOUT.data_root
DB_PATH = DATA_DIR / "opportunity_lens.db"
RESEARCH_DB_PATH = DATA_DIR / "research.db"
FINANCIAL_DB_PATH = DATA_DIR / "financial.db"
SENTIMENT_DB_PATH = DATA_DIR / "sentiment.db"
EXPORT_ROOT = RUNTIME_LAYOUT.cache_root / "opportunity_lens_exports"

SCHEMA_VERSION = "opportunity_lens.schema.v1_8"
DESIGN_VERSION = "2026-07-12.workflow.v2"
SOURCE_LADDER_VERSION = "C_SOURCE_LADDER_V1"
TAXONOMY_VERSION = "C_TAXONOMY_V1"
FACTOR_DICTIONARY_VERSION = "C_FACTOR_14_V08_1"
SLOT_DICTIONARY_VERSION = "C_SLOT_V08_1"
PREPROCESSING_VERSION = "C_PREPROCESS_V08_1"
SCORE_RULE_VERSION = "C_SCORING_V08_1"
INTAKE_CONTRACT_VERSION = "C_INTAKE_CONTRACT_V1"
EVIDENCE_POLICY_VERSION = "C_EVIDENCE_POLICY_V1"
EARLY_SIGNAL_RULE_VERSION = "C_EARLY_SIGNAL_RULE_V1"
EVENT_MAPPING_VERSION = "C_EVENT_MAPPING_V1"
AUDIT_RULE_VERSION = "C_AUDIT_RULE_V1"
API_CONTRACT_VERSION = "C_API_V1_7"
VIEWER_CONTRACT_VERSION = "C_VIEWER_V1_7"
PDF_CONTRACT_VERSION = "C_PDF_V1_6"
RESEARCH_WORKFLOW_CONTRACT_VERSION = contract_version()
RUN_PACK_SCHEMA_VERSION = str(resolve_track_config("c")["pack_schema_version"])

VERSION_BUNDLE = {
    "schema_version": SCHEMA_VERSION,
    "design_version": DESIGN_VERSION,
    "source_ladder_version": SOURCE_LADDER_VERSION,
    "taxonomy_version": TAXONOMY_VERSION,
    "factor_dictionary_version": FACTOR_DICTIONARY_VERSION,
    "slot_dictionary_version": SLOT_DICTIONARY_VERSION,
    "preprocessing_version": PREPROCESSING_VERSION,
    "score_rule_version": SCORE_RULE_VERSION,
    "intake_contract_version": INTAKE_CONTRACT_VERSION,
    "evidence_policy_version": EVIDENCE_POLICY_VERSION,
    "early_signal_rule_version": EARLY_SIGNAL_RULE_VERSION,
    "event_mapping_version": EVENT_MAPPING_VERSION,
    "audit_rule_version": AUDIT_RULE_VERSION,
    "api_contract_version": API_CONTRACT_VERSION,
    "viewer_contract_version": VIEWER_CONTRACT_VERSION,
    "pdf_contract_version": PDF_CONTRACT_VERSION,
    "research_workflow_contract_version": RESEARCH_WORKFLOW_CONTRACT_VERSION,
    "run_pack_schema_version": RUN_PACK_SCHEMA_VERSION,
}
