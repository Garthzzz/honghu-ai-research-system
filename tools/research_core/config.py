from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = ROOT / "config" / "research_workflow.yaml"


class WorkflowConfigError(ValueError):
    pass


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def _validate(config: dict[str, Any]) -> None:
    for key in ("contract_version", "manifest_version", "common", "tracks"):
        if key not in config:
            raise WorkflowConfigError(f"研究工作流配置缺少 {key}")
    tracks = config["tracks"]
    if not isinstance(tracks, dict) or set(tracks) < {"a", "b", "c"}:
        raise WorkflowConfigError("研究工作流配置必须包含 a、b、c 三个 track")
    evidence = config["common"].get("evidence", {})
    if evidence.get("count_factor_evidence_by") != "independence_key":
        raise WorkflowConfigError("因子证据必须按 independence_key 计数")
    if evidence.get("unknown_independence_is_independent") is not False:
        raise WorkflowConfigError("未知独立性不得自动算作独立证据")
    providers = config["common"].get("market_data", {}).get("allowed_providers", [])
    if set(providers) != {"api_wind", "api_tushare", "api_yfinance"}:
        raise WorkflowConfigError(
            "新增市场数据源允许列表必须为 api_wind、api_tushare 和 api_yfinance"
        )
    market_data = config["common"].get("market_data", {})
    a_share = market_data.get("a_share", {})
    expected_wind_request_policy = {
        "require_explicit_user_permission_for_large_request": True,
        "unapproved_max_securities_per_request": 10,
        "unapproved_max_fields_per_request": 20,
        "unapproved_max_estimated_observations_per_request": 5000,
        "unapproved_max_securities_per_task_day": 50,
        "unapproved_max_estimated_observations_per_task_day": 50000,
        "forbid_chunking_to_evade_limits": True,
    }
    if a_share != {
        "primary_provider": "api_wind",
        "primary_transport": "internal_http_proxy",
        "supplemental_provider": "api_tushare",
        "merge_policy": "fill_missing_only_with_field_level_provenance",
        "wind_request_policy": expected_wind_request_policy,
    }:
        raise WorkflowConfigError(
            "A 股数据源合同必须为 Wind 内网 HTTP 主源、Tushare 逐字段补缺，"
            "并对未授权的大规模 Wind 请求设硬门禁"
        )
    if market_data.get("disabled_providers") != ["akshare"]:
        raise WorkflowConfigError("当前只禁用 Akshare")
    review = config["common"].get("review", {})
    expected_gates = {"contract", "evidence_integrity", "provenance", "duplication", "scope_and_units"}
    if set(review.get("deterministic_gates", [])) != expected_gates:
        raise WorkflowConfigError(f"deterministic gate 必须恰好是 {sorted(expected_gates)}")
    canonical_stages = set(review.get("canonical_review_stages", []))
    required_stage_floor = {"evidence", "calculation", "science", "financial", "writing", "browser", "evidence_escalation", "final"}
    if canonical_stages != required_stage_floor:
        raise WorkflowConfigError(f"canonical review stage 必须恰好是 {sorted(required_stage_floor)}")
    trigger_stages = set(review.get("artifact_triggers", {}).values())
    if not trigger_stages <= canonical_stages:
        raise WorkflowConfigError(f"artifact trigger 含未知 review stage: {sorted(trigger_stages - canonical_stages)}")
    c_profile = tracks["c"]
    if not set(c_profile.get("publish_requires_review_records", [])) <= canonical_stages:
        raise WorkflowConfigError("C 轨发布 reviewer stage 不在 canonical 列表")
    adaptive_publish = c_profile.get("adaptive_publish_reviews", {})
    unknown_adaptive = {
        stage
        for stages in adaptive_publish.values()
        for stage in (stages if isinstance(stages, list) else [stages])
        if stage not in canonical_stages
    }
    if unknown_adaptive:
        raise WorkflowConfigError(f"C 轨 adaptive publish review 含未知 stage: {sorted(unknown_adaptive)}")
    if c_profile.get("series_storage") != "one_data_point_with_observations_array":
        raise WorkflowConfigError("C 轨长期序列必须以一个 data point + observations 数组存储")
    public_contract = c_profile.get("public_output_contract")
    if not isinstance(public_contract, dict):
        raise WorkflowConfigError("C 轨缺少 public_output_contract 公开输出合同")
    expected_flow = [
        "question",
        "evidence_and_data",
        "method_if_needed",
        "analysis_and_conclusion",
    ]
    if public_contract.get("section_flow") != expected_flow:
        raise WorkflowConfigError(f"C 轨公开章节流程必须是 {expected_flow}")
    required_public_flags = {
        "table_information_value_required",
        "merge_redundant_tables",
        "forbid_generic_unknown_label",
        "forbid_internal_audit_fields",
        "forbid_unexplained_model_codes",
        "require_formula_translation",
        "require_financial_method_result_analysis",
        "require_rightmost_column_visual_audit",
        "forbid_deferred_research_escape_hatch",
    }
    missing_public_flags = sorted(
        key for key in required_public_flags if public_contract.get(key) is not True
    )
    if missing_public_flags:
        raise WorkflowConfigError(
            "C 轨 public_output_contract 必须启用必要键: "
            + ", ".join(missing_public_flags)
        )
    financial_database = config["common"].get("financial_database", {})
    if financial_database.get("path") != "data/financial.db":
        raise WorkflowConfigError("独立财务数据库必须注册为 data/financial.db")
    if financial_database.get("structured_financials_are_research_data_points") is not False:
        raise WorkflowConfigError("结构化公司财务不得继续作为普通 research data point 入库")
    modeling_skills = config["common"].get("modeling_skills", {})
    expected_skills = {
        "company_financial_modeling",
        "company_valuation_modeling",
        "industry_supply_demand_modeling",
        "probability_scenario_modeling",
    }
    if set(modeling_skills) != expected_skills:
        raise WorkflowConfigError(f"建模 Skill 必须恰好是 {sorted(expected_skills)}")
    search_channels = config["common"].get("search_channels", {})
    if search_channels.get("allowed") != ["report", "web"]:
        raise WorkflowConfigError("搜索渠道必须严格区分 report 与 web")
    if search_channels.get("merge_stage") != "analysis_only" or search_channels.get("report_hit_may_suppress_web") is not False:
        raise WorkflowConfigError("研报与网络结果只能在分析阶段合并，研报命中不得抑制网络搜索")
    report_providers = search_channels.get("report_providers")
    if not isinstance(report_providers, list) or not report_providers:
        raise WorkflowConfigError("report 搜索必须登记至少一个可执行研报库 provider")
    datayes = next(
        (item for item in report_providers if item.get("provider_id") == "datayes_playwright"),
        None,
    )
    if not datayes:
        raise WorkflowConfigError("report 搜索必须登记 datayes_playwright")
    required_datayes_contract = {
        "transport": "authenticated_browser_ui",
        "credential_policy": "windows_credential_manager_keyring",
        "search_field": "title_only",
        "company_max_age_days": 183,
        "industry_max_age_days": 366,
        "industry_min_pages": 20,
        "allow_domestic_title_search_fallback": True,
        "fallback_satisfies_platform_recommendation_quota": False,
        "quota_shortfall_must_be_recorded": True,
        "aggregator_is_not_independent_publisher": True,
    }
    for key, expected in required_datayes_contract.items():
        if datayes.get(key) != expected:
            raise WorkflowConfigError(f"datayes_playwright {key} 必须为 {expected!r}")
    required_writing_checks = {
        "no_machine_or_audit_language_in_public_body",
        "no_low_information_or_redundant_tables",
        "evidence_gaps_are_described_precisely",
        "probability_and_formula_terms_are_explained",
        "financial_results_have_method_and_interpretation",
    }
    writing_checks = c_profile.get("writing_review_checks")
    if not isinstance(writing_checks, list) or not required_writing_checks <= set(writing_checks):
        missing = sorted(required_writing_checks - set(writing_checks or []))
        raise WorkflowConfigError(
            "C 轨 writing_review_checks 缺少必要检查: " + ", ".join(missing)
        )
    required_browser_checks = {
        "no_page_level_horizontal_overflow",
        "every_table_checked_at_left_and_right_scroll_extremes",
        "rightmost_header_and_cells_are_fully_visible",
        "long_text_does_not_overlap_or_clip",
        "desktop_and_mobile_screenshots_reviewed",
    }
    browser_checks = c_profile.get("browser_review_checks")
    if not isinstance(browser_checks, list) or not required_browser_checks <= set(browser_checks):
        missing = sorted(required_browser_checks - set(browser_checks or []))
        raise WorkflowConfigError(
            "C 轨 browser_review_checks 缺少必要检查: " + ", ".join(missing)
        )


