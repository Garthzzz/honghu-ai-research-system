"""碳酸锂计算器冻结输入的部署路径合同。"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


MODEL_FILENAMES = (
    "lithium_company_independent_models_v1.json",
    "lithium_external_reconciliation_v1.json",
)
PROJECT_LEDGER_RELATIVE = Path("config/lithium_calculator_project_ledger.json")
DEPLOYED_MODEL_DIR_RELATIVE = Path("config/lithium_calculator_models")
LEGACY_MODEL_DIR_RELATIVE = Path("cache/lithium_research/models")


@dataclass(frozen=True)
class LithiumCalculatorInputs:
    independent_model: Path
    reconciliation: Path
    project_ledger: Path
    used_legacy_cache: bool = False

    def missing(self) -> tuple[Path, ...]:
        return tuple(
            path
            for path in (
                self.independent_model,
                self.reconciliation,
                self.project_ledger,
            )
            if not path.is_file()
        )


def deployed_inputs(root: Path) -> LithiumCalculatorInputs:
    model_dir = root / DEPLOYED_MODEL_DIR_RELATIVE
    return LithiumCalculatorInputs(
        independent_model=model_dir / MODEL_FILENAMES[0],
        reconciliation=model_dir / MODEL_FILENAMES[1],
        project_ledger=root / PROJECT_LEDGER_RELATIVE,
    )


def resolve_inputs(
    root: Path,
    *,
    allow_legacy_cache: bool = True,
) -> LithiumCalculatorInputs:
    """Return deployable inputs, optionally falling back to the old cache paths."""
    primary = deployed_inputs(root)
    if not primary.missing() or not allow_legacy_cache:
        return primary
    legacy_dir = root / LEGACY_MODEL_DIR_RELATIVE
    legacy = LithiumCalculatorInputs(
        independent_model=legacy_dir / MODEL_FILENAMES[0],
        reconciliation=legacy_dir / MODEL_FILENAMES[1],
        project_ledger=primary.project_ledger,
        used_legacy_cache=True,
    )
    return legacy if not legacy.missing() else primary
