from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from tools.opportunity_lens.run_pack_contract import validate_run_pack


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT = ROOT / "opportunity_lens" / "research_outputs"
DEFAULT_OUTPUT = ROOT / "cache" / "workflow_refactor_20260712" / "legacy_run_pack_compatibility_audit.json"


def _issue_codes(report, severity: str) -> list[str]:
    return sorted({issue.code for issue in report.issues if issue.severity == severity})


def audit(input_dir: Path) -> dict[str, Any]:
    packs: list[dict[str, Any]] = []
    for path in sorted(input_dir.glob("*/run_pack.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            packs.append({
                "path": path.relative_to(ROOT).as_posix(),
                "stage_valid": False,
                "publish_valid": False,
                "load_error": str(exc),
            })
            continue
        stage = validate_run_pack(payload, publication_mode="stage")
        publish = validate_run_pack(payload, publication_mode="publish")
        packs.append({
            "path": path.relative_to(ROOT).as_posix(),
            "pack_schema_version": stage.pack_schema_version,
            "stage_valid": stage.valid,
            "publish_valid": publish.valid,
            "stage_error_codes": _issue_codes(stage, "error"),
            "stage_warning_codes": _issue_codes(stage, "warning"),
            "publish_only_error_codes": sorted(
                set(_issue_codes(publish, "error")) - set(_issue_codes(stage, "error"))
            ),
            "metrics": stage.metrics,
        })
    return {
        "pack_count": len(packs),
        "stage_valid_count": sum(1 for item in packs if item.get("stage_valid")),
        "publish_valid_count": sum(1 for item in packs if item.get("publish_valid")),
        "packs": packs,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="只读审计历史 Opportunity Lens run pack 的 V2 兼容边界")
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    result = audit(args.input_dir.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "pack_count": result["pack_count"],
        "stage_valid_count": result["stage_valid_count"],
        "publish_valid_count": result["publish_valid_count"],
        "output": str(args.output),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
