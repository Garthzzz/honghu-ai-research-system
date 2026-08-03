#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from urllib.parse import urlparse
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools" / "pipeline"))

import consensus_compute  # noqa: E402
import db_writer  # noqa: E402
from tools.pipeline.paper_paths import normalize_new_paper_file  # noqa: E402
from tools.portable_paths import relative_path  # noqa: E402
from tools.pipeline.paper_source_manifest import enrich_claim_sources  # noqa: E402
from tools.research_core.config import contract_version  # noqa: E402
from tools.research_core.content_cache import ContentAddressedCache  # noqa: E402
from tools.research_core.workflow import ResearchWorkflowRun  # noqa: E402


VALID_SOURCE_TYPES = {
    "卖方深度", "卖方周报", "公告", "业绩说明会", "招股书", "协会数据",
    "三方数据", "财经媒体", "自媒体", "claude_lit_review", "website_material", "其他",
}
VALID_VALUE_LAYERS = {"深度框架", "最新数据", "双层", "公司专项", "主题专项", "信息流"}
VALID_SENTIMENTS = {"看涨", "看跌", "中性", "不适用"}
PRIMARY_SOURCE_TYPES = {"公告", "业绩说明会", "招股书", "协会数据"}


@dataclass(frozen=True)
class SourceKey:
    kind: str
    value: str

    def text(self) -> str:
        return f"{self.kind}:{self.value}"


def normalize_date(value: Any) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    match = re.fullmatch(r"(\d{4})(\d{2})(\d{2})", text)
    return f"{match.group(1)}-{match.group(2)}-{match.group(3)}" if match else text


def to_number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(str(value).strip().replace(",", ""))
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def source_key(source: dict[str, Any]) -> SourceKey:
    if source.get("source_file"):
        return SourceKey("file", str(source["source_file"]).strip())
    value = str(source.get("source_url") or "").strip()
    if not re.match(r"^https?://", value, flags=re.IGNORECASE):
        raise ValueError("网页 source 必须提供 http/https 原始 URL；标题或 source_ref 不能替代来源定位")
    return SourceKey("url", value)


def source_channel(source: dict[str, Any], key: SourceKey) -> str:
    """Normalize at the parser boundary; historical claims may omit the new field."""
    value = str(source.get("source_channel") or "").strip().lower()
    if not value:
        value = "report" if key.kind == "file" else "web"
    if value not in {"report", "web"}:
        raise ValueError(f"source_channel 必须是 report 或 web: {value!r}")
    if key.kind == "file" and value != "report":
        raise ValueError("本地 papers/研报 source 必须标记为 report")
    if key.kind == "url" and value != "web":
        raise ValueError("公开 URL source 必须标记为 web")
    return value


def resolve_source_file(papers_subdir: str, source_file: str) -> tuple[Path, str]:
    raw = Path(str(source_file).strip())
    if raw.is_absolute():
        candidate = raw.resolve()
    elif raw.parts and raw.parts[0].lower() == "papers":
        candidate = (ROOT / raw).resolve()
    else:
        candidate = (ROOT / "papers" / papers_subdir / raw).resolve()
    if not candidate.is_file():
        raise FileNotFoundError(f"source_file 不存在: {candidate}")
    candidate = normalize_new_paper_file(candidate, project_root=ROOT)
    try:
        relative = relative_path(candidate, ROOT).as_posix()
    except ValueError as exc:
        raise ValueError(f"source_file 必须位于项目目录内: {candidate}") from exc
    return candidate, relative


def source_aliases(source: dict[str, Any]) -> set[str]:
    return {
        str(value).strip()
        for value in (source.get("source_file"), source.get("source_ref"), source.get("title"), source.get("source_url"))
        if str(value or "").strip()
    }


def load_claim_documents(
    files: list[Path],
    *,
    cache: ContentAddressedCache | None = None,
) -> list[dict[str, Any]]:
    documents = []
    for path in files:
        raw = path.read_bytes()
        cache_record = None
        if cache is not None:
            try:
                source_path = path.resolve().relative_to(ROOT.resolve()).as_posix()
            except ValueError:
                source_path = str(path.resolve())
            cache_record = cache.put_bytes(
                raw,
                suffix=".json",
                metadata={
                    "artifact_kind": "ab_claim_document",
                    "source_path": source_path,
                    "workflow_contract_version": contract_version(),
                },
            )
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"claims 文件顶层必须是对象: {path}")
        payload["_claim_file"] = str(path)
        if cache_record is not None:
            payload["_content_cache"] = cache_record
        documents.append(payload)
    return documents


