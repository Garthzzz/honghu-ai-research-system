from __future__ import annotations

"""Rebind already-fetched Wind consensus rows to a revised frozen model.

This performs no external request.  It is used only when discrepancy review
changes the frozen model while the Wind rows, trade date and universe remain
unchanged during the same research session.
"""

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return "sha256:" + digest


def _content_sha256(payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--freeze-artifact", type=Path, required=True)
    args = parser.parse_args()
    payload = json.loads(args.snapshot.read_text(encoding="utf-8"))
    freeze = json.loads(args.freeze_artifact.read_text(encoding="utf-8"))
    if payload.get("stage") != "external_reconciliation_after_independent_freeze":
        raise ValueError("不是Run16外部对账快照")
    payload["independent_freeze"] = {
        "path": str(args.freeze_artifact.resolve()).replace("\\", "/"),
        "sha256": _file_sha256(args.freeze_artifact),
        "declared_output_hash": freeze.get("output_hash"),
    }
    payload.setdefault("request_audit", {})["rebind_note"] = (
        "差异专项复查后仅更新冻结模型哈希；Wind证券、字段、交易日和已取回数值未变，本步骤没有再次调用外部接口。"
    )
    payload.pop("content_sha256", None)
    payload["content_sha256"] = _content_sha256(payload)
    args.snapshot.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"snapshot": str(args.snapshot.resolve()), "content_sha256": payload["content_sha256"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
