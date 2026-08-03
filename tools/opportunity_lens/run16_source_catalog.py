from __future__ import annotations

"""Run16 evidence adapter.

This module only compiles the two independently produced evidence ledgers into
the Opportunity Lens V2 source/data-point contract.  It deliberately contains
no research conclusions, portfolio weights, valuation inputs, or fabricated
translations.
"""

import json
from pathlib import Path
from typing import Any, Iterable

from tools.opportunity_lens.run16_application_industry_research import (
    APPLICATION_INDUSTRY_SOURCES,
)


ROOT = Path(__file__).resolve().parents[2]
WORKPAPER_DIR = (
    ROOT
    / "cache"
    / "research_runs"
    / "opportunity_lens_ai_app_full_chain_portfolio_20260801"
    / "workpapers"
)
APPLICATION_EVIDENCE_PATH = WORKPAPER_DIR / "ai_applications_evidence.json"
FULL_CHAIN_EVIDENCE_PATH = WORKPAPER_DIR / "ai_full_chain_evidence.json"

EXCLUDED_APPLICATION_SOURCE_IDS = {
    # Structured Wind/Tushare/yfinance observations belong to financial.db and
    # the frozen financial artifact, not the C-track source/data-point ledger.
    "M01",
}

TIER_MAP = {
    "academic_primary": "A",
    "academic_research": "A",
    "company_filing_primary": "S",
    "company_filing_secondary_mirror": "B",
    "company_primary": "S",
    "government_primary": "S",
    "industry_association_primary": "A",
    "industry_research_secondary": "B",
    "international_organization": "A",
    "market_research_secondary": "B",
    "multilateral_primary_research": "A",
    "regulator_primary": "S",
    "sell_side_secondary": "C",
    "sell_side_survey_secondary": "C",
}

SECONDARY_MIRROR_DOMAINS = {
    "money.finance.sina.com.cn": "新浪财经（公司公告镜像）",
    "vip.stock.finance.sina.com.cn": "新浪财经（公司公告镜像）",
    "www.cls.cn": "财联社（公司公告转述）",
    "www.cnfin.com": "中国金融信息网（公司公告转述）",
    "paper.cnstock.com": "上海证券报（公司公告转述）",
}


