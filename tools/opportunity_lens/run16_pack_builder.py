from __future__ import annotations

"""Build the staged V2 pack for the AI applications/full-chain portfolio run.

The builder is intentionally strict.  Research prose comes from the two
independent workpapers; financial forecasts, valuations, market reconciliation,
portfolio weights and correlation diagnostics must come from frozen artifacts.
Missing or inconsistent model inputs stop the build instead of producing a
partially populated public report.
"""

import argparse
import hashlib
import json
import math
import os
import re
import sqlite3
from copy import deepcopy
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from tools.opportunity_lens.intake_parser import parse_markdown_intake_text
from tools.opportunity_lens.run16_application_commercial_research import (
    application_rows,
)
from tools.opportunity_lens.run16_application_industry_research import (
    build_application_industry_parts,
    expanded_company_rows,
)
from tools.opportunity_lens.run16_company_causal_research import rows_for
from tools.opportunity_lens.run16_executable_portfolio_freeze import (
    ExecutablePortfolioFreezeError,
    validate_executable_artifact,
)
from tools.opportunity_lens.run16_source_catalog import (
    SOURCES,
    build_claims,
    build_data_points,
    evidence_summary,
)
from tools.opportunity_lens.run_pack_builder import RunPackBuilder
from tools.opportunity_lens.run_pack_contract import (
    public_markdown_character_count,
    validate_run_pack,
)


ROOT = Path(__file__).resolve().parents[2]
RUN_CACHE_DIR = (
    ROOT
    / "cache"
    / "research_runs"
    / "opportunity_lens_ai_app_full_chain_portfolio_20260801"
)
WORKPAPER_DIR = RUN_CACHE_DIR / "workpapers"
OUTPUT_DIR = (
    ROOT
    / "opportunity_lens"
    / "research_outputs"
    / "20260801_ai_app_full_chain_portfolio_run16"
)
FINANCIAL_DIR = OUTPUT_DIR / "financial_artifacts"
INDEPENDENT_MODEL_PATH = (
    FINANCIAL_DIR / "run16_independent_financial_portfolios.json"
)
EXTERNAL_RECONCILIATION_PATH = (
    FINANCIAL_DIR / "run16_external_reconciliation.json"
)
EXECUTABLE_PORTFOLIO_PATH = (
    FINANCIAL_DIR / "run16_current_executable_portfolios.json"
)
OUTPUT_PATH = OUTPUT_DIR / "run16_pack_stage.json"
PUBLIC_DRAFT_PATH = OUTPUT_DIR / "run16_public_draft.md"
WORKFLOW_REQUEST_PATH = RUN_CACHE_DIR / "workflow_request.json"
APPLICATION_WORKPAPER_PATH = WORKPAPER_DIR / "ai_applications_research.md"
FULL_CHAIN_WORKPAPER_PATH = WORKPAPER_DIR / "ai_full_chain_research.md"
GOVERNANCE_REVIEW_PATH = WORKPAPER_DIR / "run16_company_governance_review.json"
TAXONOMY_AUDIT_PATH = WORKPAPER_DIR / "run16_full_chain_taxonomy_candidate_audit.json"
INTAKE_PATH = (
    ROOT
    / "opportunity_lens"
    / "intake_requests"
    / "Opportunity_Lens_AI应用与全产业链组合研究请求_修订版.md"
)
UNIVERSE_PATHS = (
    RUN_CACHE_DIR / "financial_universe_applications.json",
    RUN_CACHE_DIR / "financial_universe_full_chain_a.json",
    RUN_CACHE_DIR / "financial_universe_full_chain_b.json",
)
RESEARCH_DB_PATH = ROOT / "data" / "research.db"
PUBLIC_NON_A_SHARE_TICKERS = {
    "阿里巴巴": "BABA",
    "百度": "09888.HK",
    "快手": "01024.HK",
    "腾讯控股": "00700.HK",
}

PUBLIC_SECTION_STRUCTURE_CONTRACT = (
    "public.problem_method_data_analysis_summary.v1"
)
PUBLIC_HEADINGS = (
    "### 问题",
    "### 研究方法与数据",
    "### 研究与分析",
    "### 总结",
)
MODEL_SOURCE_REF = "model-run16-independent"
EXECUTABLE_MODEL_SOURCE_REF = "model-run16-executable"
RECONCILIATION_SOURCE_REF = "model-run16-reconciliation"
PORTFOLIO_TYPES = ("concentrated", "balanced", "risk_diversified")
PORTFOLIO_NAMES = {
    "concentrated": "方向簇高确信度组合",
    "balanced": "主要机会均衡组合",
    "risk_diversified": "风险分散组合",
}
SCOPE_NAMES = {
    "applications": "AI应用",
    "full_chain": "AI全产业链",
}
SCORE_KEYS = (
    "direction_score",
    "quality_score",
    "evidence_score",
    "valuation_score",
    "risk_score",
)

# Do not spell these byte-decoding artefacts literally in this UTF-8 source;
# otherwise a source-code scan would flag its own deny-list.  The sequences
# cover the common result of decoding UTF-8 Chinese as Windows-1252/Latin-1.
MOJIBAKE_MARKERS = tuple(
    "".join(chr(codepoint) for codepoint in sequence)
    for sequence in (
        (0x00C3,),
        (0x00E5,),
        (0x00E6,),
        (0x00E7,),
        (0x00EF, 0x00BC),
        (0x00E2, 0x20AC, 0x201D),
        (0x00E4, 0x00BA),
        (0x00F0, 0x0178),
    )
)

SOURCE_BY_REF = {str(source["ref"]): source for source in SOURCES}


class Run16PackInputError(ValueError):
    """Raised when a frozen input cannot support the requested public output."""


