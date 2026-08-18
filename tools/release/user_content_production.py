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
from tools.data_platform.postgres_runtime import (
    build_catalog_connection_factory,
    load_postgres_runtime_catalog,
)
from tools.data_platform.routing import load_authority_matrix


class ProductionServeError(RuntimeError):
    pass


def configure_environment(args: argparse.Namespace) -> dict:
    release = args.release_dir.resolve()
    verification = verify_release(release)
    commit = str(verification.get("commit_sha") or "").lower()
    if commit != args.expected_commit.lower() or not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ProductionServeError("release commit is not the approved exact commit")
    common_runtime = getattr(args, "postgres_runtime_catalog", None)
    common_registry = getattr(args, "cutover_unit_registry", None)
    if (common_runtime is None) != (common_registry is None):
        raise ProductionServeError(
            "PostgreSQL runtime catalog and cutover-unit registry are required together"
        )
    common_mode = common_runtime is not None
    for path, kind in (
        (args.data_root, "data root"),
        (args.content_root, "content root"),
        (args.state_root, "state root"),
        (args.security_config, "security configuration"),
    ):
        resolved = path.resolve()
        if kind in {"data root", "content root", "state root"}:
            if not resolved.is_dir():
                raise ProductionServeError(f"missing {kind}")
        elif not resolved.is_file():
            raise ProductionServeError(f"missing {kind}")
    environment = {
        "HONGHU_DATA_ROOT": str(args.data_root.resolve()),
        "HONGHU_CONTENT_ROOT": str(args.content_root.resolve()),
        "HONGHU_STATE_ROOT": str(args.state_root.resolve()),
        "HONGHU_VIEWER_MODE": "production_hybrid" if common_mode else "production_postgresql",
        "HONGHU_RELEASE_COMMIT": commit,
        "HONGHU_RELEASE_MANIFEST": str(release / "RELEASE_MANIFEST.json"),
        "HONGHU_USER_CONTENT_SECURITY_CONFIG": str(args.security_config.resolve()),
        "HONGHU_PRODUCTION_LAUNCH_ID": args.launch_id,
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
    }
    if common_mode:
        for path, label in (
            (common_runtime, "PostgreSQL runtime catalog"),
            (common_registry, "cutover-unit registry"),
        ):
            if not path.resolve().is_file():
                raise ProductionServeError(f"missing {label}")
        if any(
            value is not None
            for value in (args.route_config, args.postgres_config, args.identity_mapping)
        ):
            raise ProductionServeError(
                "common authority matrix cannot be combined with legacy per-unit inputs"
            )
        catalog = load_postgres_runtime_catalog(common_runtime)
        if catalog.application_commit_sha.lower() != commit:
            raise ProductionServeError("PostgreSQL runtime catalog is not bound to release commit")
        reader_factory = build_catalog_connection_factory(catalog, role="reader")
        _, matrix = load_authority_matrix(common_registry, reader_factory)
        for required in ("user_content_notes", "shared_identity"):
            route = matrix.routes[required]
            if route.authority_state.value not in {"S3", "S4"}:
                raise ProductionServeError(f"required production unit is not durable S3: {required}")
        environment.update(
            {
                "HONGHU_POSTGRES_RUNTIME_CONFIG": str(common_runtime.resolve()),
                "HONGHU_CUTOVER_UNIT_REGISTRY": str(common_registry.resolve()),
            }
        )
    else:
        for path, kind in (
            (args.route_config, "authority route"),
            (args.postgres_config, "PostgreSQL runtime"),
            (args.identity_mapping, "identity mapping"),
        ):
            if path is None or not path.resolve().is_file():
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
        environment.update(
            {
                "HONGHU_USER_CONTENT_ROUTE_CONFIG": str(args.route_config.resolve()),
                "HONGHU_USER_CONTENT_POSTGRES_CONFIG": str(args.postgres_config.resolve()),
                "HONGHU_USER_CONTENT_IDENTITY_MAPPING": str(args.identity_mapping.resolve()),
            }
        )
    os.environ.update(environment)
    shared_route = getattr(args, "shared_identity_route", None) if not common_mode else None
    shared_runtime = getattr(args, "shared_identity_postgres_config", None)
    if (shared_route is None) != (shared_runtime is None):
        raise ProductionServeError(
            "shared identity route and PostgreSQL runtime must be supplied together"
        )
    if shared_route is not None:
        if not shared_route.resolve().is_file() or not shared_runtime.resolve().is_file():
            raise ProductionServeError("shared identity runtime input is missing")
        shared = json.loads(shared_route.read_text(encoding="utf-8-sig"))
        if (
            shared.get("cutover_unit") != "shared_identity"
            or shared.get("authority_state") not in {"S2", "S3", "S4"}
            or shared.get("backend") != "postgresql_production"
            or shared.get("sqlite_writer_enabled") is not False
            or shared.get("production_postgresql_enabled") is not True
        ):
            raise ProductionServeError("shared identity route does not fence SQLite")
        os.environ.update(
            {
                "HONGHU_SHARED_IDENTITY_ROUTE_CONFIG": str(shared_route.resolve()),
                "HONGHU_SHARED_IDENTITY_POSTGRES_CONFIG": str(
                    shared_runtime.resolve()
                ),
            }
        )
    return verification


def serve(args: argparse.Namespace) -> int:
    configure_environment(args)
    release = args.release_dir.resolve()
    os.chdir(release)
    if str(release) not in sys.path:
        sys.path.insert(0, str(release))
    from tools.viewer.app import (
        FINANCIAL_DB_PATH,
        OPPORTUNITY_DB_PATH,
        app,
        get_db,
        senti_conn,
    )
    from tools.data_platform.domain_data import connect_domain_database
    from werkzeug.serving import make_server

    # Build every PostgreSQL-derived compatibility cache before opening the
    # listener.  Cold TLS/cache materialization belongs to deployment
    # readiness, not to the first user's page request.
    warmup = get_db()
    warmup.close()
    sentiment_warmup = senti_conn()
    if sentiment_warmup is not None:
        sentiment_warmup.close()
    for unit, database_path in (
        ("financial_data", FINANCIAL_DB_PATH),
        ("opportunity_lens", OPPORTUNITY_DB_PATH),
    ):
        domain_warmup = connect_domain_database(unit, database_path, readonly=True)
        domain_warmup.close()

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
    parser.add_argument("--route-config", type=Path)
    parser.add_argument("--postgres-config", type=Path)
    parser.add_argument("--identity-mapping", type=Path)
    parser.add_argument("--postgres-runtime-catalog", type=Path)
    parser.add_argument("--cutover-unit-registry", type=Path)
    parser.add_argument("--security-config", type=Path, required=True)
    parser.add_argument("--shared-identity-route", type=Path)
    parser.add_argument("--shared-identity-postgres-config", type=Path)
    parser.add_argument("--launch-id", required=True)
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