class Run16EvidenceError(ValueError):
    """Raised when an evidence producer output cannot satisfy the V2 contract."""


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise Run16EvidenceError(f"Run16 缺少证据输入：{path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Run16EvidenceError(f"Run16 证据输入无法读取：{path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise Run16EvidenceError(f"Run16 证据输入顶层必须为对象：{path}")
    return payload


def load_evidence_ledgers() -> tuple[dict[str, Any], dict[str, Any]]:
    return _read_json(APPLICATION_EVIDENCE_PATH), _read_json(
        FULL_CHAIN_EVIDENCE_PATH
    )


def _required_text(row: dict[str, Any], key: str, *, row_id: str) -> str:
    value = str(row.get(key) or "").strip()
    if not value:
        raise Run16EvidenceError(f"Run16 证据 {row_id} 缺少 {key}")
    return value


def _source_tier(raw_tier: str, *, row_id: str) -> str:
    try:
        return TIER_MAP[raw_tier]
    except KeyError as exc:
        raise Run16EvidenceError(
            f"Run16 证据 {row_id} 使用未登记来源层级：{raw_tier}"
        ) from exc


def _source_review_status(tier: str) -> str:
    return "pass" if tier in {"S", "A"} else "pass_with_note"


def _carrier_adjustment(
    row: dict[str, Any], *, raw_tier: str, publisher: str
) -> tuple[str, str, str]:
    """Use the actual public carrier when a filing is only linked by a mirror.

    A document may still be a company filing, but a Sina/CLS landing page is not
    the issuer or exchange original.  Keeping that distinction prevents a mirror
    URL from receiving the same evidence tier as an exchange PDF.
    """

    url = str(row.get("url") or "").strip().lower()
    for domain, carrier in SECONDARY_MIRROR_DOMAINS.items():
        if domain in url and raw_tier in {
            "company_primary",
            "company_filing_primary",
        }:
            return "company_filing_secondary_mirror", carrier, publisher
    return raw_tier, publisher, ""


def _language(row: dict[str, Any], *, row_id: str) -> str:
    # The application producer marks every English record explicitly.  Older
    # Chinese rows predate that field, so absence is normalised to Chinese;
    # an unrecognised explicit value still fails.
    value = str(row.get("language") or "zh").strip().lower()
    if value not in {"zh", "en"}:
        raise Run16EvidenceError(
            f"Run16 证据 {row_id} 必须显式标记 language=zh/en"
        )
    return value


def _source_locator(
    row: dict[str, Any], source: dict[str, Any], *, row_id: str
) -> None:
    url = str(row.get("url") or "").strip()
    local_path = str(row.get("local_path") or "").strip()
    if not url and not local_path:
        raise Run16EvidenceError(
            f"Run16 证据 {row_id} 缺少原始 URL 或本地原文定位"
        )
    if url:
        source["url"] = url
    if local_path:
        source["local_path"] = local_path


def _normalise_application_source(row: dict[str, Any]) -> dict[str, Any]:
    row_id = _required_text(row, "id", row_id="application:<missing-id>")
    ref = f"app-{row_id.lower()}"
    language = _language(row, row_id=row_id)
    raw_tier = _required_text(row, "source_tier", row_id=row_id)
    publisher = _required_text(row, "publisher", row_id=row_id)
    raw_tier, publisher, original_issuer = _carrier_adjustment(
        row, raw_tier=raw_tier, publisher=publisher
    )
    tier = _source_tier(raw_tier, row_id=row_id)
    title = _required_text(row, "title", row_id=row_id)
    claim_zh = _required_text(row, "claim_zh", row_id=row_id)
    source: dict[str, Any] = {
        "ref": ref,
        "title": title,
        "publisher": publisher,
        "source_tier": tier,
        "source_review_status": _source_review_status(tier),
        "excerpt": (
            _required_text(row, "excerpt", row_id=row_id)
            if language == "en"
            else claim_zh
        ),
        "language": language,
        "independence_key": _required_text(
            row, "independence_key", row_id=row_id
        ),
        "independence_rationale": _required_text(
            row, "independence_rationale", row_id=row_id
        ),
        "source_channel": _required_text(
            row, "source_channel", row_id=row_id
        ),
        "published_at": str(row.get("date") or "").strip() or None,
        "accessed_at": str(row.get("accessed_at") or "").strip() or None,
        "policy_evidence_role": (
            "core_evidence" if tier in {"S", "A", "B"} else "reference"
        ),
        "original_source_tier": raw_tier,
        "original_issuer": original_issuer or None,
    }
    if source["source_channel"] not in {"report", "web"}:
        raise Run16EvidenceError(
            f"Run16 证据 {row_id} 的 source_channel 必须为 report/web"
        )
    if language == "en":
        source["title_zh"] = _required_text(row, "title_zh", row_id=row_id)
        source["excerpt_zh"] = _required_text(
            row, "excerpt_zh", row_id=row_id
        )
    _source_locator(row, source, row_id=row_id)
    return {key: value for key, value in source.items() if value is not None}


def _normalise_full_chain_source(row: dict[str, Any]) -> dict[str, Any]:
    row_id = _required_text(row, "source_id", row_id="full-chain:<missing-id>")
    ref = f"chain-{row_id.lower()}"
    language = _language(row, row_id=row_id)
    raw_tier = _required_text(row, "source_tier", row_id=row_id)
    publisher = _required_text(row, "publisher", row_id=row_id)
    raw_tier, publisher, original_issuer = _carrier_adjustment(
        row, raw_tier=raw_tier, publisher=publisher
    )
    tier = _source_tier(raw_tier, row_id=row_id)
    excerpt_zh = _required_text(row, "excerpt_zh", row_id=row_id)
    source: dict[str, Any] = {
        "ref": ref,
        "title": _required_text(row, "title", row_id=row_id),
        "publisher": publisher,
        "source_tier": tier,
        "source_review_status": _source_review_status(tier),
        "excerpt": (
            _required_text(row, "excerpt", row_id=row_id)
            if language == "en"
            else excerpt_zh
        ),
        "language": language,
        "independence_key": _required_text(
            row, "independence_key", row_id=row_id
        ),
        "independence_rationale": _required_text(
            row, "independence_rationale", row_id=row_id
        ),
        "source_channel": _required_text(
            row, "source_channel", row_id=row_id
        ),
        "published_at": str(row.get("publish_date") or "").strip() or None,
        "policy_evidence_role": (
            "core_evidence" if tier in {"S", "A", "B"} else "reference"
        ),
        "original_source_tier": raw_tier,
        "original_issuer": original_issuer or None,
    }
    if source["source_channel"] not in {"report", "web"}:
        raise Run16EvidenceError(
            f"Run16 证据 {row_id} 的 source_channel 必须为 report/web"
        )
    if language == "en":
        source["title_zh"] = _required_text(row, "title_zh", row_id=row_id)
        source["excerpt_zh"] = excerpt_zh
    _source_locator(row, source, row_id=row_id)
    return {key: value for key, value in source.items() if value is not None}


def build_sources() -> list[dict[str, Any]]:
    application, full_chain = load_evidence_ledgers()
    app_rows = application.get("evidence")
    chain_rows = full_chain.get("sources")
    if not isinstance(app_rows, list) or not isinstance(chain_rows, list):
        raise Run16EvidenceError("Run16 证据账本缺少 evidence/sources 数组")
    sources = [
        _normalise_application_source(row)
        for row in [*app_rows, *APPLICATION_INDUSTRY_SOURCES]
        if isinstance(row, dict)
        and str(row.get("id") or "") not in EXCLUDED_APPLICATION_SOURCE_IDS
    ]
    sources.extend(
        _normalise_full_chain_source(row)
        for row in chain_rows
        if isinstance(row, dict)
    )
    refs = [str(source["ref"]) for source in sources]
    if len(refs) != len(set(refs)):
        raise Run16EvidenceError("Run16 规范来源 ref 重复")
    return sources


def _app_rows() -> Iterable[dict[str, Any]]:
    application, _ = load_evidence_ledgers()
    for row in [
        *application.get("evidence", []),
        *APPLICATION_INDUSTRY_SOURCES,
    ]:
        if not isinstance(row, dict):
            continue
        if str(row.get("id") or "") in EXCLUDED_APPLICATION_SOURCE_IDS:
            continue
        yield row


def _chain_rows() -> Iterable[dict[str, Any]]:
    _, full_chain = load_evidence_ledgers()
    for row in full_chain.get("sources", []):
        if isinstance(row, dict):
            yield row


def build_data_points() -> list[dict[str, Any]]:
    """Build parallel research points without mislabelling inference.

    The application ledger contains a source fact plus an analyst interpretation
    and counter-boundary.  Those transformed statements are valid research
    points, but they are not verbatim PDF/web extraction and must therefore be
    labelled ``inferred`` with their transformation rule disclosed.
    """

    sources = {str(row["ref"]): row for row in build_sources()}
    points: list[dict[str, Any]] = []
    sequence = 0

    for row in _app_rows():
        row_id = str(row["id"])
        ref = f"app-{row_id.lower()}"
        source = sources[ref]
        candidates = "、".join(str(item) for item in row.get("candidates", []))
        primary_entity_key = str(
            row.get("entity_key") or "ai_application_companies"
        )
        primary_metric = str(
            row.get("metric") or "应用商业化与竞争证据"
        )
        for fact_kind, text, entity_key, metric in (
            (
                "primary_claim",
                _required_text(row, "claim_zh", row_id=row_id),
                primary_entity_key,
                primary_metric,
            ),
            (
                "counterevidence",
                _required_text(row, "counterevidence_zh", row_id=row_id),
                "key_risks",
                "反方证据与适用边界",
            ),
        ):
            sequence += 1
            point: dict[str, Any] = {
                "data_point_key": f"run16.fact.{sequence:03d}",
                "source_ref": ref,
                "entity_key": entity_key,
                "metric": metric,
                "unit": "研究事实",
                "period": str(
                    row.get("date")
                    or (f"访问于{row['accessed_at']}（页面未标注发布日期）" if row.get("accessed_at") else "截至2026-08-02")
                ),
                "scope_key": f"ai_application.{row_id.lower()}.{fact_kind}",
                "value_text": text,
                "source_excerpt": source["excerpt"],
                "extraction_method": "inferred",
                "note": (
                    f"适用公司：{candidates or '行业层面'}；"
                    + (
                        "输入为所引原文及中文译意；按‘主体—时间—数量—商业化环节’抽取，"
                        "再将事实放回付费、交付、壁垒或财务传导链形成研究判断。"
                        if fact_kind == "primary_claim"
                        else "输入为同一原文及其适用范围；按‘原文没有证明什么、跨市场或跨公司"
                        "外推需要什么条件’形成反方边界。"
                    )
                    + "两项仍属于同一独立证据组，不重复提高来源权重。"
                ),
            }
            if str(source["language"]).startswith("en"):
                point["source_excerpt_zh"] = source["excerpt_zh"]
            points.append(point)

    for row in _chain_rows():
        row_id = str(row["source_id"])
        ref = f"chain-{row_id.lower()}"
        source = sources[ref]
        sequence += 1
        point = {
            "data_point_key": f"run16.fact.{sequence:03d}",
            "source_ref": ref,
            "entity_key": "ai_chain_architecture",
            "metric": "全产业链供需、技术与竞争证据",
            "unit": "研究事实",
            "period": str(row.get("publish_date") or "截至2026-08-02"),
            "scope_key": f"ai_full_chain.{row_id.lower()}.source_fact",
            "value_text": _required_text(row, "excerpt_zh", row_id=row_id),
            "source_excerpt": source["excerpt"],
            "extraction_method": "pdf_direct"
            if row.get("source_channel") == "report"
            else "web_fetch",
            "note": "一个底层来源形成一个平行研究事实；未按日期或序列观测拆分计数。",
        }
        if str(source["language"]).startswith("en"):
            point["source_excerpt_zh"] = source["excerpt_zh"]
        points.append(point)

    expected_points = 2 * sum(1 for _ in _app_rows()) + sum(
        1 for _ in _chain_rows()
    )
    if len(points) != expected_points:
        raise Run16EvidenceError(
            f"Run16 平行研究事实应为 {expected_points} 条，当前为 {len(points)} 条；"
            "请检查来源生产结果，不得靠拆分时序补数。"
        )
    identities = {
        (
            point["source_ref"],
            point["entity_key"],
            point["metric"],
            point["unit"],
            point["scope_key"],
        )
        for point in points
    }
    if len(identities) != len(points):
        raise Run16EvidenceError("Run16 平行研究事实身份重复")
    return points


def build_claims() -> list[dict[str, Any]]:
    sources = {str(row["ref"]): row for row in build_sources()}
    claims: list[dict[str, Any]] = []
    sequence = 0
    for row in _app_rows():
        row_id = str(row["id"])
        ref = f"app-{row_id.lower()}"
        primary_entity_key = str(
            row.get("entity_key") or "ai_application_companies"
        )
        for claim_type, claim_text, entity_key in (
            (
                "事实与分析",
                row["claim_zh"],
                primary_entity_key,
            ),
            ("反方证据", row["counterevidence_zh"], "key_risks"),
        ):
            sequence += 1
            claim: dict[str, Any] = {
                "claim_id": f"run16.claim.{sequence:03d}",
                "entity_key": entity_key,
                "source_ref": ref,
                "claim_type": claim_type,
                "claim_text": str(claim_text),
                "source_excerpt": sources[ref]["excerpt"],
            }
            if str(sources[ref]["language"]).startswith("en"):
                claim["source_excerpt_zh"] = sources[ref]["excerpt_zh"]
            claims.append(claim)
    for row in _chain_rows():
        row_id = str(row["source_id"])
        ref = f"chain-{row_id.lower()}"
        sequence += 1
        claim = {
            "claim_id": f"run16.claim.{sequence:03d}",
            "entity_key": "ai_chain_architecture",
            "source_ref": ref,
            "claim_type": "事实与分析",
            "claim_text": str(row["excerpt_zh"]),
            "source_excerpt": sources[ref]["excerpt"],
        }
        if str(sources[ref]["language"]).startswith("en"):
            claim["source_excerpt_zh"] = sources[ref]["excerpt_zh"]
        claims.append(claim)
    return claims


def evidence_summary() -> dict[str, int]:
    sources = build_sources()
    return {
        "source_count": len(sources),
        "independent_source_group_count": len(
            {str(row["independence_key"]) for row in sources}
        ),
        "parallel_data_point_count": len(build_data_points()),
        "report_source_count": sum(
            row["source_channel"] == "report" for row in sources
        ),
        "web_source_count": sum(
            row["source_channel"] == "web" for row in sources
        ),
    }


if __name__ == "__main__":
    print(json.dumps(evidence_summary(), ensure_ascii=False, indent=2))