def _metadata_value(documents: list[dict[str, Any]], key: str) -> Any:
    for document in documents:
        for container in (document, document.get("meta"), document.get("_meta")):
            if isinstance(container, dict) and container.get(key) not in (None, "", [], {}):
                return container[key]
    return None


def _text_list(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item or "").strip()]
    return [str(value).strip()]


def _mapping_value(value: Any, *, fallback_key: str = "description") -> dict[str, Any]:
    if value in (None, "", [], {}):
        return {}
    if isinstance(value, dict):
        return dict(value)
    return {fallback_key: value}


def _load_workflow_request(path: str | Path | None) -> tuple[dict[str, Any], Path | None]:
    if not path:
        return {}, None
    request_path = Path(path)
    if not request_path.is_file():
        raise FileNotFoundError(f"workflow request 不存在: {request_path}")
    payload = json.loads(request_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("workflow request 顶层必须是 JSON 对象")
    allowed = {
        "run_key", "track", "title", "research_question", "prompt_requirements",
        "decision_use", "must_include", "exclusions", "special_constraints",
        "scope", "time_window", "required_artifacts", "quality_floor",
    }
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise ValueError(f"workflow request 含未知字段: {unknown}")
    return payload, request_path


def _start_ingest_workflow(
    *,
    track: str,
    tag: str,
    papers_subdir: str,
    documents: list[dict[str, Any]],
    claim_files: list[Path],
    workflow_request_path: str | Path | None,
) -> tuple[ResearchWorkflowRun, bool]:
    request, request_path = _load_workflow_request(workflow_request_path)
    requested_track = str(request.get("track") or track).strip().lower()
    if requested_track != track:
        raise ValueError(f"workflow request track={requested_track!r} 与 ingest track={track!r} 不一致")
    requested_run_key = str(request.get("run_key") or tag).strip()
    if requested_run_key != tag:
        raise ValueError(f"workflow request run_key={requested_run_key!r} 与 ingest tag={tag!r} 不一致")

    prompt_requirements = request.get("prompt_requirements")
    if prompt_requirements is None:
        prompt_requirements = _metadata_value(documents, "prompt_requirements")
    if prompt_requirements is None:
        prompt_requirements = _metadata_value(documents, "requirements")
    prompt_requirements = list(prompt_requirements or []) if isinstance(prompt_requirements, list) else _text_list(prompt_requirements)
    missing_b_prompt = track == "b" and not prompt_requirements
    if missing_b_prompt:
        prompt_requirements = [{
            "question": "补录并逐项核对本次 B 轨原始用户 prompt 全集",
            "output_hint": "ResearchBrief requirement matrix",
            "acceptance_criteria": "提供原始 prompt 或结构化 workflow request，并逐项记录产物、证据和状态",
        }]

    research_question = str(
        request.get("research_question")
        or _metadata_value(documents, "research_question")
        or f"{papers_subdir}行业研究的核心判断是什么？"
    ).strip()
    title = str(request.get("title") or _metadata_value(documents, "title") or papers_subdir or tag).strip()
    run = ResearchWorkflowRun.start(
        run_dir=ROOT / "cache" / "research_runs" / tag,
        run_key=tag,
        track=track,
        title=title,
        research_question=research_question,
        request_ref=request_path or f"cache/claims/{tag}_*_claims.json",
        prompt_requirements=prompt_requirements,
        decision_use=request.get("decision_use") or _metadata_value(documents, "decision_use"),
        must_include=_text_list(request.get("must_include") or _metadata_value(documents, "must_include")),
        exclusions=_text_list(request.get("exclusions") or _metadata_value(documents, "exclusions")),
        special_constraints=_text_list(request.get("special_constraints") or _metadata_value(documents, "special_constraints")),
        scope=_mapping_value(request.get("scope") or _metadata_value(documents, "scope")),
        time_window=_mapping_value(request.get("time_window") or _metadata_value(documents, "time_window")),
        required_artifacts=_text_list(request.get("required_artifacts")) or None,
        quality_floor=_mapping_value(request.get("quality_floor"), fallback_key="minimum"),
        replace_existing=True,
    )
    run.record_input_artifacts([*claim_files, *([request_path] if request_path else [])])
    artifacts = {"calculations"} if any(
        str(point.get("extraction_method") or "") == "inferred"
        for document in documents
        for point in document.get("data_points", [])
        if isinstance(point, dict)
    ) else set()
    run.configure_reviews(artifacts=artifacts)
    if missing_b_prompt:
        prompt_requirement = next(item for item in run.brief.requirements if item.origin == "prompt")
        run.record_requirement_coverage(
            prompt_requirement.requirement_id,
            "blocked",
            artifact_refs=[str(path) for path in claim_files],
            note="claims 未携带原始 B 轨 prompt；数据可暂存，但补齐并逐项核对前不得发布。",
        )
    return run, missing_b_prompt


def _record_ingest_gates(
    run: ResearchWorkflowRun,
    *,
    contract_errors: list[dict[str, Any]],
    reference_errors: list[str],
    invalid_records: list[dict[str, Any]],
    artifact_refs: list[str],
    fatal: bool,
) -> None:
    reference_findings = [{"message": message} for message in reference_errors]
    duplicate_findings = [
        item for item in invalid_records
        if any("重复" in str(problem) for problem in item.get("problems", []))
    ]
    scope_findings = [
        item for item in invalid_records
        if any(token in str(problem) for problem in item.get("problems", []) for token in ("metric", "period", "unit"))
    ]
    evidence_findings = [*reference_findings, *invalid_records]

    def verdict(findings: list[Any], *, contract: bool = False) -> str:
        if not findings:
            return "GREEN"
        return "RED" if fatal or contract else "YELLOW"

    run.record_gate("contract", verdict(contract_errors, contract=True), contract_errors, artifact_refs)
    run.record_gate("evidence_integrity", verdict(evidence_findings), evidence_findings, artifact_refs)
    run.record_gate("provenance", verdict(reference_findings), reference_findings, artifact_refs)
    run.record_gate("duplication", verdict(duplicate_findings), duplicate_findings, artifact_refs)
    run.record_gate("scope_and_units", verdict(scope_findings), scope_findings, artifact_refs)


def build_source_index(documents: list[dict[str, Any]]) -> tuple[dict[SourceKey, dict], dict[str, SourceKey]]:
    sources: dict[SourceKey, dict] = {}
    aliases: dict[str, SourceKey] = {}
    for document in documents:
        for source in document.get("sources", []):
            key = source_key(source)
            if key in sources and sources[key] != source:
                left = json.dumps(sources[key], ensure_ascii=False, sort_keys=True)
                right = json.dumps(source, ensure_ascii=False, sort_keys=True)
                if left != right:
                    raise ValueError(f"同一来源键元数据冲突: {key.text()}")
            sources.setdefault(key, source)
            for alias in source_aliases(source):
                if alias in aliases and aliases[alias] != key:
                    raise ValueError(f"source alias 指向多个来源: {alias}")
                aliases[alias] = key
    return sources, aliases


def referenced_source_keys(documents: list[dict[str, Any]], aliases: dict[str, SourceKey]) -> tuple[set[SourceKey], list[str]]:
    used: set[SourceKey] = set()
    errors: list[str] = []
    for document in documents:
        for collection in ("data_points", "key_arguments"):
            for index, row in enumerate(document.get(collection, []), start=1):
                ref = str(row.get("source_file") or row.get("source_ref") or "").strip()
                if not ref or ref not in aliases:
                    errors.append(f"{Path(document['_claim_file']).name}:{collection}[{index}] source ref 无法解析: {ref!r}")
                else:
                    used.add(aliases[ref])
    return used, errors


def register_source(
    conn,
    *,
    source: dict[str, Any],
    key: SourceKey,
    industry_id: int,
    papers_subdir: str,
    by_path: dict[str, int],
    by_url: dict[str, int],
) -> tuple[int, bool]:
    source_type = source.get("source_type") if source.get("source_type") in VALID_SOURCE_TYPES else "其他"
    value_layer = source.get("value_layer") if source.get("value_layer") in VALID_VALUE_LAYERS else "信息流"
    try:
        quality_tier = int(source.get("quality_tier") or 3)
    except (TypeError, ValueError):
        quality_tier = 3
    quality_tier = quality_tier if quality_tier in {1, 2, 3} else 3
    is_primary = bool(source.get("is_primary_source")) or source_type in PRIMARY_SOURCE_TYPES
    language = str(source.get("language") or "zh").strip()
    channel = source_channel(source, key)

    if key.kind == "file":
        _absolute_path, file_path = resolve_source_file(papers_subdir, key.value)
        if file_path in by_path:
            source_id = by_path[file_path]
            created = False
        else:
            source_id = int(conn.execute(
                """
                INSERT INTO source(
                  title,source_type,publisher,publish_date,quality_tier,is_forward_looking,
                  file_path,value_layer,fetch_method,url,source_url,source_credibility,language,
                  is_primary_source,source_subtype,fetch_timestamp,domain,content_snapshot_path
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    source.get("title") or key.value,
                    source_type,
                    source.get("publisher"),
                    normalize_date(source.get("publish_date")),
                    quality_tier,
                    int(bool(source.get("is_forward_looking"))),
                    file_path,
                    value_layer,
                    source.get("fetch_method") or "pdf_local",
                    source.get("source_url"),
                    source.get("source_url"),
                    source.get("source_credibility") or "unverified",
                    language,
                    int(is_primary),
                    source.get("source_subtype") or "research_report",
                    source.get("fetch_timestamp"),
                    source.get("domain"),
                    source.get("content_snapshot_path"),
                ),
            ).lastrowid)
            by_path[file_path] = source_id
            created = True
    else:
        source_url = str(source.get("source_url") or "").strip()
        if source_url and source_url in by_url:
            source_id = by_url[source_url]
            created = False
        else:
            source_id = int(conn.execute(
                """
                INSERT INTO source(
                  title,source_type,publisher,publish_date,quality_tier,is_forward_looking,
                  value_layer,fetch_method,url,source_url,source_credibility,language,
                  is_primary_source,source_subtype,fetch_timestamp,domain,content_snapshot_path
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    source.get("title") or key.value,
                    source_type,
                    source.get("publisher"),
                    normalize_date(source.get("publish_date")),
                    quality_tier,
                    int(bool(source.get("is_forward_looking"))),
                    value_layer,
                    source.get("fetch_method") or "web_search",
                    source_url or None,
                    source_url or None,
                    source.get("source_credibility") or "unverified",
                    language,
                    int(is_primary),
                    source.get("source_subtype") or "web_material",
                    source.get("fetch_timestamp"),
                    source.get("domain") or (urlparse(source_url).netloc if source_url else None),
                    source.get("content_snapshot_path"),
                ),
            ).lastrowid)
            if source_url:
                by_url[source_url] = source_id
            created = True
    # Reused rows must also receive the current provenance fields.  COALESCE
    # preserves a stronger existing value when an older claims file omitted it.
    source_url = str(source.get("source_url") or "").strip() or None
    conn.execute(
        """
        UPDATE source SET
          fetch_timestamp=COALESCE(?,fetch_timestamp),
          domain=COALESCE(?,domain),
          content_snapshot_path=COALESCE(?,content_snapshot_path),
          source_credibility=COALESCE(?,source_credibility),
          source_subtype=COALESCE(?,source_subtype),
          language=COALESCE(?,language),
          is_primary_source=CASE WHEN ?=1 THEN 1 ELSE is_primary_source END
        WHERE id=?
        """,
        (
            source.get("fetch_timestamp"),
            source.get("domain") or (urlparse(source_url).netloc if source_url else None),
            source.get("content_snapshot_path"),
            source.get("source_credibility"),
            source.get("source_subtype"),
            language,
            int(is_primary),
            source_id,
        ),
    )
    if "source_channel" in {row[1] for row in conn.execute("PRAGMA table_info(source)")}:
        conn.execute("UPDATE source SET source_channel=? WHERE id=?", (channel, source_id))
    conn.execute(
        "INSERT OR IGNORE INTO source_entity(source_id,entity_type,entity_id,coverage) VALUES(?,?,?,?)",
        (source_id, "industry", industry_id, "主要覆盖"),
    )
    return source_id, created


def ingest(
    *,
    track: str,
    industry_id: int,
    tag: str,
    papers_subdir: str,
    db_path: str | Path | None = None,
    canon_path: str | Path | None = None,
    workflow_request_path: str | Path | None = None,
    allow_invalid_records: bool = False,
    consensus_failure_policy: str = "raise",
) -> dict[str, Any]:
    files = sorted((ROOT / "cache" / "claims").glob(f"{tag}_*_claims.json"))
    if not files:
        raise FileNotFoundError(f"无 claims 文件: cache/claims/{tag}_*_claims.json")
    content_cache = ContentAddressedCache(ROOT / "cache" / "research_content")
    documents = load_claim_documents(files, cache=content_cache)
    enrich_claim_sources(
        documents,
        papers_subdir=papers_subdir,
        project_root=ROOT,
    )
    sources, aliases = build_source_index(documents)
    used_keys, reference_errors = referenced_source_keys(documents, aliases)
    run, missing_b_prompt = _start_ingest_workflow(
        track=track,
        tag=tag,
        papers_subdir=papers_subdir,
        documents=documents,
        claim_files=files,
        workflow_request_path=workflow_request_path,
    )
    artifact_refs = [str(path) for path in files]
    contract_errors = ([{
        "code": "missing_b_prompt_request",
        "message": "B 轨 claims 未携带原始 prompt 或结构化 workflow request，发布前必须补齐。",
    }] if missing_b_prompt else [])
    if reference_errors and not allow_invalid_records:
        _record_ingest_gates(
            run,
            contract_errors=contract_errors,
            reference_errors=reference_errors,
            invalid_records=[],
            artifact_refs=artifact_refs,
            fatal=True,
        )
        run.record_stage("ingest", "failed", reason="source_reference_validation")
        raise ValueError("claims 来源引用校验失败:\n" + "\n".join(reference_errors[:50]))

    canon: dict[str, str] = {}
    if canon_path:
        path = Path(canon_path)
        if path.exists():
            canon = json.loads(path.read_text(encoding="utf-8"))

    run.record_stage("ingest_intake", "completed", claim_file_count=len(files))

    # Preserve the legacy no-argument contract for the default live database.
    # Passing an explicit path remains available for validated temporary/live
    # targets, while callers and tests that patch ``get_db()`` without a
    # parameter continue to work.
    conn = db_writer.get_db(Path(db_path)) if db_path is not None else db_writer.get_db()
    stats = {
        "sources_new": 0,
        "sources_reused": 0,
        "sources_unused": len(sources) - len(used_keys),
        "data_points_written": 0,
        "data_points_reused": 0,
        "invalid_records": [],
        "key_arguments_written": 0,
        "parallel_research_fact_count": 0,
        "content_cache_hits": sum(
            int(bool(document.get("_content_cache", {}).get("cache_hit"))) for document in documents
        ),
        "content_cache_records": [
            document["_content_cache"] for document in documents if document.get("_content_cache")
        ],
    }
    source_ids: dict[SourceKey, int] = {}
    try:
        conn.execute("BEGIN IMMEDIATE")
        if conn.execute("SELECT 1 FROM industry WHERE id=?", (industry_id,)).fetchone() is None:
            raise ValueError(f"industry_id={industry_id} 不存在")
        by_path = {row["file_path"]: row["id"] for row in conn.execute("SELECT id,file_path FROM source WHERE file_path IS NOT NULL")}
        by_url = {row["source_url"]: row["id"] for row in conn.execute("SELECT id,source_url FROM source WHERE source_url IS NOT NULL")}
        company_cache = {row["name"]: row["id"] for row in conn.execute("SELECT id,name FROM company")}

        for key in sorted(used_keys, key=lambda item: item.text()):
            source_id, created = register_source(
                conn,
                source=sources[key],
                key=key,
                industry_id=industry_id,
                papers_subdir=papers_subdir,
                by_path=by_path,
                by_url=by_url,
            )
            source_ids[key] = source_id
            stats["sources_new" if created else "sources_reused"] += 1

        def canonical_company_name(raw_name: Any) -> str:
            raw = str(raw_name or "").strip()
            return canon.get(raw, raw)

        def company_id(name: str) -> int | None:
            if not name:
                return None
            if name not in company_cache:
                company_cache[name] = int(conn.execute("INSERT INTO company(name) VALUES(?)", (name,)).lastrowid)
            result = company_cache[name]
            conn.execute("INSERT OR IGNORE INTO company_industry(company_id,industry_id) VALUES(?,?)", (result, industry_id))
            return result

        items: list[dict[str, Any]] = []
        key_arguments: dict[int, list[dict[str, Any]]] = {}
        duplicate_keys: set[tuple[Any, ...]] = set()
        parallel_fact_identities: set[tuple[Any, ...]] = set()
        for document in documents:
            for index, row in enumerate(document.get("data_points", []), start=1):
                ref = str(row.get("source_file") or row.get("source_ref") or "").strip()
                key = aliases.get(ref)
                source_id = source_ids.get(key) if key else None
                value_num = to_number(row.get("value_num"))
                raw_text = row.get("value_text")
                value_text = str(raw_text).strip() if raw_text not in (None, "") else None
                metric = str(row.get("metric") or "").strip()
                period = str(row.get("period") or row.get("as_of_date") or "").strip()
                unit = str(row.get("unit") or "").strip()
                excerpt = str(row.get("source_excerpt") or "").strip()
                raw_method = str(row.get("extraction_method") or "").strip()
                method = raw_method
                if not method:
                    method = "web_fetch" if key and key.kind == "url" else "pdf_direct"
                company_name = canonical_company_name(row.get("company"))
                identity = (source_id, company_name or None, metric, period, unit)
                problems = []
                if not source_id:
                    problems.append("source 无法解析")
                if not metric:
                    problems.append("metric 为空")
                if not period:
                    problems.append("period/as_of_date 为空")
                if not unit:
                    problems.append("unit 为空")
                if not excerpt:
                    problems.append("source_excerpt 为空")
                if value_num is None and not value_text:
                    problems.append("value 为空或非有限数值")
                if raw_method and raw_method not in db_writer.VALID_NEW_EXTRACTION_METHODS:
                    problems.append(f"非法 extraction_method: {raw_method}")
                if identity in duplicate_keys:
                    problems.append("同批 source/company/metric/period/unit 重复")
                if method == "inferred" and not str(row.get("note") or "").strip():
                    problems.append("inferred 缺公式或计算口径 note")
                if problems:
                    stats["invalid_records"].append({
                        "file": Path(document["_claim_file"]).name,
                        "index": index,
                        "metric": metric,
                        "problems": problems,
                    })
                    continue
                duplicate_keys.add(identity)
                cid = company_id(company_name)
                scope_key = str(row.get("scope_key") or row.get("research_scope") or "industry").strip()
                parallel_fact_identities.add((source_id, company_name or None, metric, unit, scope_key))
                items.append({
                    "industry_id": industry_id,
                    "metric": metric,
                    "period": period,
                    "unit": unit,
                    "source_id": source_id,
                    "source_excerpt": excerpt,
                    "extraction_method": method,
                    "value_num": value_num,
                    "value_text": None if value_num is not None else value_text,
                    "is_forecast": int(bool(row.get("is_forecast"))),
                    "as_of_date": normalize_date(row.get("as_of_date")),
                    "sentiment": row.get("sentiment") if row.get("sentiment") in VALID_SENTIMENTS else "不适用",
                    "company_id": cid,
                    "note": row.get("note"),
                })

            for index, row in enumerate(document.get("key_arguments", []), start=1):
                ref = str(row.get("source_file") or row.get("source_ref") or "").strip()
                key = aliases.get(ref)
                source_id = source_ids.get(key) if key else None
                argument = str(row.get("argument") or row.get("claim") or "").strip()
                problems = []
                if not source_id:
                    problems.append("source 无法解析")
                if not argument:
                    problems.append("argument/claim 为空")
                if problems:
                    stats["invalid_records"].append({
                        "file": Path(document["_claim_file"]).name,
                        "collection": "key_arguments",
                        "index": index,
                        "problems": problems,
                    })
                    continue
                key_arguments.setdefault(source_id, []).append({
                    "claim": argument,
                    "sentiment": row.get("sentiment", "中性"),
                    "dimension": row.get("dimension", ""),
                })

        if stats["invalid_records"] and not allow_invalid_records:
            raise ValueError(
                f"发现 {len(stats['invalid_records'])} 条无效数据点；默认严格模式不允许静默跳过。"
                + json.dumps(stats["invalid_records"][:20], ensure_ascii=False, indent=2)
            )
        new_items: list[dict[str, Any]] = []
        reused_ids: list[int] = []
        for item in items:
            expected_as_of = item.get("as_of_date") or item["period"]
            existing = conn.execute(
                """
                SELECT id
                  FROM industry_data_point
                 WHERE industry_id=?
                   AND metric=?
                   AND period=?
                   AND unit=?
                   AND source_id=?
                   AND COALESCE(company_id,-1)=COALESCE(?,-1)
                   AND COALESCE(value_num,0)=COALESCE(?,0)
                   AND COALESCE(value_text,'')=COALESCE(?,'')
                   AND is_forecast=?
                   AND COALESCE(as_of_date,'')=COALESCE(?,'')
                   AND sentiment=?
                   AND source_excerpt=?
                   AND COALESCE(note,'')=COALESCE(?,'')
                   AND extraction_method=?
                 ORDER BY id
                 LIMIT 1
                """,
                (
                    item["industry_id"],
                    item["metric"],
                    item["period"],
                    item["unit"],
                    item["source_id"],
                    item.get("company_id"),
                    item.get("value_num"),
                    item.get("value_text"),
                    int(bool(item.get("is_forecast"))),
                    expected_as_of,
                    item.get("sentiment", "不适用"),
                    item["source_excerpt"],
                    item.get("note"),
                    item["extraction_method"],
                ),
            ).fetchone()
            if existing:
                reused_ids.append(int(existing["id"]))
            else:
                new_items.append(item)
        ids = db_writer.bulk_write_data_points(
            conn,
            new_items,
            auto_consensus=False,
            consensus_failure_policy=consensus_failure_policy,
        )
        stats["data_points_written"] = len(ids)
        stats["data_points_reused"] = len(reused_ids)
        stats["parallel_research_fact_count"] = len(parallel_fact_identities)
        for source_id, arguments in key_arguments.items():
            stats["key_arguments_written"] += db_writer.write_key_arguments(conn, source_id, arguments, merge=True)
        try:
            consensus_compute.recompute_all(industry_id, conn=conn)
        except Exception:
            if consensus_failure_policy == "raise":
                raise
        conn.commit()
    except Exception:
        conn.rollback()
        run.record_stage("ingest", "failed")
        _record_ingest_gates(
            run,
            contract_errors=contract_errors,
            reference_errors=reference_errors,
            invalid_records=stats["invalid_records"][:100],
            artifact_refs=artifact_refs,
            fatal=True,
        )
        raise
    finally:
        conn.close()

    run.record_stage(
        "ingest",
        "completed",
        **{k: v for k, v in stats.items() if k not in {"invalid_records", "content_cache_records"}},
    )
    _record_ingest_gates(
        run,
        contract_errors=contract_errors,
        reference_errors=reference_errors,
        invalid_records=stats["invalid_records"][:100],
        artifact_refs=artifact_refs,
        fatal=False,
    )
    manifest_path = run.manifest_path
    source_map_path = ROOT / "cache" / "db_queue" / f"{tag}_source_map.json"
    source_map_path.parent.mkdir(parents=True, exist_ok=True)
    source_map_path.write_text(
        json.dumps({key.text(): value for key, value in source_ids.items()}, ensure_ascii=False, sort_keys=True, indent=2),
        encoding="utf-8",
    )
    return {
        **stats,
        "brief_path": str(run.brief_path),
        "manifest_path": str(manifest_path),
        "source_map_path": str(source_map_path),
    }


def main(default_track: str | None = None) -> None:
    parser = argparse.ArgumentParser(description="A/B 轨统一 claims 入库。")
    parser.add_argument("--track", choices=("a", "b"), default=default_track, required=default_track is None)
    parser.add_argument("--industry-id", type=int, required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--papers-subdir", required=True)
    parser.add_argument(
        "--db",
        default=None,
        help="可选 research.db 路径；省略时使用 live data/research.db，便于在事务一致临时库中先验收。",
    )
    parser.add_argument("--canon", default=None)
    parser.add_argument("--workflow-request", default=None, help="可选 ResearchBrief JSON；B 轨正式发布前必须提供")
    parser.add_argument("--allow-invalid-records", action="store_true")
    parser.add_argument("--consensus-failure-policy", choices=("raise", "warn"), default="raise")
    args = parser.parse_args()
    result = ingest(
        track=args.track,
        industry_id=args.industry_id,
        tag=args.tag,
        papers_subdir=args.papers_subdir,
        db_path=args.db,
        canon_path=args.canon,
        workflow_request_path=args.workflow_request,
        allow_invalid_records=args.allow_invalid_records,
        consensus_failure_policy=args.consensus_failure_policy,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
