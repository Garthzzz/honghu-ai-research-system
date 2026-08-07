from __future__ import annotations

"""Discover and execute representative GET-only checks for a VM candidate."""

import argparse
from contextlib import closing
import json
import sqlite3
import urllib.error
import urllib.request
from urllib.parse import quote
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tools.runtime_paths import resolve_content_reference


@dataclass(frozen=True)
class SmokeCheck:
    check_id: str
    category: str
    path: str
    expected_status: int = 200
    method: str = "GET"
    expected_content_type: str | None = None
    expected_body_contains: str | None = None


def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    return conn


def _discover_industry(data_root: Path, content_root: Path) -> int:
    with closing(_connect(data_root / "research.db")) as conn:
        rows = conn.execute("SELECT id,name FROM industry ORDER BY id").fetchall()
    for row in rows:
        if (content_root / "docs" / "industries" / f"{row['name']}.md").is_file():
            return int(row["id"])
    raise RuntimeError("no industry has a matching external docs/industries main document")


def _discover_pdf_source(data_root: Path, content_root: Path) -> int:
    with closing(_connect(data_root / "research.db")) as conn:
        rows = conn.execute(
            "SELECT id,file_path FROM source "
            "WHERE file_path IS NOT NULL AND trim(file_path)<>'' ORDER BY id"
        ).fetchall()
    for row in rows:
        try:
            path = resolve_content_reference(
                content_root, str(row["file_path"]), default_prefix="papers"
            )
        except ValueError:
            continue
        if path.is_file() and path.suffix.lower() == ".pdf":
            return int(row["id"])
    raise RuntimeError("no database source resolves to an external PDF under content_root")


def _discover_company(data_root: Path) -> int:
    with closing(_connect(data_root / "financial.db")) as conn:
        candidates = [
            int(row[0])
            for row in conn.execute(
                "SELECT DISTINCT research_company_id FROM financial_security "
                "WHERE research_company_id IS NOT NULL ORDER BY research_company_id"
            )
        ]
    if not candidates:
        raise RuntimeError("financial.db has no mapped research company")
    placeholders = ",".join("?" for _ in candidates)
    with closing(_connect(data_root / "research.db")) as conn:
        row = conn.execute(
            f"SELECT id FROM company WHERE id IN ({placeholders}) ORDER BY id LIMIT 1",
            candidates,
        ).fetchone()
    if row is None:
        raise RuntimeError("financial security mappings do not resolve to research.company")
    return int(row[0])


def _discover_run(data_root: Path) -> int:
    with closing(_connect(data_root / "opportunity_lens.db")) as conn:
        row = conn.execute("SELECT id FROM opportunity_run ORDER BY id DESC LIMIT 1").fetchone()
    if row is None:
        raise RuntimeError("opportunity_lens.db has no run for representative smoke")
    return int(row[0])


def _discover_theme(data_root: Path) -> str:
    with closing(_connect(data_root / "research.db")) as conn:
        row = conn.execute("SELECT id FROM theme ORDER BY id LIMIT 1").fetchone()
    if row is None:
        raise RuntimeError("research.db has no theme for representative smoke")
    return str(row[0])


def build_representative_plan(data_root: str | Path, content_root: str | Path) -> list[SmokeCheck]:
    data = Path(data_root).resolve()
    content = Path(content_root).resolve()
    industry_id = _discover_industry(data, content)
    company_id = _discover_company(data)
    run_id = _discover_run(data)
    source_id = _discover_pdf_source(data, content)
    theme_id = _discover_theme(data)
    return [
        SmokeCheck("health", "process-and-four-db-contract", "/api/health"),
        SmokeCheck("home", "research-db-and-home", "/"),
        SmokeCheck("industry", "external-doc-and-research-db", f"/industry/{industry_id}"),
        SmokeCheck("industry-valuation", "research-and-financial", f"/industry/{industry_id}/valuation"),
        SmokeCheck("company", "research-financial-and-sentiment", f"/company/{company_id}"),
        SmokeCheck(
            "theme-db-only",
            "research-theme-with-optional-markdown",
            f"/theme/{quote(theme_id, safe='')}",
            expected_content_type="text/html",
            expected_body_contains="尚无主题分析 md",
        ),
        SmokeCheck("sentiment", "sentiment-and-research", "/dynamic/sentiment"),
        SmokeCheck("opportunity-home", "opportunity-db", "/opportunity-lens"),
        SmokeCheck("opportunity-run", "opportunity-run-detail", f"/opportunity-lens/run/{run_id}"),
        SmokeCheck("pdf", "external-paper", f"/pdf/{source_id}", expected_content_type="application/pdf"),
        SmokeCheck("tools", "tool-index", "/tools"),
        SmokeCheck("lithium-calculator", "tracked-model-and-state-fallback", "/tools/lithium-calculator"),
        SmokeCheck("copper-calculator", "tracked-model", "/tools/copper-calculator"),
        SmokeCheck("battery-calculator", "tracked-model", "/tools/battery-calculator"),
        SmokeCheck("static-css", "release-static-asset", "/static/styles.css", expected_content_type="text/css"),
        SmokeCheck("mutation-gate", "readonly-http-gate", "/api/analyst_note", expected_status=403, method="POST"),
    ]


