from __future__ import annotations

import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RUN_DIR = (
    ROOT
    / "opportunity_lens"
    / "research_outputs"
    / "20260725_chint_pv_profit_quality_run15"
)
PORTABLE_ARTIFACT_DIR = RUN_DIR / "financial_artifacts"
SOURCE_ARTIFACTS = (
    ROOT / "cache/chint_run15/financial_actual_snapshot.json",
    ROOT / "cache/chint_run15/wind_financial_snapshot_20260726.json",
    ROOT / "cache/chint_run15/run15_chint_financial_inputs.json",
    ROOT / "cache/chint_run15/run15_chint_financial_model.json",
    ROOT / "cache/chint_run15/run15_external_reconciliation.json",
    ROOT / "cache/chint_run15/wind_current_market_snapshot_20260727.json",
    ROOT / "cache/chint_run15/run15_household_contract_cashflow_model.json",
    ROOT / "cache/chint_run15/run15_household_to_group_valuation_bridge.json",
)


def portable_artifact_path(source: Path) -> Path:
    return PORTABLE_ARTIFACT_DIR / source.name


def materialize_run15_portable_artifacts() -> dict[Path, Path]:
    PORTABLE_ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    result: dict[Path, Path] = {}
    for source in SOURCE_ARTIFACTS:
        if not source.is_file():
            raise FileNotFoundError(source)
        target = portable_artifact_path(source)
        shutil.copy2(source, target)
        result[source] = target
    return result