@lru_cache(maxsize=16)
def _load_workflow_config_cached(
    resolved_path: str,
    modified_ns: int,
    file_size: int,
) -> dict[str, Any]:
    del modified_ns, file_size
    config_path = Path(resolved_path)
    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise WorkflowConfigError(f"研究工作流配置不是对象: {config_path}")
    _validate(data)
    return data


def load_workflow_config(path: str | Path | None = None) -> dict[str, Any]:
    """Load the contract with file-stat invalidation and caller-safe copies."""
    config_path = (Path(path) if path is not None else DEFAULT_CONFIG_PATH).resolve()
    stat = config_path.stat()
    data = _load_workflow_config_cached(str(config_path), stat.st_mtime_ns, stat.st_size)
    return deepcopy(data)


def validate_modeling_skill_assets(
    config: dict[str, Any] | None = None,
    *,
    root: str | Path = ROOT,
) -> dict[str, str]:
    """Validate research-only Skill files without coupling them to Viewer import.

    Research producers and model routing call this boundary (or perform the
    equivalent route-level check).  The Flask Viewer only needs the structural
    workflow contract and its deployment closure, so importing it must not
    require the backend ``skills/`` tree.
    """
    payload = config or load_workflow_config()
    modeling_skills = payload["common"].get("modeling_skills", {})
    base = Path(root).resolve()
    resolved = {
        name: str((base / str(item.get("path") or "")).resolve())
        for name, item in modeling_skills.items()
    }
    missing = sorted(
        name for name, path in resolved.items() if not Path(path).is_file()
    )
    if missing:
        raise WorkflowConfigError("建模 Skill 文件不存在: " + ", ".join(missing))
    return resolved


