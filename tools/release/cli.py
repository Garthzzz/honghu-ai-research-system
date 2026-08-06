from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .manager import (
    ReleaseError,
    activate_release,
    build_release,
    inspect_sqlite_contract,
    preflight_release,
    prime_release_health_cache,
    release_health_payload,
    resolve_current_release,
    resolve_preflighted_release,
    rollback_release,
    verify_release,
)


def _print(payload: object) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def _manifest_compatibility(release: Path) -> dict:
    return verify_release(release)["schema_compatibility"]


def _schema_for_release(release: Path, data_root: Path) -> dict:
    return inspect_sqlite_contract(data_root, _manifest_compatibility(release))


def _serve(args: argparse.Namespace) -> int:
    report_bytes = args.preflight_report.read_bytes()
    report_hash = __import__("hashlib").sha256(report_bytes).hexdigest()
    if report_hash != args.preflight_report_sha256.lower():
        raise ReleaseError("bound preflight report hash mismatch")
    report = json.loads(report_bytes.decode("utf-8-sig"))
    if not isinstance(report, dict):
        raise ReleaseError("bound preflight report must be a JSON object")
    release, pointer = resolve_preflighted_release(
        args.deploy_root,
        preflight_report=report,
        data_root=args.data_root,
        content_root=args.content_root,
        state_root=args.state_root,
    )
    if str(pointer.get("commit_sha")) != args.expected_commit.lower():
        raise ReleaseError("current candidate commit differs from expected commit")
    if not __import__("re").fullmatch(r"[0-9a-f]{32}", args.launch_id):
        raise ReleaseError("launch id must be 32 lowercase hexadecimal characters")
    if args.port == 8080:
        raise ReleaseError("read-only candidate cannot bind the production port 8080")
    os.environ.update(
        {
            "HONGHU_DATA_ROOT": str(args.data_root.resolve()),
            "HONGHU_CONTENT_ROOT": str(args.content_root.resolve()),
            "HONGHU_STATE_ROOT": str(args.state_root.resolve()),
            "HONGHU_VIEWER_MODE": "readonly_candidate",
            "HONGHU_RELEASE_COMMIT": str(pointer["commit_sha"]),
            "HONGHU_RELEASE_MANIFEST": str(release / "RELEASE_MANIFEST.json"),
            "HONGHU_RELEASE_MANIFEST_SHA256": str(pointer["manifest_sha256"]),
            "HONGHU_DEPLOY_ROOT": str(args.deploy_root.resolve()),
            "HONGHU_CANDIDATE_LAUNCH_ID": args.launch_id,
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
        }
    )
    prime_release_health_cache(
        args.deploy_root,
        args.data_root,
        pointer=pointer,
        preflight_report=report,
    )
    os.chdir(release)
    if str(release) not in sys.path:
        sys.path.insert(0, str(release))
    # Import only after the runtime roots and read-only mode are fixed.  The
    # CLI process itself owns the listener; there is no outer PID whose child
    # could survive after a failed smoke or stop operation.
    from tools.viewer.app import app

    app.run(
        host=args.host,
        port=args.port,
        debug=False,
        use_debugger=False,
        use_reloader=False,
        threaded=True,
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Honghu immutable release manager")
    sub = parser.add_subparsers(dest="command", required=True)

    build = sub.add_parser("build")
    build.add_argument("--repo-root", type=Path, required=True)
    build.add_argument("--deploy-root", type=Path, required=True)
    build.add_argument("--commit", required=True)

    verify = sub.add_parser("verify")
    verify.add_argument("--release-dir", type=Path, required=True)

    preflight = sub.add_parser("preflight")
    preflight.add_argument("--release-dir", type=Path, required=True)
    preflight.add_argument("--data-root", type=Path, required=True)
    preflight.add_argument("--content-root", type=Path, required=True)
    preflight.add_argument("--state-root", type=Path, required=True)
    preflight.add_argument("--output", type=Path)

    activate = sub.add_parser("activate")
    activate.add_argument("--deploy-root", type=Path, required=True)
    activate.add_argument("--commit", required=True)
    activate.add_argument("--data-root", type=Path, required=True)
    activate.add_argument("--actor", required=True)

    rollback = sub.add_parser("rollback")
    rollback.add_argument("--deploy-root", type=Path, required=True)
    rollback.add_argument("--data-root", type=Path, required=True)
    rollback.add_argument("--actor", required=True)
    rollback.add_argument("--target-commit")

    current = sub.add_parser("current")
    current.add_argument("--deploy-root", type=Path, required=True)

    health = sub.add_parser("health")
    health.add_argument("--deploy-root", type=Path, required=True)
    health.add_argument("--data-root", type=Path, required=True)

    serve = sub.add_parser("serve-readonly-candidate")
    serve.add_argument("--deploy-root", type=Path, required=True)
    serve.add_argument("--data-root", type=Path, required=True)
    serve.add_argument("--content-root", type=Path, required=True)
    serve.add_argument("--state-root", type=Path, required=True)
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=18080)
    serve.add_argument("--launch-id", required=True)
    serve.add_argument("--expected-commit", required=True)
    serve.add_argument("--preflight-report", type=Path, required=True)
    serve.add_argument("--preflight-report-sha256", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "build":
            _print(build_release(args.repo_root, args.deploy_root, commit=args.commit))
        elif args.command == "verify":
            _print(verify_release(args.release_dir))
        elif args.command == "preflight":
            result = preflight_release(
                args.release_dir,
                data_root=args.data_root,
                content_root=args.content_root,
                state_root=args.state_root,
            )
            _print(result)
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(
                    json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
            return 0 if result["ok"] else 1
        elif args.command == "activate":
            release = args.deploy_root / "releases" / args.commit
            schema = inspect_sqlite_contract(
                args.data_root, _manifest_compatibility(release)
            )
            _print(
                activate_release(
                    args.deploy_root,
                    args.commit,
                    actor=args.actor,
                    schema_report=schema,
                )
            )
        elif args.command == "rollback":
            _, current = resolve_current_release(args.deploy_root)
            target = args.target_commit or current.get("previous_commit_sha")
            if not target:
                raise ReleaseError("no previous release is recorded for rollback")
            target_release = args.deploy_root.resolve() / "releases" / str(target)
            schema = _schema_for_release(target_release, args.data_root)
            _print(
                rollback_release(
                    args.deploy_root,
                    actor=args.actor,
                    schema_report=schema,
                    target_commit=args.target_commit,
                )
            )
        elif args.command == "current":
            release, pointer = resolve_current_release(args.deploy_root)
            _print({"release_dir": str(release), **pointer})
        elif args.command == "health":
            _print(
                release_health_payload(args.deploy_root, data_root=args.data_root)
            )
        elif args.command == "serve-readonly-candidate":
            return _serve(args)
        return 0
    except ReleaseError as exc:
        _print({"ok": False, "error": str(exc)})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