def _request(base_url: str, check: SmokeCheck) -> dict[str, Any]:
    request = urllib.request.Request(
        base_url.rstrip("/") + check.path,
        data=b"{}" if check.method == "POST" else None,
        method=check.method,
        headers={"Content-Type": "application/json"} if check.method == "POST" else {},
    )
    status = 0
    content_type = ""
    sample = b""
    error: str | None = None
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            status = int(response.status)
            content_type = str(response.headers.get("Content-Type") or "")
            sample = response.read(65536)
    except urllib.error.HTTPError as exc:
        status = int(exc.code)
        content_type = str(exc.headers.get("Content-Type") or "")
        sample = exc.read(65536)
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    content_ok = (
        check.expected_content_type is None
        or content_type.lower().startswith(check.expected_content_type.lower())
    )
    body_text = sample.decode("utf-8", errors="replace")
    body_ok = (
        check.expected_body_contains is None
        or check.expected_body_contains in body_text
    )
    return {
        "id": check.check_id,
        "category": check.category,
        "method": check.method,
        "path": check.path,
        "expected_status": check.expected_status,
        "status": status,
        "content_type": content_type,
        "response_bytes_sampled": len(sample),
        "expected_body_contains": check.expected_body_contains,
        "ok": status == check.expected_status and content_ok and body_ok and error is None,
        "error": error,
    }


def run_representative_smoke(
    base_url: str,
    data_root: str | Path,
    content_root: str | Path,
    *,
    expected_commit: str,
    expected_launch_id: str,
    expected_pid: int,
) -> dict[str, Any]:
    discovery_failures: list[str] = []
    try:
        plan = build_representative_plan(data_root, content_root)
    except Exception as exc:
        plan = []
        discovery_failures.append(f"{type(exc).__name__}: {exc}")
    results = [_request(base_url, check) for check in plan]
    health_payload: dict[str, Any] = {}
    if plan and results and results[0]["ok"]:
        try:
            with urllib.request.urlopen(base_url.rstrip("/") + "/api/health", timeout=10) as response:
                health_payload = json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            discovery_failures.append(f"health identity read failed: {type(exc).__name__}: {exc}")
    process = health_payload.get("candidate_process") or {}
    release = health_payload.get("release") or {}
    identity = {
        "ok": bool(
            health_payload.get("viewer_mode") == "readonly_candidate"
            and release.get("commit_sha") == expected_commit
            and process.get("launch_id") == expected_launch_id
            and int(process.get("pid") or -1) == int(expected_pid)
        ),
        "viewer_mode": health_payload.get("viewer_mode"),
        "commit_sha": release.get("commit_sha"),
        "launch_id": process.get("launch_id"),
        "pid": process.get("pid"),
        "database_contract_compatible": (health_payload.get("database_contract") or {}).get("compatible"),
    }
    return {
        "schema_version": "honghu.readonly_candidate_smoke.v1",
        "base_url": base_url,
        "ok": not discovery_failures and identity["ok"] and all(item["ok"] for item in results),
        "identity": identity,
        "checks": results,
        "discovery_failures": discovery_failures,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--content-root", type=Path, required=True)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--expected-launch-id", required=True)
    parser.add_argument("--expected-pid", type=int, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    result = run_representative_smoke(
        args.base_url,
        args.data_root,
        args.content_root,
        expected_commit=args.expected_commit,
        expected_launch_id=args.expected_launch_id,
        expected_pid=args.expected_pid,
    )
    payload = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
