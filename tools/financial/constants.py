from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "data" / "financial.db"
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