def clear_workflow_config_cache() -> None:
    """Explicit invalidation for tests and same-timestamp filesystem replacements."""
    _load_workflow_config_cached.cache_clear()


def resolve_track_config(track: str, path: str | Path | None = None) -> dict[str, Any]:
    config = load_workflow_config(path)
    key = str(track or "").strip().lower()
    if key not in config["tracks"]:
        raise WorkflowConfigError(f"未知研究轨道: {track!r}")

    def resolve_profile(profile_key: str, chain: tuple[str, ...] = ()) -> dict[str, Any]:
        if profile_key in chain:
            raise WorkflowConfigError("研究轨道继承形成循环: " + " -> ".join((*chain, profile_key)))
        raw = config["tracks"].get(profile_key)
        if not isinstance(raw, dict):
            raise WorkflowConfigError(f"未知父研究轨道: {profile_key!r}")
        parent_key = raw.get("inherits")
        if not parent_key:
            return deepcopy(raw)
        parent = resolve_profile(str(parent_key), (*chain, profile_key))
        return _deep_merge(parent, {k: v for k, v in raw.items() if k != "inherits"})

    return _deep_merge(config["common"], resolve_profile(key))


def contract_version(path: str | Path | None = None) -> str:
    return str(load_workflow_config(path)["contract_version"])


def manifest_contract_version(path: str | Path | None = None) -> str:
    return str(load_workflow_config(path)["manifest_version"])


def brief_contract_version(path: str | Path | None = None) -> str:
    return str(load_workflow_config(path)["brief_version"])


def cache_contract_version(path: str | Path | None = None) -> str:
    return str(load_workflow_config(path)["cache_version"])


def publish_review_stages(track: str, signals: list[str] | tuple[str, ...] = ()) -> list[str]:
    profile = resolve_track_config(track)
    stages = list(profile.get("publish_requires_review_records", []))
    adaptive = profile.get("adaptive_publish_reviews", {})
    for signal in signals:
        configured = adaptive.get(signal, [])
        stages.extend(configured if isinstance(configured, list) else [configured])
    selected = set(str(stage) for stage in stages if str(stage))
    canonical_order = profile.get("review", {}).get("canonical_review_stages", [])
    return [stage for stage in canonical_order if stage in selected]
