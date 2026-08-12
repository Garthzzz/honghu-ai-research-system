from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def build(
    *,
    output_root: Path,
    environment_id: str,
    application_commit_sha: str,
    bootstrap_config_sha256: str,
    artifacts: dict[str, Path],
) -> dict:
    output_root.mkdir(parents=True, exist_ok=False)
    artifact_root = output_root / "artifacts"
    artifact_root.mkdir()
    identities = {}
    for name, source in sorted(artifacts.items()):
        source = source.resolve()
        if not source.is_file():
            raise FileNotFoundError(source)
        target = artifact_root / f"{name}.json"
        shutil.copy2(source, target)
        identities[name] = {
            "path": target.relative_to(output_root).as_posix(),
            "sha256": _sha(target),
        }
    bundle = {
        "schema_version": "honghu.stage4_execution_evidence_bundle.v1",
        "subject": {
            "environment_id": environment_id,
            "application_commit_sha": application_commit_sha,
            "bootstrap_config_sha256": bootstrap_config_sha256,
        },
        "artifacts": identities,
    }
    (output_root / "execution_bundle.json").write_text(
        json.dumps(bundle, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return bundle


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--environment-id", required=True)
    parser.add_argument("--application-commit-sha", required=True)
    parser.add_argument("--bootstrap-config-sha256", required=True)
    parser.add_argument("--artifact", action="append", required=True)
    args = parser.parse_args(argv)
    artifacts = {}
    for value in args.artifact:
        if "=" not in value:
            raise ValueError("artifact must be NAME=PATH")
        name, raw_path = value.split("=", 1)
        if not name or name in artifacts:
            raise ValueError(f"invalid/duplicate artifact name: {name}")
        artifacts[name] = Path(raw_path)
    result = build(
        output_root=args.output_root.resolve(),
        environment_id=args.environment_id,
        application_commit_sha=args.application_commit_sha,
        bootstrap_config_sha256=args.bootstrap_config_sha256,
        artifacts=artifacts,
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