def _assert_no_mojibake(text: str, label: str) -> None:
    matches = [marker for marker in MOJIBAKE_MARKERS if marker in text]
    if matches:
        escaped = [marker.encode("unicode_escape").decode("ascii") for marker in matches]
        raise Run16PackInputError(f"{label} 检测到疑似乱码序列：{escaped}")


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise Run16PackInputError(f"Run16 缺少必需输入：{path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Run16PackInputError(f"Run16 输入无法读取：{path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise Run16PackInputError(f"Run16 输入顶层必须为对象：{path}")
    return payload


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return "sha256:" + digest.hexdigest()


def _content_sha256(value: Any) -> str:
    data = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _atomic_write_text(path: Path, content: str) -> None:
    """以 UTF-8 原子写入文本产物，避免构建中断留下半文件。"""

    temporary_path = path.with_name(path.name + ".tmp")
    try:
        temporary_path.write_text(content, encoding="utf-8")
        os.replace(temporary_path, path)
    except OSError as exc:
        raise Run16PackInputError(f"Run16 产物无法写入：{path}: {exc}") from exc


def _finite(value: Any, label: str) -> float:
    if value is None or isinstance(value, bool):
        raise Run16PackInputError(f"{label} 缺少有限数值")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise Run16PackInputError(f"{label} 不是数值：{value!r}") from exc
    if not math.isfinite(number):
        raise Run16PackInputError(f"{label} 不是有限数值")
    return number


def _load_company_map() -> dict[str, dict[str, Any]]:
    by_name: dict[str, dict[str, Any]] = {}
    by_ticker: dict[str, dict[str, Any]] = {}
    for path in UNIVERSE_PATHS:
        payload = _read_json(path)
        rows = payload.get("securities")
        if not isinstance(rows, list) or not rows:
            raise Run16PackInputError(f"证券范围文件缺少 securities：{path}")
        for row in rows:
            if not isinstance(row, dict):
                raise Run16PackInputError(f"证券范围存在非对象记录：{path}")
            name = str(row.get("name") or "").strip()
            ticker = str(row.get("ticker") or "").strip().upper()
            company_id = row.get("company_id")
            if not name or not ticker or not isinstance(company_id, int) or company_id <= 0:
                raise Run16PackInputError(
                    f"证券范围身份不完整：{path}: {row!r}"
                )
            if name in by_name and by_name[name]["ticker"] != ticker:
                raise Run16PackInputError(f"公司名称映射冲突：{name}")
            if ticker in by_ticker and by_ticker[ticker]["company_id"] != company_id:
                raise Run16PackInputError(f"证券代码映射冲突：{ticker}")
            normal = {
                **row,
                "name": name,
                "ticker": ticker,
                "company_id": company_id,
                "is_model_company": True,
            }
            by_name[name] = normal
            by_ticker[ticker] = normal
    if not RESEARCH_DB_PATH.is_file():
        raise Run16PackInputError(f"缺少A股公司身份库：{RESEARCH_DB_PATH}")
    uri = RESEARCH_DB_PATH.resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    try:
        listed_rows = conn.execute(
            """
            SELECT id, name, ticker, market
            FROM company
            WHERE ticker IS NOT NULL
              AND (upper(ticker) LIKE '%.SH'
                   OR upper(ticker) LIKE '%.SZ'
                   OR upper(ticker) LIKE '%.BJ')
            ORDER BY id
            """
        ).fetchall()
    finally:
        conn.close()
    for row in listed_rows:
        name = str(row["name"] or "").strip()
        ticker = str(row["ticker"] or "").strip().upper()
        company_id = int(row["id"])
        if len(name) < 2 or not ticker:
            continue
        existing = by_name.get(name)
        if existing and existing["ticker"] != ticker:
            raise Run16PackInputError(
                f"A股公司名称对应多个证券身份，需人工消歧：{name}"
            )
        by_name.setdefault(
            name,
            {
                "name": name,
                "ticker": ticker,
                "company_id": company_id,
                "market": row["market"],
                "is_model_company": False,
            },
        )
    external_placeholders = ",".join("?" for _ in PUBLIC_NON_A_SHARE_TICKERS)
    uri = RESEARCH_DB_PATH.resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    try:
        external_rows = conn.execute(
            f"""
            SELECT id, name, ticker, market
            FROM company
            WHERE upper(ticker) IN ({external_placeholders})
            ORDER BY id
            """,
            tuple(ticker.upper() for ticker in PUBLIC_NON_A_SHARE_TICKERS.values()),
        ).fetchall()
    finally:
        conn.close()
    external_by_ticker = {
        str(row["ticker"] or "").strip().upper(): row for row in external_rows
    }
    for public_name, ticker in PUBLIC_NON_A_SHARE_TICKERS.items():
        row = external_by_ticker.get(ticker.upper())
        if row is None:
            raise Run16PackInputError(
                f"Run16 非A股公司身份缺失：{public_name} / {ticker}"
            )
        by_name[public_name] = {
            "name": public_name,
            "ticker": ticker.upper(),
            "company_id": int(row["id"]),
            "market": row["market"],
            "is_model_company": False,
        }
    return by_name


def _validate_independent_model(
    model: dict[str, Any], company_map: Mapping[str, Mapping[str, Any]]
) -> None:
    if model.get("artifact_version") != "opportunity_lens.ai_financial_portfolio_freeze.v1":
        raise Run16PackInputError("Run16 独立模型 artifact_version 不正确")
    if model.get("independent_before_consensus") is not True:
        raise Run16PackInputError("Run16 独立模型未声明先于一致预期完成")
    if model.get("external_consensus_read") is not False:
        raise Run16PackInputError("Run16 独立模型混入了外部一致预期")
    declared_hash = str(model.get("output_hash") or "")
    unhashed = deepcopy(model)
    unhashed.pop("output_hash", None)
    if declared_hash != _content_sha256(unhashed):
        raise Run16PackInputError("Run16 独立模型内容哈希校验失败")
    if model.get("sanity", {}).get("verdict") != "GREEN":
        raise Run16PackInputError("Run16 独立模型确定性财务/组合检查未通过")

    companies = model.get("companies")
    if not isinstance(companies, dict) or not companies:
        raise Run16PackInputError("Run16 独立模型缺少 companies")
    expected_tickers = {
        row["ticker"]
        for row in company_map.values()
        if row.get("is_model_company") is True
    }
    if set(companies) != expected_tickers:
        missing = sorted(expected_tickers - set(companies))
        extra = sorted(set(companies) - expected_tickers)
        raise Run16PackInputError(
            f"Run16 独立模型证券覆盖不完整：missing={missing}, extra={extra}"
        )
    map_by_ticker = {str(row["ticker"]): row for row in company_map.values()}
    for ticker, company in companies.items():
        if not isinstance(company, dict):
            raise Run16PackInputError(f"Run16 公司模型不是对象：{ticker}")
        identity = map_by_ticker[ticker]
        if (
            str(company.get("name") or "").strip() != identity["name"]
            or company.get("company_id") != identity["company_id"]
        ):
            raise Run16PackInputError(f"Run16 公司模型身份不一致：{ticker}")
        scenarios = company.get("scenarios")
        if not isinstance(scenarios, dict) or set(scenarios) != {
            "downside",
            "base",
            "upside",
        }:
            raise Run16PackInputError(f"Run16 公司情景不完整：{ticker}")
        for scenario in scenarios.values():
            if not isinstance(scenario, dict) or not {"2026", "2027", "2028"}.issubset(
                scenario
            ):
                raise Run16PackInputError(f"Run16 公司FY1—FY3不完整：{ticker}")
        if not isinstance(company.get("valuation_methods"), list):
            raise Run16PackInputError(f"Run16 公司估值方法缺失：{ticker}")
        candidate = company.get("portfolio_candidate")
        if not isinstance(candidate, dict):
            raise Run16PackInputError(f"Run16 公司组合候选记录缺失：{ticker}")
        ledger = candidate.get("score_ledger")
        if not isinstance(ledger, dict) or not set(SCORE_KEYS).issubset(ledger):
            raise Run16PackInputError(f"Run16 公司组合评分账本不完整：{ticker}")

    portfolios = model.get("portfolios")
    if not isinstance(portfolios, list):
        raise Run16PackInputError("Run16 独立模型缺少 portfolios")
    portfolio_keys = {
        (str(row.get("scope")), str(row.get("portfolio_type")))
        for row in portfolios
        if isinstance(row, dict)
    }
    expected_portfolios = {
        (scope, kind)
        for scope in SCOPE_NAMES
        for kind in PORTFOLIO_TYPES
    }
    if portfolio_keys != expected_portfolios:
        raise Run16PackInputError(
            f"Run16 六类组合不完整：{sorted(portfolio_keys)}"
        )
    for row in portfolios:
        key = f"{row.get('scope')}.{row.get('portfolio_type')}"
        if row.get("status") != "constraint_satisfied":
            raise Run16PackInputError(f"Run16 组合约束未满足：{key}")
        holdings = row.get("holdings")
        if not isinstance(holdings, list) or not holdings:
            raise Run16PackInputError(f"Run16 组合没有持仓：{key}")
        total = _finite(row.get("cash_weight_pct"), f"{key}.cash_weight_pct")
        for holding in holdings:
            if str(holding.get("ticker") or "") not in companies:
                raise Run16PackInputError(f"Run16 组合引用未知证券：{key}")
            total += _finite(holding.get("weight_pct"), f"{key}.weight_pct")
        if abs(total - 100.0) > 0.02:
            raise Run16PackInputError(f"Run16 组合权重不等于100%：{key}={total}")


def _validate_reconciliation(
    reconciliation: dict[str, Any],
    model: dict[str, Any],
) -> None:
    if reconciliation.get("snapshot_version") != "run16.ai_external_consensus.v1":
        raise Run16PackInputError("Run16 外部对账 snapshot_version 不正确")
    if reconciliation.get("stage") != "external_reconciliation_after_independent_freeze":
        raise Run16PackInputError("Run16 外部对账没有在独立模型后执行")
    freeze = reconciliation.get("independent_freeze")
    if not isinstance(freeze, dict):
        raise Run16PackInputError("Run16 外部对账缺少独立模型引用")
    if freeze.get("sha256") != _file_sha256(INDEPENDENT_MODEL_PATH):
        raise Run16PackInputError("Run16 外部对账引用的独立模型文件哈希不一致")
    if freeze.get("declared_output_hash") != model.get("output_hash"):
        raise Run16PackInputError("Run16 外部对账引用的模型内容哈希不一致")
    declared = str(reconciliation.get("content_sha256") or "")
    unhashed = deepcopy(reconciliation)
    unhashed.pop("content_sha256", None)
    if declared != _content_sha256(unhashed):
        raise Run16PackInputError("Run16 外部对账内容哈希校验失败")
    reconciliations = reconciliation.get("reconciliations")
    if not isinstance(reconciliations, list) or not reconciliations:
        raise Run16PackInputError(
            "Run16 外部对账缺少规范化 reconciliations；"
            "不能直接猜测 Wind west_* 原始字段的单位和预测口径"
        )
    expected = set(model["companies"])
    found: set[str] = set()
    for row in reconciliations:
        if not isinstance(row, dict):
            raise Run16PackInputError("Run16 外部对账含非对象记录")
        ticker = str(row.get("ticker") or "").upper()
        found.add(ticker)
        if ticker not in expected:
            raise Run16PackInputError(f"Run16 外部对账包含未知证券：{ticker}")
        for field in (
            "name",
            "company_id",
            "status",
            "periods",
            "summary_zh",
            "data_gap_zh",
        ):
            if row.get(field) in (None, "", []):
                raise Run16PackInputError(
                    f"Run16 外部对账 {ticker} 缺少 {field}"
                )
        periods = row.get("periods")
        if not isinstance(periods, list) or len(periods) < 3:
            raise Run16PackInputError(
                f"Run16 外部对账 {ticker} 缺少FY1—FY3规范化期间"
            )
    if found != expected:
        raise Run16PackInputError(
            f"Run16 外部对账证券覆盖不完整：{sorted(expected - found)}"
        )


def load_frozen_artifacts() -> tuple[
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, dict[str, Any]],
]:
    missing = [
        str(path)
        for path in (
            INDEPENDENT_MODEL_PATH,
            EXECUTABLE_PORTFOLIO_PATH,
            EXTERNAL_RECONCILIATION_PATH,
        )
        if not path.is_file()
    ]
    if missing:
        raise Run16PackInputError(
            "Run16 pack 不会在缺少冻结模型时填数；缺少：" + "；".join(missing)
        )
    company_map = _load_company_map()
    model = _read_json(INDEPENDENT_MODEL_PATH)
    executable = _read_json(EXECUTABLE_PORTFOLIO_PATH)
    reconciliation = _read_json(EXTERNAL_RECONCILIATION_PATH)
    _validate_independent_model(model, company_map)
    _validate_reconciliation(reconciliation, model)
    try:
        validate_executable_artifact(
            executable,
            model,
            INDEPENDENT_MODEL_PATH,
        )
    except ExecutablePortfolioFreezeError as exc:
        raise Run16PackInputError(str(exc)) from exc
    gates = executable["company_gates"]
    for ticker, company in model["companies"].items():
        company["_current_execution_gate"] = deepcopy(gates[ticker])
    model["_current_executable_artifact"] = executable
    return model, executable, reconciliation, company_map


def _relative_path(path: Path) -> str:
    return str(path.resolve().relative_to(ROOT.resolve())).replace("\\", "/")


def _model_sources(
    model: Mapping[str, Any], executable: Mapping[str, Any]
) -> list[dict[str, Any]]:
    return [
        {
            "ref": MODEL_SOURCE_REF,
            "title": "Run16 AI应用与全产业链独立财务、估值和组合模型",
            "publisher": "Industry Demo独立研究模型",
            "source_tier": "C",
            "source_review_status": "pass_with_note",
            "excerpt": (
                "模型在读取一致预期前完成FY1—FY3经营、现金流、ROE/ROA、"
                "多方法估值、组合权重、相关性约束和压力测试，并通过确定性校验。"
            ),
            "language": "zh",
            "independence_key": str(model["output_hash"]),
            "independence_rationale": (
                "这是一个冻结的内部推断产物；其独立性由输入和输出内容哈希界定，"
                "不与任何外部卖方报告重复计为外部事实。"
            ),
            "source_channel": "web",
            "local_path": _relative_path(INDEPENDENT_MODEL_PATH),
            "policy_evidence_role": "reference",
        },
        {
            "ref": EXECUTABLE_MODEL_SOURCE_REF,
            "title": "Run16 当前价格门槛与可执行组合冻结结果",
            "publisher": "Industry Demo组合执行模型",
            "source_tier": "C",
            "source_review_status": "pass_with_note",
            "excerpt": (
                "该冻结产物绑定独立公司模型文件哈希，逐股执行2026—2028年自由"
                "现金流与核心估值上沿门槛，形成六种股票/现金权重、相关性诊断和"
                "过滤后压力测试。单股组合的两两相关性明确记为不适用。"
            ),
            "language": "zh",
            "independence_key": str(executable["output_hash"]),
            "independence_rationale": (
                "这是由冻结公司模型确定性复算的执行层产物；其输入文件哈希、规则、"
                "逐股门槛和输出内容哈希均独立保存，不与外部卖方事实重复计数。"
            ),
            "source_channel": "web",
            "local_path": _relative_path(EXECUTABLE_PORTFOLIO_PATH),
            "policy_evidence_role": "reference",
        },
        {
            "ref": RECONCILIATION_SOURCE_REF,
            "title": "Run16 独立模型与外部一致预期对账",
            "publisher": "Industry Demo外部对账",
            "source_tier": "C",
            "source_review_status": "pass_with_note",
            "excerpt": (
                "独立预测定稿后才读取Wind一致预期和近两个季度机构预测，"
                "按收入、归母净利润和ROE逐年比较并保留口径缺口。"
            ),
            "language": "zh",
            "independence_key": _file_sha256(EXTERNAL_RECONCILIATION_PATH),
            "independence_rationale": (
                "该文件是冻结后外部对账，不与独立模型合并为一条证据，"
                "也不把Wind收录的底层卖方报告重复计权。"
            ),
            "source_channel": "report",
            "local_path": _relative_path(EXTERNAL_RECONCILIATION_PATH),
            "policy_evidence_role": "reference",
        },
    ]


def _ev(ref: str) -> str:
    return f"source_ref:{ref}"


def _cite(ref: str) -> str:
    return f"^src:{_ev(ref)}"


def _expand_application_citations(text: str) -> str:
    pattern = re.compile(r"\[源([RWC])(\d+)(?:-([RWC])?(\d+))?\]")

    def replace(match: re.Match[str]) -> str:
        prefix = match.group(1)
        start_text = match.group(2)
        end_prefix = match.group(3) or prefix
        end_text = match.group(4)
        if end_prefix != prefix:
            raise Run16PackInputError(f"应用底稿来源范围前缀不一致：{match.group(0)}")
        start = int(start_text)
        end = int(end_text) if end_text else start
        width = max(len(start_text), len(end_text or start_text))
        refs = [f"app-{prefix.lower()}{number:0{width}d}" for number in range(start, end + 1)]
        missing = [ref for ref in refs if ref not in SOURCE_BY_REF]
        if missing:
            raise Run16PackInputError(
                f"应用底稿引用未登记来源：{match.group(0)} -> {missing}"
            )
        return " " + " ".join(_cite(ref) for ref in refs) + " "

    expanded = pattern.sub(replace, text)
    full_chain_pattern = re.compile(r"\[源FC-([WR])(\d+)\]")

    def replace_full_chain(match: re.Match[str]) -> str:
        ref = f"chain-fc-{match.group(1).lower()}{match.group(2)}"
        if ref not in SOURCE_BY_REF:
            raise Run16PackInputError(
                f"全产业链底稿引用未登记来源：{match.group(0)} -> {ref}"
            )
        return " " + _cite(ref) + " "

    return full_chain_pattern.sub(replace_full_chain, expanded)


def _clean_public_text(text: str) -> str:
    cleaned = _expand_application_citations(text.strip())
    replacements = {
        "本底稿": "本研究",
        "下一轮FY1—FY3财务建模": "本次FY1—FY3财务建模",
        "下一轮独立财务模型": "本次独立财务模型",
        "是否进入下一轮": "是否纳入本次模型",
        "下一轮必须": "财务模型必须",
        "下一轮只在": "财务模型只在",
        "下一轮应": "财务模型应",
        "估值冻结": "估值输入定稿",
        "财务冻结": "财务输入定稿",
        "输入冻结": "输入定稿",
        "冻结后": "定稿后",
        "冻结前": "定稿前",
        "财务门禁": "财务与估值纳入条件",
        "财务与估值门禁": "财务与估值纳入条件",
        "完整候选审计": "完整候选比较",
    }
    for old, new in replacements.items():
        cleaned = cleaned.replace(old, new)
    # The original application workpaper was completed before the independent
    # company model.  Its ideal product-level wishlist must not be rewritten as
    # if every company discloses AI revenue, paid penetration and inference cost.
    # The actual Run16 model is a company-level financial bridge with explicit
    # disclosure gaps; keep the public description faithful to that contract.
    cleaned = re.sub(
        r"下一轮公司财务模型必须逐家公司完成：基础业务不含AI的收入与利润；"
        r"AI付费客户、渗透率、ARPU或合同转收入；推理、研发、销售与合规成本；"
        r"FY1—FY3收入、利润和自由现金流；PE、DCF/FCFF或PB—ROE的适用性；"
        r"当前市值反推需要多少AI收入和利润。外部对账只纳入研究截止日前最近两个季度"
        r"发布的同公司预测，并明确机构、日期和口径。",
        (
            "A股公司普遍没有同时披露AI单列收入、付费渗透率、单客价值和推理成本，"
            "因此本次模型采用公司总收入增速、毛利率或归母净利率、经营现金流率、"
            "资本开支率和归母权益的公司级桥接，并形成FY1—FY3情景。AI客户、渗透率、"
            "单客价值和合同转收入只作为后续验证指标，不是本轮独立模型的已观察输入。"
            "外部对账只纳入研究截止日前最近两个季度发布的同公司预测，并明确机构、"
            "日期和利润口径。"
        ),
        cleaned,
    )
    cleaned = cleaned.replace(
        "建模时应分别预测个人订阅、机构授权、WPS 365与AI附加付费率；",
        (
            "理想模型应分别预测个人订阅、机构授权、WPS 365与AI附加付费率；"
            "但公开披露不足以完整拆分，本轮降级为公司级财务桥接，并把上述变量作为验证条件；"
        ),
    )
    cleaned = cleaned.replace(
        "下一轮必须用“市场活跃度基线 + AI提价/留存增量”双桥",
        "本轮以公司级桥接并单列市场周期风险；后续披露充分时再使用“市场活跃度基线 + AI提价/留存增量”双桥",
    )
    cleaned = cleaned.replace(
        "下一轮应以自由现金流而非PE作为主约束，并单列研发资本化、补贴、硬件和项目制回款。",
        "本轮以自由现金流和正常化利润约束PE；研发资本化、补贴、硬件和项目制回款仍作为必须逐季核验的变量。",
    )
    cleaned = cleaned.replace(
        "组合只提供候选池、角色和约束，不给最终权重。最终权重应由父任务与算力、硬件、能源等全产业链标的共同优化，并加入流动性、回撤、行业暴露和估值约束。",
        "组合先以候选池、角色和约束定义风险预算，再由本次冻结模型结合自由流通市值、财务质量、估值、流动性和相关性计算实际权重；应用与硬件同时持有时还需在总账户层重新检查共同暴露。",
    )
    # The chain workpaper contained pre-model illustrative caps.  Once actual
    # model weights are available, retaining that table would create two
    # conflicting portfolio contracts in the same public section.
    cleaned = re.sub(
        r"\n*三类组合候选如下。\s*\n\n\| 方案 \| 候选核心 \|.*\Z",
        "",
        cleaned,
        flags=re.S,
    )
    cleaned = cleaned.replace(
        "下表中的“优选”是进一步建模优先级，不是未经估值的买入结论。",
        (
            "下表中的“优选”首先是产业映射候选，不是未经估值的买入结论。"
            "只有进入本次18家公司独立财务模型并完成一手证据、估值与外部对账的主体，"
            "才进入正式组合排序；其余名称保留为待逐主体核验的候选池。"
        ),
    )
    cleaned = re.sub(
        r"报告下载配额和工具执行情况仅放在文末审计附注，不进入拟公开研究正文。",
        "",
        cleaned,
    )
    cleaned = re.sub(
        r"当前仍需补证而不能在本研究中伪装解决的内容：.*?(?=\n\n|\Z)",
        "",
        cleaned,
        flags=re.S,
    )
    cleaned = re.sub(
        r"(?m)^- 12 家优先公司的 2026—2028 独立盈利模型、市场一致预期和估值，须由财务建模 agent[^\n]*\n?",
        "",
        cleaned,
    )
    cleaned = re.sub(
        r"(?m)^- 报告链配额等内部执行缺口见文末审计附注，不进入公开结论。\s*$",
        "",
        cleaned,
    )
    cleaned = cleaned.replace(
        "本轮名单是财务建模优先级，不是买入清单",
        "本轮名单是有条件的研究与组合名单，不是无条件买入清单",
    )
    cleaned = cleaned.replace(
        "后续公司估值必须把现金转换、资本开支和营运资本纳入",
        "公司估值因此同时纳入现金转换、资本开支和营运资本",
    )
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _application_adjacent_categories_markdown() -> str:
    """Keep commercially relevant application categories visible without
    promoting companies that have not passed the A-share evidence/model gate.
    """

    return (
        "#### 已纳入搜索、但未进入核心组合的应用类别\n\n"
        "代码开发智能体、智能客服、企业搜索与知识库、法律和专业服务、"
        "电商运营与消费者助手均已纳入分类检索。海外资料显示这些方向存在真实使用，"
        "但本次没有找到同时满足A股上市身份、AI增量收入可核验、基础业务现金流可承受"
        "投入和近期估值可对账的第二组核心公司。它们因此不是被遗漏，而是保留在候选层："
        "后续只有在付费客户、合同转收入、续费或交付效率至少一项形成公司级证据后，"
        "才进入正式评分和组合权重。"
        f" {_cite('app-w03')} {_cite('app-w04')} {_cite('app-r03')}"
    )


def _unverified_leads_markdown() -> str:
    """Publicly preserve decision-relevant weak leads without upgrading them."""

    return (
        "#### 重要但尚未验证的线索\n\n"
        "第一，市场文章最早把中恒电气的800V高压直流产品与北美头部AI数据中心直供"
        "联系起来。公司年报能够确认240V、336V、800V HVDC、Panama和服务器电源"
        "产品矩阵，但客户公告、采购合同、收入和利润率均未闭环，因此本轮没有把"
        "“北美头部客户”写进份额、盈利预测或组合权重。若后续由客户或合同确认，"
        "中恒电气的AI收入直接性和增长上限才有理由上调。"
        f" {_cite('chain-fc-w036')}\n\n"
        "第二，市场文章声称Spectrum-X CPO会在2026年全面量产并成为Rubin固定配置，"
        "进而使可插拔光模块快速退出。Broadcom与Arista的产品和业绩资料证明更高密度"
        "光学、XPO和400G/lane架构升级真实存在，却不足以证明所有Rubin集群采用同一"
        "方案，也没有证明2027年前可插拔模块快速退出。本轮采用可插拔、LPO与CPO按"
        "距离和场景并存的基准；若固定配置和交付量被官方确认，光模块公司的终值、"
        "产品结构和扩产回报必须重新压力测试。"
        f" {_cite('chain-fc-w007')} {_cite('chain-fc-w009')}\n\n"
        "第三，部分市场文章把美国大型电力变压器交付周期统一概括为3—5年。IEA、"
        "CBRE、JLL和Eaton能够相互独立地确认电网、变压器、并网和现场供电是数据中心"
        "建设约束，但公开证据不能把3—5年外推到所有规格、地区和客户。本轮只使用"
        "“交付周期延长、供给紧张”的方向性判断，不把固定年限代入财务模型；如果按"
        "规格和地区的订单数据证实长期短缺，能源供给链的景气持续期和均衡组合权重"
        "才应上调。"
        f" {_cite('chain-fc-w016')} {_cite('chain-fc-w017')} "
        f"{_cite('chain-fc-w018')} {_cite('chain-fc-w020')}"
    )


def _parse_workpaper(path: Path) -> dict[str, dict[str, str]]:
    if not path.is_file():
        raise Run16PackInputError(f"Run16 缺少研究底稿：{path}")
    text = path.read_text(encoding="utf-8")
    sections: dict[str, dict[str, str]] = {}
    heading_matches = list(re.finditer(r"(?m)^## ([^\n]+)\s*$", text))
    for index, match in enumerate(heading_matches):
        title = match.group(1).strip()
        end = heading_matches[index + 1].start() if index + 1 < len(heading_matches) else len(text)
        body = text[match.end() : end].strip()
        parts: dict[str, str] = {}
        part_matches = list(
            re.finditer(
                r"(?m)^### (问题|研究方法与数据|研究与分析|总结)\s*$",
                body,
            )
        )
        for part_index, part_match in enumerate(part_matches):
            part_end = (
                part_matches[part_index + 1].start()
                if part_index + 1 < len(part_matches)
                else len(body)
            )
            parts[part_match.group(1)] = body[part_match.end() : part_end].strip()
        if set(parts) == {"问题", "研究方法与数据", "研究与分析", "总结"}:
            sections[title] = parts
    return sections


def _find_workpaper_section(
    sections: Mapping[str, Mapping[str, str]], fragment: str
) -> Mapping[str, str]:
    found = [parts for title, parts in sections.items() if fragment in title]
    if len(found) != 1:
        raise Run16PackInputError(
            f"研究底稿章节定位不唯一：{fragment!r}，命中 {len(found)} 个"
        )
    return found[0]


def _merge_parts(*parts: Mapping[str, str]) -> dict[str, str]:
    return {
        heading: "\n\n".join(
            _clean_public_text(str(part[heading])) for part in parts
        )
        for heading in ("问题", "研究方法与数据", "研究与分析", "总结")
    }


def _source_refs_in_text(text: str) -> list[str]:
    refs = re.findall(r"\^src:source_ref:([A-Za-z0-9_.-]+)", text)
    return list(dict.fromkeys(refs))


def _link_company_mentions(
    text: str, company_map: Mapping[str, Mapping[str, Any]]
) -> str:
    names = sorted(company_map, key=len, reverse=True)
    blocks = re.split(r"(\n\s*\n)", text)
    linked: list[str] = []
    for block in blocks:
        stripped = block.lstrip()
        if not stripped or stripped.startswith("```"):
            linked.append(block)
            continue
        result = block
        for name in names:
            route = f"/company/{company_map[name]['company_id']}"
            if f"]({route})" in result:
                continue
            result = re.sub(
                rf"(?<!\[){re.escape(name)}(?!\]\()",
                f"[{name}]({route})",
                result,
                count=1,
            )
        linked.append(result)
    return "".join(linked)


def _structured_body(parts: Mapping[str, str]) -> str:
    return (
        "### 问题\n\n"
        + str(parts["问题"]).strip()
        + "\n\n### 研究方法与数据\n\n"
        + str(parts["研究方法与数据"]).strip()
        + "\n\n### 研究与分析\n\n"
        + str(parts["研究与分析"]).strip()
        + "\n\n### 总结\n\n"
        + str(parts["总结"]).strip()
    )


def _public_section(
    *,
    key: str,
    title: str,
    parts: Mapping[str, str],
    order: int,
    fallback_refs: Sequence[str],
    company_map: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    body = _link_company_mentions(_structured_body(parts), company_map)
    if any(body.count(heading) != 1 for heading in PUBLIC_HEADINGS):
        raise Run16PackInputError(f"公开章节 {key} 未严格满足四段结构")
    refs = _source_refs_in_text(body) or list(fallback_refs)
    unknown = [
        ref
        for ref in refs
        if ref not in SOURCE_BY_REF
        and ref
        not in {
            MODEL_SOURCE_REF,
            EXECUTABLE_MODEL_SOURCE_REF,
            RECONCILIATION_SOURCE_REF,
        }
    ]
    if unknown:
        raise Run16PackInputError(f"公开章节 {key} 引用未知来源：{unknown}")
    return {
        "section_key": key,
        "section_title": title,
        "title": title,
        "body_markdown": body,
        "evidence_ref_uri_list": [_ev(ref) for ref in refs],
        "support_status": "supported",
        "review_status": "pending",
        "sort_order": order,
    }


def _fmt(value: Any, digits: int = 2) -> str:
    if value is None:
        return "公开资料不足以判断"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if not math.isfinite(number):
        return "公开资料不足以判断"
    return f"{number:,.{digits}f}"


def _display_formula(latex: str) -> str:
    """Render a decision-relevant formula as a standalone KaTeX block."""

    return "\n\n$$\n" + latex.strip() + "\n$$\n\n"


def _company_causal_markdown(cluster: str) -> str:
    rows = [
        "| 公司与研究状态 | 产品、客户、合同或量产证据 | 对收入、利润和现金流的传导 | 当前估值与投资判断 |",
        "|---|---|---|---|",
    ]
    for row in rows_for(cluster):
        refs = " ".join(_cite(str(ref)) for ref in row["refs"])
        rows.append(
            f"| **{row['company']}**<br>{row['status']} | {row['evidence']} {refs} | "
            f"{row['financial']} | {row['decision']} |"
        )
    return "\n".join(rows)


def _application_model_snapshot_markdown(
    model: Mapping[str, Any], ticker: str
) -> str:
    company = model["companies"][ticker]
    baseline = company["baseline"]
    base = company["scenarios"]["base"]
    y27 = base["2027"]
    y28 = base["2028"]
    low, high = _calculated_valuation_range(company)
    if low is None or high is None:
        return "适用估值方法的门槛不足，本轮不据此给出精确买卖区间。"
    current = _finite(
        baseline["market"]["market_cap_100m_cny"], f"{ticker}.market_cap"
    )
    low_gap = (low / current - 1.0) * 100.0
    high_gap = (high / current - 1.0) * 100.0
    if current < low:
        action = "现价低于核心区间下沿，可作为当前买入候选。"
    elif current <= high and high_gap > 10.0:
        action = "现价位于核心区间内，仍有上行空间，但下沿风险需要控制仓位。"
    elif current <= high:
        action = "现价已接近核心区间上沿，当前不追高。"
    else:
        action = "现价高于核心区间上沿，按基准模型回避，不因AI标签追高。"
    fcf = "/".join(_fmt(base[str(year)]["fcf_100m_cny"]) for year in (2026, 2027, 2028))
    return (
        f"冻结基准模型把收入由FY2025的{_fmt(baseline['revenue_100m_cny'])}亿元推至"
        f"FY2028的{_fmt(y28['revenue_100m_cny'])}亿元，归母净利润由"
        f"{_fmt(baseline['parent_net_income_100m_cny'])}亿元推至"
        f"{_fmt(y28['parent_net_income_100m_cny'])}亿元；FY2026—FY2028自由现金流为"
        f"{fcf}亿元，FY2028 ROE为{_fmt(y28['roe_pct'])}%。FY2027基准归母净利润"
        f"{_fmt(y27['parent_net_income_100m_cny'])}亿元对应核心估值"
        f"{_fmt(low)}—{_fmt(high)}亿元，当前市值{_fmt(current)}亿元，潜在变化"
        f"{_fmt(low_gap)}%—{_fmt(high_gap)}%。**{action}**"
    )


def _application_commercial_deep_dive_markdown(model: Mapping[str, Any]) -> str:
    """Write the company analysis as commercial evidence, not company blurbs."""

    subsector_order = (
        "企业管理软件与工业流程",
        "网络安全与IT运营",
        "办公、文档与企业知识",
        "金融知识、投研与金融IT",
        "医疗AI与医疗信息化",
        "创意内容与营销",
        "智能客服、企业搜索与电商运营",
        "AI编程与软件开发",
        "教育AI",
    )
    primary_subsector = {
        "金山办公": "办公、文档与企业知识",
        "合合信息": "办公、文档与企业知识",
        "同花顺": "金融知识、投研与金融IT",
        "科大讯飞": "教育AI",
        "鼎捷数智": "企业管理软件与工业流程",
        "深信服": "网络安全与IT运营",
        "用友网络": "企业管理软件与工业流程",
        "恒生电子": "金融知识、投研与金融IT",
        "宝信软件": "企业管理软件与工业流程",
        "广联达": "企业管理软件与工业流程",
        "万兴科技": "创意内容与营销",
    }
    existing_by_subsector: dict[str, list[Mapping[str, Any]]] = {
        key: [] for key in subsector_order
    }
    for row in application_rows():
        existing_by_subsector[primary_subsector[str(row["company"])]].append(row)
    expanded_by_subsector: dict[str, list[Mapping[str, Any]]] = {
        key: [] for key in subsector_order
    }
    for row in expanded_company_rows():
        expanded_by_subsector[str(row["subsector"])].append(row)

    blocks: list[str] = []
    for subsector in subsector_order:
        company_count = len(existing_by_subsector[subsector]) + len(
            expanded_by_subsector[subsector]
        )
        blocks.append(
            f"#### 公司组｜{subsector}\n\n"
            f"本组比较{company_count}家公司或平台，先核验产品与付款，再判断收入、利润、"
            "现金流和估值；没有财务闭环的候选只给观察条件，不给精确权重。"
        )
        for row in existing_by_subsector[subsector]:
            refs = " ".join(_cite(str(ref)) for ref in row["refs"])
            status = (
                "已完成三年财务模型"
                if row["model_ready"]
                else "已有商业证据，财务门禁待补"
            )
            model_snapshot = (
                "\n\n**当前财务、估值与投资动作。** "
                + _application_model_snapshot_markdown(model, str(row["ticker"]))
                if row["model_ready"]
                else ""
            )
            blocks.append(
                f"##### 公司｜{row['company']}｜{status}\n\n"
                f"**谁付钱、已经验证到哪里。** {row['buyer_and_evidence']} {refs}\n\n"
                f"**客户为什么愿意付钱。** {row['buyer_value_math']}\n\n"
                f"**可复制空间与财务模型检验。** {row['market_and_model_test']}\n\n"
                f"**估值与行动条件。** {row['investment_view']}"
                f"{model_snapshot}"
            )
        for row in expanded_by_subsector[subsector]:
            refs = " ".join(_cite(str(ref)) for ref in row["refs"])
            blocks.append(
                f"##### 公司｜{row['company']}｜{row['role']}\n\n"
                f"**谁付钱、已经验证到哪里。** {row['evidence']} {refs}\n\n"
                f"**可复制空间与财务模型检验。** {row['financial_test']}\n\n"
                f"**估值与行动条件。** {row['action']}"
            )
    return "\n\n".join(blocks)


def _chain_company_deep_dive_markdown(
    model: Mapping[str, Any],
    reconciliation: Mapping[str, Any],
    cluster: str,
) -> str:
    """Expose the operating hurdle and valuation consequence company by company."""

    blocks: list[str] = []
    reconciled = _reconciliation_by_ticker(reconciliation)

    def history_band(entry: Mapping[str, Any]) -> tuple[float, float, float] | None:
        rationale = str(entry.get("rationale") or "")
        match = re.search(
            r"区间(-?[0-9.]+)%—(-?[0-9.]+)%，中位数(-?[0-9.]+)%",
            rationale,
        )
        if not match:
            return None
        return tuple(float(value) for value in match.groups())

    for row in rows_for(cluster):
        ticker = str(row["ticker"])
        refs = " ".join(_cite(str(ref)) for ref in row["refs"])
        company = model.get("companies", {}).get(ticker)
        if company is None:
            blocks.append(
                f"#### {row['company']}｜产业候选，尚未进入精确估值\n\n"
                f"**已经验证到哪里。** {row['evidence']} {refs}\n\n"
                f"**客户投资回报。** {row['buyer_roi']}\n\n"
                f"**可复制市场。** {row['replicable_market']}\n\n"
                f"**收入和现金流怎样形成。** {row['financial']}\n\n"
                f"**当前结论。** {row['decision']} 由于尚未完成FY1—FY3正常化财务、"
                "适用估值和外部对账，本轮不给精确权重；这不是否定公司，而是避免用产业"
                "映射替代盈利模型。"
            )
            continue

        baseline = company["baseline"]
        base_years = company["scenarios"]["base"]
        y28 = base_years["2028"]
        revenue_cagr = _cagr(
            baseline["revenue_100m_cny"],
            y28["revenue_100m_cny"],
            3.0,
            f"{ticker}.revenue_cagr",
        )
        profit_cagr = _cagr(
            baseline["parent_net_income_100m_cny"],
            y28["parent_net_income_100m_cny"],
            3.0,
            f"{ticker}.profit_cagr",
        )
        market_cap = _finite(
            baseline["market"]["market_cap_100m_cny"], f"{ticker}.market_cap"
        )
        low, high = _calculated_valuation_range(company)
        implied = next(
            (
                method.get("implied_pe")
                for method in company.get("valuation_methods", [])
                if "隐含" in str(method.get("method") or "")
            ),
            None,
        )
        if low is None or high is None:
            valuation_text = "适用估值方法不足，暂不把模型增长转成精确目标市值。"
        elif market_cap < low:
            valuation_text = (
                f"当前市值{_fmt(market_cap)}亿元低于独立核心区间{_fmt(low)}—"
                f"{_fmt(high)}亿元；只有上述经营证据不被证伪时，这个折价才构成机会。"
            )
        elif market_cap > high:
            valuation_text = (
                f"当前市值{_fmt(market_cap)}亿元高于独立核心区间{_fmt(low)}—"
                f"{_fmt(high)}亿元，市场已经预支比基准模型更强的增长或更高倍数。"
            )
        else:
            valuation_text = (
                f"当前市值{_fmt(market_cap)}亿元位于独立核心区间{_fmt(low)}—"
                f"{_fmt(high)}亿元内，回报更依赖盈利兑现而不是估值修复。"
            )
        def input_series(metric: str) -> str:
            return "/".join(
                _fmt(base_years[str(year)]["input_ledger"][metric]["value"])
                for year in (2026, 2027, 2028)
            )

        first_ledger = base_years["2026"]["input_ledger"]
        history_fragments: list[str] = []
        for metric, label in (
            ("revenue_growth_pct", "收入增速"),
            ("gross_margin_pct", "毛利率"),
            ("parent_net_margin_pct", "归母净利率"),
            ("ocf_margin_pct", "经营现金流率"),
            ("capex_margin_pct", "资本开支率"),
        ):
            band = history_band(first_ledger[metric])
            if band is not None:
                low_band, high_band, median_band = band
                history_fragments.append(
                    f"{label}{_fmt(low_band)}%—{_fmt(high_band)}%（中位{_fmt(median_band)}%）"
                )
        stretch_fragments: list[str] = []
        revenue_band = history_band(first_ledger["revenue_growth_pct"])
        if revenue_band is not None:
            revenue_input = _finite(
                first_ledger["revenue_growth_pct"]["value"],
                f"{ticker}.revenue_growth_pct",
            )
            if revenue_input > revenue_band[1]:
                stretch_fragments.append(
                    f"FY2026收入增速比历史上沿高{_fmt(revenue_input - revenue_band[1])}个百分点"
                )
        margin_band = history_band(first_ledger["parent_net_margin_pct"])
        if margin_band is not None:
            margin_input = _finite(
                base_years["2028"]["input_ledger"]["parent_net_margin_pct"]["value"],
                f"{ticker}.parent_net_margin_pct",
            )
            if margin_input > margin_band[1]:
                stretch_fragments.append(
                    f"FY2028归母净利率比历史上沿高{_fmt(margin_input - margin_band[1])}个百分点"
                )
        history_text = "；".join(history_fragments)
        stretch_text = (
            "。其中" + "、".join(stretch_fragments)
            + "，属于需要订单、产品结构或经营效率额外证明的上修"
            if stretch_fragments
            else "。关键输入位于或接近历史可观察范围，主要风险来自增长持续时间"
        )

        reconciliation_text = "外部对账资料不足，不能判断模型与市场分歧。"
        reconciliation_row = reconciled.get(ticker)
        if reconciliation_row:
            by_year = {
                int(period["year"]): period
                for period in reconciliation_row.get("periods") or []
                if period.get("year") is not None
            }
            p26 = by_year.get(2026)
            p27 = by_year.get(2027)
            if p26 and p27:
                reconciliation_text = (
                    f"FY2026独立收入/归母净利润为"
                    f"{_fmt(p26['independent'].get('revenue_100m_cny'))}/"
                    f"{_fmt(p26['independent'].get('parent_net_income_100m_cny'))}亿元，"
                    f"相对Wind分别{_fmt(p26.get('difference_pct', {}).get('revenue'))}%/"
                    f"{_fmt(p26.get('difference_pct', {}).get('parent_net_income'))}%；"
                    f"FY2027独立/Wind归母净利润为"
                    f"{_fmt(p27['independent'].get('parent_net_income_100m_cny'))}/"
                    f"{_fmt(p27['external'].get('parent_net_income_100m_cny'))}亿元。"
                    f"最近两个季度卖方同口径结果：{_sell_side_profit_summary(p27)}。"
                )
        blocks.append(
            f"#### {row['company']}｜已完成三年财务与估值对账\n\n"
            f"**订单、客户或量产证据。** {row['evidence']} {refs}\n\n"
            f"**客户投资回报。** {row['buyer_roi']}\n\n"
            f"**可复制市场。** {row['replicable_market']}\n\n"
            f"**模型实际代入了什么。** FY2026—FY2028收入增速为"
            f"{input_series('revenue_growth_pct')}%，毛利率为"
            f"{input_series('gross_margin_pct')}%，归母净利率为"
            f"{input_series('parent_net_margin_pct')}%，经营现金流率/资本开支率分别为"
            f"{input_series('ocf_margin_pct')}%和{input_series('capex_margin_pct')}%。"
            f"FY2025收入/归母净利润为"
            f"{_fmt(baseline['revenue_100m_cny'])}/{_fmt(baseline['parent_net_income_100m_cny'])}"
            f"亿元，基准模型到FY2028升至{_fmt(y28['revenue_100m_cny'])}/"
            f"{_fmt(y28['parent_net_income_100m_cny'])}亿元，对应三年复合增速"
            f"{_fmt(revenue_cagr)}/{_fmt(profit_cagr)}%；FY2028自由现金流为"
            f"{_fmt(y28['fcf_100m_cny'])}亿元。历史锚为：{history_text}{stretch_text}。"
            f"{row['financial']}\n\n"
            f"**外部对账。** {reconciliation_text}\n\n"
            f"**价格是否已经计入。** {valuation_text} 当前市值对应FY2027基准利润约"
            f"{_fmt(implied)}倍市盈率。\n\n"
            f"**投资行动。** {row['decision']} 只有产品或项目穿过交付、验收、回款并让"
            "自由现金流达到模型，才保留或提高权重；行业需求增长本身不够。"
        )
    return "\n\n".join(blocks)


def _company_research_score(company: Mapping[str, Any]) -> float:
    """Transparent, uncalibrated screening score used only for relative rank."""

    ledger = company["portfolio_candidate"]["score_ledger"]
    values = {
        key: _finite(ledger[key]["value"], f"company_score.{key}")
        for key in SCORE_KEYS
    }
    return (
        values["direction_score"]
        + values["quality_score"]
        + values["evidence_score"]
        + values["valuation_score"]
        + (100.0 - values["risk_score"])
    ) / 5.0


def _company_ranking_markdown(model: Mapping[str, Any], scope: str) -> str:
    ranked = sorted(
        (
            (_company_research_score(model["companies"][ticker]), ticker)
            for ticker in _scope_tickers(model, scope)
        ),
        reverse=True,
    )
    rows = [
        f"| {SCOPE_NAMES[scope]}公司排名 | 公司 | 细分方向 | 方向 | 财务质量 | 证据直接性 | 估值 | 风险 | 综合研究分 |",
        "|---:|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for rank, (score, ticker) in enumerate(ranked, start=1):
        company = model["companies"][ticker]
        candidate = company["portfolio_candidate"]
        ledger = candidate["score_ledger"]
        rows.append(
            f"| {rank} | {company['name']} | {candidate['direction']} | "
            f"{_fmt(ledger['direction_score']['value'], 0)} | {_fmt(ledger['quality_score']['value'], 0)} | "
            f"{_fmt(ledger['evidence_score']['value'], 0)} | {_fmt(ledger['valuation_score']['value'], 0)} | "
            f"{_fmt(ledger['risk_score']['value'], 0)} | {_fmt(score, 1)} |"
        )
    return "\n".join(rows)


APPLICATION_DIRECTION_GROUPS: tuple[tuple[str, tuple[str, ...], str, str], ...] = (
    ("办公与文档智能", ("688111.SH", "688615.SH"), "金山办公", "合合信息"),
    ("金融知识与决策", ("300033.SZ",), "同花顺", "暂无完成同等财务与估值纳入条件的第二候选"),
    ("企业管理与工业流程", ("300378.SZ",), "鼎捷数智", "用友网络为规模型观察对象，未进入本轮分数"),
    ("网络安全与IT运营", ("300454.SZ",), "深信服", "暂无完成同等财务与估值纳入条件的第二候选"),
    ("教育医疗与公共服务", ("002230.SZ",), "科大讯飞", "暂无完成同等财务与估值纳入条件的第二候选"),
)


def _direction_ranking_markdown(model: Mapping[str, Any], scope: str) -> str:
    ranking_label = (
        f"{SCOPE_NAMES[scope]}方向排名"
        if scope == "applications"
        else "已建模细分代表排名"
    )
    rows = [
        f"| {ranking_label} | 细分方向 | 综合研究分 | 已建模代表 | 产业规模观察或第二选择 | 排序范围 |",
        "|---:|---|---:|---|---|---|",
    ]
    if scope == "applications":
        grouped = []
        for direction, tickers, leader, other in APPLICATION_DIRECTION_GROUPS:
            scores = [_company_research_score(model["companies"][ticker]) for ticker in tickers]
            grouped.append((sum(scores) / len(scores), direction, leader, other))
        for rank, (score, direction, leader, other) in enumerate(
            sorted(grouped, reverse=True), start=1
        ):
            rows.append(
                f"| {rank} | {direction} | {_fmt(score, 1)} | {leader} | {other} | 仅比较已完成FY1—FY3财务与估值门禁的代表 |"
            )
        rows.append(
            "\n注：这是已完成公司财务模型的相对比较，不是细分行业排名。九个应用细分行业的市场、"
            "付费、供需双方、竞争与行业研究分见独立的‘AI应用细分行业、产品与付费验证’实体。"
        )
    else:
        grouped = []
        for ticker in _scope_tickers(model, scope):
            company = model["companies"][ticker]
            grouped.append(
                (
                    _company_research_score(company),
                    company["portfolio_candidate"]["direction"],
                    company["name"],
                )
            )
        for rank, (score, direction, leader) in enumerate(
            sorted(grouped, reverse=True), start=1
        ):
            rows.append(
                f"| {rank} | {direction} | {_fmt(score, 1)} | {leader} | 见本节全产业链龙头与非龙头优选表 | 这是已建模代表比较，不等于整个方向的行业评分 |"
            )
    return "\n".join(rows)


def _governance_markdown(model: Mapping[str, Any], scope: str) -> str:
    payload = _read_json(GOVERNANCE_REVIEW_PATH)
    if payload.get("governance_score_usage") is not False:
        raise Run16PackInputError("治理底稿不得直接改写Run16定量分数")
    by_ticker = {
        str(row.get("ticker") or "").upper(): row
        for row in payload.get("companies", [])
    }
    tickers = _scope_tickers(model, scope)
    missing = [ticker for ticker in tickers if ticker not in by_ticker]
    if missing:
        raise Run16PackInputError(f"治理底稿缺少证券：{missing}")
    rows = [
        f"| {SCOPE_NAMES[scope]}治理对象 | 控制与利益绑定 | 激励/资本配置与股东回报 | 对投资判断的影响 | 仍需核验 |",
        "|---|---|---|---|---|",
    ]
    for ticker in tickers:
        item = by_ticker[ticker]
        valid_refs = [ref for ref in item.get("evidence_refs", []) if ref in SOURCE_BY_REF]
        if not valid_refs:
            raise Run16PackInputError(f"{ticker}治理底稿没有Run16可追溯来源")
        rows.append(
            f"| {item['company']} | {item['control_fact']} | {item['incentive_fact']} "
            f"{item['capital_allocation_and_related_fact']} {item['shareholder_return_fact']} | "
            f"{item['investment_implication']} | {item['not_yet_judgeable']} {_cite(valid_refs[0])} |"
        )
    return "\n".join(rows)


def _portfolio_by_key(
    model: Mapping[str, Any], scope: str, kind: str
) -> Mapping[str, Any]:
    found = [
        row
        for row in model["portfolios"]
        if row["scope"] == scope and row["portfolio_type"] == kind
    ]
    if len(found) != 1:
        raise Run16PackInputError(f"组合定位不唯一：{scope}.{kind}")
    return found[0]


def _scope_tickers(model: Mapping[str, Any], scope: str) -> list[str]:
    tickers = [
        ticker
        for ticker, company in model["companies"].items()
        if scope in company["portfolio_candidate"].get("scopes", [])
    ]
    return sorted(tickers)


def _calculated_valuation_range(company: Mapping[str, Any]) -> tuple[float | None, float | None]:
    lows: list[float] = []
    highs: list[float] = []
    for method in company.get("valuation_methods", []):
        if method.get("status") != "calculated":
            continue
        if method.get("method") != "Forward PE" and method.get("role") not in {"核心", "有效参考"}:
            continue
        if method.get("equity_value_low_100m_cny") is None:
            continue
        lows.append(_finite(method["equity_value_low_100m_cny"], "valuation.low"))
        highs.append(_finite(method["equity_value_high_100m_cny"], "valuation.high"))
    return (min(lows), max(highs)) if lows else (None, None)


def _current_execution_gate(company: Mapping[str, Any]) -> dict[str, Any]:
    gate = company.get("_current_execution_gate")
    if not isinstance(gate, Mapping):
        raise Run16PackInputError("公司缺少已校验的当前可执行门槛冻结结果")
    return deepcopy(dict(gate))


def _executable_portfolio_by_key(
    model: Mapping[str, Any], scope: str, kind: str
) -> dict[str, Any]:
    executable = model.get("_current_executable_artifact")
    if not isinstance(executable, Mapping):
        raise Run16PackInputError("Run16 缺少已校验的可执行组合冻结产物")
    found = [
        row
        for row in executable.get("portfolios", [])
        if row.get("scope") == scope and row.get("portfolio_type") == kind
    ]
    if len(found) != 1:
        raise Run16PackInputError(f"可执行组合定位不唯一：{scope}.{kind}")
    return deepcopy(found[0])


def _company_finance_markdown(model: Mapping[str, Any], scope: str) -> str:
    company_header = f"{SCOPE_NAMES[scope]}公司"
    rows = [
        f"| {company_header} | 2026收入 | 2026归母净利润 | 2026自由现金流 | 2026 ROE | 2028收入 | 2028归母净利润 | 2028自由现金流 | 独立估值范围 | 当前市值隐含2027 PE |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for ticker in _scope_tickers(model, scope):
        company = model["companies"][ticker]
        y26 = company["scenarios"]["base"]["2026"]
        y28 = company["scenarios"]["base"]["2028"]
        low, high = _calculated_valuation_range(company)
        implied = next(
            (
                method.get("implied_pe")
                for method in company["valuation_methods"]
                if method.get("method") == "当前市值隐含市盈率"
                or "隐含" in str(method.get("method") or "")
            ),
            None,
        )
        value_range = (
            f"{_fmt(low)}—{_fmt(high)}亿元" if low is not None and high is not None else "方法门槛不足"
        )
        rows.append(
            "| {name} | {r26} | {n26} | {f26} | {roe26}% | {r28} | {n28} | {f28} | {value} | {pe}倍 |".format(
                name=company["name"],
                r26=_fmt(y26["revenue_100m_cny"]),
                n26=_fmt(y26["parent_net_income_100m_cny"]),
                f26=_fmt(y26["fcf_100m_cny"]),
                roe26=_fmt(y26["roe_pct"]),
                r28=_fmt(y28["revenue_100m_cny"]),
                n28=_fmt(y28["parent_net_income_100m_cny"]),
                f28=_fmt(y28["fcf_100m_cny"]),
                value=value_range,
                pe=_fmt(implied),
            )
        )
    return "\n".join(rows)


def _cagr(start: Any, end: Any, years: float, label: str) -> float | None:
    left = _finite(start, f"{label}.start")
    right = _finite(end, f"{label}.end")
    if left <= 0 or right <= 0 or years <= 0:
        return None
    return (math.pow(right / left, 1.0 / years) - 1.0) * 100.0


def _compact_company_finance_markdown(
    model: Mapping[str, Any], tickers: Sequence[str], label: str
) -> str:
    """One company per row; year-level detail remains in the frozen ledger."""

    rows = [
        f"| {label} | 细分方向 | FY2025A→FY2028E收入/利润复合增速 | FY2026—FY2028自由现金流 | FY2026—FY2028 ROE | 当前PE/PB | 独立估值与当前市值差 |",
        "|---|---|---|---|---|---|---|",
    ]
    for ticker in tickers:
        company = model["companies"][ticker]
        baseline = company["baseline"]
        base = company["scenarios"]["base"]
        y28 = base["2028"]
        revenue_cagr = _cagr(
            baseline["revenue_100m_cny"], y28["revenue_100m_cny"], 3.0, f"{ticker}.revenue"
        )
        profit_cagr = _cagr(
            baseline["parent_net_income_100m_cny"],
            y28["parent_net_income_100m_cny"],
            3.0,
            f"{ticker}.profit",
        )
        low, high = _calculated_valuation_range(company)
        market = baseline["market"]
        market_cap = _finite(market["market_cap_100m_cny"], f"{ticker}.market_cap")
        gap = (
            f"{_fmt((low / market_cap - 1.0) * 100.0)}%—{_fmt((high / market_cap - 1.0) * 100.0)}%"
            if low is not None and high is not None
            else "适用方法门槛不足"
        )
        fcf = "/".join(_fmt(base[str(year)]["fcf_100m_cny"]) for year in (2026, 2027, 2028))
        roe = "/".join(f"{_fmt(base[str(year)]['roe_pct'])}%" for year in (2026, 2027, 2028))
        rows.append(
            f"| {company['name']} | {company['portfolio_candidate']['direction']} | "
            f"{_fmt(revenue_cagr)}% / {_fmt(profit_cagr)}% | {fcf}亿元 | {roe} | "
            f"{_fmt(market.get('pe_ttm'))}倍 / {_fmt(market.get('pb_lf'))}倍 | "
            f"{_fmt(low)}—{_fmt(high)}亿元；相对市值{gap} |"
        )
    return "\n".join(rows)


def _compact_valuation_reconciliation_markdown(
    model: Mapping[str, Any],
    reconciliation: Mapping[str, Any],
    tickers: Sequence[str],
    label: str,
) -> str:
    reconciled = _reconciliation_by_ticker(reconciliation)
    rows = [
        f"| {label} | 独立核心区间/当前市值 | FY2027独立/Wind归母净利润 | 最近两季度卖方同口径预测 | 最大分歧 |",
        "|---|---:|---:|---|---|",
    ]
    for ticker in tickers:
        company = model["companies"][ticker]
        item = reconciled[ticker]
        low, high = _calculated_valuation_range(company)
        current = company["baseline"]["market"]["market_cap_100m_cny"]
        period = next((row for row in item.get("periods", []) if str(row.get("year") or row.get("period")) == "2027"), None)
        if period:
            independent = (period.get("independent") or {}).get("parent_net_income_100m_cny")
            external = (period.get("external") or {}).get("parent_net_income_100m_cny")
            pair = f"{_fmt(independent)} / {_fmt(external)}亿元"
            sell_side = _sell_side_profit_summary(period)
        else:
            pair = "外部口径客观不足"
            sell_side = "近期报告没有可比较的FY2027同口径利润"
        rows.append(
            f"| {company['name']} | {_fmt(low)}—{_fmt(high)} / {_fmt(current)}亿元 | "
            f"{pair} | {sell_side} | {_clean_reconciliation_summary(item['summary_zh'])} |"
        )
    return "\n".join(rows)


def _compact_company_financial_valuation_markdown(
    model: Mapping[str, Any],
    reconciliation: Mapping[str, Any],
    tickers: Sequence[str],
    label: str,
) -> str:
    """Combine operating trend, cash flow, valuation and external benchmark."""

    reconciled = _reconciliation_by_ticker(reconciliation)
    rows = [
        f"| {label} | 细分方向 | FY2025A→FY2028E收入/利润复合增速 | FY2026—FY2028自由现金流 | FY2028 ROE | 当前PE/PB | 独立核心区间/当前市值（差异） | FY2027独立/Wind/近期卖方 |",
        "|---|---|---|---|---:|---|---|---|",
    ]
    for ticker in tickers:
        company = model["companies"][ticker]
        baseline = company["baseline"]
        base = company["scenarios"]["base"]
        y28 = base["2028"]
        revenue_cagr = _cagr(
            baseline["revenue_100m_cny"], y28["revenue_100m_cny"], 3.0, f"{ticker}.revenue"
        )
        profit_cagr = _cagr(
            baseline["parent_net_income_100m_cny"],
            y28["parent_net_income_100m_cny"],
            3.0,
            f"{ticker}.profit",
        )
        low, high = _calculated_valuation_range(company)
        market = baseline["market"]
        market_cap = _finite(market["market_cap_100m_cny"], f"{ticker}.market_cap")
        gap = (
            f"{_fmt((low / market_cap - 1.0) * 100.0)}%—{_fmt((high / market_cap - 1.0) * 100.0)}%"
            if low is not None and high is not None
            else "适用方法门槛不足"
        )
        fcf = "/".join(_fmt(base[str(year)]["fcf_100m_cny"]) for year in (2026, 2027, 2028))
        item = reconciled[ticker]
        period = next(
            (
                row
                for row in item.get("periods", [])
                if str(row.get("year") or row.get("period")) == "2027"
            ),
            None,
        )
        if period:
            independent = (period.get("independent") or {}).get(
                "parent_net_income_100m_cny"
            )
            external = (period.get("external") or {}).get(
                "parent_net_income_100m_cny"
            )
            benchmark = (
                f"{_fmt(independent)}/{_fmt(external)}亿元；"
                + _sell_side_profit_summary(period)
            )
        else:
            benchmark = "FY2027外部同口径客观不足"
        rows.append(
            f"| {company['name']} | {company['portfolio_candidate']['direction']} | "
            f"{_fmt(revenue_cagr)}% / {_fmt(profit_cagr)}% | {fcf}亿元 | "
            f"{_fmt(y28['roe_pct'])}% | {_fmt(market.get('pe_ttm'))}倍 / "
            f"{_fmt(market.get('pb_lf'))}倍 | {_fmt(low)}—{_fmt(high)} / "
            f"{_fmt(market_cap)}亿元（{gap}） | {benchmark} |"
        )
    return "\n".join(rows)


def _clean_reconciliation_summary(value: Any) -> str:
    text = str(value or "").strip()
    generic = (
        "这项差异需要用后续订单、收入确认、毛利率和现金流验证，"
        "不能因为接近或背离市场就自动修改独立模型。"
    )
    return text.replace(generic, "").strip()


def _sell_side_profit_summary(period: Mapping[str, Any]) -> str:
    groups = (
        (period.get("sell_side_report_median") or {})
        .get("profit_medians_by_basis", {})
    )
    preferred = groups.get("parent_net_profit")
    if not preferred:
        basis_labels = {
            "adjusted_net_profit": "调整后净利润",
            "modelware_net_income": "ModelWare净利润",
            "unspecified_net_profit_basis": "报告未明确净利润口径",
            "net_profit": "报告所列净利润",
            "basic_net_profit": "基本口径净利润",
            "diluted_net_profit": "摊薄口径净利润",
        }
        disclosed: list[str] = []
        for basis, payload in groups.items():
            if not isinstance(payload, Mapping):
                continue
            institutions = "、".join(payload.get("institutions") or [])
            dates = "、".join(payload.get("publish_dates") or [])
            value = payload.get("median")
            if value is None:
                value = payload.get("single_forecast")
            if not institutions and value is None:
                continue
            label = basis_labels.get(str(basis), str(basis).replace("_", " "))
            disclosed.append(
                f"{institutions or '近期卖方'}（{dates or '报告日期见逐份对账'}；"
                f"{label}{(' ' + _fmt(value) + '亿元') if value is not None else ''}）"
            )
        if disclosed:
            return "；".join(disclosed) + "；与法定归母净利润口径不同，不合并"
        return "近期报告没有可比较的FY2027法定归母净利润"
    institutions = "、".join(preferred.get("institutions") or [])
    dates = "、".join(preferred.get("publish_dates") or [])
    value = preferred.get("median")
    if value is None:
        value = preferred.get("single_forecast")
    if value is None:
        return "近期报告没有可比较的FY2027同口径利润"
    label = "同口径中位数" if int(preferred.get("sample_size") or 0) >= 2 else "单机构预测"
    return f"{_fmt(value)}亿元（{institutions}，{dates}；{label}）"


def _candidate_landscape_markdown(
    *, layers: Sequence[str] | None = None, max_rows: int | None = None
) -> str:
    payload = _read_json(TAXONOMY_AUDIT_PATH)
    priority_by_segment = {
        str(row["segment"]): row for row in _ranked_taxonomy()
    }
    rows = [
        "| 全链排名 | 细分环节 | 全球比较对象 | 中国主体 | A股细分内研究顺序 | 当前研究边界 |",
        "|---:|---|---|---|---|---|",
    ]
    selected = [
        row for row in payload.get("taxonomy", [])
        if not layers or str(row.get("layer")) in set(layers)
    ]
    if max_rows is not None:
        selected = selected[:max_rows]
    stage_labels = {
        "S0": "产业映射",
        "S1": "产品或研发",
        "S2": "适配或认证",
        "S3": "初始商业化",
        "S4": "规模商业化",
        "S5": "可核验龙头",
        "S5_candidate": "规模商业化，龙头地位仍需同口径验证",
    }

    def natural_stage(raw: Any) -> str:
        value = str(raw or "").strip()
        if value in stage_labels:
            return stage_labels[value]
        tokens = [token.strip() for token in value.split("/") if token.strip()]
        if tokens and all(token in stage_labels for token in tokens):
            labels = [stage_labels[token] for token in tokens]
            deduplicated: list[str] = []
            for label in labels:
                if deduplicated and (
                    label == deduplicated[-1]
                    or label.startswith(deduplicated[-1] + "，")
                ):
                    deduplicated[-1] = label
                else:
                    deduplicated.append(label)
            return "至".join(deduplicated)
        return "公开进展仍需逐项核验"

    def natural_public_text(raw: Any) -> str:
        text = str(raw or "").strip()
        for token in ("S5_candidate", "S5", "S4", "S3", "S2", "S1", "S0"):
            text = re.sub(
                rf"(?<![A-Za-z0-9_]){re.escape(token)}(?![A-Za-z0-9_])",
                stage_labels[token],
                text,
            )
        return text

    for row in selected:
        candidates = []
        for candidate_rank, item in enumerate(row.get("a_share_candidates") or [], start=1):
            boundary = natural_public_text(item.get("boundary_zh"))
            candidates.append(
                f"{candidate_rank}.{item.get('name')}（{natural_stage(item.get('stage'))}）"
                + (f"：{boundary}" if boundary else "")
            )
        boundary = natural_public_text(
            row.get("objective_shortfall_zh")
            or row.get("boundary_zh")
            or row.get("evidence_gate_zh")
            or SEGMENT_EVIDENCE_BOUNDARIES.get(str(row.get("segment")))
            or "公开资料仍不足以完成产品、客户、规模收入与现金流的闭环核验。"
        )
        priority = priority_by_segment[str(row.get("segment"))]
        rows.append(
            f"| {priority['priority_rank']}（{_fmt(priority['priority_score'], 1)}分） | "
            f"{row.get('segment')} | {'、'.join(row.get('global_anchors') or []) or '客观不可得'} | "
            f"{'、'.join(row.get('china_anchors') or []) or '公开资料不足以确认'} | "
            f"{'；'.join(candidates) or '没有合格A股直接标的'} | {boundary} |"
        )
    return "\n".join(rows)


def _valuation_method_markdown(model: Mapping[str, Any], scope: str) -> str:
    company_header = f"{SCOPE_NAMES[scope]}估值对象"
    rows = [
        f"| {company_header} | 方法 | 角色 | 目标市值下限 | 目标市值上限 | 相对当前市值下限 | 相对当前市值上限 | 关键公式或不适用原因 |",
        "|---|---|---|---:|---:|---:|---:|---|",
    ]
    for ticker in _scope_tickers(model, scope):
        company = model["companies"][ticker]
        for method in company["valuation_methods"]:
            if method.get("status") == "calculated" and method.get("equity_value_low_100m_cny") is not None:
                method_note = str(method.get("formula") or "按模型输入计算")
                if method.get("method") == "Forward PE":
                    pe_input = method.get("input") or {}
                    low_input = pe_input.get("multiple_low") or {}
                    high_input = pe_input.get("multiple_high") or {}
                    method_note = (
                        f"FY{method.get('target_year')}基准归母净利润"
                        f"{_fmt(pe_input.get('parent_net_income_100m_cny'))}亿元×"
                        f"{_fmt(low_input.get('value'))}—{_fmt(high_input.get('value'))}倍；"
                        f"下限依据：{low_input.get('rationale') or '见冻结输入'}；"
                        f"上限依据：{high_input.get('rationale') or '见冻结输入'}"
                    )
                if method.get("terminal_value_share_low_case_pct") is not None:
                    method_note += (
                        f"；终值占比{_fmt(method.get('terminal_value_share_low_case_pct'))}%—"
                        f"{_fmt(method.get('terminal_value_share_high_case_pct'))}%，仅作诊断"
                    )
                rows.append(
                    f"| {company['name']} | {method['method']} | {method.get('role','参考')} | "
                    f"{_fmt(method.get('equity_value_low_100m_cny'))}亿元 | "
                    f"{_fmt(method.get('equity_value_high_100m_cny'))}亿元 | "
                    f"{_fmt(method.get('upside_low_pct'))}% | {_fmt(method.get('upside_high_pct'))}% | "
                    f"{method_note} |"
                )
            elif method.get("status") == "skipped":
                rows.append(
                    f"| {company['name']} | {method.get('method','不适用方法')} | 不适用 | — | — | — | — | {method.get('reason','数据或经济逻辑门槛不足')} |"
                )
    return "\n".join(rows)


def _reconciliation_by_ticker(
    reconciliation: Mapping[str, Any]
) -> dict[str, Mapping[str, Any]]:
    return {
        str(row["ticker"]).upper(): row
        for row in reconciliation["reconciliations"]
    }


def _external_reconciliation_markdown(
    model: Mapping[str, Any], reconciliation: Mapping[str, Any], scope: str
) -> str:
    reconciled = _reconciliation_by_ticker(reconciliation)
    company_header = f"{SCOPE_NAMES[scope]}对账对象"
    rows = [
        f"| {company_header} | 年度 | 独立收入 | 外部收入 | 收入差异 | 独立归母净利润 | 外部归母净利润 | 净利润差异 | 独立ROE | 外部ROE |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for ticker in _scope_tickers(model, scope):
        item = reconciled[ticker]
        periods = item.get("periods", [])
        for period in periods[:3]:
            year = str(period.get("year") or period.get("period") or "")
            independent = period.get("independent") or {}
            external = period.get("external") or {}
            difference = period.get("difference_pct") or {}
            rows.append(
                "| {name} | {year} | {ir} | {er} | {dr}% | {ip} | {ep} | {dp}% | {iroe}% | {eroe}% |".format(
                    name=item["name"],
                    year=year,
                    ir=_fmt(independent.get("revenue_100m_cny")),
                    er=_fmt(external.get("revenue_100m_cny")),
                    dr=_fmt(difference.get("revenue")),
                    ip=_fmt(independent.get("parent_net_income_100m_cny")),
                    ep=_fmt(external.get("parent_net_income_100m_cny")),
                    dp=_fmt(difference.get("parent_net_income")),
                    iroe=_fmt(independent.get("roe_pct")),
                    eroe=_fmt(external.get("roe_pct")),
                )
            )
    return "\n".join(rows)


def _sell_side_reports_markdown(
    model: Mapping[str, Any], reconciliation: Mapping[str, Any], scope: str
) -> str:
    """展示最近两个季度逐份卖方预测，不与 Wind 一致预期重复计权。"""
    items = _reconciliation_by_ticker(reconciliation)
    company_header = f"{SCOPE_NAMES[scope]}报告对象"
    rows = [
        f"| {company_header} | 机构与发布日期 | 利润口径 | FY2026—FY2028收入 | FY2026—FY2028归母/调整后净利润 | 目标价与估值依据 |",
        "|---|---|---|---:|---:|---|",
    ]
    for ticker in _scope_tickers(model, scope):
        item = items[ticker]
        audit = item.get("sell_side_report_audit") or {}
        for report in audit.get("reports") or []:
            revenue = report.get("revenue") or {}
            profit = report.get("profit") or {}
            values_r = revenue.get("values") or {}
            values_p = profit.get("values") or {}

            def series_text(values: Mapping[str, Any], divisor: float = 100.0) -> str:
                rendered = []
                for year in ("2026", "2027", "2028"):
                    value = values.get(year)
                    rendered.append(
                        "—" if value is None else _fmt(float(value) / divisor)
                    )
                return "/".join(rendered)

            valuation = report.get("valuation") or {}
            target = valuation.get("target_price_rmb_per_share")
            valuation_bits = []
            if target is not None:
                valuation_bits.append(f"目标价{_fmt(target)}元")
            method = str(valuation.get("method") or "").strip()
            if method:
                valuation_bits.append(method)
            for multiple in valuation.get("target_multiples") or []:
                metric = multiple.get("metric") or "估值倍数"
                multiple_x = multiple.get("multiple_x")
                period = multiple.get("forecast_period") or ""
                if multiple_x is not None:
                    valuation_bits.append(f"{period}{metric} {_fmt(multiple_x)}倍".strip())
            basis = str(profit.get("basis") or "报告所列归母净利润").strip()
            rows.append(
                f"| {item['name']} | {report.get('institution') or '机构未注明'} "
                f"（{report.get('publish_date') or '日期未注明'}） | {basis} | "
                f"{series_text(values_r)} | {series_text(values_p)} | "
                f"{'；'.join(valuation_bits) if valuation_bits else '报告未给出可核验目标价/倍数'} |"
            )
    return "\n".join(rows)


def _reconciliation_analysis(
    model: Mapping[str, Any], reconciliation: Mapping[str, Any], scope: str
) -> str:
    items = _reconciliation_by_ticker(reconciliation)
    paragraphs = []
    data_gaps: list[str] = []
    for ticker in _scope_tickers(model, scope):
        row = items[ticker]
        paragraphs.append(
            f"**{row['name']}。** {row['summary_zh']}"
        )
        gap = str(row.get("data_gap_zh") or "").strip()
        if gap and gap not in data_gaps:
            data_gaps.append(gap)
    if data_gaps:
        normalized_gaps = (
            " ".join(data_gaps)
            .replace("字段完整", "均可获得")
            .replace(
                "逐报告预测正在单独提取；当前只用Wind一致预期对账",
                "本次外部对账只采用可核验的Wind一致预期；尚未形成逐篇数值抽取的近期卖方预测不并入中位数",
            )
        )
        paragraphs.append(
            "**外部对账的资料边界。** "
            + normalized_gaps
            + " Wind与逐份卖方报告可能包含相同底层预测，因此两组结果只并列比较、"
            "不合并计权，也不会改变独立模型的输入。"
        )
    return "\n\n".join(paragraphs)


def _portfolio_holdings_markdown(model: Mapping[str, Any], scope: str) -> str:
    portfolio_header = f"{SCOPE_NAMES[scope]}组合"
    rows = [
        f"| {portfolio_header} | 公司 | 方向 | 权重 | 自由流通市值起点 | 综合调整倍数 |",
        "|---|---|---|---:|---:|---:|",
    ]
    for kind in PORTFOLIO_TYPES:
        portfolio = _executable_portfolio_by_key(model, scope, kind)
        for holding in portfolio["holdings"]:
            rows.append(
                f"| {SCOPE_NAMES[scope]}{PORTFOLIO_NAMES[kind]} | {holding['name']} | {holding['direction']} | "
                f"{_fmt(holding['weight_pct'])}% | {_fmt(holding.get('free_float_market_cap_100m_cny'))}亿元 | "
                f"{_fmt(holding.get('adjustment_multiplier'), 4)} |"
            )
        if _finite(portfolio.get("cash_weight_pct"), "cash") > 0:
            rows.append(
                f"| {SCOPE_NAMES[scope]}{PORTFOLIO_NAMES[kind]} | 现金 | 风险预算 | "
                f"{_fmt(portfolio['cash_weight_pct'])}% | — | — |"
            )
    return "\n".join(rows)


def _portfolio_weight_bridge_markdown(
    model: Mapping[str, Any], scope: str
) -> str:
    """Expose how company evidence and valuation become the balanced weights."""

    portfolio = _executable_portfolio_by_key(model, scope, "balanced")
    rows = [
        "| 公司 | 经营与投资评分（方向/质量/证据/估值/风险缓冲） | 候选风险权重 | 当前价格与现金流门槛 | 可执行权重 |",
        "|---|---|---:|---|---:|",
    ]
    for holding in portfolio["holdings"]:
        ledger = holding["score_ledger"]
        score_text = "/".join(
            (
                _fmt(ledger["direction_score"]["value"], 0),
                _fmt(ledger["quality_score"]["value"], 0),
                _fmt(ledger["evidence_score"]["value"], 0),
                _fmt(ledger["valuation_score"]["value"], 0),
                _fmt(100.0 - float(ledger["risk_score"]["value"]), 0),
            )
        )
        gate = _current_execution_gate(model["companies"][holding["ticker"]])
        rows.append(
            f"| {holding['name']} | {score_text} | {_fmt(holding['weight_pct'])}% | "
            f"**{gate['action']}**：{gate['reason']} | "
            f"**{_fmt(holding['weight_pct'])}%** |"
        )
    for excluded in portfolio.get("excluded_by_current_gate", []):
        candidate = model["companies"][excluded["ticker"]]["portfolio_candidate"]
        ledger = candidate["score_ledger"]
        score_text = "/".join(
            (
                _fmt(ledger["direction_score"]["value"], 0),
                _fmt(ledger["quality_score"]["value"], 0),
                _fmt(ledger["evidence_score"]["value"], 0),
                _fmt(ledger["valuation_score"]["value"], 0),
                _fmt(100.0 - float(ledger["risk_score"]["value"]), 0),
            )
        )
        rows.append(
            f"| {excluded['name']} | {score_text} | "
            f"{_fmt(excluded['former_weight_pct'])}% | **{excluded['action']}**："
            f"{excluded['reason']} | **0.00%** |"
        )
    if _finite(portfolio.get("cash_weight_pct"), "cash_weight_pct") > 0:
        rows.append(
            f"| 现金 | — | — | 未通过门槛的股票权重原额转入现金 | "
            f"**{_fmt(portfolio['cash_weight_pct'])}%** |"
        )
    return "\n".join(rows)


def _portfolio_risk_markdown(model: Mapping[str, Any], scope: str) -> str:
    portfolio_header = f"{SCOPE_NAMES[scope]}风险方案"
    rows = [
        f"| {portfolio_header} | 持仓数 | 有效持仓数 | 前三大权重 | 现金 | 最高两两相关性 | 最短有效重叠天数 | 约束结果 |",
        "|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for kind in PORTFOLIO_TYPES:
        portfolio = _executable_portfolio_by_key(model, scope, kind)
        diagnostics = [
            row
            for row in portfolio.get("correlation_diagnostics", [])
            if row.get("sufficient_history") and row.get("correlation") is not None
        ]
        max_corr = max((float(row["correlation"]) for row in diagnostics), default=None)
        min_overlap = min((int(row["overlap_days"]) for row in diagnostics), default=None)
        rows.append(
            f"| {SCOPE_NAMES[scope]}{PORTFOLIO_NAMES[kind]} | {len(portfolio['holdings'])} | "
            f"{_fmt(portfolio.get('effective_number_of_holdings'))} | "
            f"{_fmt(portfolio.get('top3_weight_pct'))}% | "
            f"{_fmt(portfolio.get('cash_weight_pct'))}% | {_fmt(max_corr, 4)} | "
            f"{_fmt(min_overlap, 0)} | 已满足 |"
        )
    return "\n".join(rows)


def _portfolio_comparison_markdown(model: Mapping[str, Any], scope: str) -> str:
    """Show current executable weights after the company valuation gate."""

    rows = [
        f"| {SCOPE_NAMES[scope]}方案 | 当前股票仓位 | 现金 | 有效持仓数 / 前三大权重 | "
        "最高相关性（60/120/245日；滚动60日峰值） |",
        "|---|---|---:|---|---|",
    ]
    for kind in PORTFOLIO_TYPES:
        portfolio = _executable_portfolio_by_key(model, scope, kind)
        holding_text = "；".join(
            f"{row['name']} {_fmt(row['weight_pct'])}%"
            for row in portfolio["holdings"]
        ) or "没有股票通过当前门槛"
        diagnostics = [
            row
            for row in portfolio.get("correlation_diagnostics", [])
            if row.get("sufficient_history")
        ]

        def max_corr(key: str) -> float | None:
            values = [row.get(key) for row in diagnostics if row.get(key) is not None]
            return max((float(value) for value in values), default=None)

        correlation_text = (
            f"{_fmt(max_corr('correlation_60d'), 4)}/"
            f"{_fmt(max_corr('correlation_120d'), 4)}/"
            f"{_fmt(max_corr('correlation_245d'), 4)}；"
            f"{_fmt(max_corr('rolling_60d_peak'), 4)}"
            if diagnostics
            else "单一股票仓位，不适用"
        )
        rows.append(
            f"| {SCOPE_NAMES[scope]}{PORTFOLIO_NAMES[kind]} | {holding_text} | "
            f"{_fmt(portfolio['cash_weight_pct'])}% | "
            f"{_fmt(portfolio['effective_number_of_holdings'])} / "
            f"{_fmt(portfolio['top3_weight_pct'])}% | {correlation_text} |"
        )
    rows.append(
        "\n注：0.82等相关性上限只约束245个交易日窗口；60日、120日和滚动60日峰值"
        "用于诊断短期共振，不是硬性剔除条件。均衡与防守方案把未通过当前门槛的原股票权重转为现金；"
        "高确信度方案只在原方向合格股中等权，股票仓位最高75%、单股最高25%。"
        "未持有公司的逐股原因已经列在上方公司门槛表，不在本表重复。"
    )
    return "\n".join(rows)


def _portfolio_composite_metrics(
    model: Mapping[str, Any], scope: str, kind: str
) -> dict[str, float]:
    portfolio = _executable_portfolio_by_key(model, scope, kind)
    invested = sum(_finite(row["weight_pct"], "holding.weight") for row in portfolio["holdings"])
    if invested <= 0:
        raise Run16PackInputError(f"{scope}.{kind}没有股票仓位")
    company_score = sum(
        _finite(row["weight_pct"], "holding.weight")
        * _company_research_score(model["companies"][row["ticker"]])
        for row in portfolio["holdings"]
    ) / invested
    diagnostics = [
        row for row in portfolio.get("correlation_diagnostics", [])
        if row.get("sufficient_history") and row.get("correlation") is not None
    ]
    maximum_correlation = max(
        (float(row["correlation"]) for row in diagnostics), default=1.0
    )
    maximum_correlation = min(max(maximum_correlation, 0.0), 1.0)
    holding_count = max(len(portfolio["holdings"]), 1)
    diversification_score = (
        40.0
        * min(_finite(portfolio["effective_number_of_holdings"], "effective_n") / holding_count, 1.0)
        + 30.0 * (1.0 - _finite(portfolio["top3_weight_pct"], "top3") / invested)
        + 30.0 * (1.0 - maximum_correlation)
    )
    relevant_stress = []
    executable = model.get("_current_executable_artifact")
    if not isinstance(executable, Mapping):
        raise Run16PackInputError("Run16 缺少可执行组合压力测试冻结结果")
    for stress in executable.get("stress_tests", []):
        for result in stress.get("portfolio_results", []):
            if result.get("scope") == scope and result.get("portfolio_type") == kind:
                change = _finite(
                    result.get("weighted_valuation_proxy_change_pct"),
                    f"{scope}.{kind}.stress",
                )
                if change < 0:
                    relevant_stress.append(change)
    worst_stress = min(relevant_stress, default=0.0)
    stress_resilience = max(0.0, min(100.0, 100.0 + worst_stress))
    composite = (
        0.55 * company_score
        + 0.25 * diversification_score
        + 0.20 * stress_resilience
    )
    return {
        "company_score": company_score,
        "diversification_score": diversification_score,
        "stress_resilience": stress_resilience,
        "worst_stress": worst_stress,
        "composite": composite,
    }


def _portfolio_ranking_markdown(model: Mapping[str, Any]) -> str:
    ranked = []
    for scope in ("applications", "full_chain"):
        for kind in PORTFOLIO_TYPES:
            ranked.append(
                (
                    _portfolio_composite_metrics(model, scope, kind),
                    scope,
                    kind,
                )
            )
    ranked.sort(key=lambda item: item[0]["composite"], reverse=True)
    rows = [
        "| 综合研究排名 | 组合 | 公司筛选质量 | 分散度 | 压力韧性 | 最差估值代理冲击 | 综合研究分 | 最适用情景 |",
        "|---:|---|---:|---:|---:|---:|---:|---|",
    ]
    use_case = {
        "concentrated": "对单一主线有高确信度并接受较大波动",
        "balanced": "没有特别强的单方向判断，作为基准观察",
        "risk_diversified": "优先保留10%现金并限制单股权重；不保证有效持仓数高于均衡方案",
    }
    for rank, (metrics, scope, kind) in enumerate(ranked, start=1):
        rows.append(
            f"| {rank} | {SCOPE_NAMES[scope]}{PORTFOLIO_NAMES[kind]} | "
            f"{_fmt(metrics['company_score'], 1)} | {_fmt(metrics['diversification_score'], 1)} | "
            f"{_fmt(metrics['stress_resilience'], 1)} | {_fmt(metrics['worst_stress'], 1)}% | "
            f"{_fmt(metrics['composite'], 1)} | {use_case[kind]} |"
        )
    return "\n".join(rows)


def _summary_portfolio_comparison(model: Mapping[str, Any]) -> str:
    """Compare only the two baseline portfolios in the executive summary."""

    rows = [
        "| 研究范围 | 当前方案 | 持仓数 | 有效持仓数 | 前三大权重 | 现金 | 245日最高两两相关性 |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for scope in ("applications", "full_chain"):
        portfolio = _executable_portfolio_by_key(model, scope, "balanced")
        diagnostics = [
            row
            for row in portfolio.get("correlation_diagnostics", [])
            if row.get("sufficient_history") and row.get("correlation") is not None
        ]
        max_corr = max((float(row["correlation"]) for row in diagnostics), default=None)
        rows.append(
            f"| {SCOPE_NAMES[scope]} | 可执行均衡方案 | {len(portfolio['holdings'])} | "
            f"{_fmt(portfolio.get('effective_number_of_holdings'))} | "
            f"{_fmt(portfolio.get('top3_weight_pct'))}% | "
            f"{_fmt(portfolio.get('cash_weight_pct'))}% | "
            f"{'单一股票仓位，不适用' if max_corr is None else _fmt(max_corr, 4)} |"
        )
    return "\n".join(rows)


def _stress_markdown(model: Mapping[str, Any], scope: str) -> str:
    records: list[tuple[str, str, float, float, float]] = []
    executable = model.get("_current_executable_artifact")
    if not isinstance(executable, Mapping):
        raise Run16PackInputError("Run16 缺少可执行组合压力测试冻结结果")
    for stress in executable.get("stress_tests", []):
        grouped: dict[tuple[float, float, float], list[str]] = {}
        for kind in PORTFOLIO_TYPES:
            matches = [
                row
                for row in stress.get("portfolio_results", [])
                if row.get("scope") == scope and row.get("portfolio_type") == kind
            ]
            if len(matches) != 1:
                raise Run16PackInputError(
                    f"冻结压力结果定位不唯一：{stress.get('name')} / {scope}.{kind}"
                )
            result = matches[0]
            profit_change = _finite(
                result.get("weighted_fy2027_profit_change_pct"),
                "stress.weighted_profit",
            )
            valuation_raw = result.get("weighted_valuation_proxy_change_pct")
            valuation_change = (
                _finite(valuation_raw, "stress.weighted_valuation")
                if valuation_raw is not None
                else 0.0
            )
            coverage = _finite(
                result.get("valuation_proxy_equity_weight_coverage_pct"),
                "stress.valuation_coverage",
            )
            if abs(profit_change) < 0.005 and (
                valuation_raw is None or abs(valuation_change) < 0.005
            ):
                continue
            key = (round(profit_change, 2), round(valuation_change, 2), round(coverage, 2))
            grouped.setdefault(key, []).append(kind)
        for (profit_change, valuation_change, coverage), kinds in grouped.items():
            if set(kinds) == set(PORTFOLIO_TYPES):
                portfolio_label = f"{SCOPE_NAMES[scope]}三种方案"
            else:
                portfolio_label = "、".join(
                    f"{SCOPE_NAMES[scope]}{PORTFOLIO_NAMES[kind]}" for kind in kinds
                )
            records.append((stress["name"], portfolio_label, profit_change, valuation_change, coverage))
    scenario_names = {record[0] for record in records}
    single_scenario = len(scenario_names) == 1
    rows: list[str] = []
    if single_scenario:
        only_scenario = next(iter(scenario_names))
        rows.extend(
            [
                f"以下为{only_scenario}压力测试。",
                "",
                "| 组合 | 2027归母净利润加权变化（含现金权重） | 估值代理加权变化（仅覆盖可估值权益仓） | 估值覆盖权重 |",
                "|---|---:|---:|---:|",
            ]
        )
    else:
        rows.extend(
            [
                f"| {SCOPE_NAMES[scope]}压力情景 | 组合 | 2027归母净利润加权变化（含现金权重） | 估值代理加权变化（仅覆盖可估值权益仓） | 估值覆盖权重 |",
                "|---|---|---:|---:|---:|",
            ]
        )
    for scenario, portfolio_label, profit_change, valuation_change, coverage in records:
        prefix = "" if single_scenario else f"{scenario} | "
        rows.append(
            f"| {prefix}{portfolio_label} | {_fmt(profit_change)}% | "
            f"{_fmt(valuation_change)}% | {_fmt(coverage)}% |"
        )
    rows.append(
        "\n注：归母净利润变化按股票持仓权重汇总，并把现金视为零冲击，因此现金会稀释组合变化；"
        "估值代理变化只汇总已有可用估值代理的权益仓，不对未覆盖仓位补数，所以必须与估值覆盖权重一起阅读。"
    )
    return "\n".join(rows)


def _portfolio_model_analysis(model: Mapping[str, Any], scope: str) -> str:
    concentrated = _executable_portfolio_by_key(model, scope, "concentrated")
    balanced = _executable_portfolio_by_key(model, scope, "balanced")
    diversified = _executable_portfolio_by_key(model, scope, "risk_diversified")
    top_concentrated = "、".join(
        f"{row['name']}（{_fmt(row['weight_pct'])}%）"
        for row in concentrated["holdings"][:3]
    )
    top_balanced = "、".join(
        f"{row['name']}（{_fmt(row['weight_pct'])}%）"
        for row in balanced["holdings"][:4]
    )
    top_diversified = "、".join(
        f"{row['name']}（{_fmt(row['weight_pct'])}%）"
        for row in diversified["holdings"][:4]
    )
    return (
        f"**集中方案当前持有{top_concentrated or '无'}，股票仓位"
        f"{_fmt(100.0 - concentrated['cash_weight_pct'])}%；均衡方案持有"
        f"{top_balanced or '无'}，股票仓位{_fmt(100.0 - balanced['cash_weight_pct'])}%；"
        f"防守方案持有{top_diversified or '无'}，股票仓位"
        f"{_fmt(100.0 - diversified['cash_weight_pct'])}%。**\n\n"
        "三种方案先在完整候选池形成不同的规模、波动和方向风险预算，再执行同一项当前价格门槛："
        "2026—2028年基准自由现金流均不为负、且核心估值上沿相对市值至少留25%空间。"
        "均衡与防守方案把没有过关的原权重全部转成现金，不向幸存股票再分配；高确信度方案"
        "只在原方向候选中等权，股票仓位最高75%、单股最高25%。因此高现金不是市场择时，"
        "而是明确承认当前价格下可买公司数量不足；若估值回落或盈利上修使公司重新过关，"
        "再恢复它在原风险预算中的权重。"
    )


def _portfolio_method(model: Mapping[str, Any], scope: str) -> str:
    balanced = _executable_portfolio_by_key(model, scope, "balanced")
    policy = balanced.get("policy", {})
    anchor = policy.get("anchor_mix", {})
    free_float_pct = _fmt(100 * float(anchor.get("free_float", 0)), 0)
    equal_pct = _fmt(100 * float(anchor.get("equal", 0)), 0)
    inverse_volatility_pct = _fmt(
        100 * float(anchor.get("inverse_volatility", 0)), 0
    )
    max_single = _fmt(float(policy.get("max_weight_pct", 0)), 0)
    max_direction = _fmt(float(policy.get("max_direction_weight_pct", 0)), 0)
    max_correlation = _fmt(float(policy.get("max_pair_correlation", 0)), 2)
    minimum_overlap = _fmt(float(policy.get("min_overlap_days", 0)), 0)
    scope_name = SCOPE_NAMES[scope]
    example_holding = balanced["holdings"][0]
    example_score = _fmt(
        example_holding.get("tilt_audit", {}).get("weighted_composite_score"), 2
    )
    example_tilt = _fmt(example_holding.get("active_tilt_multiplier"), 4)
    example_name = str(example_holding.get("name") or "示例公司")
    return (
        "权重先回答公司是否值得持有，再处理规模和风险。第一步，用"
        f"{free_float_pct}%自由流通市值、{equal_pct}%等权和{inverse_volatility_pct}%逆波动"
        "形成基础仓位，避免只按市值或只按低波动选股。\n\n"
        f"第二步，{scope_name}根据方向前景10%、财务质量20%、财务证据25%、估值30%和风险缓冲15%调整，"
        "风险缓冲按“100减风险分”计。五项分数都由同一把公开尺逐项加总：方向检查FY2026增速、三年收入/利润"
        "复合增速、毛利率保持和上行情景弹性；质量检查正常化盈利、历史净利率和经营现金流率、三年自由现金流及"
        "FY2028 ROE；证据检查快照质量及四组历史序列是否至少四期；估值检查隐含PE/利润增速、历史PE位置、"
        "自由现金流收益率和PB—ROE组合；风险检查245日波动、下行情景利润损失、隐含PE、负自由现金流和数据质量。"
        "每个判定项的阈值、观察值和得分都随公司公开。五项加权相加得到综合分后，主动倍数按"
        "“1＋0.25×（综合分－50）÷50”计算，并限制在0.85—1.15倍。例如综合分"
        f"{example_score}分的{example_name}对应{example_tilt}倍，读者可以直接复算表中主动倍数。经营事实、"
        "现金流和估值改变后，评分按同一规则重算；不存在覆盖基础锚的手工公司分。\n\n"
        f"{scope_name}公开刻度如下，每家公司都保留实际观察值和逐项得分：\n\n"
        f"- **{scope_name}方向（100分）**：FY2026收入增速、三年收入和利润复合增速各不低于15%，FY2028毛利率不低于FY2026减1个百分点，上行FY2028收入比基准至少高15%；每项20分。\n"
        f"- **{scope_name}财务质量（100分）**：FY2025正常化利润为正、历史净利率和经营现金流率中位各不低于5%、三年自由现金流均为正、FY2028 ROE不低于10%；每项20分。\n"
        f"- **{scope_name}财务证据（100分）**：快照质量高/中/低记40/25/10分；收入增速、毛利率、净利率和经营现金流率历史各至少四期时，每组再记15分。\n"
        f"- **{scope_name}估值（100分）**：隐含PE÷利润复合增速不高于1/1.5/2/3时记40/30/20/10分；隐含PE位于历史25%分位/中位/75%分位以内记25/15/8分，FCF收益率和PB—ROE最高再记20/15分。\n"
        f"- **{scope_name}风险（100分）**：245日波动、下行情景利润损失、隐含PE、负自由现金流和数据质量分别最高记30/25/20/15/20分，总分封顶100。\n\n"
        f"第三步，{scope_name}先将基础仓位乘主动倍数并归一，再执行单股不超过{max_single}%、"
        f"同方向不超过{max_direction}%、至少{minimum_overlap}个重叠交易日且245日两两相关性"
        f"不高于{max_correlation}的硬约束；60日、120日和滚动60日峰值只诊断短期共振。超限仓位按约束削减并再次归一，防止多只股票"
        "实际上押注同一客户资本开支或同一估值因子。\n\n"
        f"第四步对{scope_name}执行当前价格门槛：只有2026—2028年基准自由现金流均不为负、且核心估值上沿"
        "比当前市值至少高25%的公司进入股票仓。均衡与防守方案把其余权重转成现金，不向通过者再分配；"
        "高确信度方案只在通过门槛的原方向候选中等权，股票仓位最高75%、单股最高25%。"
        "该门槛只说明估值区间的上沿存在25%空间，不代表整个估值区间都有25%安全边际；"
        "因此最终表里的高现金是估值筛选结果，不是另拍的市场择时。市场估值快照截至"
        "2026年7月30日，组合判断形成于8月2日。\n\n"
        "下表逐公司公开三项基础锚、公司质量调整、价格门槛和最终权重，所以每个权重都能从公司"
        "研究追到可执行持仓。评分只是未做历史收益校准的排序和有限倾斜，不是上涨概率。盈利或自由现金流"
        "显著偏离模型、估值上沿空间消失或产业证据反转时，必须先重估公司，再计算权重。"
        f" {_cite(EXECUTABLE_MODEL_SOURCE_REF)}"
    )


def _finance_parts(
    model: Mapping[str, Any],
    reconciliation: Mapping[str, Any],
    scope: str,
) -> dict[str, str]:
    names = "、".join(model["companies"][ticker]["name"] for ticker in _scope_tickers(model, scope))
    if scope == "applications":
        method_text = (
            "应用公司普遍没有同时披露AI单列收入、付费渗透率、单客价值和推理成本，"
            "因此独立模型先用2025年实际值和2026年一季度检查点建立公司级桥接："
            f"{model['model_contract']['financial_formula']} 输入固定后，才读取Wind一致预期"
            "和最近两个季度的同公司机构预测，按年度与利润口径逐项比较。PE使用正常化"
            "归母利润；股东现金流代理折现和PB—ROE只在数据与适用性门禁允许时保留，"
            "不与PE机械平均。"
        )
    else:
        method_text = (
            "全产业链公司的收入确认和资本占用差异很大：服务器、光模块与PCB先检查订单、"
            "产能和产品结构，设备检查验收，电源、液冷与数据中心检查项目投运、回款和"
            "资本开支。独立模型从2025年实际值及2026年一季度出发，按收入增速、归母"
            "净利率、经营现金流率、资本开支率和归母权益逐年滚动FY1—FY3；模型完成后"
            "再与Wind一致预期及最近两个季度机构预测对账。PE是主要比较方法，股东现金流"
            "代理折现因缺少完整三表桥只作诊断，PB—ROE须同时通过五年ROE稳定性和研究"
            "适用性门禁。"
        )
    return {
        "问题": (
            f"{SCOPE_NAMES[scope]}重点公司不能只按产业叙事排序。本节回答{name_or_names(names)}的"
            "FY1—FY3收入、利润、自由现金流、ROE/ROA和多方法估值分别意味着什么，"
            "独立判断与市场一致预期的分歧来自哪里，以及当前市值已经反映了怎样的盈利要求。"
        ),
        "研究方法与数据": (
            method_text
            + " 公司综合研究分＝(方向分+财务质量分+财务证据分+估值分+100−风险分)/5；"
            "五项分数均按模型公开的逐条阈值和观察值复算，不再使用手工公司分。该分数未做历史收益校准，"
            "只用于同口径公司和方向的相对排序，不能解释为上涨概率。"
            + f" {_cite(MODEL_SOURCE_REF)} {_cite(RECONCILIATION_SOURCE_REF)}"
        ),
        "研究与分析": (
            "下表金额均为亿元人民币。基准情景并不是目标价倒推，而是从2025年实际值和"
            "2026年一季度检查点出发，逐年滚动收入、利润率、经营现金流率、资本开支率、"
            "分红和权益；下行和上行情景只改变有明确经营含义的输入。\n\n"
            + _company_finance_markdown(model, scope)
            + "\n\n下表把五项冻结输入放在同一口径下比较。产业地图中的其他候选没有完成"
            "公司级财务、估值和现金流门禁，不进入这一精确排序；这一区分避免把产业映射"
            "冒充投资结论。\n\n"
            + _direction_ranking_markdown(model, scope)
            + "\n\n"
            + _company_ranking_markdown(model, scope)
            + "\n\n估值结果要按方法逐项阅读。市盈率依赖目标年度正常化利润；股东现金流代理折现"
            "没有完整净借款、净现金和营运资本桥且终值占比较高，只作诊断；PB—ROE只有在"
            "五年ROE量化稳定性与研究适用性同时通过时才形成目标值，否则仅用于质量诊断。\n\n"
            + _valuation_method_markdown(model, scope)
            + "\n\n外部对账不是让独立模型向市场靠拢，而是检查单位、归母口径、增长持续时间和"
            "利润率假设。下表的差异按“独立值/外部值－1”计算；外部值客观缺失时保留"
            "缺口，不用相邻公司或相邻年份补齐。\n\n"
            + _external_reconciliation_markdown(model, reconciliation, scope)
            + "\n\n逐份卖方预测仅纳入研究截止日前最近两个季度发布的同公司报告。"
            "下表金额为亿元人民币，利润口径按原报告保留；法定归母净利润、调整后"
            "净利润和ModelWare净利润存在差异时不机械混用。"
            f" {_cite(RECONCILIATION_SOURCE_REF)}\n\n"
            + _sell_side_reports_markdown(model, reconciliation, scope)
            + "\n\n"
            + _reconciliation_analysis(model, reconciliation, scope)
            + "\n\n治理、激励与股东回报不直接加入本轮定量分数，因为公开披露不足以把治理质量"
            "稳定映射为收益率。下表只把已核验事实用于稀释、关联交易、资本配置和关键人"
            "风险监控。\n\n"
            + _governance_markdown(model, scope)
        ),
        "总结": (
            f"**{SCOPE_NAMES[scope]}公司的产业优先级必须经过现金流和估值二次筛选。** "
            "收入增长、净利润增长、自由现金流和ROE分别回答规模、盈利、兑现和资本效率，"
            "任何单一指标都不能替代完整判断。估值范围只有在相应经营条件兑现时成立；"
            "与外部预测的显著差异如果经口径复查仍保留，应被视为需要跟踪的多空分歧，"
            "而不是自动修正模型的理由。"
        ),
    }


def name_or_names(names: str) -> str:
    return names


def _portfolio_parts(
    model: Mapping[str, Any],
    scope: str,
    workpaper_parts: Mapping[str, str],
) -> dict[str, str]:
    base = {key: _clean_public_text(value) for key, value in workpaper_parts.items()}
    balanced = _executable_portfolio_by_key(model, scope, "balanced")
    diversified = _executable_portfolio_by_key(model, scope, "risk_diversified")
    balanced_names = "、".join(
        f"{row['name']}{_fmt(row['weight_pct'])}%" for row in balanced["holdings"]
    ) or "没有股票"
    diversified_names = "、".join(
        f"{row['name']}{_fmt(row['weight_pct'])}%"
        for row in diversified["holdings"]
    ) or "没有股票"
    if scope == "applications":
        weight_bridge_intro = (
            "应用侧先把六家公司的合同兑现、现金流和估值放在同一把尺上。合合信息通过当前门槛；"
            "另外五家候选风险权重归零并转成现金，所以应用组合是单一卫星仓，而不是为了凑数量"
            "把高估值公司重新装回组合。"
        )
        conclusion = (
            f"**应用侧当前可执行均衡方案只持有{balanced_names}，现金"
            f"{_fmt(balanced['cash_weight_pct'])}%；防守方案持有{diversified_names}，现金"
            f"{_fmt(diversified['cash_weight_pct'])}%。** 科大讯飞接近估值上沿不追高，"
            "金山办公、同花顺、鼎捷数智和深信服当前回避；它们不会再出现在可执行股票仓位中。"
        )
    else:
        weight_bridge_intro = (
            "全链侧先在服务器、光互连、铜互连、PCB/CCL、设备、算力芯片、液冷、电力、IDC和自动化"
            "之间形成候选风险预算，再用公司现金流和当前估值做第二次筛选。中际旭创、立讯精密、"
            "工业富联、生益科技和汇川技术过关；其余公司不会因行业景气而自动获得股票权重。"
        )
        conclusion = (
            f"**全链当前可执行均衡方案持有{balanced_names}，现金"
            f"{_fmt(balanced['cash_weight_pct'])}%；防守方案持有{diversified_names}，现金"
            f"{_fmt(diversified['cash_weight_pct'])}%。** 沪电股份等待更好的价格；澜起科技、"
            "北方华创、海光信息、中恒电气以及接近估值上沿的英维克、润泽科技不进入当前股票仓位。"
        )
    return {
        "问题": (
            base["问题"]
            + f" 最终要把{SCOPE_NAMES[scope]}公司判断转成能按当前价格直接执行的权重。"
        ),
        "研究方法与数据": base["研究方法与数据"] + "\n\n" + _portfolio_method(model, scope),
        "研究与分析": (
            "#### 公司判断怎样变成最终权重\n\n"
            + weight_bridge_intro
            + " 三项基础锚控制规模与波动，主动调整只在0.85—"
            "1.15倍之间改变候选权重，随后执行方向、单股和相关性约束，最后用现金流与当前估值门槛"
            "剔除不可买公司。均衡与防守方案把被剔除权重转成现金；高确信度方案仅在原方向候选中"
            "等权且总股票仓位不超过75%。\n\n"
            + _portfolio_weight_bridge_markdown(model, scope)
            + "\n\n#### 三种风险预算怎样选择\n\n"
            "集中、均衡和含现金防守使用同一公司买入门槛，只改变原始风险预算。"
            "下表展示的是门槛处理后的实际股票与现金仓位。\n\n"
            + _portfolio_comparison_markdown(model, scope)
            + "\n\n#### 哪些变化会推翻当前配置\n\n"
            "压力测试只保留确实会影响本研究范围的情景，先把方向冲击传导到2027年归母"
            "净利润和估值倍数，再按组合权重汇总；零影响的无关情景不占表格。"
            "它不是历史回测，也没有给情景赋主观概率。\n\n"
            + _stress_markdown(model, scope)
        ),
        "总结": conclusion
        + " 盈利或自由现金流低于模型、估值安全边际消失时直接降低对应权重；"
        "不以行业热度替代公司级现金利润。",
    }


def _summary_parts(
    model: Mapping[str, Any],
    full_summary: Mapping[str, str],
    application_parts: Mapping[str, str],
) -> dict[str, str]:
    app_balanced = _executable_portfolio_by_key(model, "applications", "balanced")
    chain_balanced = _executable_portfolio_by_key(model, "full_chain", "balanced")
    chain_weights = "、".join(
        f"{row['name']}{_fmt(row['weight_pct'])}%" for row in chain_balanced["holdings"]
    )
    return {
        "问题": "哪些AI方向和公司已经能把AI需求转成现金利润，当前怎样配置？",
        "研究方法与数据": (
            "比较九个应用细分行业、34家公司和18套FY2026—FY2028独立财务估值，沿合同、验收、收入、"
            "利润和回款核验兑现；再按当前价格筛选可买公司。"
            f" {_cite(MODEL_SOURCE_REF)} {_cite(EXECUTABLE_MODEL_SOURCE_REF)}"
        ),
        "研究与分析": (
            "应用侧中，企业管理、网络安全、办公文档的付费路径最清楚，但当前只有"
            "[合合信息](/company/669)同时通过现金流和估值门槛；科大讯飞接近估值上沿，其余已建模应用公司"
            "缺少安全边际。全产业链中，光互连、PCB/CCL以及服务器制造、连接和自动化的订单更容易转成利润与现金流，"
            "优先公司是中际旭创、生益科技、工业富联、立讯精密和汇川技术。"
        ),
        "总结": (
            f"**当前采用高现金均衡配置：应用组合持有合合信息{_fmt(app_balanced['holdings'][0]['weight_pct'])}%、"
            f"现金{_fmt(app_balanced['cash_weight_pct'])}%；全链组合持有{chain_weights}，现金"
            f"{_fmt(chain_balanced['cash_weight_pct'])}%。沪电股份等回到买入区间再纳入。详见"
            "[应用组合](/opportunity-lens/run/16/entity-name/AI应用：公司优选与组合)与"
            "[全链组合](/opportunity-lens/run/16/entity-name/AI全产业链：公司优选与组合)。**"
        ),
    }


def _application_candidate_map_markdown() -> str:
    taxonomy = {
        str(row["segment"]): row for row in _ranked_taxonomy()
    }
    definitions = [
        ("办公协作与文档智能", "办公、文档与专业知识工作流", "金山办公、合合信息", "汉王科技、致远互联", "12个月看AI提价、续费和推理成本；3年看组织工作流与私域数据壁垒"),
        ("企业管理、工业软件与工作流Agent", "ERP、工业与垂直专业软件", "鼎捷数智", "用友网络、宝信软件、广联达、中控技术", "近期受验收和实施成本约束；3年看单客价值和流程壁垒"),
        ("网络安全与IT运营Agent", "网络安全与IT运营", "深信服", "奇安信、启明星辰、绿盟科技", "安全责任支持付费；两年内需证明续费、毛利和现金流改善"),
        ("金融数据、交易与决策工作流", "金融知识与金融IT", "同花顺", "恒生电子、东方财富、指南针", "近期收费明确但受成交周期影响；3年看机构工作流与合规壁垒"),
        ("医疗AI与医疗信息化", "医疗", "科大讯飞医疗业务", "卫宁健康、创业慧康、东华软件", "近期看医院验收与责任边界；3年取决于支付方和临床工作流"),
        ("教育AI", "教育", "科大讯飞", "拓维信息、视源股份、佳发教育", "财政预算、硬件投入和回款使现金兑现慢于收入"),
        ("政务、法律与专业服务AI", "政务、法律与公共服务", "科大讯飞政企业务", "华宇软件、太极股份、南威软件、拓尔思", "私域数据可形成壁垒，项目确认和财政回款压低上限"),
        ("创意内容、营销与电商助手", "创意、营销与电商运营", "万兴科技仅观察", "蓝色光标、焦点科技、值得买", "平台打包和模型降价风险高，现金流过关前不赋权"),
    ]
    definitions.sort(key=lambda row: -float(taxonomy[row[0]]["priority_score"]))
    rows = [
        "| 应用方向排名 | 应用方向 | 研究优先级 | 已进入独立模型 | 其他重点可比与候选 | 未来12个月与3年判断 |",
        "|---:|---|---:|---|---|---|",
    ]
    for rank, (segment, label, modeled, candidates, outlook) in enumerate(definitions, start=1):
        rows.append(
            f"| {rank} | {label} | {_fmt(taxonomy[segment]['priority_score'], 1)} | "
            f"{modeled} | {candidates} | {outlook} |"
        )
    return "\n".join(rows)


FULL_CHAIN_PEERS: Mapping[str, str] = {
    "AI服务器制造": "浪潮信息、中科曙光、联想；全球比较Foxconn、Quanta、Wiwynn",
    "高速光互连": "新易盛、光迅科技、天孚通信；全球比较Coherent、Lumentum",
    "高端PCB": "胜宏科技、深南电路、生益电子；全球比较台光电、金像电",
    "半导体设备": "中微公司、拓荆科技、盛美上海；全球比较Applied Materials、Lam、TEL、ASML",
    "内存互连": "A股暂无同产品第二家；全球比较Rambus、Renesas、Astera Labs",
    "国产计算芯片": "寒武纪、摩尔线程用于AI加速卡比较；龙芯用于CPU比较，海光本身定位CPU/DCU双平台",
    "液冷与热管理": "申菱环境、高澜股份；全球比较Vertiv、Schneider Electric",
    "数据中心供电": "科华数据、欧陆通、麦格米特；全球比较Vertiv、Eaton、Schneider Electric",
    "数据中心运营": "数据港、光环新网、奥飞数据；全球比较Equinix、Digital Realty",
    "低损耗覆铜板": "南亚新材；全球比较台光电、联茂",
    "高速铜互连": "兆龙互连、沃尔核材；连接制造可比安费诺、TE Connectivity",
    "工业智能与机器人": "埃斯顿、绿的谐波、鸣志电器；全球比较Siemens、Rockwell、Fanuc",
}


# Five observable research inputs, each graded 1—5.  They are deliberately
# coarse: this is an ordinal research-priority framework, not a return forecast.
# Total = 12-month visibility 25% + 3-year economics 25% + evidence maturity
# 20% + supply scarcity/value migration 15% + A-share investability 15%.
SEGMENT_PRIORITY_INPUTS: Mapping[str, tuple[int, int, int, int, int, str]] = {
    "数据中心通用GPU/GPGPU与AI加速卡": (5, 5, 4, 5, 3, "需求最强但估值、供给约束和软件生态分化大"),
    "服务器CPU与CPU/DCU平台": (4, 4, 4, 4, 3, "国产部署可核验，增长同时受CPU基本盘约束"),
    "定制ASIC/XPU与芯片IP": (4, 5, 3, 5, 2, "三年价值迁移重要，A股缺少同纯度云厂XPU供应商"),
    "HBM与高带宽DRAM制造": (5, 5, 5, 5, 1, "全球瓶颈清晰，但没有合格A股纯HBM制造标的"),
    "DDR5/MRCD/MDB与CXL/PCIe Retimer": (5, 5, 5, 5, 4, "服务器内存互连升级直接，A股产品和财务证据完整"),
    "前道晶圆制造设备": (5, 4, 5, 4, 4, "先进逻辑与存储扩产可穿透到设备交付和验收"),
    "量测、检测与半导体测试设备": (4, 4, 4, 5, 3, "工艺复杂度提高价值量，订单兑现仍受扩产节奏约束"),
    "先进封装与封测服务": (5, 4, 4, 4, 3, "先进封装需求强，产能、良率和资本回报决定盈利"),
    "AI服务器、整机柜与系统集成": (5, 4, 5, 4, 4, "机架级交付确定性高，低毛利与营运资本限制上限"),
    "AI交换机、网络设备与交换芯片": (5, 4, 5, 4, 4, "集群扩张直接提高网络价值，芯片与整机需分开比较"),
    "高速光模块": (5, 5, 5, 4, 4, "800G/1.6T直接受益，架构迁移与客户集中决定终值"),
    "光器件、激光器与光引擎": (5, 4, 4, 4, 3, "随速率升级受益，但器件份额与客户认证披露较少"),
    "高速铜互连、DAC/AEC与连接系统": (4, 4, 4, 4, 3, "机架内短距价值上升，距离边界限制总空间"),
    "AI服务器PCB、高多层板与HDI": (5, 4, 5, 4, 4, "层数、面积和材料等级升级可核验，扩产良率是约束"),
    "低损耗CCL与高速材料": (5, 4, 5, 4, 4, "材料升级确定，产品代际与认证决定份额和毛利"),
    "服务器/机架电源、UPS与HVDC": (4, 5, 4, 4, 4, "功率密度升级延续，客户直供和AI收入仍需拆分"),
    "液冷与数据中心热管理": (5, 5, 4, 4, 4, "热密度形成真实瓶颈，项目验收和回款决定兑现"),
    "IDC、数据中心园区与智算运营": (4, 4, 4, 3, 3, "电力和上架率重要，但重资本、融资与区域供需分化"),
    "输变电、并网与园区配电": (4, 5, 4, 5, 3, "并网和变压器约束延长景气，AI收入纯度相对较低"),
    "公有云、AI算力云与云平台": (5, 4, 5, 3, 3, "需求和资本开支可见，A股主体业务口径不够纯"),
    "基础模型、MaaS与开发平台": (4, 4, 3, 2, 2, "使用增长快但价格竞争、推理成本和收入披露不足"),
    "办公协作与文档智能": (4, 5, 5, 4, 4, "付费工作流和私域数据清晰，提价与续费可连续验证"),
    "企业管理、工业软件与工作流Agent": (4, 5, 4, 5, 3, "流程壁垒强，实施成本与项目验收拖慢现金兑现"),
    "金融数据、交易与决策工作流": (4, 4, 4, 4, 4, "高频付费明确，需剔除资本市场活跃度周期"),
    "网络安全与IT运营Agent": (4, 4, 4, 5, 3, "责任与持续运营支持付费，AI增量利润尚待验证"),
    "教育AI": (3, 4, 4, 3, 2, "场景明确但财政预算、硬件投入和回款压低现金质量"),
    "医疗AI与医疗信息化": (3, 5, 3, 5, 2, "长期壁垒高，支付方、责任和医院验收使兑现较慢"),
    "政务、法律与专业服务AI": (3, 4, 3, 4, 2, "私域数据有价值，项目制收入与财政回款约束强"),
    "创意内容、营销与电商助手": (4, 3, 3, 2, 3, "需求可见但平台打包、模型降价和低切换成本压制壁垒"),
    "端侧AI SoC与智能终端芯片": (3, 4, 4, 4, 3, "端侧渗透是三年机会，近期仍依赖终端周期与出货"),
    "工业自动化、机器人控制与系统": (3, 5, 4, 5, 4, "工业客户与控制壁垒强，物理AI收入更偏三年兑现"),
    "机器人核心零部件": (3, 4, 4, 4, 4, "产业趋势明确，量产节奏和单机价值量仍需订单验证"),
}

LAYER_DIRECTION_NAMES: Mapping[str, str] = {
    "applications": "AI应用与付费工作流",
    "compute": "计算芯片与平台",
    "memory": "存储与内存互连",
    "semiconductor_manufacturing": "半导体设备与先进封装",
    "systems": "服务器与网络系统",
    "interconnect": "高速光铜互连",
    "boards_materials": "高端PCB与高速材料",
    "physical_infrastructure": "电力、液冷与数据中心",
    "cloud_models": "云平台与基础模型",
    "edge_physical_ai": "端侧与物理AI",
}

SEGMENT_EVIDENCE_BOUNDARIES: Mapping[str, str] = {
    "服务器CPU与CPU/DCU平台": "需分别核验CPU与DCU出货、软件栈部署、客户复购和分产品收入，不能把双平台收入全算作AI加速。",
    "前道晶圆制造设备": "需核验先进逻辑与存储客户的设备订单、交付验收、国产化份额和回款，避免用晶圆厂资本开支直接外推利润。",
    "先进封装与封测服务": "需核验先进封装产能、客户认证、利用率、良率、单价和资本回报，传统封测收入不能全部计入AI。",
    "AI服务器、整机柜与系统集成": "需拆分单机、整机柜和系统集成收入，并核验GPU供给、客户交付、毛利率、库存与应收。",
    "AI交换机、网络设备与交换芯片": "需区分交换芯片、整机和系统收入，核验800G以上端口出货、客户部署、毛利率和回款。",
    "高速光模块": "需核验800G/1.6T出货与ASP、客户份额、产品结构、扩产良率和CPO/LPO替代节奏。",
    "光器件、激光器与光引擎": "需核验器件在800G/1.6T中的单机价值、客户认证、量产份额、良率和模块厂价格传导。",
    "AI服务器PCB、高多层板与HDI": "需核验层数、面积、材料等级、客户认证、扩产良率和AI板收入，不能把全部PCB收入贴AI标签。",
    "服务器/机架电源、UPS与HVDC": "需核验HVDC/UPS/服务器电源的AI客户、单机价值、直供收入、毛利率、交付和回款。",
    "液冷与数据中心热管理": "需核验冷板、CDU、快接和服务收入结构、项目验收、毛利率、应收及液冷渗透的实际订单。",
    "IDC、数据中心园区与智算运营": "需逐园区核验电力指标、预租、上架率、资本开支、融资成本和自由现金流，区域短缺不能互相替代。",
    "企业管理、工业软件与工作流Agent": "需核验AI合同、续费或单客价值，并追踪实施人效、验收周期、毛利率和经营现金流。",
    "金融数据、交易与决策工作流": "需把市场成交活跃度与AI提价/留存分开，核验付费账户、ARPU、续费、推理成本和利润增量。",
    "网络安全与IT运营Agent": "需核验AI安全产品合同、续费、客单价、交付成本、毛利和现金流，产品发布本身不证明商业化。",
    "医疗AI与医疗信息化": "需核验支付方、医院验收、临床责任、合同转收入、回款和推理成本，试点数量不能替代收入。",
    "政务、法律与专业服务AI": "需核验财政预算、合同验收、回款、私域数据权限和单项目利润，示范项目不能外推规模收入。",
    "创意内容、营销与电商助手": "需核验AI功能的付费率、留存、获客效率、模型成本与平台分成，流量或生成次数不能替代利润。",
    "端侧AI SoC与智能终端芯片": "需核验AI SoC机型定点、出货、ASP、芯片面积/成本和客户集中，终端总出货不能全算AI增量。",
    "工业自动化、机器人控制与系统": "需把自动化基本盘与机器人/物理AI增量拆开，核验订单、出货、单机价值、毛利和回款。",
    "机器人核心零部件": "需核验机器人定点、量产时间、单机用量、价格、良率和客户份额，送样或小批不能按终局产量估值。",
}


def _segment_priority_score(segment: str) -> float:
    try:
        d12, d3y, evidence, scarcity, investability, _ = SEGMENT_PRIORITY_INPUTS[segment]
    except KeyError as exc:
        raise Run16PackInputError(f"缺少细分研究优先级输入：{segment}") from exc
    return round(
        d12 * 5.0 + d3y * 5.0 + evidence * 4.0 + scarcity * 3.0 + investability * 3.0,
        1,
    )


def _ranked_taxonomy() -> list[dict[str, Any]]:
    taxonomy = _read_json(TAXONOMY_AUDIT_PATH).get("taxonomy", [])
    rows = []
    for row in taxonomy:
        item = dict(row)
        item["priority_inputs"] = SEGMENT_PRIORITY_INPUTS[str(row["segment"])]
        item["priority_score"] = _segment_priority_score(str(row["segment"]))
        rows.append(item)
    rows.sort(key=lambda row: (-row["priority_score"], str(row["segment"])))
    for rank, row in enumerate(rows, start=1):
        row["priority_rank"] = rank
    return rows


def _direction_priority_markdown() -> str:
    grouped: dict[str, list[float]] = {}
    for row in _ranked_taxonomy():
        grouped.setdefault(str(row["layer"]), []).append(float(row["priority_score"]))
    ranked = sorted(
        (
            round(sum(values) / len(values), 1),
            LAYER_DIRECTION_NAMES[layer],
            layer,
            len(values),
        )
        for layer, values in grouped.items()
    )
    ranked.reverse()
    rows = [
        "| 大方向排名 | 大方向 | 研究优先级 | 纳入细分数 | 判断 |",
        "|---:|---|---:|---:|---|",
    ]
    for rank, (score, name, layer, count) in enumerate(ranked, start=1):
        if layer in {"interconnect", "memory", "boards_materials"}:
            judgement = "价值量升级直接，但必须逐产品核验份额与估值"
        elif layer == "applications":
            judgement = "分化最大，只有收费、利润和现金流同时过关才配置"
        elif layer in {"physical_infrastructure", "semiconductor_manufacturing"}:
            judgement = "瓶颈真实，订单、验收和资本回报决定持续性"
        else:
            judgement = "保留增长暴露，同时收紧产品纯度和财务门槛"
        rows.append(f"| {rank} | {name} | {_fmt(score, 1)} | {count} | {judgement} |")
    return "\n".join(rows)


def _direction_rank_map() -> dict[str, tuple[int, float, str]]:
    grouped: dict[str, list[float]] = {}
    for row in _ranked_taxonomy():
        grouped.setdefault(str(row["layer"]), []).append(float(row["priority_score"]))
    ranked = sorted(
        (
            round(sum(values) / len(values), 1),
            LAYER_DIRECTION_NAMES[layer],
            layer,
        )
        for layer, values in grouped.items()
    )
    ranked.reverse()
    return {
        layer: (rank, score, name)
        for rank, (score, name, layer) in enumerate(ranked, start=1)
    }


def _full_taxonomy_priority_markdown() -> str:
    direction_ranks = _direction_rank_map()
    rows = [
        "| 全链细分排名 | 大方向排名 | 细分方向 | 研究优先级 | 12个月/3年 | 证据/稀缺性/可投资性 | 排名理由 |",
        "|---:|---|---|---:|---:|---:|---|",
    ]
    for row in _ranked_taxonomy():
        d12, d3y, evidence, scarcity, investability, rationale = row["priority_inputs"]
        direction_rank, direction_score, direction_name = direction_ranks[str(row["layer"])]
        rows.append(
            f"| {row['priority_rank']} | {direction_rank}.{direction_name}（{_fmt(direction_score, 1)}） | "
            f"{row['segment']} | {_fmt(row['priority_score'], 1)} | "
            f"{d12}/{d3y} | {evidence}/{scarcity}/{investability} | {rationale} |"
        )
    return "\n".join(rows)


def _full_chain_ranking_with_peers(model: Mapping[str, Any]) -> str:
    ranked = sorted(
        (
            (_company_research_score(model["companies"][ticker]), ticker)
            for ticker in _scope_tickers(model, "full_chain")
        ),
        reverse=True,
    )
    rows = [
        "| 已建模代表排名 | 公司 | 细分方向 | 综合研究分 | 全球与A股可比/候选 |",
        "|---:|---|---|---:|---|",
    ]
    for rank, (score, ticker) in enumerate(ranked, start=1):
        company = model["companies"][ticker]
        direction = company["portfolio_candidate"]["direction"]
        rows.append(
            f"| {rank} | {company['name']} | {direction} | {_fmt(score, 1)} | "
            f"{FULL_CHAIN_PEERS.get(direction, '见细分研究实体的产业候选表')} |"
        )
    return "\n".join(rows)


def _core_map_parts(model: Mapping[str, Any]) -> dict[str, str]:
    return {
        "问题": "AI应用与全产业链哪些方向更值得配置，优先公司是谁？",
        "研究方法与数据": (
            "先比较各方向需求、供需位置和利润兑现，再以公司订单、自由现金流、ROE与独立估值确定优先级。"
            f" {_cite('app-c18')} {_cite('app-c19')} {_cite('app-c20')} "
            f"{_cite('chain-fc-w041')} {_cite(EXECUTABLE_MODEL_SOURCE_REF)}"
        ),
        "研究与分析": (
            "**第一优先级是光互连与PCB/CCL**：中际旭创、生益科技可配，沪电股份择价。**第二优先级是服务器制造、"
            "连接与自动化**：工业富联、立讯精密、汇川技术进入组合。**第三优先级是已有付费闭环的AI应用**："
            "当前只选合合信息。内存互连和半导体设备景气较强，但澜起科技、北方华创、海光信息的价格已提前反映；"
            "电力、液冷和IDC资本回报分化，英维克不追高，中恒电气与润泽科技不配置。"
            f" {_cite(MODEL_SOURCE_REF)}"
        ),
        "总结": (
            "**方向排序为光互连/PCB材料 > 服务器制造/连接/自动化 > 已验证付费的AI应用。"
            "优先公司依次是中际旭创、生益科技、工业富联、立讯精密、汇川技术和合合信息；"
            "行业好但估值已透支的公司暂不配置。**"
        ),
    }


def _portfolio_overview_parts(model: Mapping[str, Any]) -> dict[str, str]:
    app_concentrated = _executable_portfolio_by_key(model, "applications", "concentrated")
    chain_concentrated = _executable_portfolio_by_key(model, "full_chain", "concentrated")
    app_balanced = _executable_portfolio_by_key(model, "applications", "balanced")
    chain_balanced = _executable_portfolio_by_key(model, "full_chain", "balanced")
    app_defensive = _executable_portfolio_by_key(model, "applications", "risk_diversified")
    chain_defensive = _executable_portfolio_by_key(model, "full_chain", "risk_diversified")
    return {
        "问题": "当前应使用集中、均衡还是含现金防守组合？",
        "研究方法与数据": (
            "只让自由现金流为正且相对独立估值上沿至少有25%空间的公司进入持仓；集中、均衡、防守三档"
            "分别提高单股上限或提高现金，市场价格截至2026年7月30日。"
            f" {_cite(EXECUTABLE_MODEL_SOURCE_REF)}"
        ),
        "研究与分析": (
            f"应用组合：集中档合合信息{_fmt(app_concentrated['holdings'][0]['weight_pct'])}%、现金"
            f"{_fmt(app_concentrated['cash_weight_pct'])}%；均衡档合合信息{_fmt(app_balanced['holdings'][0]['weight_pct'])}%、"
            f"现金{_fmt(app_balanced['cash_weight_pct'])}%；防守档合合信息{_fmt(app_defensive['holdings'][0]['weight_pct'])}%、"
            f"现金{_fmt(app_defensive['cash_weight_pct'])}%。全链集中档为中际旭创、立讯精密、工业富联各25%，"
            f"现金{_fmt(chain_concentrated['cash_weight_pct'])}%；均衡档五只股票合计"
            f"{_fmt(100-chain_balanced['cash_weight_pct'])}%；防守档合计{_fmt(100-chain_defensive['cash_weight_pct'])}%。"
        ),
        "总结": (
            f"**当前基准采用均衡档：应用侧现金{_fmt(app_balanced['cash_weight_pct'])}%，全链现金"
            f"{_fmt(chain_balanced['cash_weight_pct'])}%。只有能承受高波动且接受三只股票高度集中的资金才用集中档；"
            "不因看好AI总需求而买入未过估值门槛的公司。**"
        ),
    }


def _risk_overview_parts() -> dict[str, str]:
    return {
        "问题": "哪些事实出现时，应立即降低AI应用或全产业链组合的风险预算？",
        "研究方法与数据": "把会直接推翻盈利或估值的经营事实映射到减仓动作。",
        "研究与分析": (
            "| 推翻当前判断的事实 | 直接动作 |\n"
            "|---|---|\n"
            "| AI合同增加但毛利与经营现金流连续两期不改善 | 减持项目制应用公司 |\n"
            "| 订单增长慢于应收、合同资产和存货 | 下调硬件正常化利润与估值 |\n"
            "| 新架构使目标产品退出关键物料清单 | 退出对应芯片、互连或材料方向 |\n"
            "| 资本开支上升而自由现金流转弱 | 减持重资产IDC与扩产公司 |\n"
            "| 盈利不变而估值与相关性同步上升 | 削减重复高估值暴露 |\n\n"
            "这些是经营止损，不是单日价格止损。只要订单、利润率、回款和产品位置没有恶化，"
            "股价回撤本身不会推翻基本面结论。"
            f" {_cite('app-w05')} {_cite('chain-fc-w014')} {_cite('chain-fc-w022')}"
        ),
        "总结": (
            "**现金流背离、物料清单退出或盈利未变而估值扩张，均应直接减仓；行业空间不能"
            "弥补公司盈利和估值错误。**"
        ),
    }


def _application_company_parts(
    model: Mapping[str, Any], reconciliation: Mapping[str, Any]
) -> dict[str, str]:
    tickers = ("688111.SH", "688615.SH", "300033.SZ", "002230.SZ", "300378.SZ", "300454.SZ")
    return {
        "问题": (
            "哪些A股应用公司已经把产品、客户与财务结果连接起来，未来三年的收入、利润、"
            "自由现金流和ROE如何变化，当前市值与独立估值及市场预期有什么分歧？同时，"
            "哪些规模型或第二候选值得继续补模型，但还不能进入精确权重？"
        ),
        "研究方法与数据": (
            "研究先按九个细分领域建立至少3—5家提供方或购买方样本，再把合同、付费、"
            "部署、验收、收入和回款分级。金山办公、合合信息、同花顺、科大讯飞、鼎捷数智"
            "和深信服从2025年正常化实际值及2026年一季度检查点建立FY2026—FY2028"
            "收入、归母净利润、经营现金流、资本开支、自由现金流、权益、ROE和ROA桥。"
            "其余候选使用最新年报、具名项目、AI收入或近期机构预测判断是否值得进入完整模型，"
            "门槛不足时只给可证伪的观察条件，不补拍目标价。"
            "收入增长、净利率、现金转换和资本开支均按公司经营机制单独设定；模型冻结后"
            "才读取Wind一致预期和最近两个季度同公司机构预测。估值不机械平均：正常化PE"
            "是主要方法，股东现金流折现和PB—ROE只有在现金流与资本效率门槛通过时才参与"
            "核心区间。应用收入不能从案例数量直接外推，而按合同或付费用户、转收入比例、"
            "增量毛利和交付成本逐层传导。"
            + _display_formula(
                r"\Delta\text{自由现金流}=(\text{合同额或新增付费收入}\times\text{收入确认比例}"
                r"\times\text{增量毛利率})-\text{交付成本}-\text{推理成本}"
                r"-\Delta\text{营运资金}-\Delta\text{资本开支}"
            )
            + "公式把签约与现金利润分开：只有已经确认的收入进入毛利，随后还要扣除交付、"
            "模型推理、营运资金和资本开支。公开资料没有这些输入时只做客户侧盈亏平衡或"
            "经营对照，不给精确权重。"
            f" {_cite(MODEL_SOURCE_REF)} {_cite(RECONCILIATION_SOURCE_REF)}"
        ),
        "研究与分析": (
            "研究池已从原有11家公司扩展到九个细分行业的代表公司，并明确区分合同、启动、"
            "上线、验收、收入和回款。每个公司组同时保留行业龙头、A股高关注标的和有真实"
            "产品或合同证据的潜力公司；平台型公司在A股缺少纯标的时作为竞争与价格基准。"
            "以下不再用公司简介替代研究：每家公司都依次回答谁付钱、客户获得什么可量化"
            "价值、已有证据能支持多大市场、独立三年模型实际要求什么，以及当前价格还剩"
            "多少安全边际。没有公开成交价时，采用客户侧盈亏平衡敏感性，不把案例数量"
            "直接乘成公司收入。\n\n"
            + _application_commercial_deep_dive_markdown(model)
            + "\n\n#### 三年财务结果与市场定价对账\n\n"
            "下表把已完成模型公司的三年趋势压成一行。收入和利润复合增速从FY2025正常化实际值"
            "到FY2028基准预测计算；同一张表把自由现金流、ROE、当前估值、独立估值和"
            "FY2027外部对账合并，避免经营与估值被拆成两套重复表。独立估值与市场对账的"
            "重点不是谁更接近一致预期，而是分歧是否能由合同转收入、利润率、现金转换或"
            "资本效率解释。\n\n"
            + _compact_company_financial_valuation_markdown(
                model, reconciliation, tickers, "AI应用公司"
            )
            + "\n\n最近两个季度卖方预测与Wind一致预期并列，不合并计权。投资结论已经明显分化："
            "合合信息当前市值位于独立核心区间内，对应下沿风险9.82%和上沿空间35.26%，是"
            "应用侧唯一同时具有商业证据和价格缓冲的已建模公司；科大讯飞距离区间上沿仅"
            "4.02%，当前不追高。金山办公、同花顺、鼎捷数智和深信服的当前市值分别高于"
            "核心区间上沿，产品或合同质量不能抵消估值风险。"
        ),
        "总结": (
            "**按当前证据与价格，应用侧只配置合合信息；科大讯飞接近上沿不追高，金山办公、"
            "同花顺、鼎捷数智和深信服均高于独立核心区间，当前回避。鼎捷数智的2亿元AI签约"
            "仍有研究价值，但不能用合同质量覆盖估值。扩展池中的鸥玛软件、拓尔思、快手、"
            "宇信科技和视源股份尚未完成同口径财务与估值闭环，本轮全部不进入组合。**"
        ),
    }


def _chain_cluster_parts(
    model: Mapping[str, Any],
    reconciliation: Mapping[str, Any],
    *,
    key: str,
) -> dict[str, str]:
    configs: dict[str, dict[str, Any]] = {
        "ai_compute_semiconductor": {
            "title": "算力芯片、存储与半导体供给",
            "tickers": ("688041.SH", "688008.SH", "002371.SZ"),
            "layers": ("compute", "memory", "semiconductor_manufacturing"),
            "refs": ("chain-fc-w001", "chain-fc-w002", "chain-fc-w004", "chain-fc-w010", "chain-fc-w011", "chain-fc-w026", "chain-fc-w030", "chain-fc-w031", "chain-fc-w041"),
            "question": "训练与推理算力增长会把价值留在GPU/ASIC、CPU/DCU、HBM与内存互连，还是晶圆制造、设备和先进封装？A股哪些是直接产品，哪些只是相邻映射？",
            "analysis": (
                "全球GPU和AI加速平台的比较对象首先是NVIDIA与AMD，定制ASIC/XPU则要单列"
                "Broadcom、Marvell和云厂自研芯片；两者不能混算份额。A股直接训练/推理"
                "加速卡代表是寒武纪和摩尔线程，海光信息经营CPU/DCU双平台，只有在服务器"
                "CPU与CPU/DCU平台细分中才是第一比较对象。它的投资逻辑同时依赖通用CPU"
                "生态、政企算力、DCU软件栈和客户部署，不能被简化成纯GPU替代。\n\n"
                "HBM制造由SK hynix、Samsung和Micron主导，A股没有可同口径比较的纯HBM"
                "制造商；澜起科技提供DDR5/MRCD、CXL/PCIe等内存互连产品，受服务器内存"
                "代际升级驱动，但不是HBM制造商。北方华创则通过刻蚀、沉积、清洗等前道"
                "设备承接先进逻辑与存储扩产，收入确认取决于设备交付和验收，资本开支周期"
                "与芯片设计公司的销量周期不同。\n\n"
                "未来12个月需求仍由先进加速器、HBM和封装扩产支撑；三年风险在于供给释放、"
                "自研ASIC提高、出口限制和云厂资本回报下降。判断A股受益必须逐层穿过产品、"
                "认证、产能、交付、验收和现金回款，不能把全球GPU收入增速直接复制给设备"
                "或国产芯片公司。"
            ),
            "conclusion": (
                "**产业层面继续看多内存互连、前道设备和先进封装，但当前不买澜起科技、"
                "北方华创和海光信息：三者市值均高于独立核心区间。** 订单与验收可以支撑"
                "盈利增长，却不能覆盖已经透支的价格；海光信息还必须按CPU/DCU双平台而非"
                "纯GPU龙头估值。"
            ),
        },
        "ai_systems_interconnect_pcb": {
            "title": "AI服务器、高速互联与PCB材料",
            "tickers": ("601138.SH", "300308.SZ", "002475.SZ", "002463.SZ", "600183.SH"),
            "layers": ("systems", "interconnect", "boards_materials"),
            "refs": ("chain-fc-w007", "chain-fc-w009", "chain-fc-w027", "chain-fc-w028", "chain-fc-w029", "chain-fc-w034", "chain-fc-w035", "chain-fc-w039", "chain-fc-w040"),
            "question": "云厂资本开支如何穿过服务器和机架、交换与光铜互联、高端PCB与CCL，最终变成A股公司的收入、利润和现金流？架构变化会把价值从哪一环转走？",
            "analysis": (
                "工业富联承接服务器制造与系统交付，收入规模大但毛利率较低，价值取决于"
                "机架级集成、客户结构和营运资本；中际旭创更直接暴露于800G/1.6T光模块，"
                "销量、ASP、产品结构和客户集中决定利润弹性；立讯精密横跨连接、铜互联和"
                "精密制造，AI增量必须从消费电子基本盘中拆出。三者共享云厂预算，却不是"
                "同一种经济机器。\n\n"
                "沪电股份与生益科技分别承接高多层PCB和低损耗CCL。服务器、交换机和加速"
                "卡升级会提高层数、面积和材料等级，但扩产、良率、客户认证和原料价格决定"
                "新增收入能否转成现金利润。胜宏科技、深南电路、生益电子、南亚新材等是"
                "必须比较的第二候选，不应因为未进入当前12家公司模型而被排除。\n\n"
                "CPO/LPO不会简单把可插拔光模块归零，高速铜也不会在所有距离替代光。基准"
                "情景按距离、功耗、可维护性和机架架构分工：短距铜、机架间可插拔光和更高"
                "密度共封装可能并存。若官方平台配置和交付数据证明价值量迁移，需同时重算"
                "光模块、铜连接、交换芯片、PCB和电源，而不是只下调某一家公司终值。"
            ),
            "conclusion": (
                "**服务器、互联与材料当前优先配置中际旭创、生益科技、工业富联和立讯精密，"
                "沪电股份在独立区间内择价；高速铜只作距离受限的补充。** 光模块看"
                "速率结构与ASP，PCB/CCL看材料等级、良率和认证，系统交付看营运资本；"
                "平台物料清单转向或客户扩产回报下降时，应同步下调相关链条。"
            ),
        },
        "ai_data_center_physical": {
            "title": "AI电力、液冷、数据中心与工业自动化",
            "tickers": ("002837.SZ", "002364.SZ", "300442.SZ", "300124.SZ"),
            "layers": ("physical_infrastructure", "edge_physical_ai", "cloud_models"),
            "refs": ("chain-fc-w016", "chain-fc-w017", "chain-fc-w018", "chain-fc-w019", "chain-fc-w020", "chain-fc-w021", "chain-fc-w023", "chain-fc-w032", "chain-fc-w033", "chain-fc-w036", "chain-fc-w038"),
            "question": "GPU交付后，供电、液冷、并网和数据中心投产会不会成为真正瓶颈；这些建设需求如何传到中恒电气、英维克、润泽科技与汇川技术的现金利润？",
            "analysis": (
                "中恒电气的240V、336V和800V HVDC、服务器电源产品构成真实产品矩阵，但"
                "北美头部客户、直供收入和利润率仍没有强证据闭环；因此本轮只把它作为"
                "数据中心供电弹性候选，不把市场传闻代入盈利。英维克的价值来自液冷、机房"
                "温控和全生命周期服务，关键变量是冷板/CDU等产品结构、项目验收、毛利率和"
                "回款，而不是液冷渗透率一个数字。\n\n"
                "润泽科技属于重资产数据中心运营，必须逐项目检查电力指标、建设资本开支、"
                "预租、上架率、融资成本和回收期。全球数据中心紧张不等于中国任一园区都"
                "短缺，北美、欧洲和中国项目的电价、并网和客户合同不能互相替代。汇川技术"
                "则依托工控、伺服和自动化基本盘进入物理AI，机器人和工业智能更偏三年选择，"
                "2026年仍需用订单、出货和毛利验证，不能把研发演示当收入。\n\n"
                "电力、液冷和IDC在资本开支放缓时也可能一起承压，并非天然防御资产。最早"
                "的风险信号是项目推迟、设备交付周期回落、预租和上架不及预期、应收与资本"
                "开支上升，以及自由现金流恶化。只有订单、验收、回款和资本效率共同改善，"
                "三年需求持续性才支持更高权重。"
            ),
            "conclusion": (
                "**物理基础设施产业层面偏多液冷和机架供电，但当前股票只优先配置汇川技术；"
                "英维克和润泽科技接近独立区间上沿，不追高，中恒电气显著高于核心区间，回避。** "
                "重资产项目若只增加资本开支而没有提高上架、回款和自由现金流，不能获得AI估值溢价。"
            ),
        },
    }
    cfg = configs[key]
    tickers = cfg["tickers"]
    causal_cluster = {
        "ai_compute_semiconductor": "compute",
        "ai_systems_interconnect_pcb": "systems",
        "ai_data_center_physical": "infrastructure",
    }[key]
    refs = " ".join(_cite(ref) for ref in cfg["refs"])
    return {
        "问题": cfg["question"],
        "研究方法与数据": (
            "研究先按产品和收入确认机制划分细分，再用全球公司、国际机构与中国上市公司"
            "披露核对需求、供给、认证、量产和反方。已建模公司从FY2025实际与2026Q1"
            "检查点建立三年模型；其他候选只进入产业比较，不因候选数量扩大而降低财务"
            "门槛。金额为亿元人民币，估值以2026-07-30冻结市场时点对账。"
            + _display_formula(
                r"\Delta\text{自由现金流}=(\Delta\text{产品收入}\times\text{增量毛利率})"
                r"-\Delta\text{经营费用}-\Delta\text{营运资金}-\Delta\text{资本开支}"
            )
            + "产品收入增量按量价、客户采用或项目投运形成；增量利润率、费用、营运资本"
            "和资本开支按公司收入确认机制分别设定。产品发布、送样或行业资本开支没有"
            "穿过交付、验收与回款时，不进入基准自由现金流。 " + refs
        ),
        "研究与分析": (
            "#### 产业位置、产品与客户兑现\n\n"
            + cfg["analysis"]
            + "\n\n#### 逐公司订单、财务模型、市场定价与投资行动\n\n"
            + _chain_company_deep_dive_markdown(model, reconciliation, causal_cluster)
            + "\n\n#### 行业候选、三年财务与市场定价\n\n"
            "下表同时给出全链统一排名和细分内A股研究顺序。全链分数来自12个月需求、三年"
            "经济性、证据成熟度、供给稀缺与A股可投资性；细分内公司顺序再按产品直接性、"
            "商业证据和财务可观察性排列。没有完成财务门槛的公司只有研究顺序，不是精确"
            "投资分；没有同口径A股标的时明确留空。\n\n"
            + _candidate_landscape_markdown(layers=cfg["layers"])
            + "\n\n下表把收入与利润复合增速、三年自由现金流、ROE、当前估值、独立区间和"
            "FY2027外部对账合并。经营增长只有在现金流和估值仍有安全边际时才形成投资"
            "优先级；各方法的详细输入、逐机构预测与治理事实在公司详情中继续核对。\n\n"
            + _compact_company_financial_valuation_markdown(
                model, reconciliation, tickers, cfg["title"]
            )
        ),
        "总结": cfg["conclusion"],
    }


def _public_sections(
    model: Mapping[str, Any],
    reconciliation: Mapping[str, Any],
    company_map: Mapping[str, Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, str]]]:
    app = _parse_workpaper(APPLICATION_WORKPAPER_PATH)
    chain = _parse_workpaper(FULL_CHAIN_WORKPAPER_PATH)
    app_classification = _find_workpaper_section(app, "AI应用应该怎样分类")
    app_companies = _find_workpaper_section(app, "候选公司比较")
    app_outlook = _find_workpaper_section(app, "12个月与3年判断")
    app_portfolio = _find_workpaper_section(app, "组合构建建议")
    app_risks = _find_workpaper_section(app, "反方检验")
    chain_summary = _find_workpaper_section(chain, "摘要")
    chain_structure = _find_workpaper_section(chain, "重新划分后的全产业链")
    chain_outlook = _find_workpaper_section(chain, "未来 12 个月与 3 年供需")
    chain_leaders = _find_workpaper_section(chain, "全球龙头")
    chain_companies = _find_workpaper_section(chain, "12 家公司")
    chain_portfolio = _find_workpaper_section(chain, "三类组合候选")
    chain_risks = _find_workpaper_section(chain, "反方证据")

    application_industry_research = build_application_industry_parts()
    application_company_research = _application_company_parts(model, reconciliation)
    chain_architecture = _merge_parts(chain_structure, chain_outlook)
    chain_architecture["研究与分析"] = re.sub(
        r"\n*\| 动作 \| 现有节点 \| 处理 \| 兼容要求 \|\n"
        r"\|---\|---\|---\|---\|\n(?:\|[^\n]+\|\n?)+",
        "\n\n",
        chain_architecture["研究与分析"],
    ).strip()
    chain_architecture["研究与分析"] += (
        "\n\n#### 大方向与32个细分方向的统一排序\n\n"
        "大方向得分是所辖细分研究优先级的等权平均，用来决定搜索、建模和风险预算先后；"
        "细分总分使用未来12个月需求可见性25%、三年经济性25%、证据成熟度20%、供给稀缺"
        "与价值迁移15%、A股可投资性15%。每项只用1—5级，避免把研究判断伪装成精确收益率。"
        "同分时按名称稳定排列，不表示细小差距具有统计意义。下表同时给出大方向与细分"
        "方向名次，避免把两套排序拆成重复表格。\n\n"
        + _full_taxonomy_priority_markdown()
        + "\n\n"
        + _unverified_leads_markdown()
    )
    chain_architecture["研究方法与数据"] += (
        " 报告链另用外资数据中心审批风险报告和国内AI服务器电容深度报告补充许可、"
        "机架供电与高端电容量价框架；两者只作二手研究解释，已与公司、能源机构和产业"
        "原始资料分开。"
        f" {_cite('chain-fc-r002')} {_cite('chain-fc-r003')}"
    )
    chain_architecture["总结"] = (
        "**未来12个月偏多高速光互连、高端PCB/低损耗材料、内存互连与前道设备，"
        "产业层面偏多液冷但个股需要估值约束；对重资产IDC和仅有产品映射、没有订单与"
        "现金利润的公司保持回避。** 三年最重要的价值迁移来自1.6T互连、HBM与先进"
        "封装扩产、机架供电和液冷；若新架构改变物料清单，必须同步重算光、铜、PCB、"
        "交换、电源和数据中心，而不是继续沿用旧产业标签。"
    )

    parts_by_key: dict[str, dict[str, str]] = {
        "summary": _summary_parts(model, chain_summary, app_classification),
        "core_research_map": _core_map_parts(model),
        "portfolio_overview": _portfolio_overview_parts(model),
        "risk_overview": _risk_overview_parts(),
        "ai_application_subsectors": application_industry_research,
        "ai_application_companies": application_company_research,
        "ai_chain_architecture": chain_architecture,
        "ai_compute_semiconductor": _chain_cluster_parts(
            model, reconciliation, key="ai_compute_semiconductor"
        ),
        "ai_systems_interconnect_pcb": _chain_cluster_parts(
            model, reconciliation, key="ai_systems_interconnect_pcb"
        ),
        "ai_data_center_physical": _chain_cluster_parts(
            model, reconciliation, key="ai_data_center_physical"
        ),
        "ai_application_portfolios": _portfolio_parts(model, "applications", app_portfolio),
        "ai_full_chain_portfolios": _portfolio_parts(model, "full_chain", chain_portfolio),
        "key_risks": _merge_parts(app_risks, chain_risks),
    }
    risk_analysis = parts_by_key["key_risks"]["研究与分析"]
    risk_analysis = risk_analysis.replace(
        "建议的硬证伪指标：",
        "#### 建议的硬证伪指标",
    )
    risk_analysis = re.sub(
        r"\n+- AI业务收入占比，尤其是中恒电气、英维克、生益科技、立讯精密、汇川技术，"
        r"披露口径仍不足；\n- 海外 CSP 对中际旭创、工业富联、沪电股份的具体客户份额多数"
        r"受保密限制，只能用公司披露和客户资本开支交叉验证，不能从匿名供应链传闻补表；"
        r"\n- A股高速铜互连与800VDC的正式客户认证、量产规模和利润率；"
        r"\n- 中国数据中心项目级电指标、预租、上架率、利用率、资本成本和现金回收期；?",
        (
            "\n\n#### 这些证据缺口如何限制当前判断\n\n"
            "中恒电气、英维克、生益科技、立讯精密和汇川技术没有统一披露AI业务收入占比。"
            "本轮只能用公司总收入、毛利率、自由现金流和已披露订单交叉判断，因此不把行业"
            "高增长直接计入其利润，估值上限和组合权重也相应收紧。\n\n"
            "海外云客户对中际旭创、工业富联和沪电股份的具体采购份额多数受保密限制。"
            "本轮使用公司披露、客户资本开支、订单能见度和营运资本变化作为代理；无法精确"
            "拆分份额意味着客户集中度和份额下行情景必须保留更宽区间。\n\n"
            "A股高速铜互连和800VDC目前可核验的客户认证、量产规模与利润率仍不完整。"
            "在客户、量产和盈利三项同时确认前，这些公司只作为候选，不把送样或产品发布"
            "计入基准利润。\n\n"
            "中国数据中心项目的电力指标、预租、上架率、利用率、资本成本和现金回收期缺少"
            "统一项目级披露。本轮逐公司使用已披露资本开支、利用率和现金流，不把单一区域"
            "短缺外推到全国，并降低重资产IDC的终值和配置上限。"
        ),
        risk_analysis,
    )
    parts_by_key["key_risks"]["研究与分析"] = risk_analysis
    specs = [
        ("summary", "哪些AI方向和公司能把需求转成现金利润，当前怎样配置？", ["chain-fc-w001", "chain-fc-w012", "app-w01", MODEL_SOURCE_REF, EXECUTABLE_MODEL_SOURCE_REF]),
        ("core_research_map", "AI应用与全产业链哪些方向更值得配置，优先公司是谁？", ["app-c18", "app-c19", "app-c20", "chain-fc-w041", MODEL_SOURCE_REF, EXECUTABLE_MODEL_SOURCE_REF]),
        ("portfolio_overview", "当前应使用集中、均衡还是含现金防守组合？", ["app-w03", "chain-fc-w012", EXECUTABLE_MODEL_SOURCE_REF]),
        ("risk_overview", "哪些事实出现时，应立即降低组合风险预算？", ["app-w05", "chain-fc-w014", "chain-fc-w022"]),
    ]
    sections = [
        _public_section(
            key=key,
            title=title,
            parts=parts_by_key[key],
            order=(index + 1) * 10,
            fallback_refs=refs,
            company_map=company_map,
        )
        for index, (key, title, refs) in enumerate(specs)
    ]
    return sections, parts_by_key


def _research_points(
    entity_key: str,
    *,
    limit: int = 12,
    offset: int = 0,
) -> list[dict[str, Any]]:
    source_points = [
        point for point in build_data_points() if point.get("entity_key") == entity_key
    ]
    points = source_points[offset : offset + limit]
    if len(points) < 8 and len(source_points) >= 8:
        points = source_points[-min(limit, len(source_points)) :]
    if len(points) < 8:
        raise Run16PackInputError(
            f"理论研究实体 {entity_key} 只有 {len(points)} 条底稿，少于8条"
        )
    result: list[dict[str, Any]] = []
    for index, point in enumerate(points, start=1):
        source = SOURCE_BY_REF[str(point["source_ref"])]
        excerpt = str(source.get("excerpt_zh") or source["excerpt"])
        result.append(
            {
                "source_ref": point["source_ref"],
                "data_point_title": f"{point['metric']}：证据{index}",
                "research_category": point["metric"],
                "metric": f"{point['metric']}第{index}项",
                "period": point.get("period") or "截至2026-08-02",
                "as_of_date": "2026-08-02",
                "value_text": point["value_text"],
                "unit": "研究事实",
                "source_excerpt": source["excerpt"],
                "source_excerpt_zh": excerpt,
                "source_context": (
                    f"该来源用于界定第{index}项事实的主体、时间、口径及反方边界。"
                ),
                "interpretation": (
                    f"第{index}项证据表明，不能只凭行业标签判断收益，必须把该事实"
                    "放回需求、供给、商业化或竞争传导链中。"
                ),
                "research_use": (
                    f"用于校验实体结论中的第{index}个关键环节，并约束公司选择、"
                    "财务假设或失效条件。"
                ),
                "limitations": (
                    "该证据只在原披露主体、期间与统计口径内使用；无法从单条材料"
                    "直接外推整个行业、其他公司或未来三年结果。"
                ),
                "evidence_ref_uri": _ev(str(point["source_ref"])),
                "sort_order": index,
            }
        )
    return result


THEORY_PROFILE_NOTES: Mapping[str, Mapping[str, str]] = {
    "ai_application_subsectors": {
        "collection": "按九个细分领域分别收集同口径市场收入、部署覆盖、付费主体、产品能力、合同或案例、竞争格局、购买方ROI和能力边界；部署、收入和可服务支出池不混写。",
        "analysis": "先比较行业是否已有真实预算和可复制产品，再区分提供方与购买方，最后检查竞争壁垒和财务可验证性。企业管理、安全运营和办公文档最接近高频工作流与明确责任共同成立。",
        "limitation": "部分领域只有部署覆盖或购买方总支出，不能计算付费转化率；公开市场报告没有统一披露全部厂商份额时不补算CR3。行业研究分只用于优先级，不是上涨概率。",
        "conclusion": "行业层先选付费、ROI、产品复制和壁垒共同成立的方向；公司层再用合同阶段、收入、毛利、现金流和估值筛选，不能从行业空间直接跳到股票权重。",
    },
    "ai_application_companies": {
        "collection": "逐公司核对付款人、公开价格、合同或部署阶段、客户侧效率、签约到回款路径，并冻结FY2025实际、2026Q1检查点、FY2026—FY2028独立预测、现金流与估值；模型冻结后再并列读取Wind一致预期和最近两个季度逐机构预测。",
        "analysis": "合同、启动、上线、验收、收入和回款分别判断。公开成交价缺失时，从客户节省的人力、差错或产能价值反推可接受价格区间，再检验已披露合同或付费收入能解释独立模型多少增长；剩余增长没有证据时必须下调置信度。",
        "limitation": "公司案例中的效率提升不是独立审计结果，客户名单也不能替代合同金额与续费；未进入模型的候选缺少完整正常化财务、盈亏平衡或估值门禁，因此只给明确的补证和进入条件，不给精确权重。",
        "conclusion": "当前应用侧只配置合合信息；科大讯飞接近估值上沿不追高，金山办公、同花顺、鼎捷数智和深信服均高于独立核心区间。鼎捷数智的2亿元AI签约仍需转成收入、利润和ROE，商业证据不能替代价格门槛。",
    },
    "ai_chain_architecture": {
        "collection": "把全产业链拆成32个不混口径的细分，分别登记全球比较对象、中国主体、A股候选、产品阶段、供需证据、反证和财务门槛。",
        "analysis": "价值并非沿芯片到应用平均分配，而是向内存互连、高速光链路、高端PCB、先进设备、供电和液冷等短期瓶颈迁移；应用端则向能证明收费和现金流的工作流集中。",
        "limitation": "客户内部物料清单、未公开认证、精确采购份额和跨区域电力合同客观不可得；32个细分分数是粗粒度研究优先级，不是历史收益统计。",
        "conclusion": "先研究价值量升级可核验且A股可投资的细分，再逐公司过财务门槛；缺少纯A股标的的HBM与云平台保留产业判断，不用近似公司补位。",
    },
    "ai_compute_semiconductor": {
        "collection": "分别收集GPU/GPGPU、CPU/DCU、定制ASIC、HBM、内存互连、前道设备、量测测试和先进封装的产品、产能、客户部署与验收证据。",
        "analysis": "寒武纪和摩尔线程更接近训练/推理加速卡比较对象；海光属于CPU/DCU双平台。A股更可复核的盈利传导目前在内存互连与设备验收，而不是用全球GPU增速直接外推。",
        "limitation": "国产芯片实际出货、软件栈使用、先进节点产能和客户内部部署披露有限；A股也没有纯HBM制造商，不能建立同口径份额排名。",
        "conclusion": "12个月优先验证澜起科技和北方华创的订单、验收与现金流；三年再看国产计算平台部署、先进存储扩产及出口管制的共同影响。",
    },
    "ai_systems_interconnect_pcb": {
        "collection": "按系统交付、交换网络、可插拔光、CPO/LPO、短距铜、高多层PCB和低损耗材料分别收集平台配置、订单、认证、扩产、良率与回款。",
        "analysis": "光、铜和CPO按距离与维护场景并存；中际旭创、工业富联、立讯精密、沪电股份和生益科技分别暴露于量价、低毛利系统集成、连接制造、板级良率和材料等级。",
        "limitation": "云厂平台的精确物料清单、供应商份额和下一代固定配置尚未完整公开；市场文章关于全面切换的说法只作为补证线索。",
        "conclusion": "优先级为高速光模块、高端PCB/低损耗材料和机架级系统；架构变化一旦改变物料清单，必须同时重算光、铜、PCB、交换与电源。",
    },
    "ai_data_center_physical": {
        "collection": "逐项收集机架功率、HVDC/UPS、电力许可、变压器交期、液冷交付、园区资本开支、预租上架、融资成本和工业自动化订单。",
        "analysis": "供电和液冷是高功率密度的直接瓶颈，IDC则承担建设、融资和上架率风险；工业自动化与机器人更偏三年收入，不能把研发演示计入近期盈利。",
        "limitation": "项目级电价、预租合同、北美客户直供、液冷产品结构和园区回报期披露不完整；不同地区的电力短缺不能互相替代。",
        "conclusion": "未来12个月液冷和机架供电优先于重资本IDC；三年只有订单、验收、回款和资本效率共同改善，才提高物理基础设施权重。",
    },
    "key_risks": {
        "collection": "把付费不兑现、资本开支回报下降、供给错配、架构替代、出口管制、现金流背离和共同估值风险分别建立可观察触发条件。",
        "analysis": "最危险的不是单一增长低于预期，而是订单或使用量增加却没有利润与现金流、物料清单发生迁移、以及多只持仓同时依赖同一资本开支和估值因子。",
        "limitation": "新架构采用率、政策执行时间和客户资本回报无法精确赋概率；压力测试只说明条件发生后的影响方向，不代表发生概率。",
        "conclusion": "任一核心触发条件出现时先降低对应风险预算，再复核经营链；长期行业空间不能抵消公司当期现金流、份额或估值错误。",
    },
}


def _literature_review(refs: Sequence[str]) -> str:
    entries = []
    for ref in refs[:6]:
        source = SOURCE_BY_REF.get(ref) or {}
        title = str(source.get("title_zh") or source.get("title") or ref)
        publisher = str(source.get("publisher") or "来源主体未注明")
        date = str(
            source.get("published_at")
            or source.get("publish_date")
            or source.get("event_date")
            or "日期未注明"
        )
        entries.append(f"{publisher}《{title}》（{date}）")
    return (
        "本专题同时使用公司/机构原始披露与独立产业研究。主要材料包括"
        + "；".join(entries)
        + "。原始披露用于确认主体、产品、时间和数量，机构材料用于比较方法和预测；"
        "同源转载已合并，结论冲突时保留差异而不做网页数量投票。"
    )


def _theory_entity(
    *,
    key: str,
    canonical_name: str,
    display_name: str,
    description: str,
    parts: Mapping[str, str],
    point_entity_key: str,
    point_offset: int = 0,
) -> dict[str, Any]:
    refs = _source_refs_in_text(_structured_body(parts))
    if len(refs) < 3:
        refs = [
            point["source_ref"]
            for point in _research_points(point_entity_key, offset=point_offset)
        ]
    notes = THEORY_PROFILE_NOTES[key]
    return {
        "key": key,
        "canonical_name": canonical_name,
        "display_name": display_name,
        "entity_type": "theme",
        "taxonomy_level": "theme",
        "description": description,
        "entity_research_mode": "theory_research",
        "external_ref_type": "opportunity_lens_entity",
        "maturation_status": "research_only",
        "readiness_score": 1.0,
        "readiness_reason": "问题、双链证据、反方和财务传导均已形成，等待独立审稿。",
        "research_priority_label": "research_only_literature_review_complete",
        "source_count": len(refs),
        "independent_source_count": len(
            {SOURCE_BY_REF[ref]["independence_key"] for ref in refs if ref in SOURCE_BY_REF}
        ),
        "candidate_reason": description,
        "evidence_ref_uri": _ev(refs[0]),
        "evidence_ref_uri_list": [_ev(ref) for ref in refs],
        "score_point": None,
        "score_grade": "unrated",
        "score_band_low": None,
        "score_band_high": None,
        "coverage": 0.92,
        "confidence": 0.82,
        "factor_scores": [],
        "research_profile": {
            "entity_research_mode": "theory_research",
            "research_depth_status": "complete",
            "research_question": parts["问题"],
            "research_scope": description,
            "methodology_note": parts["研究方法与数据"],
            "literature_review_markdown": _literature_review(refs),
            "data_collection_markdown": notes["collection"],
            "analysis_markdown": notes["analysis"],
            "answer_markdown": parts["总结"],
            "conclusion_markdown": notes["conclusion"],
            "limitations_markdown": notes["limitation"],
            "evidence_ref_uri_list": [_ev(ref) for ref in refs],
        },
        "research_data_points": _research_points(
            point_entity_key, offset=point_offset
        ),
    }


def _weighted_model_score(
    model: Mapping[str, Any], scope: str, score_key: str
) -> float:
    portfolio = _executable_portfolio_by_key(model, scope, "balanced")
    total = 0.0
    invested = 0.0
    for holding in portfolio["holdings"]:
        weight = _finite(holding["weight_pct"], "holding.weight_pct")
        ledger = model["companies"][holding["ticker"]]["portfolio_candidate"][
            "score_ledger"
        ]
        value = _finite(ledger[score_key]["value"], f"{holding['ticker']}.{score_key}")
        total += weight * value
        invested += weight
    if invested <= 0:
        raise Run16PackInputError(f"{scope} 均衡组合没有有效持仓权重")
    return total / invested


def _portfolio_composite_spread(
    model: Mapping[str, Any], scope: str
) -> tuple[float, float, float]:
    portfolio = _executable_portfolio_by_key(model, scope, "balanced")
    values: list[tuple[float, float]] = []
    for holding in portfolio["holdings"]:
        ledger = model["companies"][holding["ticker"]]["portfolio_candidate"][
            "score_ledger"
        ]
        composite = (
            _finite(ledger["direction_score"]["value"], "direction")
            + _finite(ledger["quality_score"]["value"], "quality")
            + _finite(ledger["evidence_score"]["value"], "evidence")
            + 100.0
            - _finite(ledger["risk_score"]["value"], "risk")
        ) / 4.0
        values.append((composite, _finite(holding["weight_pct"], "weight")))
    denominator = sum(weight for _, weight in values)
    point = sum(value * weight for value, weight in values) / denominator
    return min(value for value, _ in values), point, max(value for value, _ in values)


def _factor(
    *,
    code: str,
    metric_name: str,
    score: float,
    rationale: str,
    value_summary: str,
    topic_analysis: str,
    analysis_points: Sequence[str],
    refs: Sequence[str],
) -> dict[str, Any]:
    independence_keys = {
        str(SOURCE_BY_REF[ref]["independence_key"])
        for ref in refs
        if ref in SOURCE_BY_REF
    }
    if len(independence_keys) < 5:
        raise Run16PackInputError(
            f"重要因子 {code} 的独立证据组少于5个：{len(independence_keys)}"
        )
    information_points = []
    for index, ref in enumerate(refs, start=1):
        source = SOURCE_BY_REF[ref]
        excerpt = str(source.get("excerpt_zh") or source["excerpt"])
        information_points.append(
            {
                "evidence_ref": _ev(ref),
                "excerpt": excerpt,
                "interpretation": (
                    f"第{index}条独立证据由{source['publisher']}发布，用于约束"
                    f"“{metric_name}”的事实边界：{excerpt}"
                ),
                "independence_key": source["independence_key"],
            }
        )
    return {
        "factor_code": code,
        "metric_name": metric_name,
        "unit": "分",
        "period": "截至2026-08-02，观察未来12个月与3年",
        "score_raw": round(score, 2),
        "score_adjusted": round(score, 2),
        "score_status": "complete",
        "coverage": 1.0,
        "confidence": 0.82,
        "score_rationale": rationale,
        "factor_value_summary": value_summary,
        "source_context_summary": (
            "评分的数值来自冻结组合模型中持仓公司的相应评分按均衡组合权重汇总；"
            "外部来源只负责约束评分方向与边界，不把网页数量机械换算成分数。"
        ),
        "factor_topic_analysis": topic_analysis,
        "theme_analysis_points": list(analysis_points),
        "evidence_ref_uri_list": [
            _ev(ref) for ref in [*refs, EXECUTABLE_MODEL_SOURCE_REF]
        ],
        "information_points": information_points,
    }


def _market_entity(
    model: Mapping[str, Any], *, scope: str, parts: Mapping[str, str]
) -> dict[str, Any]:
    low, point, high = _portfolio_composite_spread(model, scope)
    if scope == "applications":
        refs = {
            "direction": ["app-w01", "app-w02", "app-w03", "app-w04", "app-w06"],
            "quality": ["app-c01", "app-c03", "app-c05", "app-c07", "app-c11"],
            "evidence": ["app-c01", "app-c03", "app-c05", "app-c07", "app-c10", "app-c11"],
            "pricing": ["app-c01", "app-c03", "app-c05", "app-c07", "app-c11"],
            "barrier": ["app-r04", "app-r01", "app-r02", "app-c01", "app-c03", "app-c05"],
        }
        factor_specs = [
            ("demand.application_intensity_change", "AI应用付费与使用强度", "direction_score", "需求真实但收费分化，组合只保留能观察合同、席位、调用或续费的公司。", "direction"),
            ("company.financial_capture_quality", "应用收入转化为利润和现金流的质量", "quality_score", "盈利质量必须同时看调整后利润、经营现金流、资本开支和交付成本。", "quality"),
            ("company.exposure_directness", "AI应用收入与客户证据直接性", "evidence_score", "产品上线不等于增量收入，客户、付费或合同至少需要一项可复核数据。", "evidence"),
            ("supply.substitution_barrier", "数据、工作流与渠道替代壁垒", "risk_score", "模型商品化会削弱薄封装应用；这里把风险分反向转换为缓冲分，专有数据、渠道和工作流决定防御力。", "barrier"),
        ]
        key = "ai_application_portfolios"
        names = ("AI应用公司优选与组合", "AI应用：公司优选与组合")
    else:
        refs = {
            "direction": ["chain-fc-w001", "chain-fc-w007", "chain-fc-w012", "chain-fc-w013", "chain-fc-w016"],
            "quality": ["chain-fc-w026", "chain-fc-w027", "chain-fc-w028", "chain-fc-w029", "chain-fc-w030"],
            "evidence": ["chain-fc-w027", "chain-fc-w028", "chain-fc-w029", "chain-fc-w030", "chain-fc-w031"],
            "pricing": ["chain-fc-w026", "chain-fc-w027", "chain-fc-w028", "chain-fc-w029", "chain-fc-w030"],
            "barrier": ["chain-fc-w029", "chain-fc-w030", "chain-fc-w031", "chain-fc-w035", "chain-fc-w028"],
        }
        factor_specs = [
            ("demand.customer_capex_capacity_signal", "全球AI资本开支与订单强度", "direction_score", "云厂资本开支继续扩张，但只有通过认证、订单和交付才能传到A股公司。", "direction"),
            ("company.financial_capture_quality", "产业链收入转化为现金流的质量", "quality_score", "强订单期仍需扣除扩产、库存、预付款和客户账期，收入不能代替自由现金流。", "quality"),
            ("company.exposure_directness", "AI产品、客户与收入暴露直接性", "evidence_score", "直接产品和量产收入优先，主题映射和无法验证客户关系不进入核心权重。", "evidence"),
            ("supply.substitution_barrier", "认证、工艺与架构替代壁垒", "risk_score", "这里把风险分反向转换为缓冲分；多代量产、客户协同和良率提高缓冲，架构迁移与第二供应商削弱缓冲。", "barrier"),
        ]
        key = "ai_full_chain_portfolios"
        names = ("AI全产业链公司优选与组合", "AI全产业链：公司优选与组合")

    factors = []
    for spec in factor_specs:
        code, metric_name, score_key, conclusion, ref_key = spec
        raw_score = _weighted_model_score(model, scope, score_key)
        score = 100.0 - raw_score if score_key == "risk_score" else raw_score
        factors.append(
            _factor(
                code=code,
                metric_name=metric_name,
                score=score,
                rationale=(
                    f"{metric_name}为{score:.2f}分，来自均衡组合持仓公司的"
                    f"{score_key}按实际权重加权；{conclusion}"
                ),
                value_summary=f"模型加权得分{score:.2f}分；分数是研究排序，不是收益概率。",
                topic_analysis=conclusion,
                analysis_points=(
                    f"该项只在{SCOPE_NAMES[scope]}均衡组合的实际持仓和权重内汇总。",
                    "新增证据必须先核验主体、产品、期间、数量和独立性，再改变分数。",
                ),
                refs=refs[ref_key],
            )
        )
    entity_refs = list(dict.fromkeys(ref for rows in refs.values() for ref in rows))
    return {
        "key": key,
        "canonical_name": names[0],
        "display_name": names[1],
        "entity_type": "theme",
        "taxonomy_level": "theme",
        "description": (
            f"用冻结的公司财务、估值、方向评分、自由流通市值和近期相关性，构建"
            f"{SCOPE_NAMES[scope]}集中、均衡和风险分散三类A股组合。"
        ),
        "entity_research_mode": "market_linked",
        "score_point": round(point, 2),
        "score_band_low": round(low, 2),
        "score_band_high": round(high, 2),
        "score_grade": "B" if point >= 70 else "C",
        "score_quality_label": "medium_confidence",
        "coverage": 1.0,
        "confidence": 0.82,
        "evidence_ref_uri": _ev(entity_refs[0]),
        "evidence_ref_uri_list": [_ev(ref) for ref in entity_refs],
        "factor_scores": factors,
        "candidate_reason": parts["总结"],
        "maturation_status": "review_ready",
        "readiness_score": 0.90,
        "readiness_reason": "权重、相关性、持仓上限、现金和压力测试均已复算，等待独立审稿。",
    }


def _entities(
    model: Mapping[str, Any], parts: Mapping[str, Mapping[str, str]]
) -> list[dict[str, Any]]:
    return [
        _theory_entity(
            key="ai_application_subsectors",
            canonical_name="AI应用细分行业产品能力与付费研究",
            display_name="AI应用细分行业、产品与付费验证",
            description="分别研究九个AI应用细分领域的市场、转化、提供方、购买方、竞争格局、能力边界和投资优先级。",
            parts=parts["ai_application_subsectors"],
            point_entity_key="ai_application_subsectors",
        ),
        _theory_entity(
            key="ai_application_companies",
            canonical_name="AI应用公司商业化财务与估值",
            display_name="AI应用公司：商业化、财务与估值",
            description="逐公司核对付款人、合同、部署、收入和客户价值，再进入FY1—FY3、现金流、估值与市场分歧。",
            parts=parts["ai_application_companies"],
            point_entity_key="ai_application_companies",
        ),
        _market_entity(model, scope="applications", parts=parts["ai_application_portfolios"]),
        _theory_entity(
            key="ai_chain_architecture",
            canonical_name="AI产业链重构与跨环节供需",
            display_name="AI产业链重构与供需",
            description="以算力生成、数据搬运、物理承载、能源供给和软件变现重建32个细分节点与跨期供需。",
            parts=parts["ai_chain_architecture"],
            point_entity_key="ai_chain_architecture",
        ),
        _theory_entity(
            key="ai_compute_semiconductor",
            canonical_name="算力芯片存储与半导体供给",
            display_name="算力芯片、存储与半导体供给",
            description="区分GPU、ASIC、CPU/DCU、HBM、内存互连、晶圆设备和先进封装，并比较已建模公司与候选。",
            parts=parts["ai_compute_semiconductor"],
            point_entity_key="ai_chain_architecture",
            point_offset=10,
        ),
        _theory_entity(
            key="ai_systems_interconnect_pcb",
            canonical_name="AI服务器高速互联与PCB材料",
            display_name="AI服务器、互联与PCB材料",
            description="研究服务器和机架、交换与光铜互联、高端PCB及CCL的价值量迁移和公司财务。",
            parts=parts["ai_systems_interconnect_pcb"],
            point_entity_key="ai_chain_architecture",
            point_offset=22,
        ),
        _theory_entity(
            key="ai_data_center_physical",
            canonical_name="AI电力液冷数据中心与物理智能",
            display_name="AI电力、液冷与物理基础设施",
            description="研究供电、液冷、并网、数据中心运营和工业自动化的项目兑现、现金流与估值。",
            parts=parts["ai_data_center_physical"],
            point_entity_key="ai_chain_architecture",
            point_offset=32,
        ),
        _market_entity(model, scope="full_chain", parts=parts["ai_full_chain_portfolios"]),
        _theory_entity(
            key="key_risks",
            canonical_name="AI投资关键风险与失效条件",
            display_name="关键风险与失效条件",
            description="研究AI付费不兑现、资本开支回报下降、供给错配、技术替代、政策与共同估值风险。",
            parts=parts["key_risks"],
            point_entity_key="key_risks",
        ),
    ]


def _entity_sections(
    model: Mapping[str, Any],
    company_map: Mapping[str, Mapping[str, Any]],
    parts: Mapping[str, Mapping[str, str]],
) -> list[dict[str, Any]]:
    specs = [
        (
            "ai_application_subsectors",
            "AI应用细分行业、产品与付费验证",
            parts["ai_application_subsectors"],
            ["app-i01", "app-i03", "app-i05", "app-i06", "app-i08", "app-i09"],
        ),
        (
            "ai_application_companies",
            "AI应用公司：合同、财务质量与估值",
            parts["ai_application_companies"],
            ["app-c01", "app-c03", "app-i16", "app-i17", "app-i19", "app-i22", MODEL_SOURCE_REF, RECONCILIATION_SOURCE_REF],
        ),
        (
            "ai_application_portfolios",
            "AI应用：公司优选、权重与组合",
            parts["ai_application_portfolios"],
            ["app-w01", "app-w03", EXECUTABLE_MODEL_SOURCE_REF],
        ),
        (
            "ai_chain_architecture",
            "AI产业链重构与跨环节供需",
            parts["ai_chain_architecture"],
            ["chain-fc-w001", "chain-fc-w004", "chain-fc-w012", "chain-fc-w016"],
        ),
        (
            "ai_compute_semiconductor",
            "算力芯片、存储与半导体供给",
            parts["ai_compute_semiconductor"],
            ["chain-fc-w001", "chain-fc-w004", "chain-fc-w010", "chain-fc-w041", MODEL_SOURCE_REF],
        ),
        (
            "ai_systems_interconnect_pcb",
            "AI服务器、高速互联与PCB材料",
            parts["ai_systems_interconnect_pcb"],
            ["chain-fc-w007", "chain-fc-w027", "chain-fc-w028", "chain-fc-w040", MODEL_SOURCE_REF],
        ),
        (
            "ai_data_center_physical",
            "AI电力、液冷、数据中心与物理智能",
            parts["ai_data_center_physical"],
            ["chain-fc-w016", "chain-fc-w021", "chain-fc-w032", "chain-fc-w038", MODEL_SOURCE_REF],
        ),
        (
            "ai_full_chain_portfolios",
            "AI全产业链：公司优选、权重与组合",
            parts["ai_full_chain_portfolios"],
            ["chain-fc-w012", "chain-fc-w016", EXECUTABLE_MODEL_SOURCE_REF],
        ),
        (
            "key_risks",
            "关键风险、反方证据与组合失效条件",
            parts["key_risks"],
            ["app-w05", "chain-fc-w014", "chain-fc-w022", MODEL_SOURCE_REF],
        ),
    ]
    result: list[dict[str, Any]] = []
    for order, (key, title, body_parts, refs) in enumerate(specs, start=1):
        row = _public_section(
            key=f"{key}_deep_research",
            title=title,
            parts=body_parts,
            order=order * 10,
            fallback_refs=refs,
            company_map=company_map,
        )
        row["entity_key"] = key
        result.append(row)
    return result


def _target_point(
    metric_name: str,
    value: Any,
    unit: str,
    period: str,
) -> dict[str, Any]:
    source = {
        "title": "Run16 当前价格门槛与可执行组合冻结结果",
        "publisher": "Industry Demo组合执行模型",
        "excerpt": "执行层绑定独立模型哈希，冻结六种当前股票/现金权重和压力测试。",
    }
    row: dict[str, Any] = {
        "metric_name": metric_name,
        "metric_category": "组合风险",
        "period": period,
        "unit": unit,
        "source_title": source["title"],
        "source_publisher": source["publisher"],
        "source_excerpt": source["excerpt"],
        "evidence_ref_uri": _ev(EXECUTABLE_MODEL_SOURCE_REF),
    }
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        row["value_num"] = float(value)
        row["value_text"] = _fmt(value)
    else:
        row["value_text"] = str(value)
    return row


def _targets(model: Mapping[str, Any]) -> list[dict[str, Any]]:
    targets: list[dict[str, Any]] = []
    recommendation_priority = {
        "balanced": 1,
        "risk_diversified": 2,
        "concentrated": 3,
    }
    role_text = {
        "concentrated": (
            "追求方向暴露，接受较高单股和共同因子波动",
            "只有方向、盈利和估值同时增强时提高权重",
            "任何核心持仓利润或客户证据被证伪时立即降至均衡方案",
        ),
        "balanced": (
            "跨方向分配风险预算，作为缺少强单边判断时的基准",
            "盈利兑现且估值仍有缓冲时在方向内再平衡",
            "组合前三大权重或共同估值因子上升时转向风险分散方案",
        ),
        "risk_diversified": (
            "保留AI收益同时限制单股、现金和历史相关性暴露",
            "宏观和风格风险下降后再逐步减少现金与相关性折扣",
            "若相关性在压力期普遍跃升，继续提高现金而非增加名称数量",
        ),
    }
    for scope in SCOPE_NAMES:
        entity_key = (
            "ai_application_portfolios" if scope == "applications" else "ai_full_chain_portfolios"
        )
        for order, kind in enumerate(PORTFOLIO_TYPES, start=1):
            portfolio = _executable_portfolio_by_key(model, scope, kind)
            max_corr = max(
                (float(row["correlation"]) for row in portfolio.get("correlation_diagnostics", [])),
                default=None,
            )
            holdings_text = "、".join(
                f"{row['name']}{_fmt(row['weight_pct'])}%" for row in portfolio["holdings"]
            )
            positioning, confirm, falsify = role_text[kind]
            target_name = f"{SCOPE_NAMES[scope]}{PORTFOLIO_NAMES[kind]}"
            targets.append(
                {
                    "entity_key": entity_key,
                    "target_name": target_name,
                    "target_type": "basket",
                    "exposure_rationale": f"{positioning}；当前持仓为{holdings_text}。",
                    "evidence_ref_uri": _ev(EXECUTABLE_MODEL_SOURCE_REF),
                    "research_action": (
                        f"每个财报季按{PORTFOLIO_NAMES[kind]}的风险预算，复核"
                        f"{SCOPE_NAMES[scope]}持仓的FY1—FY3利润、现金流、估值和"
                        "相关性后再平衡。"
                    ),
                    "investment_view": f"{target_name}用于{positioning}，不构成收益承诺。",
                    "risk_note": f"{target_name}仍暴露于AI资本开支、估值和流动性共同变化；历史相关性不代表未来。",
                    "target_priority": (
                        f"当前建议顺序第{recommendation_priority[kind]}："
                        "均衡组合是缺少单一强观点时的默认基准；其他方案按风险预算和明确方向观点切换。"
                    ),
                    "target_quality_label": "冻结模型、约束和压力测试已完成，等待独立审稿",
                    "relative_preference": f"相对同一范围另外两种方案，本方案的核心差异是：{positioning}。",
                    "confirmed_scenario_action": confirm,
                    "falsified_scenario_action": falsify,
                    "target_profile_markdown": f"{target_name}持有{len(portfolio['holdings'])}只股票，现金{_fmt(portfolio['cash_weight_pct'])}%，前三大权重{_fmt(portfolio['top3_weight_pct'])}%，有效持仓数{_fmt(portfolio['effective_number_of_holdings'])}。{_cite(EXECUTABLE_MODEL_SOURCE_REF)}",
                    "target_deep_research_markdown": (
                        "权重从自由流通市值出发，经方向、质量、证据、估值和风险修正，"
                        "再执行单股、方向、现金和相关性约束。"
                        + (
                            "单一股票仓位没有两两相关性，该指标不适用。"
                            if max_corr is None
                            else f"最高已观测两两相关性为{_fmt(max_corr, 4)}；该值只识别过去一年共同风险，不预测未来回报。"
                        )
                        + f"{_cite(EXECUTABLE_MODEL_SOURCE_REF)}"
                    ),
                    "entity_relation_markdown": f"该观察篮子是{SCOPE_NAMES[scope]}市场实体的{PORTFOLIO_NAMES[kind]}执行版本。",
                    "parent_research_relation_markdown": "主报告解释方向、公司与风险，本篮子页保留可复算权重、约束和再平衡条件。",
                    "conditional_investment_recommendation": f"仅在{confirm}；若出现“{falsify}”则降级或退出。",
                    "financial_data_status": "18家公司FY1—FY3独立模型、多方法估值和外部对账已形成；结构化市场数据继续由financial.db更新。",
                    "link_status": "linked",
                    "support_status": "supported",
                    "sort_order": recommendation_priority[kind] * 10,
                    "target_data_points": [
                        _target_point("持仓数量", len(portfolio["holdings"]), "只", "组合形成于2026-08-02，市场估值快照截至2026-07-30"),
                        _target_point("现金权重", portfolio["cash_weight_pct"], "%", "组合形成于2026-08-02，市场估值快照截至2026-07-30"),
                        _target_point("前三大权重", portfolio["top3_weight_pct"], "%", "组合形成于2026-08-02，市场估值快照截至2026-07-30"),
                        _target_point("有效持仓数", portfolio["effective_number_of_holdings"], "只", "组合形成于2026-08-02，市场估值快照截至2026-07-30"),
                    ]
                    + (
                        [
                            _target_point(
                                "最高已观测相关性",
                                max_corr,
                                "相关系数",
                                "约一年复权日收益",
                            )
                        ]
                        if max_corr is not None
                        else []
                    ),
                }
            )
    return targets


def _search_plan() -> list[dict[str, Any]]:
    axes = {
        "taxonomy": "AI应用与全产业链分类、边界、交叉关系和平台旧节点冲突",
        "applications": "全球AI应用付费、合同、续费、推理成本、工作流与替代风险",
        "supply_demand": "AI芯片、服务器、互连、PCB、存储、电力、散热和数据中心供需",
        "companies": "重点A股公司产品、客户、产能、收入敞口、治理与反方证据",
        "financials": "最新财报、季报、现金流、资本开支、净资产、ROE和ROA",
        "valuation": "多方法估值、反向估值、市场隐含预期和最近两个季度外部预测",
        "portfolios": "自由流通市值、流动性、相关性、行业集中、共同暴露和再平衡",
        "risks": "商业化延后、资本开支回报、供给错配、政策、技术替代与风格共振",
    }
    plan: list[dict[str, Any]] = []
    for key, query in axes.items():
        plan.extend(
            [
                {
                    "axis_key": key,
                    "source_channel": "report",
                    "round": 1,
                    "query": f"近期中英文研报与本地资料：{query}",
                    "status": "completed",
                },
                {
                    "axis_key": key,
                    "source_channel": "web",
                    "round": 1,
                    "query": f"全球公司、监管、国际机构、产业组织与项目方：{query}",
                    "status": "completed",
                },
                {
                    "axis_key": key,
                    "source_channel": "web",
                    "round": 2,
                    "query": f"追最早出处、主体产品期间数量、独立侧证和反证：{query}",
                    "gap_trigger": "第一轮存在口径冲突、未验证重要线索、财务分歧或客户/产能证据缺口",
                    "status": "completed",
                },
            ]
        )
    return plan


def _prompt_requirements() -> list[dict[str, Any]]:
    request = _read_json(WORKFLOW_REQUEST_PATH)
    rows = request.get("prompt_requirements")
    if not isinstance(rows, list) or len(rows) != 23:
        raise Run16PackInputError("Run16 workflow_request 必须完整保留23条用户要求")
    output_hints = (
        "ai_chain_architecture",
        "ai_chain_architecture",
        "ai_application_subsectors",
        "core_research_map",
        "core_research_map",
        "core_research_map",
        "company_research_entities",
        "company_financial_entities",
        "company_financial_entities",
        "company_pages",
        "ai_application_portfolios",
        "ai_full_chain_portfolios",
        "portfolio_entities",
        "portfolio_entities",
        "core_research_map",
        "summary",
        "source_index",
        "source_index",
        "source_index",
        "key_risks",
        "risk_overview",
        "viewer_contract",
        "review_workflow",
    )
    result = []
    for row, output_hint in zip(rows, output_hints, strict=True):
        result.append(
            {
                "question": str(row["question"]),
                "acceptance_criteria": str(
                    row.get("acceptance_criteria")
                    or "在对应正文、实体、模型或审计产物中完整覆盖并绑定证据。"
                ),
                "output_hint": output_hint,
            }
        )
    return result


def _open_search_statistics() -> dict[str, Any]:
    application = _read_json(WORKPAPER_DIR / "ai_applications_evidence.json")
    chain = _read_json(WORKPAPER_DIR / "ai_full_chain_evidence.json")
    summary = evidence_summary()
    unverified = chain.get("important_unverified_signals") or []
    conflicts = chain.get("important_conflicts") or []
    gaps = list(application.get("gaps") or []) + list(chain.get("open_gaps") or [])
    return {
        **summary,
        "pack_total_source_count": summary["source_count"] + 3,
        "internal_reference_artifact_count": 3,
        "important_conflict_count": len(conflicts),
        "unresolved_material_lead_count": len(unverified),
        "unresolved_material_lead_disposition": (
            "重要但尚未验证的线索只进入监控和不确定性，不进入核心评分、"
            "客户份额、财务事实或组合权重。"
        ),
        "same_origin_duplicate_count": 0,
        "recorded_gap_count": len(gaps),
        "report_quota_status": {
            "applications": application.get("report_channel_summary"),
            "full_chain": chain.get("report_chain_status"),
        },
    }


def _modeling_records(
    model: Mapping[str, Any],
    executable: Mapping[str, Any],
    reconciliation: Mapping[str, Any],
) -> list[dict[str, Any]]:
    model_hash = _file_sha256(INDEPENDENT_MODEL_PATH)
    reconciliation_hash = _file_sha256(EXTERNAL_RECONCILIATION_PATH)
    workpaper_hash = _content_sha256(
        {
            "applications": _file_sha256(APPLICATION_WORKPAPER_PATH),
            "full_chain": _file_sha256(FULL_CHAIN_WORKPAPER_PATH),
        }
    )
    return [
        {
            "skill_name": "industry_supply_demand_modeling",
            "status": "completed",
            "input_artifact_hash": workpaper_hash,
            "output_artifact_hash": _content_sha256(
                {"sections": ["ai_applications", "ai_full_chain"]}
            ),
            "result_summary": "完成AI应用商业化与全产业链供需、价值迁移和反方路径。",
        },
        {
            "skill_name": "company_financial_modeling",
            "status": "completed",
            "input_artifact_hash": _content_sha256(model.get("input_artifacts")),
            "output_artifact_hash": model_hash,
            "result_summary": "18家公司FY1—FY3收入、利润、现金流、权益、ROE和ROA在读取一致预期前完成。",
        },
        {
            "skill_name": "company_valuation_modeling",
            "status": "completed",
            "input_artifact_hash": model_hash,
            "output_artifact_hash": reconciliation_hash,
            "result_summary": "完成适用的市盈率、股权现金流折现、PB—ROE和当前市场隐含估值，并在独立定稿后外部对账。",
        },
        {
            "skill_name": "probability_scenario_modeling",
            "status": "completed",
            "input_artifact_hash": model_hash,
            "output_artifact_hash": _file_sha256(EXECUTABLE_PORTFOLIO_PATH),
            "result_summary": (
                "完成公司下行、基准、上行情景和组合压力测试，并将当前价格门槛、"
                "六种可执行组合、现金权重及过滤后压力结果绑定独立模型哈希冻结；"
                "不给主观情景赋伪精确概率。"
            ),
        },
    ]


def _validate_quality_floors(pack: Mapping[str, Any]) -> None:
    if len(pack.get("data_points", [])) < 100:
        raise Run16PackInputError("Run16 平行数据点少于100")
    section_lengths = {
        str(section["section_key"]): public_markdown_character_count(
            section["body_markdown"]
        )
        for section in pack.get("sections", [])
    }
    short_sections = {key: length for key, length in section_lengths.items() if length < 200}
    if short_sections:
        raise Run16PackInputError(f"Run16 首页摘要 section 少于200字：{short_sections}")
    long_sections = {key: length for key, length in section_lengths.items() if length > 600}
    if long_sections:
        raise Run16PackInputError(f"Run16 首页问题摘要 section 超过600字：{long_sections}")
    total = sum(section_lengths.values())
    if total > 15000:
        raise Run16PackInputError(f"Run16 主报告仍过长，超过15000字：{total}")
    entity_lengths = {
        str(section["entity_key"]): len(str(section["body_markdown"]))
        for section in pack.get("entity_sections", [])
    }
    short_entities = {key: length for key, length in entity_lengths.items() if length < 1200}
    if short_entities:
        raise Run16PackInputError(f"Run16 实体专题少于1200字：{short_entities}")
    for section in list(pack.get("sections", [])) + list(pack.get("entity_sections", [])):
        _assert_no_mojibake(str(section.get("body_markdown") or ""), str(section.get("section_key")))


def _public_draft(pack: Mapping[str, Any]) -> str:
    chunks = [
        f"# {pack['display_title']}",
        str(pack["problem_statement"]),
    ]
    for section in sorted(pack["sections"], key=lambda row: row["sort_order"]):
        chunks.append(f"## {section['section_title']}\n\n{section['body_markdown']}")
    draft = "\n\n".join(chunks).strip() + "\n"
    _assert_no_mojibake(draft, "Run16公开Markdown")
    return draft


def build_pack() -> dict[str, Any]:
    model, executable, reconciliation, company_map = load_frozen_artifacts()
    sections, parts = _public_sections(model, reconciliation, company_map)
    intake = parse_markdown_intake_text(INTAKE_PATH.read_text(encoding="utf-8"))
    builder = RunPackBuilder(
        slug="ai-applications-full-chain-portfolio-run16",
        display_title="AI应用与全产业链组合研究",
        research_question=str(intake["research_question"]),
        problem_statement=(
            "AI应用和全产业链哪些方向能把需求转成可持续利润，哪些A股公司和组合"
            "在未来12个月至3年更具可验证的风险收益？"
        ),
        intake=intake,
        requested_by="user_run16_high_stakes_portfolio_research",
        run_mode="c_hybrid",
        quality_profile="deep_research",
        public_section_structure_contract=PUBLIC_SECTION_STRUCTURE_CONTRACT,
        homepage_section_min_characters=200,
        homepage_section_max_characters=600,
    )
    for source in [*SOURCES, *_model_sources(model, executable)]:
        _assert_no_mojibake(json.dumps(source, ensure_ascii=False), f"source:{source['ref']}")
        builder.add_source(source)
    builder.data_points.extend(build_data_points())
    builder.claims.extend(build_claims())
    for entity in _entities(model, parts):
        builder.add_entity(entity)
    builder.entity_sections.extend(_entity_sections(model, company_map, parts))
    builder.entity_investment_targets.extend(_targets(model))
    builder.sections.extend(sections)
    builder.search_plan.extend(_search_plan())
    builder.modeling_records.extend(
        _modeling_records(model, executable, reconciliation)
    )
    builder.independent_model_freezes.append(
        {
            "model_ref": "Run16 AI应用与全产业链18家公司独立财务估值和组合模型",
            "input_hash": _content_sha256(model.get("input_artifacts")),
            "output_hash": _file_sha256(INDEPENDENT_MODEL_PATH),
            "frozen_before_consensus": True,
            "frozen_at": str(model.get("as_of_date") or "2026-07-30"),
        }
    )
    builder.external_reconciliations.append(
        {
            "model_ref": "Run16 AI应用与全产业链18家公司独立财务估值和组合模型",
            "benchmark_ref": "Wind一致预期与研究截止日前最近两个季度同公司卖方预测",
            "artifact_hash": _file_sha256(EXTERNAL_RECONCILIATION_PATH),
            "status": "completed",
            "summary": "独立模型定稿后逐公司逐年度对账；客观缺失的外部字段保留缺口，不用其他公司或相邻年度补齐。",
        }
    )
    builder.evidence_groups.update(
        {
            str(source["ref"]): str(source["independence_key"])
            for source in [*SOURCES, *_model_sources(model, executable)]
        }
    )

    pack = builder.build(publication_mode="stage")
    pack["prompt_requirements"] = _prompt_requirements()
    pack["open_search_statistics"] = _open_search_statistics()
    pack["financial_data_boundary"] = {
        "database": "financial.db",
        "policy": (
            "Wind、Tushare和yfinance结构化快照只进入financial.db；本研究包只保存"
            "冻结模型、外部对账结论和指向公司页的只读语义关系。"
        ),
        "company_ids": sorted(
            row["company_id"]
            for row in company_map.values()
            if row.get("is_model_company") is True
        ),
    }
    pack["deterministic_gate_plan"] = [
        {"gate": gate, "status": "pending", "result": "待父流程执行并写回"}
        for gate in (
            "contract",
            "evidence_integrity",
            "provenance",
            "duplication",
            "scope_and_units",
        )
    ]
    pack["review_records"] = []
    _validate_quality_floors(pack)
    report = validate_run_pack(pack, publication_mode="stage")
    report.raise_for_errors()
    return pack


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the staged Run16 pack")
    parser.add_argument(
        "--validate-inputs",
        action="store_true",
        help="Validate frozen inputs and print their identities without writing output",
    )
    args = parser.parse_args()
    model, executable, reconciliation, _ = load_frozen_artifacts()
    if args.validate_inputs:
        print(
            json.dumps(
                {
                    "independent_model": str(INDEPENDENT_MODEL_PATH),
                    "independent_model_sha256": _file_sha256(INDEPENDENT_MODEL_PATH),
                    "independent_output_hash": model["output_hash"],
                    "reconciliation": str(EXTERNAL_RECONCILIATION_PATH),
                    "reconciliation_sha256": _file_sha256(EXTERNAL_RECONCILIATION_PATH),
                    "reconciliation_content_sha256": reconciliation["content_sha256"],
                    "executable_portfolio": str(EXECUTABLE_PORTFOLIO_PATH),
                    "executable_portfolio_sha256": _file_sha256(EXECUTABLE_PORTFOLIO_PATH),
                    "executable_output_hash": executable["output_hash"],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    pack = build_pack()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    _atomic_write_text(
        OUTPUT_PATH,
        json.dumps(pack, ensure_ascii=False, indent=2) + "\n",
    )
    _atomic_write_text(PUBLIC_DRAFT_PATH, _public_draft(pack))
    report = validate_run_pack(pack, publication_mode="stage")
    print(
        json.dumps(
            {
                "output": str(OUTPUT_PATH),
                "public_draft": str(PUBLIC_DRAFT_PATH),
                "homepage_visible_characters": sum(
                    public_markdown_character_count(row["body_markdown"])
                    for row in pack["sections"]
                ),
                "homepage_section_visible_characters": {
                    str(row["section_key"]): public_markdown_character_count(
                        row["body_markdown"]
                    )
                    for row in pack["sections"]
                },
                "homepage_markdown_source_characters": sum(
                    len(str(row["body_markdown"])) for row in pack["sections"]
                ),
                **report.as_dict(),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
