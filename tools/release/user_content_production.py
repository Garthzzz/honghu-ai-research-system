from __future__ import annotations

"""Serve the exact production release for the first user-content cutover.

This entrypoint owns its listener directly, imports the application only after
all external runtime roots and authority files are fixed, and never provides a
SQLite fallback.  ``--tls`` is required for authenticated analyst-note writes;
the paired HTTP listener remains useful for legacy read-only navigation because
the application transport gate rejects authenticated user-content operations.
"""

import argparse
import json
import os
import re
import ssl
import sys
from pathlib import Path

# The production launcher is invoked with ``python -I -B <exact file>``.  Add
# only the repository that owns this reviewed file; ambient working-directory
# and PYTHONPATH entries remain excluded by isolated mode.
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if not (REPOSITORY_ROOT / "AGENTS.md").is_file():
    raise RuntimeError("exact production release is missing AGENTS.md")
sys.path.insert(0, str(REPOSITORY_ROOT))

from tools.release.manager import verify_release


class ProductionServeError(RuntimeError):
    pass


def configure_environment(args: argparse.Namespace) -> dict:
    release = args.release_dir.resolve()
    verification = verify_release(release)
    commit = str(verification.get("commit_sha") or "").lower()
    if commit != args.expected_commit.lower() or not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ProductionServeError("release commit is not the approved exact commit")
    for path, kind in (
        (args.data_root, "data root"),
        (args.content_root, "content root"),
        (args.state_root, "state root"),
        (args.route_config, "authority route"),
        (args.postgres_config, "PostgreSQL runtime"),
        (args.identity_mapping, "identity mapping"),
        (args.security_config, "security configuration"),
    ):
        resolved = path.resolve()
        if kind in {"data root", "content root", "state root"}:
            if not resolved.is_dir():
                raise ProductionServeError(f"missing {kind}")
        elif not resolved.is_file():
            raise ProductionServeError(f"missing {kind}")
    route = json.loads(args.route_config.read_text(encoding="utf-8-sig"))
    if route.get("authority_state") not in {"S2", "S3", "S4"}:
        raise ProductionServeError("production route is outside S2/S3/S4")
    if (
        route.get("backend") != "postgresql_production"
        or route.get("sqlite_writer_enabled") is not False
        or route.get("production_postgresql_enabled") is not True
    ):
        raise ProductionServeError("production route does not fence SQLite")
    os.environ.update(
        {
            "HONGHU_DATA_ROOT": str(args.data_root.resolve()),
            "HONGHU_CONTENT_ROOT": str(args.content_root.resolve()),
            "HONGHU_STATE_ROOT": str(args.state_root.resolve()),
            "HONGHU_VIEWER_MODE": "production_postgresql",
            "HONGHU_RELEASE_COMMIT": commit,
            "HONGHU_RELEASE_MANIFEST": str(release / "RELEASE_MANIFEST.json"),
            "HONGHU_USER_CONTENT_ROUTE_CONFIG": str(args.route_config.resolve()),
            "HONGHU_USER_CONTENT_POSTGRES_CONFIG": str(args.postgres_config.resolve()),
            "HONGHU_USER_CONTENT_IDENTITY_MAPPING": str(args.identity_mapping.resolve()),
            "HONGHU_USER_CONTENT_SECURITY_CONFIG": str(args.security_config.resolve()),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
        }
    )
    return verification


def serve(args: argparse.Namespace) -> int:
    configure_environment(args)
    release = args.release_dir.resolve()
    os.chdir(release)
    if str(release) not in sys.path:
        sys.path.insert(0, str(release))
    from tools.viewer.app import app
    from werkzeug.serving import make_server

    ssl_context: ssl.SSLContext | None = None
    if args.tls:
        if args.tls_cert is None or args.tls_key is None:
            raise ProductionServeError("TLS listener requires certificate and private key")
        if not args.tls_cert.is_file() or not args.tls_key.is_file():
            raise ProductionServeError("TLS certificate or private key is missing")
        ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ssl_context.minimum_version = ssl.TLSVersion.TLSv1_2
        ssl_context.load_cert_chain(str(args.tls_cert), str(args.tls_key))
    elif args.port != 8080:
        raise ProductionServeError("the only approved plaintext listener is legacy port 8080")
    server = make_server(
        args.host,
        args.port,
        app,
        threaded=True,
        ssl_context=ssl_context,
    )
    server.serve_forever()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-dir", type=Path, required=True)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--content-root", type=Path, required=True)
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--route-config", type=Path, required=True)
    parser.add_argument("--postgres-config", type=Path, required=True)
    parser.add_argument("--identity-mapping", type=Path, required=True)
    parser.add_argument("--security-config", type=Path, required=True)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--tls", action="store_true")
    parser.add_argument("--tls-cert", type=Path)
    parser.add_argument("--tls-key", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    return serve(build_parser().parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
