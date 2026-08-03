from pathlib import Path

from tools.runtime_paths import resolve_runtime_layout


ROOT = Path(__file__).resolve().parents[2]
RUNTIME_LAYOUT = resolve_runtime_layout(ROOT)
DB_PATH = RUNTIME_LAYOUT.data_root / "financial.db"
SCHEMA_VERSION = "financial.schema.v1"

FACT_TYPES = {
    "actual",
    "market",
    "consensus",
    "guidance",
    "internal_estimate",
    "implied",
}

SOURCE_CHANNELS = {"structured_api", "report", "web", "internal_calculation", "legacy_compat"}

MODEL_SKILLS = {
    "company_financial_modeling",
    "company_valuation_modeling",
    "industry_supply_demand_modeling",
    "probability_scenario_modeling",
}
