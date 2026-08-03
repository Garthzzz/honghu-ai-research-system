from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Iterable, Mapping

from tools.opportunity_lens.intake_parser import parse_markdown_intake_text
from tools.opportunity_lens.run_pack_builder import RunPackBuilder
from tools.opportunity_lens.run_pack_contract import validate_run_pack


ROOT = Path(__file__).resolve().parents[2]
RUN_CACHE = ROOT / "cache" / "research_runs" / "20260803_nev_production_inventory_run18"
AGENT_DIR = RUN_CACHE / "agent_outputs"
OUTPUT_DIR = (
    ROOT
    / "opportunity_lens"
    / "research_outputs"
    / "20260803_nev_production_inventory_run18"
)
INTAKE_PATH = (
    ROOT
    / "opportunity_lens"
    / "intake_requests"
    / "Opportunity_Lens_用户研究请求_中国生产新能源汽车未来3个月排产与历史库存.md"
)
MODEL_PATH = OUTPUT_DIR / "nev_three_method_model_v1.json"
REPORT_REVIEW_PATH = AGENT_DIR / "report_chain_review.json"
OUTPUT_PATH = OUTPUT_DIR / "run18_pack_stage.json"
MODEL_SOURCE_REF = "model-run18-three-method"

AGENT_PATHS = {
    "industry": AGENT_DIR / "industry_total.json",
    "brand": AGENT_DIR / "brand_bottomup.json",
    "upstream": AGENT_DIR / "upstream_leading.json",
}

PUBLIC_SECTION_STRUCTURE_CONTRACT = "public.problem_method_data_analysis_summary.v1"
ENTITY_KEYS = (
    "industry_total_method",
    "brand_factory_method",
    "upstream_battery_method",
    "three_method_synthesis",
)


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _fmt_whole_half_up(value: Any) -> str:
    rounded = Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return str(int(rounded))


def _slug(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip()).strip("-").lower()
    return cleaned[:56] or hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def _ev(ref: str) -> str:
    return f"source_ref:{ref}"


def _cite(ref: str) -> str:
    return f"^src:{_ev(ref)}"


def _visible_length(markdown: str) -> int:
    text = re.sub(r"\^src:source_ref:[A-Za-z0-9_.-]+", "", markdown)
    text = re.sub(r"[#*_`|>\-]", "", text)
    return len(re.sub(r"\s+", "", text))


def _source_tier(source: Mapping[str, Any]) -> str:
    url = str(source.get("url") or "").lower()
    publisher = str(source.get("publisher") or "").lower()
    tier = str(source.get("tier") or "").lower()
    if any(token in url for token in (".gov.cn", "cada.cn", "caam.org.cn")):
        return "S"
    if any(token in publisher for token in ("乘联", "流通协会", "工信部", "财政部", "国家发改委")):
        return "S"
    if "primary" in tier or any(token in url for token in ("ir.", "cninfo.com.cn")):
        return "S"
    if any(token in tier for token in ("major_media", "association_republication", "company_data")):
        return "A"
    if "weak" in tier:
        return "C"
    return "B"


def _collect_web_sources(
    payloads: Mapping[str, Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], dict[tuple[str, str], str], dict[str, str]]:
    sources: list[dict[str, Any]] = []
    aliases: dict[tuple[str, str], str] = {}
    by_url: dict[str, str] = {}
    by_url_ref: dict[str, str] = {}
    for origin, payload in payloads.items():
        for index, raw in enumerate(payload.get("sources") or [], start=1):
            raw_id = str(raw.get("source_id") or raw.get("id") or f"source-{index}")
            url = str(raw.get("url") or "").strip()
            if not url:
                continue
            url_key = url.rstrip("/").lower()
            if url_key in by_url:
                aliases[(origin, raw_id)] = by_url[url_key]
                continue
            ref = f"w-{origin}-{_slug(raw_id)}"
            title_zh = str(raw.get("title_zh") or "").strip()
            title = str(raw.get("title") or title_zh or raw_id).strip()
            excerpt_zh = str(raw.get("excerpt_zh") or raw.get("excerpt") or "").strip()
            if not excerpt_zh:
                excerpt_zh = f"该来源用于核验{title_zh or title}的时间、数量和统计口径。"
            # Agent 已把英文网页的事实摘录译成中文；只有同时保留英文原文时才标 en。
            original_excerpt = str(raw.get("excerpt") or "").strip()
            is_english = bool(title_zh and original_excerpt and not re.search(r"[\u4e00-\u9fff]", original_excerpt))
            independence_key = str(raw.get("independence_key") or "").strip()
            if not independence_key:
                independence_key = f"{origin}:{raw_id}:{hashlib.sha256(url_key.encode()).hexdigest()[:12]}"
            tier = _source_tier(raw)
            source: dict[str, Any] = {
                "ref": ref,
                "title": title if is_english else (title_zh or title),
                "publisher": str(raw.get("publisher") or "公开发布主体待网页核验").strip(),
                "publish_date": str(
                    raw.get("publish_date")
                    or raw.get("published_at")
                    or raw.get("date")
                    or raw.get("event_period")
                    or "2026-08-03"
                ),
                "url": url,
                "source_tier": tier,
                "source_review_status": "pass" if tier in {"S", "A"} else "pass_with_note",
                "excerpt": original_excerpt if is_english else excerpt_zh,
                "language": "en" if is_english else "zh",
                "independence_key": independence_key,
                "independence_rationale": (
                    "按底层发布主体、原始记录和披露期间合并；转载同一协会月报或公司公告不重复计为独立证据。"
                ),
                "source_channel": "web",
            }
            if is_english:
                source["title_zh"] = title_zh
                source["excerpt_zh"] = excerpt_zh
            sources.append(source)
            aliases[(origin, raw_id)] = ref
            by_url[url_key] = ref
            by_url_ref[url_key] = ref
    return sources, aliases, by_url_ref


REPORT_SOURCES = [
    {
        "ref": "r-barclays-china-signals-20260716",
        "title": "China Signals – Property & infra still weak; NEVs move up a gear",
        "title_zh": "中国经济信号：地产与基建偏弱，新能源汽车提速",
        "publisher": "Barclays",
        "publish_date": "2026-07-16",
        "local_path": "papers/新能源汽车排产与库存/2026-07-16_巴克莱_中国信号——房地产与基建依旧疲软；新能源汽车加速发展.pdf",
        "source_tier": "A",
        "source_review_status": "pass",
        "excerpt": "China NEV output reached 1.62 million units in June, up 29.4% year on year, on the broader NBS definition.",
        "excerpt_zh": "国家统计局宽口径下，6月新能源汽车产量162万辆，同比增长29.4%；该口径宽于新能源乘用车。",
        "language": "en",
        "independence_key": "barclays_nbs_nev_20260716",
        "independence_rationale": "Barclays引用国家统计局和Bloomberg序列，和乘联分会新能源乘用车月报不是同一底层序列。",
        "source_channel": "report",
    },
    {
        "ref": "r-morgan-stanley-global-autos-20260724",
        "title": "Global Autos: June Global Auto Sales: back to growth",
        "title_zh": "全球汽车：6月全球汽车销量恢复增长",
        "publisher": "Morgan Stanley",
        "publish_date": "2026-07-24",
        "local_path": "papers/新能源汽车排产与库存/2026-07-24_待核验券商_全球汽车；6月全球汽车销量：重回增长.pdf",
        "source_tier": "A",
        "source_review_status": "pass_with_note",
        "excerpt": "The report separates China passenger-car sales between domestic and foreign OEMs and also shows exports and dealer inventory charts.",
        "excerpt_zh": "报告拆分6月中国乘用车本土与外资车企销量，并展示出口和经销商库存图；没有标签的最新库存端点不进行视觉猜数。",
        "language": "en",
        "independence_key": "morgan_stanley_global_auto_20260724",
        "independence_rationale": "报告的CPCA/Yiche数据与协会网页同源部分合并，Datastream结构和分析师处理仅作为对账。",
        "source_channel": "report",
    },
    {
        "ref": "r-guosen-auto-strategy-20260617",
        "title": "汽车行业2026年6月投资策略：看好自主乘用车出海加速",
        "publisher": "国信证券",
        "publish_date": "2026-06-17",
        "local_path": "papers/新能源汽车排产与库存/2026-06-17_国信证券_汽车行业2026年6月投资策略：2026年5月全国乘用车批发销量同比下降5%，看好自主乘用车出海加速.pdf",
        "source_tier": "A",
        "source_review_status": "pass_with_note",
        "excerpt": "报告第28—31页整理5月新能源乘用车产、批、零、出口、主要厂商和经销商库存预警指数，并保留初值与终值版本差异。",
        "language": "zh",
        "independence_key": "guosen_cpca_auto_20260617",
        "independence_rationale": "产销库存数据底层来自乘联分会/流通协会，不与网页链重复计权；全年预测属于国信独立判断。",
        "source_channel": "report",
    },
    {
        "ref": "r-deutsche-inovance-20260723",
        "title": "Inovance Technology: 2Q26 results preview",
        "title_zh": "汇川技术：2026年第二季度业绩前瞻",
        "publisher": "Deutsche Bank",
        "publish_date": "2026-07-23",
        "local_path": "papers/新能源汽车排产与库存/2026-07-24_德意志银行_汇川技术（300124）：2026年第二季度业绩前瞻：销售表现稳健，但新能源汽车业务的盈利压力仍将持续.pdf",
        "source_tier": "A",
        "source_review_status": "pass_with_note",
        "excerpt": "The supplier customer basket grew faster in 2Q26, but the exposure is concentrated and cannot represent the whole NEV market.",
        "excerpt_zh": "汇川前五客户二季度批发增速较快，但理想在其汽车业务历史收入中权重较高，不能把客户篮子外推为全行业。",
        "language": "en",
        "independence_key": "deutsche_inovance_20260723",
        "independence_rationale": "供应商客户篮子是局部独立信号；其中车企销量与公开披露同源，不重复计数。",
        "source_channel": "report",
    },
    {
        "ref": "r-deutsche-auto-weekly-20260703",
        "title": "Auto sector weekly: selected company and demand indicators",
        "title_zh": "汽车行业周报：公司与需求指标",
        "publisher": "Deutsche Bank",
        "publish_date": "2026-07-03",
        "local_path": "papers/新能源汽车排产与库存/2026-07-04_德意志银行_汽车行业周报；过去一周；节选自题为宝马斯帕坦堡投资者日观察的研究报告.pdf",
        "source_tier": "A",
        "source_review_status": "pass_with_note",
        "excerpt": "The PDF references weekly new-order indicators but does not disclose the numerical series needed for an independent production forecast.",
        "excerpt_zh": "报告提到新能源车企周度新订单指标，但本PDF没有给出可复算的数值序列，因此不把它作为排产输入。",
        "language": "en",
        "independence_key": "deutsche_auto_weekly_20260703",
        "independence_rationale": "卖方订单框架具有独立性，但缺少可复算数值，只用于说明研报链缺口。",
        "source_channel": "report",
    },
    {
        "ref": "r-morgan-stanley-tyre-20260721",
        "title": "Global Tyres: June tyre tracker",
        "title_zh": "全球轮胎：6月轮胎需求跟踪",
        "publisher": "Morgan Stanley",
        "publish_date": "2026-07-21",
        "local_path": "papers/新能源汽车排产与库存/2026-07-21_待核验券商_全球轮胎6月轮胎追踪：卡车需求走强，乘用车OE需求疲软.pdf",
        "source_tier": "A",
        "source_review_status": "pass_with_note",
        "excerpt": "China passenger-car original-equipment tyre sell-in fell 4% year on year in June while replacement demand rose 1%.",
        "excerpt_zh": "6月中国乘用车原配胎需求同比下降4%、替换胎增长1%；该口径含燃油车，只能作为上游反证。",
        "language": "en",
        "independence_key": "morgan_stanley_michelin_tyre_20260721",
        "independence_rationale": "Michelin/轮胎协会sell-in与整车产量不同源，但燃油车混入且存在渠道时差，只作弱校准。",
        "source_channel": "report",
    },
]


def _source_for_ids(
    aliases: Mapping[tuple[str, str], str], origin: str, ids: Iterable[str], fallback: str
) -> str:
    for item in ids:
        ref = aliases.get((origin, str(item)))
        if ref:
            return ref
    return fallback


def _data_point(
    *,
    key: str,
    entity_key: str,
    metric: str,
    unit: str,
    source_ref: str,
    source_excerpt: str,
    value_num: float | None = None,
    value_text: str | None = None,
    period: str | None = None,
    scope_key: str | None = None,
    observations: list[dict[str, Any]] | None = None,
    note: str = "",
    extraction_method: str | None = None,
    underlying_source_refs: list[str] | None = None,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "data_point_key": key,
        "entity_key": entity_key,
        "metric": metric,
        "unit": unit,
        "source_ref": source_ref,
        "source_excerpt": source_excerpt,
        "source_excerpt_zh": source_excerpt,
        "scope_key": scope_key or key,
        "extraction_method": extraction_method or ("inferred" if note else "web_fetch"),
        "note": note,
    }
    if underlying_source_refs:
        refs = list(dict.fromkeys(str(ref) for ref in underlying_source_refs if str(ref)))
        row["underlying_source_refs"] = refs
        row["evidence_ref_uri_list"] = [_ev(ref) for ref in refs]
    if observations:
        row["observations"] = observations
        row["value_text"] = value_text or f"{len(observations)}期完整序列"
    else:
        row["period"] = period or "截至2026-08-03"
        if value_num is not None:
            row["value_num"] = value_num
        row["value_text"] = value_text or (str(value_num) if value_num is not None else "见说明")
    return row


def _build_data_points(
    industry: Mapping[str, Any],
    brand: Mapping[str, Any],
    upstream: Mapping[str, Any],
    model: Mapping[str, Any],
    aliases: Mapping[tuple[str, str], str],
    model_source_ref: str,
) -> list[dict[str, Any]]:
    core_ref = aliases[("industry", "cpca_2026_06")]
    battery_ref = aliases.get(("upstream", "S25"), core_ref)
    result: list[dict[str, Any]] = []
    history_fields = [
        ("production", "中国境内新能源乘用车产量", "万辆"),
        ("wholesale", "新能源乘用车厂商批发", "万辆"),
        ("retail", "新能源乘用车国内零售", "万辆"),
        ("export", "中国工厂新能源乘用车出口", "万辆"),
        ("insurance_registration", "新能源乘用车上险量", "万辆"),
        ("manufacturer_inventory_flow", "厂商库存月度变化", "万辆"),
        ("channel_inventory_flow", "渠道库存月度变化", "万辆"),
        ("system_inventory_flow", "生产体系库存月度变化", "万辆"),
        ("nev_only_oem_stock_proxy", "仅生产新能源车企业库存代理", "万辆"),
        ("dealer_inventory_coefficient", "全乘用车经销商库存系数", "月"),
        ("inventory_days_all_passenger", "全乘用车库存天数", "天"),
    ]
    for field, metric, unit in history_fields:
        observations = [
            {"period": row["month"], "value_num": row[field]}
            for row in industry["monthly_observations"]
            if row.get(field) is not None
        ]
        result.append(
            _data_point(
                key=f"industry-history-{field}",
                entity_key="industry_total_method",
                metric=metric,
                unit=unit,
                source_ref=core_ref,
                source_excerpt="乘联分会月报及流通协会库存序列提供最近12个月统一口径；上险量只在可核验月份保留。",
                observations=observations,
                scope_key=f"china-nev-passenger-monthly-{field}",
                note=(
                    "厂商库存变化=产量-厂商批发；渠道库存变化=厂商批发-中国工厂出口-国内零售；生产体系库存变化=产量-国内零售-中国工厂出口。"
                    if field in {"manufacturer_inventory_flow", "channel_inventory_flow", "system_inventory_flow"}
                    else "逐月月报序列合并为一个数据点，不按月份拆分凑数。"
                ),
                extraction_method=(
                    "inferred"
                    if field in {"manufacturer_inventory_flow", "channel_inventory_flow", "system_inventory_flow"}
                    else "web_fetch"
                ),
            )
        )
    july = industry["july_2026_high_frequency"]
    for obs in july["observations"]:
        for metric_key, label in (("retail", "新能源零售"), ("wholesale", "新能源厂商批发")):
            result.append(
                _data_point(
                    key=f"july-{_slug(obs['period'])}-{metric_key}",
                    entity_key="industry_total_method",
                    metric=f"2026年7月高频{label}",
                    unit="万辆",
                    source_ref=_source_for_ids(
                        aliases,
                        "industry",
                        [
                            "cpca_jul_1_12" if obs["period"].endswith("12") else "",
                            "cpca_jul_1_19" if obs["period"].endswith("19") else "",
                            "cpca_jul_1_26_reprint" if obs["period"].endswith("26") else "",
                        ],
                        core_ref,
                    ),
                    source_excerpt="7月旬度/周度扫描用于识别月内低谷和月末修复，不当作正式整月产量。",
                    value_num=float(obs[metric_key]),
                    period=obs["period"],
                    scope_key=f"july-hf-{obs['period']}-{metric_key}",
                )
            )
    for field, metric, unit in (
        ("production_10k", "综合模型中国境内排产", "万辆"),
        ("wholesale_10k", "综合模型厂商批发", "万辆"),
        ("domestic_retail_10k", "综合模型国内零售", "万辆"),
        ("china_factory_export_10k", "综合模型中国工厂出口", "万辆"),
        ("system_inventory_flow_10k", "综合模型库存变化", "万辆"),
    ):
        observations = []
        for row in model["ensemble_forecast"]:
            value = row[field]
            observations.append(
                {
                    "period": row["month"],
                    "value_num": float(value["point"]),
                    "value_text": f"{value['low']:.1f}—{value['high']:.1f}，中值{value['point']:.1f}",
                }
            )
        result.append(
            _data_point(
                key=f"ensemble-{field}",
                entity_key="three_method_synthesis",
                metric=metric,
                unit=unit,
                source_ref=model_source_ref,
                source_excerpt="三条独立模型冻结后按可解释权重合成，销售、出口与库存桥使用行业同口径序列。",
                observations=observations,
                scope_key=f"ensemble-{field}",
                note="综合值=45%×行业总量法+30%×品牌/工厂法+25%×动力电池校准法；区间不是统计置信区间。",
                extraction_method="inferred",
            )
        )
    for company_index, company in enumerate(brand["companies"], start=1):
        company_name = str(company.get("entity") or company.get("company") or company.get("name") or f"主体{company_index}")
        evidence_ids = company.get("evidence_ids") or []
        source_ref = _source_for_ids(aliases, "brand", evidence_ids, core_ref)
        base = float(company["june_2026_wholesale_k"]) / 10.0
        result.append(
            _data_point(
                key=f"brand-{company_index:02d}-june-base",
                entity_key="brand_factory_method",
                metric=f"{company_name}6月境内新能源批发基线",
                unit="万辆",
                source_ref=source_ref,
                source_excerpt="6月厂商榜与公司披露共同用于确认生产主体、境内批发基线和边界。",
                value_num=base,
                period="2026-06",
                scope_key=f"{company_index:02d}-june-base",
            )
        )
        forecast_rows = []
        for month, values in company["forecast_k"].items():
            forecast_rows.append(
                {
                    "period": month,
                    "value_num": round((float(values["low"]) + float(values["high"])) / 20.0, 2),
                    "value_text": f"{float(values['low'])/10:.1f}—{float(values['high'])/10:.1f}",
                }
            )
        for band, label in (("low", "排产下限"), ("high", "排产上限")):
            observations = [
                {"period": month, "value_num": float(values[band]) / 10.0}
                for month, values in company["forecast_k"].items()
            ]
            result.append(
                _data_point(
                    key=f"brand-{company_index:02d}-{band}",
                    entity_key="brand_factory_method",
                    metric=f"{company_name}未来三个月{label}",
                    unit="万辆",
                    source_ref=source_ref,
                    source_excerpt="以6月境内厂商基线为起点，叠加新车、订单、出口、产线和口径风险后形成主体区间。",
                    observations=observations,
                    scope_key=f"{company_index:02d}-{band}",
                    note="公司区间按主体独立研究生成；不能由行业总量结论反向填充。",
                )
            )
        result.append(
            _data_point(
                key=f"brand-{company_index:02d}-mid",
                entity_key="brand_factory_method",
                metric=f"{company_name}未来三个月排产中值",
                unit="万辆",
                source_ref=source_ref,
                source_excerpt="中值仅是公司区间中心，用于汇总，不代表公司正式排产指引。",
                observations=forecast_rows,
                scope_key=f"{company_index:02d}-mid",
                note="中值=(主体下限+主体上限)/2；每家公司单独汇总后再补尾部厂商。",
            )
        )
    monthly_fields = [
        ("nev_passenger_production_10k", "新能源乘用车产量", "万辆"),
        ("battery_installation_gwh", "动力电池装车量", "GWh"),
        ("power_battery_sales_gwh", "动力电池销量", "GWh"),
        ("power_battery_exports_gwh", "动力电池出口", "GWh"),
        ("domestic_apparent_sales_gwh", "境内表观动力电池销量", "GWh"),
        ("lfp_output_10k_t", "磷酸铁锂产量", "万吨"),
    ]
    for field, metric, unit in monthly_fields:
        observations = [
            {"period": row["month"], "value_num": row[field]}
            for row in upstream["monthly_history"]
            if row.get(field) is not None
        ]
        result.append(
            _data_point(
                key=f"upstream-history-{field}",
                entity_key="upstream_battery_method",
                metric=f"上游前推：{metric}",
                unit=unit,
                source_ref=battery_ref,
                source_excerpt="动力电池月度销量、出口、装车和LFP产量序列用于筛选领先性与重复覆盖。",
                observations=observations,
                scope_key=f"upstream-monthly-{field}",
                note="表观境内销量=动力电池销量-动力电池出口；包含商用车和备库，因此不能等同整车台数。",
                extraction_method=("inferred" if field == "domestic_apparent_sales_gwh" else "web_fetch"),
            )
        )
    for index, row in enumerate(upstream["concentration"], start=1):
        source_ref = _source_for_ids(aliases, "upstream", row.get("source_ids") or [], battery_ref)
        for field, label in (("cr3_pct", "CR3"), ("cr5_pct", "CR5"), ("cr6_pct", "CR6")):
            if row.get(field) is None:
                continue
            result.append(
                _data_point(
                    key=f"upstream-concentration-{index}-{field}",
                    entity_key="upstream_battery_method",
                    metric=f"{row['node']}{row['period']}年{label}",
                    unit="%",
                    source_ref=source_ref,
                    source_excerpt="集中度用于筛选节点，不足以证明其对整车排产具有领先性。",
                    value_num=float(row[field]),
                    period=str(row["period"]),
                    scope_key=f"concentration-{index}-{field}",
                )
            )
    formal = upstream["node_selection"]["formal_node"]
    for index, layer in enumerate(formal["observation_layers"], start=1):
        result.append(
            _data_point(
                key=f"upstream-formal-layer-{index}",
                entity_key="upstream_battery_method",
                metric=f"正式节点观测层：{layer['metric']}",
                unit="研究规则",
                source_ref=battery_ref,
                source_excerpt="节点须同时满足集中度、连续月度数据和与整车产量的可复算关系。",
                value_text=f"领先期{layer['lead']}；用途：{layer['use']}",
                period="2025-07至2026-06",
                scope_key=f"formal-layer-{index}",
                note="该规则来自节点筛选与回测，不是外部事实。",
            )
        )
    for index, row in enumerate(upstream["node_selection"]["rejected_nodes"], start=1):
        result.append(
            _data_point(
                key=f"upstream-rejected-{index}",
                entity_key="upstream_battery_method",
                metric=f"未进入正式模型：{row['node']}",
                unit="筛选结论",
                source_ref=battery_ref,
                source_excerpt="未入选节点在连续月度物理量、需求纯度或领先性上不满足门槛。",
                value_text=row["reason"],
                period="截至2026-08-03",
                scope_key=f"rejected-{index}",
                note="不入选不等于行业不重要，只表示不适合本次未来三个月整车排产推算。",
            )
        )
    for signal_index, signal in enumerate(upstream["recent_signals"], start=1):
        source_ref = _source_for_ids(aliases, "upstream", signal.get("source_ids") or [], battery_ref)
        for field, value in signal.items():
            if field in {"period", "interpretation", "source_ids"} or not isinstance(value, (int, float)):
                continue
            if field.endswith("_gwh"):
                unit = "GWh"
            elif field.endswith("_10k_t"):
                unit = "万吨"
            elif field.endswith("_pct") or field.endswith("_pct_approx"):
                unit = "%"
            elif field.endswith("_rmb_per_wh"):
                unit = "元/Wh"
            else:
                raise ValueError(f"未定义的上游信号单位: {field}")
            result.append(
                _data_point(
                    key=f"upstream-signal-{signal_index}-{field}",
                    entity_key="upstream_battery_method",
                    metric=f"{signal['period']}上游信号：{field}",
                    unit=unit,
                    source_ref=source_ref,
                    source_excerpt=str(signal["interpretation"]),
                    value_num=float(value),
                    period=str(signal["period"]),
                    scope_key=f"signal-{signal_index}-{field}",
                )
            )
    diagnostics = upstream["model"]
    diagnostic_values = {
        "同期相关系数": diagnostics["backtest"]["same_month_correlation"],
        "逐月留一MAPE": diagnostics["backtest"]["leave_one_out_mape_pct"],
        "逐月留一MAE": diagnostics["backtest"]["leave_one_out_mae_10k"],
        "领先一月相关系数": diagnostics["leading_test"]["one_month_lead_correlation"],
        "非春节领先模型MAPE": diagnostics["leading_test"]["one_month_model_mape_excluding_lunar_new_year_pct"],
        "全样本领先模型MAPE": diagnostics["leading_test"]["one_month_model_mape_full_sample_pct"],
        "LFP同期相关系数": diagnostics["lfp_test"]["same_month_correlation"],
        "LFP领先一月相关系数": diagnostics["lfp_test"]["one_month_lead_correlation"],
    }
    for index, (metric, value) in enumerate(diagnostic_values.items(), start=1):
        diagnostic_unit = "%" if "MAPE" in metric else ("万辆" if "MAE" in metric else "无量纲")
        result.append(
            _data_point(
                key=f"upstream-diagnostic-{index}",
                entity_key="upstream_battery_method",
                metric=f"上游模型{metric}",
                unit=diagnostic_unit,
                source_ref=model_source_ref,
                source_excerpt="模型以2025年7月至2026年6月完整月度序列回测，并分别检验同期与领先一月关系。",
                value_num=float(value),
                period="2025-07至2026-06",
                scope_key=f"diagnostic-{index}",
                note="相关性和回测误差是模型诊断，不是外部事实或因果证明。",
            )
        )
    return result


def _build_data_points_v2(
    industry: Mapping[str, Any],
    brand: Mapping[str, Any],
    upstream: Mapping[str, Any],
    model: Mapping[str, Any],
    aliases: Mapping[tuple[str, str], str],
    model_source_ref: str,
) -> list[dict[str, Any]]:
    """逐期、逐主体绑定证据的正式数据点集合。

    旧构建器保留以便历史比较；V2 不允许以最后一个月来源替代整段序列，
    也不把同一公司预测区间的低/中/高拆成三个伪独立事实。
    """
    result: list[dict[str, Any]] = []
    core_ref = aliases[("industry", "cpca_2026_06")]
    monthly_refs = {
        str(row["month"]): aliases[("industry", f"cpca_{str(row['month']).replace('-', '_')}")]
        for row in industry["monthly_observations"]
    }
    for row in industry["monthly_observations"]:
        month = str(row["month"])
        source_ref = monthly_refs[month]
        for field, metric in (
            ("production", "中国境内新能源乘用车产量"),
            ("wholesale", "新能源乘用车厂商批发"),
            ("retail", "新能源乘用车国内零售"),
            ("export", "中国工厂新能源乘用车出口"),
        ):
            result.append(
                _data_point(
                    key=f"industry-{month}-{field}",
                    entity_key="industry_total_method",
                    metric=metric,
                    unit="万辆",
                    source_ref=source_ref,
                    source_excerpt=f"{month}乘联分会月报披露的同月{metric}。",
                    value_num=float(row[field]),
                    period=month,
                    scope_key=f"china-nev-passenger-{month}-{field}",
                )
            )
        for field, metric, formula in (
            ("manufacturer_inventory_flow", "厂商库存月度变化", "产量-厂商批发"),
            ("channel_inventory_flow", "渠道库存月度变化", "厂商批发-中国工厂出口-国内零售"),
            ("system_inventory_flow", "生产体系库存月度变化", "产量-国内零售-中国工厂出口"),
        ):
            result.append(
                _data_point(
                    key=f"industry-{month}-{field}",
                    entity_key="industry_total_method",
                    metric=metric,
                    unit="万辆",
                    source_ref=source_ref,
                    source_excerpt=f"以{month}同一月报的产、批、零、出口复算。",
                    value_num=float(row[field]),
                    period=month,
                    scope_key=f"china-nev-passenger-{month}-{field}",
                    note=f"推断公式：{formula}。",
                    extraction_method="inferred",
                )
            )

    insurance_source_ids = {
        "2025-08": "insurance_2025_08", "2025-09": "insurance_2025_10",
        "2025-10": "insurance_2025_10", "2025-11": "insurance_2025_11",
        "2025-12": "insurance_2025_12", "2026-01": "insurance_2026_01",
        "2026-02": "insurance_2026_02", "2026-03": "insurance_2026_03",
        "2026-04": "insurance_2026_04", "2026-05": "insurance_2026_05",
        "2026-06": "insurance_2026_06",
    }
    for row in industry["monthly_observations"]:
        month = str(row["month"])
        if row.get("insurance_registration") is None:
            continue
        inferred = month == "2025-09"
        result.append(
            _data_point(
                key=f"insurance-{month}",
                entity_key="industry_total_method",
                metric="新能源乘用车上险量",
                unit="万辆",
                source_ref=aliases[("industry", insurance_source_ids[month])],
                source_excerpt=(
                    "2025年9月由10月119.5万辆及10月环比下降7.7%反推。"
                    if inferred else f"{month}新能源乘用车上险跟踪。"
                ),
                value_num=float(row["insurance_registration"]),
                period=month,
                scope_key=f"insurance-{month}",
                note=("119.5÷(1-7.7%)=129.5万辆，不是9月直接发布值。" if inferred else ""),
                extraction_method="inferred" if inferred else "web_fetch",
            )
        )

    stock_ref = aliases[("industry", "cada_stock_series")]
    result.append(
        _data_point(
            key="nev-oem-stock-proxy-direct-series",
            entity_key="industry_total_method",
            metric="仅生产新能源车企业库存代理",
            unit="万辆",
            source_ref=stock_ref,
            source_excerpt="协会连续序列只覆盖仅生产新能源车的企业，不能代表行业财报存货。",
            observations=[
                {"period": row["month"], "value_num": float(row["nev_only_oem_stock_proxy"])}
                for row in industry["monthly_observations"] if row["month"] != "2025-12"
            ],
            scope_key="nev-only-oem-stock-direct-series",
            extraction_method="web_fetch",
        )
    )
    dec_stock = next(row for row in industry["monthly_observations"] if row["month"] == "2025-12")
    result.append(
        _data_point(
            key="nev-oem-stock-proxy-2025-12-inferred",
            entity_key="industry_total_method",
            metric="仅生产新能源车企业库存代理",
            unit="万辆",
            source_ref=stock_ref,
            source_excerpt="由2026年1月72万辆且较12月增加6万辆、2月68万辆且较12月增加2万辆交叉重建。",
            value_num=float(dec_stock["nev_only_oem_stock_proxy"]),
            period="2025-12",
            scope_key="nev-only-oem-stock-2025-12-inferred",
            note="两条后续变化均反推66万辆；另一转载写78万辆，存在冲突，因此仅作低置信度代理。",
            extraction_method="inferred",
        )
    )
    result.append(
        _data_point(
            key="dealer-inventory-coefficient-2026-06",
            entity_key="industry_total_method",
            metric="全乘用车经销商库存系数",
            unit="月",
            source_ref=aliases[("industry", "cada_dealer_inventory_june")],
            source_excerpt="2026年6月全乘用车经销商库存系数1.58；不是新能源专属。",
            value_num=1.58,
            period="2026-06",
            scope_key="dealer-inventory-coefficient-2026-06",
        )
    )

    july = industry["july_2026_high_frequency"]
    for obs in july["observations"]:
        source_id = (
            "cpca_jul_1_12" if str(obs["period"]).endswith("12")
            else "cpca_jul_1_19" if str(obs["period"]).endswith("19")
            else "cpca_jul_1_26_reprint"
        )
        for metric_key, label in (("retail", "新能源零售"), ("wholesale", "新能源厂商批发")):
            result.append(
                _data_point(
                    key=f"july-{_slug(str(obs['period']))}-{metric_key}",
                    entity_key="industry_total_method",
                    metric=f"2026年7月高频{label}",
                    unit="万辆",
                    source_ref=aliases[("industry", source_id)],
                    source_excerpt="7月累计扫描只用于识别未结月低谷和修复，不当作完整月度值。",
                    value_num=float(obs[metric_key]),
                    period=str(obs["period"]),
                    scope_key=f"july-hf-{obs['period']}-{metric_key}",
                )
            )

    for field, metric in (
        ("production_10k", "综合模型中国境内排产"),
        ("wholesale_10k", "综合模型厂商批发"),
        ("domestic_retail_10k", "综合模型国内零售"),
        ("china_factory_export_10k", "综合模型中国工厂出口"),
        ("system_inventory_flow_10k", "综合模型库存变化"),
    ):
        result.append(
            _data_point(
                key=f"ensemble-{field}",
                entity_key="three_method_synthesis",
                metric=metric,
                unit="万辆",
                source_ref=model_source_ref,
                source_excerpt="三种独立建模口径共享部分行业底层数据；低/中/高按45%/30%/25%合成。",
                observations=[
                    {
                        "period": row["month"],
                        "value_num": float(row[field]["point"]),
                        "value_text": (
                            f"{row[field]['low']:.1f}—{row[field]['high']:.1f}"
                            f"（{row[field]['point']:.3f}）"
                            if field == "battery_installation_gwh"
                            else f"{row[field]['low']:.1f}—{row[field]['high']:.1f}"
                            f"（{row[field]['point']:.1f}）"
                        ),
                    }
                    for row in model["ensemble_forecast"]
                ],
                scope_key=f"ensemble-{field}",
                note="研究区间，不是统计置信区间。",
                extraction_method="inferred",
            )
        )

    bridge_by_rank = {int(row["rank"]): row for row in model["brand_company_bridge"]["companies"]}
    for company_index, company in enumerate(brand["companies"], start=1):
        company_name = str(company["entity"])
        evidence_refs = list(dict.fromkeys(
            aliases[("brand", str(item))]
            for item in company.get("evidence_ids") or []
            if ("brand", str(item)) in aliases
        ))
        primary_ref = evidence_refs[0] if evidence_refs else core_ref
        result.append(
            _data_point(
                key=f"brand-{company_index:02d}-june-base",
                entity_key="brand_factory_method",
                metric=f"{company_name}6月中国工厂厂商批发基线（含出口）",
                unit="万辆",
                source_ref=primary_ref,
                source_excerpt="6月厂商榜与公司披露共同确认中国生产主体、厂商批发及出口边界。",
                value_num=float(company["june_2026_wholesale_k"]) / 10.0,
                period="2026-06",
                scope_key=f"{company_index:02d}-june-base",
                underlying_source_refs=evidence_refs,
            )
        )
        bridge = bridge_by_rank[company_index]
        for field, label in (
            ("production_10k", "未来三个月中国工厂排产"),
            ("domestic_sales_10k", "未来三个月国内销售"),
            ("china_factory_export_10k", "未来三个月中国工厂出口"),
            ("inventory_change_10k", "未来三个月库存变化"),
        ):
            result.append(
                _data_point(
                    key=f"brand-{company_index:02d}-{field}",
                    entity_key="brand_factory_method",
                    metric=f"{company_name}{label}",
                    unit="万辆",
                    source_ref=model_source_ref,
                    source_excerpt="以该公司6月基线和逐主体证据约束W/S/R/N、出口份额及库存率。",
                    observations=[
                        {
                            "period": row["month"],
                            "value_num": float(row[field]["point"]),
                            "value_text": f"{row[field]['low']:.1f}—{row[field]['high']:.1f}（{row[field]['point']:.1f}）",
                        }
                        for row in bridge["months"]
                    ],
                    scope_key=f"{company_index:02d}-{field}",
                    note="研究区间，不是企业指引；输入、公式和误差带均已冻结。",
                    extraction_method="inferred",
                    underlying_source_refs=[*evidence_refs, model_source_ref],
                )
            )

    upstream_month_source = {
        "2025-07": "S13", "2025-08": "S12", "2025-09": "S14", "2025-10": "S14",
        "2025-11": "S14", "2025-12": "S14", "2026-01": "S20", "2026-02": "S21",
        "2026-03": "S22", "2026-04": "S23", "2026-05": "S24", "2026-06": "S25",
    }
    compiled_months = {"2025-09", "2025-10", "2025-11", "2025-12"}
    for row in upstream["monthly_history"]:
        month = str(row["month"])
        if month in compiled_months:
            continue
        result.append(
            _data_point(
                key=f"battery-installation-{month}",
                entity_key="upstream_battery_method",
                metric="动力电池装车量",
                unit="GWh",
                source_ref=aliases[("upstream", upstream_month_source[month])],
                source_excerpt=f"{month}动力电池装车量月度记录。",
                value_num=float(row["battery_installation_gwh"]),
                period=month,
                scope_key=f"battery-installation-{month}",
            )
        )
    result.append(
        _data_point(
            key="battery-installation-2025-09-to-12",
            entity_key="upstream_battery_method",
            metric="动力电池装车量",
            unit="GWh",
            source_ref=aliases[("upstream", "S14")],
            source_excerpt="同一资料列示2025年9月至12月动力电池装车量月度序列。",
            observations=[
                {"period": row["month"], "value_num": float(row["battery_installation_gwh"])}
                for row in upstream["monthly_history"] if row["month"] in compiled_months
            ],
            scope_key="battery-installation-2025-09-to-12",
        )
    )

    for index, row in enumerate(upstream["concentration"], start=1):
        source_ref = _source_for_ids(aliases, "upstream", row.get("source_ids") or [], aliases[("upstream", "S25")])
        for field, label in (("cr3_pct", "CR3"), ("cr5_pct", "CR5"), ("cr6_pct", "CR6")):
            if row.get(field) is None:
                continue
            calculated = bool(row.get("calculation")) and field != "cr5_pct"
            result.append(
                _data_point(
                    key=f"upstream-concentration-{index}-{field}",
                    entity_key="upstream_battery_method",
                    metric=f"{row['node']}{row['period']}年{label}",
                    unit="%",
                    source_ref=source_ref,
                    source_excerpt=str(row.get("calculation") or "来源披露的集中度，仅用于筛选节点。"),
                    value_num=float(row[field]),
                    period=str(row["period"]),
                    scope_key=f"concentration-{index}-{field}",
                    note=(str(row.get("calculation") or "") if calculated else ""),
                    extraction_method="inferred" if calculated else "web_fetch",
                )
            )

    diagnostics = upstream["model"]
    diagnostic_values = {
        "同期相关系数": diagnostics["backtest"]["same_month_correlation"],
        "逐月留一MAPE": diagnostics["backtest"]["leave_one_out_mape_pct"],
        "逐月留一MAE": diagnostics["backtest"]["leave_one_out_mae_10k"],
        "领先一月相关系数": diagnostics["leading_test"]["one_month_lead_correlation"],
    }
    for index, (metric, value) in enumerate(diagnostic_values.items(), start=1):
        result.append(
            _data_point(
                key=f"upstream-diagnostic-{index}",
                entity_key="upstream_battery_method",
                metric=f"上游模型{metric}",
                unit="%" if "MAPE" in metric else ("万辆" if "MAE" in metric else "无量纲"),
                source_ref=model_source_ref,
                source_excerpt="冻结的12个月装车量与整车产量逐月复算同期关系；领先检验不进入最终权重优化。",
                value_num=float(value),
                period="2025-07至2026-06",
                scope_key=f"diagnostic-{index}",
                note="模型诊断，不是外部事实或因果证明。",
                extraction_method="inferred",
            )
        )
    for field, label, unit in (
        ("battery_installation_gwh", "未来三个月动力电池装车量假设", "GWh"),
        ("production_10k", "动力电池校准法未来三个月排产", "万辆"),
    ):
        result.append(
            _data_point(
                key=f"upstream-forecast-{field}",
                entity_key="upstream_battery_method",
                metric=label,
                unit=unit,
                source_ref=model_source_ref,
                source_excerpt="中心装车量与上下界、回归输出及逐月留一误差均在冻结模型中逐月记录。",
                observations=[
                    {
                        "period": row["month"],
                        "value_num": float(row[field]["point"]),
                        "value_text": f"{row[field]['low']:.1f}—{row[field]['high']:.1f}（{row[field]['point']:.1f}）",
                    }
                    for row in model["upstream_forecast_bridge"]
                ],
                scope_key=f"upstream-forecast-{field}",
                note="研究假设和计算结果；上下界=回归对应装车量边界±逐月留一RMSE。",
                extraction_method="inferred",
            )
        )
    return result


def _claim(
    *, key: str, entity_key: str, text: str, source_ref: str, excerpt: str,
    claim_type: str = "analysis", supporting_source_refs: list[str] | None = None
) -> dict[str, Any]:
    row = {
        "claim_key": key,
        "entity_key": entity_key,
        "claim_type": claim_type,
        "claim_text": text,
        "source_ref": source_ref,
        "source_excerpt": excerpt,
        "source_excerpt_zh": excerpt,
        "verification_status": "supported",
    }
    if supporting_source_refs:
        row["supporting_source_refs"] = list(dict.fromkeys(supporting_source_refs))
    return row


def _research_point(
    source_ref: str,
    title: str,
    category: str,
    value_text: str,
    interpretation: str,
    order: int,
) -> dict[str, Any]:
    return {
        "source_ref": source_ref,
        "data_point_title": title,
        "research_category": category,
        "metric": title,
        "period": "2025-07至2026-10",
        "as_of_date": "2026-08-03",
        "value_text": value_text,
        "unit": "研究数据点",
        "source_excerpt": interpretation,
        "source_excerpt_zh": interpretation,
        "source_context": "该数据点用于约束未来三个月中国境内新能源乘用车排产与库存。",
        "interpretation": interpretation,
        "research_use": (
            f"用于“{title}”这一底稿项，约束{category}中的第{order}项判断；"
            "不跨方法反向填充。"
        ),
        "limitations": "公开口径、时间确认和库存层级存在差异，区间不是统计置信区间。",
        "evidence_ref_uri": _ev(source_ref),
        "sort_order": order,
    }


def _theory_entity(
    *,
    key: str,
    name: str,
    description: str,
    question: str,
    methodology: str,
    literature: str,
    analysis: str,
    answer: str,
    conclusion: str,
    limitations: str,
    refs: list[str],
    points: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "key": key,
        "canonical_name": name,
        "display_name": name,
        "entity_type": "industry",
        "taxonomy_level": "theme",
        "description": description,
        "entity_research_mode": "theory_research",
        "external_ref_type": "opportunity_lens_entity",
        "maturation_status": "research_only",
        "readiness_score": 1.0,
        "readiness_reason": "独立数据链、公式、输入、误差与结论均已形成，等待独立复核。",
        "research_priority_label": "research_only_literature_review_complete",
        "source_count": len(refs),
        "independent_source_count": len(set(refs)),
        "candidate_reason": conclusion,
        "evidence_ref_uri": _ev(refs[0]),
        "evidence_ref_uri_list": [_ev(ref) for ref in refs],
        "score_point": None,
        "score_grade": "unrated",
        "score_quality_label": "unrated_insufficient_evidence",
        "score_band_low": None,
        "score_band_high": None,
        "coverage": 0.92,
        "confidence": 0.80,
        "factor_scores": [],
        "research_profile": {
            "entity_research_mode": "theory_research",
            "research_depth_status": "complete",
            "research_question": question,
            "research_scope": description,
            "methodology_note": methodology,
            "literature_review_markdown": literature,
            "data_collection_markdown": "研报和网页分别检索；同一协会月报或公司公告的转载合并为一个证据组。",
            "analysis_markdown": analysis,
            "answer_markdown": answer,
            "conclusion_markdown": conclusion,
            "limitations_markdown": limitations,
            "evidence_ref_uri_list": [_ev(ref) for ref in refs],
        },
        "research_data_points": points,
    }


def _public_section(key: str, title: str, body: str, refs: list[str], order: int) -> dict[str, Any]:
    return {
        "section_key": key,
        "section_title": title,
        "title": title,
        "body_markdown": body.strip(),
        "evidence_ref_uri_list": [_ev(ref) for ref in refs],
        "support_status": "supported",
        "review_status": "approved",
        "sort_order": order,
    }


def _entity_section(key: str, title: str, body: str, refs: list[str], order: int) -> dict[str, Any]:
    row = _public_section(f"{key}_deep_research", title, body, refs, order)
    row["entity_key"] = key
    return row


def _format_history_rows(model: Mapping[str, Any], month_refs: Mapping[str, str]) -> str:
    rows = []
    for row in model["history_12m"]:
        insurance = row.get("insurance_registration")
        insurance_text = "—" if insurance is None else f"{float(insurance):.1f}"
        if row["month"] == "2025-09":
            insurance_text += "*"
        stock_text = f"{row['nev_only_oem_stock_proxy']:.0f}"
        if row["month"] == "2025-12":
            stock_text += "†"
        rows.append(
            f"| {row['month']} | {row['production']:.1f} | {row['wholesale']:.1f} | "
            f"{row['retail']:.1f} | {insurance_text} | {row['export']:.1f} | "
            f"{row['manufacturer_inventory_flow']:+.1f} | "
            f"{row['channel_inventory_flow']:+.1f} | "
            f"{row['system_inventory_flow']:+.1f} | "
            f"{stock_text} | {_cite(month_refs[row['month']])} |"
        )
    return "\n".join(rows)


def _format_high_frequency_rows(model: Mapping[str, Any]) -> str:
    observations = model["july_2026_high_frequency"]["observations"]
    return "\n".join(
        f"| {row['period'].replace('/', '至')} | {row['retail']:.1f} | {row['wholesale']:.1f} | "
        f"累计扫描，并非完整月度值 |"
        for row in observations
    )


def _fmt_range(value: Mapping[str, Any]) -> str:
    return f"{float(value['low']):.1f}—{float(value['high']):.1f}（{float(value['point']):.1f}）"


def _format_brand_rows(model: Mapping[str, Any], evidence_refs: Mapping[int, list[str]]) -> str:
    rows = []
    for company in model["brand_company_bridge"]["companies"]:
        months = {row["month"]: row for row in company["months"]}
        domestic = company.get("june_domestic_10k")
        export = company.get("june_export_10k")
        domestic_text = "—" if domestic is None else f"{float(domestic):.1f}"
        export_text = "—" if export is None else f"{float(export):.1f}"
        citations = " ".join(_cite(ref) for ref in evidence_refs.get(int(company["rank"]), []))
        cells = []
        for month in ("2026-08", "2026-09", "2026-10"):
            item = months[month]
            cells.append(
                f"产 {_fmt_range(item['production_10k'])}<br>"
                f"内 {_fmt_range(item['domestic_sales_10k'])}<br>"
                f"出 {_fmt_range(item['china_factory_export_10k'])}<br>"
                f"库 {_fmt_range(item['inventory_change_10k'])}"
            )
        rows.append(
            f"| {company['entity']} | {company['ownership_class']} | {float(company['june_wholesale_10k']):.1f} / {domestic_text} / {export_text} | "
            f"{cells[0]} | {cells[1]} | {cells[2]} | {citations} |"
        )
    return "\n".join(rows)


def _format_brand_input_rows(model: Mapping[str, Any]) -> str:
    rows = []
    for company in model["brand_company_bridge"]["companies"]:
        monthly = company["months"]
        r_values = "/".join(f"{float(row['formula_inputs']['company_adjustment_r']['point']):.2f}" for row in monthly)
        export_values = "/".join(f"{float(row['formula_inputs']['export_share_pct']):.1f}%" for row in monthly)
        inventory_values = "/".join(f"{float(row['formula_inputs']['inventory_rate_pct']):+.1f}%" for row in monthly)
        rows.append(
            f"| {company['entity']} | {float(company['june_wholesale_10k']):.1f} | "
            f"{r_values} | {export_values} | {inventory_values} | 0.0 |"
        )
    return "\n".join(rows)


def _format_upstream_history_rows(upstream: Mapping[str, Any], month_refs: Mapping[str, str]) -> str:
    rows = []
    for row in upstream["monthly_history"]:
        rows.append(
            f"| {row['month']} | {float(row['battery_installation_gwh']):.1f} | "
            f"{float(row['nev_passenger_production_10k']):.1f} | {_cite(month_refs[row['month']])} |"
        )
    return "\n".join(rows)


def _format_ownership_rows(model: Mapping[str, Any]) -> str:
    rows = []
    for row in model["ownership_bridge"]:
        supplement = row["supplemental_chinese_scope_10k"]
        rows.append(
            f"| {row['month']} | {row['brand_total_10k']:.1f} | {row['identified_chinese_system_10k']:.1f} | "
            f"{row['identified_chinese_brand_jv_10k']:.1f} | "
            f"{row['identified_foreign_brand_jv_10k']:.1f} | {row['foreign_wholly_owned_10k']:.1f} | "
            f"{row['unidentified_tail_10k']:.1f} | {_fmt_range(supplement)} |"
        )
    return "\n".join(rows)


def _format_method_rows(model: Mapping[str, Any]) -> str:
    labels = {
        "industry_total": "行业总量法",
        "brand_bottom_up": "品牌/工厂法",
        "upstream_leading": "动力电池法",
    }
    rows = []
    for month, methods in model["method_forecasts"].items():
        for key, value in methods.items():
            rows.append(
                f"| {month} | {labels[key]} | {value['low']:.0f}—{value['high']:.0f} | {value['point']:.0f} |"
            )
    return "\n".join(rows)


def _format_industry_input_rows(model: Mapping[str, Any]) -> str:
    return "\n".join(
        f"| {row['month']} | {row['previous_month_point_10k']:.1f} | "
        f"{row['same_period_seasonal_factor']:.4f} | {row['raw_seasonal_point_10k']:.1f} | "
        f"{row['demand_export_inventory_adjustment_10k']:+.1f} | {_fmt_range(row['production_10k'])} |"
        for row in model["industry_forecast_bridge"]
    )


def _format_upstream_forecast_rows(model: Mapping[str, Any]) -> str:
    return "\n".join(
        f"| {row['month']} | {float(row['battery_installation_gwh']['low']):.1f}—"
        f"{float(row['battery_installation_gwh']['high']):.1f}"
        f"（{float(row['battery_installation_gwh']['point']):.3f}） | "
        f"{_fmt_range(row['regression_output_before_error_10k'])} | {row['error_extension_10k']:.2f} | "
        f"{_fmt_range(row['production_10k'])} |"
        for row in model["upstream_forecast_bridge"]
    )


def _format_final_rows(model: Mapping[str, Any]) -> str:
    autonomous = {row["month"]: row for row in model["autonomous_supplement"]}
    rows = []
    for row in model["ensemble_forecast"]:
        auto = autonomous[row["month"]]
        rows.append(
            f"| {row['month']} | {_fmt_whole_half_up(row['method_union_10k']['low'])}—{_fmt_whole_half_up(row['method_union_10k']['high'])} | "
            f"{_fmt_whole_half_up(row['production_10k']['low'])}—{_fmt_whole_half_up(row['production_10k']['high'])} "
            f"（{_fmt_whole_half_up(row['production_10k']['point'])}） | {row['mom_pct']:+.1f}% | {row['yoy_pct']:+.1f}% | "
            f"{_fmt_whole_half_up(row['wholesale_10k']['low'])}—{_fmt_whole_half_up(row['wholesale_10k']['high'])}（{_fmt_whole_half_up(row['wholesale_10k']['point'])}） | "
            f"{_fmt_whole_half_up(row['domestic_retail_10k']['low'])}—{_fmt_whole_half_up(row['domestic_retail_10k']['high'])}（{_fmt_whole_half_up(row['domestic_retail_10k']['point'])}） | "
            f"{_fmt_whole_half_up(row['china_factory_export_10k']['low'])}—{_fmt_whole_half_up(row['china_factory_export_10k']['high'])}（{_fmt_whole_half_up(row['china_factory_export_10k']['point'])}） | "
            f"{_fmt_whole_half_up(row['system_inventory_flow_10k']['low'])}—{_fmt_whole_half_up(row['system_inventory_flow_10k']['high'])} "
            f"（{_fmt_whole_half_up(row['system_inventory_flow_10k']['point'])}） | "
            f"{_fmt_whole_half_up(auto['production_10k']['low'])}—{_fmt_whole_half_up(auto['production_10k']['high'])}（{_fmt_whole_half_up(auto['production_10k']['point'])}） |"
        )
    return "\n".join(rows)


def _bodies(
    model: Mapping[str, Any], brand: Mapping[str, Any], upstream: Mapping[str, Any],
    refs: Mapping[str, Any], aliases: Mapping[tuple[str, str], str]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    c = lambda key: _cite(refs[key])
    final_rows = _format_final_rows(model)
    high_frequency_rows = _format_high_frequency_rows(model)
    ownership_rows = _format_ownership_rows(model)
    industry_month_refs = {
        str(row["month"]): aliases[("industry", f"cpca_{str(row['month']).replace('-', '_')}")]
        for row in model["history_12m"]
    }
    upstream_source_ids = {
        "2025-07": "S13", "2025-08": "S12", "2025-09": "S14", "2025-10": "S14",
        "2025-11": "S14", "2025-12": "S14", "2026-01": "S20", "2026-02": "S21",
        "2026-03": "S22", "2026-04": "S23", "2026-05": "S24", "2026-06": "S25",
    }
    upstream_month_refs = {
        month: aliases[("upstream", source_id)] for month, source_id in upstream_source_ids.items()
    }
    brand_evidence_refs = {
        int(company["rank"]): list(dict.fromkeys(
            aliases[("brand", str(item))]
            for item in company.get("evidence_ids") or []
            if ("brand", str(item)) in aliases
        ))
        for company in brand["companies"]
    }
    upstream_history_rows = _format_upstream_history_rows(upstream, upstream_month_refs)
    main_sections = [
        _public_section(
            "executive_result",
            "未来三个月排产、销量与库存",
            f"""
### 问题
2026年8—10月中国境内新能源乘用车将生产多少，内销、出口和库存怎样变化？

### 研究方法与数据
以最近12个月乘联分会产、批、零、出口为历史锚，把7月1—26日高频数据作为未结月估算，再分别运行总量、15家品牌/工厂和动力电池三种建模口径。三者共享部分行业底层数据，但计算链和调整项分别冻结。{c('cpca_june')}

### 研究与分析
综合中值为8月139万、9月159万、10月169万辆，环比分别约+14.3%、+13.7%、+6.7%，同比分别约+11.0%、+5.6%、+2.0%；国内零售约107万、119万、121万辆，中国工厂出口约47万、51万、54万辆。8月从7月低谷修复，9月旺季加速，10月仍增产但弱于单纯季节外推。

### 总结
**基准情形不是连续累库：生产体系库存残差约减少15万、12万、6万辆。** 但区间上沿仍允许局部增库，尤其取决于新车爬坡能否被国内零售和出口吸收。{c('cada_inventory')} {c('model')}
""",
            [refs["cpca_june"], refs["cada_inventory"], refs["model"]],
            10,
        ),
        _public_section(
            "method_comparison",
            "三个建模口径为何不同",
            f"""
### 问题
行业总量、品牌/工厂和动力电池三种方法是否相互验证，未来三个月的主要分歧集中在哪个月份、哪些假设和多大数量级？

### 研究方法与数据
总量法闭合产销库存，品牌法覆盖6月主要生产主体87.82%，动力电池法以12个月装车量回归校准。三者分别建模，但共享乘联分会历史产量或6月厂商基线，不能理解为三组统计独立样本。{c('battery_june')}

### 研究与分析
8月三法中值138/141/140万辆，9月160/155/160万辆，差异很小；10月174/160/171万辆，分歧扩大到14万辆，原因是总量法赋予旺季更强修复，品牌法受大集团谨慎排产约束。电池法逐月留一回测MAPE为4.99%，但领先一月相关性仅0.180。

### 总结
**8—9月方向高度一致，10月上沿可信度较低。** 综合权重为总量45%、品牌30%、电池25%，这是研究员按数据闭合、覆盖率和回测能力设定的压缩权重，不是统计优化结果。正文同时保留三法并集，避免权重掩盖分歧。{c('model')}
""",
            [refs["cpca_june"], refs["battery_june"], refs["model"]],
            20,
        ),
        _public_section(
            "scope_and_inventory",
            "生产地口径与库存边界",
            f"""
### 问题
哪些车辆被计入，库存数字能否直接理解为财报存货？

### 研究方法与数据
主口径纳入自主、合资和特斯拉上海等中国工厂产量及其出口，排除进口和中国品牌海外工厂本地产量；补充口径再剔除外企及外国品牌合资体系。

### 研究与分析
补充口径以品牌/工厂法为分母：8月122—130万、中值126万；9月134—143万、中值138万；10月140—149万、中值145万辆。下限计入已识别中国自主/控制体系和单列的中国品牌合资体系，上限再把未识别尾部全部视作中国体系，因此不把尾部残差伪装成外国品牌合资贡献。库存残差等于产量减国内零售和中国工厂出口，不等于企业资产负债表存货；6月纯新能源车企库存代理为79万辆，全乘用车经销商库存系数1.58。{c('brand_top20')} {c('cada_inventory')}

### 总结
**总量判断必须保留中国工厂出口；只看国内零售会系统性低估排产。** 自主口径只作结构对照，不能替代生产地主结果。
""",
            [refs["july_scan"], refs["cada_inventory"]],
            30,
        ),
    ]

    industry_body = f"""
### 问题

从行业总量出发，最近12个月中国境内新能源乘用车的产量、批发、国内零售、出口和库存处于什么位置，2026年8—10月怎样延伸？这里的主体是中国境内工厂，不按品牌国别归类；特斯拉上海和合资工厂均计入，进口车与中国品牌海外工厂产量排除。

### 研究方法与数据

最近12个月使用同一乘联分会新能源乘用车口径，并把月报的产量、厂商批发、国内零售和中国工厂出口放在一张表中。上险量只作为国内交付侧校验；全乘用车经销商库存系数和“仅生产新能源车企业库存”用于判断库存压力，不与产销残差混成同一个库存概念。{c('cpca_june')} {c('report_barclays')}

厂商库存、渠道库存和生产体系库存分别计算：

$$
\\text{{厂商库存变化}}_t=\\text{{产量}}_t-\\text{{厂商批发}}_t
$$

$$
\\text{{渠道库存变化}}_t=(\\text{{厂商批发}}_t-\\text{{中国工厂出口}}_t)-\\text{{国内零售}}_t
$$

$$
\\text{{生产体系库存变化}}_t=\\text{{产量}}_t-\\text{{国内零售}}_t-\\text{{中国工厂出口}}_t
$$

第三个算式是前两个残差之和，只在生产、零售和出口边界一致时有意义。出口含整车与部分CKD，所以下表更适合判断库存方向和压力，而不是充当企业财报存货。7月正式月报在研究截止时尚未发布；7月1—12日、1—19日和1—26日批发分别由26.2万升至50.9万、82.0万辆，据此估计7月产量122万辆，区间117—128万辆。{c('july_scan')}

### 研究与分析

| 月份 | 产量 | 批发 | 国内零售 | 上险 | 中国工厂出口 | 厂商库存变化 | 渠道库存变化 | 生产体系库存变化 | 纯新能源车企库存代理 | 来源 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
{_format_history_rows(model, industry_month_refs)}

上险量和零售量在可得月份方向一致，但上险是交强险注册、零售是乘联分会终端口径，不能互相填空；2025年7月公开资料没有同口径上险值，因此保留“—”。* 2025年9月上险129.5万辆由10月119.5万辆及环比下降7.7%反推，不是直接发布值。† 2025年12月纯新能源车企库存代理由随后两个月变化交叉反推为66万辆，另一转载写78万辆，因冲突只作低置信度代理。过去12个月呈现三个阶段。2025年10—11月生产体系残差累计增加27.6万辆；2026年3—6月按每月产量减国内零售减中国工厂出口复算，累计减少16.7万辆，因此8月不需要复制2025年四季度的主动加库强度。{c('model')}

最近三个月的高频重点是5月产量139.4万辆、库存残差增加2.0万辆，6月产量143.9万辆、库存残差减少6.7万辆，以及7月逐旬扫描持续低于6月。7月未结月明细如下：

| 高频窗口 | 累计国内零售 | 累计厂商批发 | 数据性质 |
|---|---:|---:|---|
{high_frequency_rows}

7月月度零售工作值为98万辆，出口工作值44万辆，产量工作值122万辆、区间117—128万辆，因此库存残差中值为122-98-44=-20万辆；它只承担8月环比基数，不进入已经结束的12个月实际序列。{c('july_scan_12')} {c('july_scan')} {c('july_scan_26')} {c('july_forecast')}

总量法不是只写“季节性调整”。它先将7月122万辆乘以2025年同月环比因子，再用终端需求、出口与库存压力作显式调整：

| 月份 | 前月中值 | 2025年同月环比因子 | 纯季节外推 | 需求/出口/库存调整 | 总量法排产区间（中值） |
|---|---:|---:|---:|---:|---:|
{_format_industry_input_rows(model)}

8月纯季节外推约133.6万辆，再上调4.4万辆，反映7月车型切换结束和出口吸收；9月从8月中值按历史因子外推约164.9万辆，再下调4.9万辆，反映内销仍弱和经销商库存压力；10月外推约176.6万辆，再下调2.6万辆，避免机械复制2025年四季度累库。独立结果是8月130—148万、中值138万；9月148—174万、中值160万；10月158—190万、中值174万辆。Barclays的国家统计局宽口径6月产量162万辆高于乘联分会143.9万辆，是因为前者包含更宽的新能源汽车范围，二者不平均。{c('report_barclays')} {c('model')}

### 总结

**总量法判断：7月是政策透支后的月度低谷，8月恢复，9—10月继续增产；但库存约束使10月难以无条件重演2025年四季度的主动加库。** 未来三个月总量法产量中值为138万、160万、174万辆；8—9月去库较明确，10月接近平衡。该方法对行业总量、销售和库存最完整，但无法回答每家工厂具体排班，因此必须与品牌和上游方法交叉验证。
"""

    brand_body = f"""
### 问题

如果把主要生产企业、集团和中国工厂逐一拆开，未来三个月排产能否汇总回行业总量？本方法先按6月中国厂商新能源乘用车批发建立生产主体排名，而不是按国内零售排名；这样才能把比亚迪、奇瑞、特斯拉上海等出口型主体补回，并避免把海外工厂本地产量误算为中国生产。

### 研究方法与数据

入选15个生产主体的6月厂商批发合计130.07万辆，占行业批发148.1万辆的87.82%；这是批发覆盖率，不是生产量覆盖率。前20家占93.6%，榜单第16—20名进一步识别为广汽埃安、极狐、广汽丰田、上汽通用和一汽奔腾，余量继续保留为未识别尾部。特斯拉中国按上海工厂纳入主结果；上汽通用五菱按中国生产主体纳入，同时在所有制敏感性中单列。{c('cpca_june')} {c('brand_top20')} {c('report_ms_auto')}

每家公司先从6月境内批发基线出发，再分别调整季节、出口、车型切换、产能爬坡与订单兑现：

$$
P_{{i,m}}=W_{{i,6月}}\\times S_m\\times R_{{i,m}}+N_{{i,m}}
$$

其中，$W$是6月中国工厂厂商批发基线，8—10月行业季节因子$S$分别为0.9521、1.0466和1.0804；$R$吸收逐公司订单、出口、车型切换和维护差异，$N$只允许在有明确、可量化的新产线净增量时加入。本轮所有公司$N=0$，避免把未经确认的爬坡传闻当确定增量；每家公司实际$R$、出口份额和库存率如下。公司没有公开正式排产时，这些参数属于研究判断，不伪装成厂方指引。{c('report_db_weekly')} {c('model')}

| 生产主体 | 6月批发W | 8/9/10月R中值 | 8/9/10月出口份额 | 8/9/10月库存率 | 新增量N |
|---|---:|---:|---:|---:|---:|
{_format_brand_input_rows(model)}

### 研究与分析

下表每个月均按“产/内/出/库”展示区间和中值，单位为万辆；四个指标的边界是各自误差带，不应把所有最差边界机械相加。出口份额通常上下浮动2个百分点，特斯拉因季度交付波动使用4个百分点；库存率上下浮动2个百分点，内销由产量减出口减库存复算。

| 生产主体 | 所有制与边界 | 6月批发/内销/中国工厂出口 | 2026年8月：产/内/出/库 | 2026年9月：产/内/出/库 | 2026年10月：产/内/出/库 | 逐主体证据 |
|---|---|---:|---|---|---|---|
{_format_brand_rows(model, brand_evidence_refs)}

绝对量稳定器仍是比亚迪、吉利、奇瑞、上汽体系和特斯拉上海；新增斜率更多来自零跑、小米、小鹏、蔚来、长安新能源和部分新车型。比亚迪6月基线39.73万辆，8—10月中值约37.5万、39.8万、40.8万辆，模型没有因出口强就机械外推更高增速。特斯拉上海6月8.91万辆，其中出口占比较高；其月度节奏更受季度末交付与出口航运影响，不能用中国国内零售代替工厂产量。{c('tesla_june')}

与6月基线相比，前15个主体8月中值合计少约6.3万辆，减量主要来自比亚迪约2.2万辆、吉利约1.1万辆、奇瑞约0.9万辆和特斯拉上海约0.9万辆；这解释了8月虽较7月回升，却仍略低于6月。到9月，前15个主体相对6月净增约5.7万辆，小米约贡献1.1万辆，零跑、长安、蔚来、小鹏、赛力斯等合计贡献主要增量；10月净增约9.8万辆，小米约贡献1.8万辆、零跑约1.2万辆，比亚迪约1.1万辆，而特斯拉上海因季度节奏比6月少约1.3万辆。以上是公司区间中值对6月基线的差额，不是公司正式排班。

公司汇总后的行业结果为8月132—150万、中值141万；9月146—164万、中值155万；10月150—169万、中值160万辆。它比总量法10月中值低14万辆，原因不是品牌法看空行业，而是大集团按已确认车型和产线爬坡逐家相加后，没有出现足以支持174万辆的新增量。品牌法的库存中值为8月轻微增库2万辆、9月去库1万辆、10月去库4万辆；与总量法在8月方向不同，核心分歧是国内零售取95万还是107万辆。结合7月预计零售98万辆和8月季节回升，总量法的107万辆更符合行业序列，因此最终库存权重不直接照搬品牌法。{c('report_guosen')}

品牌法还能把生产地总量拆成五个互不混写的结构部分：

| 月份 | 品牌法中国生产总量 | 已识别中国自主/控制体系 | 中国品牌合资体系 | 已识别外国品牌合资 | 外资独资在华生产 | 未识别尾部 | 剔除外资及外国品牌合资后的补充口径 |
|---|---:|---:|---:|---:|---:|---:|---:|
{ownership_rows}

外资独资在华生产目前主要是特斯拉上海，8—10月中值约8.0万、9.0万、7.6万辆。已识别外国品牌合资来自前20名中的广汽丰田和上汽通用，并按各自6月基线随行业季节调整为约2.6万、2.8万、3.0万辆；未识别尾部另列8.4万、9.7万、9.9万辆，不再与合资混成一栏。上汽通用五菱虽然是中外合资法人，但主销五菱/宝骏中国品牌，因此单列为“中国品牌合资体系”并保留在补充口径；若按纯所有权口径处理，可再从补充口径扣除其8—10月约6.5万、7.2万、7.7万辆。补充口径的下限计入已识别中国自主/控制体系与中国品牌合资体系，上限假设全部未识别尾部均属中国体系，得到8月122—130万、9月134—143万、10月140—149万辆；中值126万、138万、145万辆只用于对照，分母始终是品牌/工厂法总量。{c('brand_top20')} {c('model')}

### 总结

**品牌/工厂法确认8—9月修复，但对10月更谨慎：中值141万、155万、160万辆。** 15个主体已覆盖87.82%的6月行业量，出口型和外资在华工厂没有漏掉。增产主要来自小米、零跑、小鹏、蔚来、长安及新车型爬坡，大集团提供稳定基数；最大的误差不是少算一个小品牌，而是集团、品牌、合资公司与工厂边界错配，以及新车订单能否真正转成中国工厂批发。
"""

    upstream_body = f"""
### 问题

哪些上游原材料或核心硬件能在未来三个月排产判断中提供有效信息？集中度高并不自动等于领先指标：节点还必须有连续月度物理量、与整车产量存在稳定关系，并区分“提前信号”和“同期校准”。

### 研究方法与数据

初筛覆盖动力电池、磷酸铁锂、湿法隔膜、电解液、负极、驱动电机/电控、功率半导体和热管理。动力电池2025年CR3为71.98%、CR5为81.74%；2026年6月CR3按42.74%+18.49%+6.82%复算为68.05%，来源直接公布CR5为80.34%，逐家公司四舍五入份额相加为80.38%，正式采用80.34%。湿法隔膜虽集中度高，但缺少统一连续月度物理量；电解液、负极和LFP受储能、3C、出口和备库污染；电机电控接近同期且一车多电机；功率半导体和热管理缺少新能源车专属月度量，均不进入加权。{c('battery_concentration_2025')} {c('battery_concentration_2026')}

正式模型只使用逐月可追溯的动力电池装车量做同期经验校准：

$$
\\widehat P_t=30.8279+1.48028\\times B_t^{{装车量}}
$$

式子以2025年7月至2026年6月12个月回归，$P$单位为万辆、$B$单位为GWh；常数项吸收商用车、单车带电量和时间确认差异，不是物理单车电量换算。电池销量减出口的表观销量曾用于尝试提前一月检验，但来源和需求边界更杂、领先相关性也弱，因此不进入未来三个月的正式加权输入。{c('battery_june')} {c('model')}

### 研究与分析

正式入选的动力电池节点最近12个月装车量与整车产量如下，每个月分别链接对应月度来源。

| 月份 | 动力电池装车量 | 新能源乘用车产量 | 来源 |
|---|---:|---:|---|
{upstream_history_rows}

动力电池装车量与新能源乘用车产量的同期相关系数为0.970，逐月留一回测MAPE为4.99%，说明它适合校准同月产量。境内表观动力电池销量提前一月相关性只有0.180，说明当前公开上游序列并不具备稳定领先能力；它只用作供给方向反证，不承担点预测。2025年8月整车产量采用正式月报125.6万辆，不采用由不同累计口径反算的128.5万辆。

2026年5月动力与储能电池总产量191.7GWh、总销量182.2GWh，生产高于销售9.5GWh；6月差额扩大至10.0GWh。6月动力电池销量133.4GWh、出口25.5GWh，境内表观销量约107.9GWh，仅比5月增加0.9GWh；这说明电芯供给充裕，但没有给出整车排产大幅上修的强信号。7月LFP预计产量53.66万吨、环比增长4.68%，电芯价格约0.39元/Wh，主要反映储能和商用重卡需求，不直接换算乘用车台数。{c('lfp_july')} {c('report_ms_tyre')}

未来装车量不是外部事实，而是依据历史季节、7月整车低谷后的复产路径和无材料短缺约束设定的研究区间；每个月把低/中/高装车量代入回归，再用逐月留一RMSE 9.91万辆扩展上下界：

| 月份 | 装车量假设区间（中值） | 回归直接输出区间（中值） | 留一RMSE | 最终排产区间（中值） |
|---|---:|---:|---:|---:|
{_format_upstream_forecast_rows(model)}

由此，上游校准法给出8月125—156万、中值140万；9月145—178万、中值160万；10月155—190万、中值171万辆。Morgan Stanley轮胎跟踪显示6月乘用车原配胎需求同比下降4%，但该数据混合燃油车、规格和渠道库存，只作为对“全面强上修”的反证。供应商研报中的汇川客户篮子二季度增速较快，但历史客户集中度高，也不能替代全行业。{c('report_db_inovance')} {c('model')}

### 总结

**上游法的有效结论是“动力电池装车可校准同期，但现有公开序列不能稳定提前一个月预测整车”。** 未来三个月中值140万、160万、171万辆，与总量法接近；LFP、隔膜、电解液等不重复加权，避免把同一电池需求计数多次。上游没有出现材料短缺，也没有出现足以支持大幅超季节增产的强备货信号，10月上沿190万辆应视为压力边界而非基准。
"""

    synthesis_body = f"""
### 问题

把三条分别建模、但共享部分行业底层数据的结果放在一起，未来三个月最可信的中国境内新能源乘用车排产、批发、国内零售、出口和库存区间是什么？哪些差异来自真正的信息分歧，哪些只是口径或时间差？

### 研究方法与数据

三条模型先分别冻结再对账。总量法权重45%，因为它直接闭合12个月产、批、零、出口和库存；品牌/工厂法权重30%，因为15个主体覆盖6月行业批发87.82%，但集团与工厂边界更易错配；动力电池法权重25%，因为同期回测较好但一月领先能力弱。权重由研究员按可解释性设定，并非历史优化。{c('cpca_june')} {c('battery_june')}

$$
P_t^{{综合}}=0.45P_t^{{总量}}+0.30P_t^{{品牌/工厂}}+0.25P_t^{{动力电池}}
$$

这个权重只压缩为研究员可使用的核心区间，不覆盖三条原始输出。低/高边界按同样权重合成；库存再用综合产量减行业总量法的国内零售和中国工厂出口。正文同时展示“三法并集”，即取三种方法全部上下界的最宽范围，避免权重把真实分歧压窄。{c('model')}

### 研究与分析

| 月份 | 方法 | 产量区间 | 中值 |
|---|---|---:|---:|
{_format_method_rows(model)}

8月三法中值只差3万辆，说明7月低谷后恢复到约140万辆具有较强交叉支持。9月总量与电池法均为160万辆，品牌法155万辆，差异仍小。10月总量174万、品牌160万、电池171万辆，分歧扩大：总量法使用历史旺季和出口恢复，品牌法只累计已识别公司的车型与产线增量，电池法则允许较高装车上沿但没有强领先信号。最终不采用三法简单等权，而把10月中心压到169万辆。

| 月份 | 三法并集 | 加权核心排产区间（中值） | 环比 | 同比 | 厂商批发区间（中值） | 国内零售区间（中值） | 中国工厂出口区间（中值） | 库存变化区间（中值） | 中国体系补充口径区间（中值） |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
{final_rows}

为避免把预测写成伪精确单点，主表按整万辆展示；冻结模型以两位小数保存加权产量、零售、出口和库存桥，并在未圆整数上严格满足“库存变化＝产量－国内零售－中国工厂出口”。因此读者若只用表内四舍五入后的整数反算，个别月份可能出现1万辆的表面差额，不代表模型未闭合。{c('model')}

| 直接变化因素 | 已进入模型的可观察量 | 对8—10月结果的影响 |
|---|---|---|
| 主体复产与新车型爬坡 | 前15个主体相对6月的中值净变化约-6.3万、+5.7万、+9.8万辆 | 8月仍低于6月，9—10月由小米、零跑、小鹏、蔚来、长安等增量推动 |
| 中国工厂出口 | 综合中值47万、51万、54万辆 | 出口吸收约三成产量；若落到区间下沿，库存会转向上沿或迫使排产下修 |
| 特斯拉上海季度节奏 | 中值8.0万、9.0万、7.6万辆 | 9月季末交付偏强，10月回落约1.4万辆，造成外资独资贡献波动 |
| 折扣与渠道库存 | 6月经销商库存系数1.58，纯新能源车企库存代理79万辆 | 压低8月主动补库和10月季节性上沿，基准库存残差仍为负 |
| 车型切换、检修与产能切换 | 公开资料没有完整逐厂排班；公司区间已吸收已识别事件 | 主要扩大单体和10月区间，不把未核实停线传闻写进基准 |

8月生产体系库存残差中值减少14.6万辆，9月减少11.5万辆，10月减少6.0万辆；但三项输入的可行边界很宽，8月约-39至+8万辆、9月-41至+17万辆、10月-39至+26万辆。这个宽区间说明库存方向的置信度低于产量中值：品牌法若采用较弱内销，8月会轻微增库；总量法若国内零售随季节恢复，则继续去库。6月经销商库存系数1.58、纯新能源车企库存代理79万辆，使厂商没有必要在8月大幅主动加库。{c('cada_inventory')}

直接上修因素是9—10月新车集中交付、特斯拉上海和自主品牌出口、部分新产线爬坡；下修因素是终端折扣仍高、经销商库存压力、车型切换停线和海外本地生产替代中国出口。研报链没有逐工厂排产表，因此没有拿卖方叙事覆盖模型；Barclays宽口径产量、Morgan Stanley全球销售和轮胎数据只用于对账口径与反证。{c('report_barclays')} {c('report_ms_tyre')}

### 总结

**最可信的加权核心结果是：8月排产129—151万、中值139万；9月147—172万、中值159万；10月155—184万、中值169万辆。** 三法全部边界的并集分别为125—156万、145—178万和150—190万辆。对应国内零售约107万、119万、121万辆，出口约47万、51万、54万辆；基准库存仍去化，不支持“全行业连续三个月主动累库”。剔除外企及外国品牌合资后的品牌法补充口径中值约126万、138万、145万辆。三种方法对8—9月的一致性高于10月，因此实际决策应把10月区间而非174万单点作为核心。
"""

    entity_sections = [
        _entity_section("industry_total_method", "行业总量：产销、出口与库存", industry_body, [refs["cpca_may"], refs["cpca_june"], refs["july_scan_12"], refs["july_scan"], refs["july_scan_26"], refs["july_forecast"], refs["cada_inventory"], refs["report_barclays"], refs["model"]], 10),
        _entity_section("brand_factory_method", "品牌、集团与工厂自下而上排产", brand_body, [refs["cpca_june"], refs["brand_top20"], refs["tesla_june"], refs["report_ms_auto"], refs["report_guosen"], refs["model"]], 20),
        _entity_section("upstream_battery_method", "动力电池与上游约束校准", upstream_body, [refs["battery_june"], refs["battery_concentration_2025"], refs["battery_concentration_2026"], refs["lfp_july"], refs["report_db_inovance"], refs["report_ms_tyre"], refs["model"]], 30),
        _entity_section("three_method_synthesis", "三个建模口径对比与最终判断", synthesis_body, [refs["cpca_june"], refs["battery_june"], refs["cada_inventory"], refs["report_barclays"], refs["model"]], 40),
    ]
    return main_sections, entity_sections


def _line_panel(title: str, periods: list[str], series: list[dict[str, Any]], unit: str, y_axis: str) -> dict[str, Any]:
    values = [float(value) for item in series for value in item["values"] if value is not None]
    y_min = min(values)
    y_max = max(values)
    padding = max((y_max - y_min) * 0.12, 1.0)
    low = y_min - padding
    high = y_max + padding
    span = max(high - low, 1e-9)
    count = max(len(periods) - 1, 1)
    for item in series:
        points = []
        for index, value in enumerate(item["values"]):
            if value is None:
                continue
            x = index / count * 100.0
            y = 90.0 - (float(value) - low) / span * 80.0
            points.append(f"{x:.2f},{y:.2f}")
        item["svg_points"] = " ".join(points)
        item["latest_period"] = periods[-1]
        item["latest_value"] = f"{float(item['values'][-1]):.1f}"
        item["observation_count"] = len([value for value in item["values"] if value is not None])
    x_indices = sorted(set([0, len(periods) - 1] + [round(i * (len(periods) - 1) / 3) for i in range(1, 3)]))
    return {
        "title": title,
        "unit": unit,
        "x_start": periods[0],
        "x_end": periods[-1],
        "x_axis_label": "横轴：月份",
        "y_axis_label": y_axis,
        "y_min": round(low, 1),
        "y_max": round(high, 1),
        "y_ticks": [
            {"position": position, "label": f"{high - position / 100.0 * span:.0f}"}
            for position in (10, 50, 90)
        ],
        "x_ticks": [
            {"position": index / count * 100.0, "label": periods[index]}
            for index in x_indices
        ],
        "series": series,
    }


def _visuals(model: Mapping[str, Any], upstream: Mapping[str, Any], refs: Mapping[str, str]) -> list[dict[str, Any]]:
    history = model["history_12m"]
    forecasts = model["ensemble_forecast"]
    periods = [row["month"] for row in history] + [row["month"] for row in forecasts]
    actual_prod = [row["production"] for row in history]
    actual_retail = [row["retail"] for row in history]
    actual_export = [row["export"] for row in history]
    prod_values = actual_prod + [int(_fmt_whole_half_up(row["production_10k"]["point"])) for row in forecasts]
    retail_values = actual_retail + [int(_fmt_whole_half_up(row["domestic_retail_10k"]["point"])) for row in forecasts]
    export_values = actual_export + [int(_fmt_whole_half_up(row["china_factory_export_10k"]["point"])) for row in forecasts]
    inventory_values = [row["system_inventory_flow"] for row in history] + [int(_fmt_whole_half_up(row["system_inventory_flow_10k"]["point"])) for row in forecasts]
    history_rows = [
        [row["month"], f"{row['production']:.1f}", f"{row['wholesale']:.1f}", f"{row['retail']:.1f}",
         "—" if row.get("insurance_registration") is None else f"{row['insurance_registration']:.1f}",
         f"{row['export']:.1f}", f"{row['system_inventory_flow']:+.1f}"]
        for row in history
    ]
    method_periods = list(model["method_forecasts"].keys())
    method_series = []
    method_specs = [
        ("industry_total", "行业总量法", "#d94841"),
        ("brand_bottom_up", "品牌/工厂法", "#2f6da4"),
        ("upstream_leading", "动力电池法", "#8d5bd2"),
    ]
    for key, label, color in method_specs:
        method_series.append({"label": label, "color": color, "values": [model["method_forecasts"][month][key]["point"] for month in method_periods]})
    method_series.append({
        "label": "综合中值",
        "color": "#d18b00",
        "values": [int(_fmt_whole_half_up(row["production_10k"]["point"])) for row in forecasts],
    })
    battery_periods = [row["month"] for row in upstream["monthly_history"]]
    prod_index = [row["nev_passenger_production_10k"] / upstream["monthly_history"][0]["nev_passenger_production_10k"] * 100.0 for row in upstream["monthly_history"]]
    battery_index = [row["battery_installation_gwh"] / upstream["monthly_history"][0]["battery_installation_gwh"] * 100.0 for row in upstream["monthly_history"]]
    final_rows = []
    auto_by_month = {row["month"]: row for row in model["autonomous_supplement"]}
    for row in forecasts:
        final_rows.append([
            row["month"],
            f"{_fmt_whole_half_up(row['production_10k']['low'])}—{_fmt_whole_half_up(row['production_10k']['high'])}（{_fmt_whole_half_up(row['production_10k']['point'])}）",
            f"{row['mom_pct']:+.1f}%",
            f"{row['yoy_pct']:+.1f}%",
            f"{_fmt_whole_half_up(row['wholesale_10k']['low'])}—{_fmt_whole_half_up(row['wholesale_10k']['high'])}（{_fmt_whole_half_up(row['wholesale_10k']['point'])}）",
            f"{_fmt_whole_half_up(row['domestic_retail_10k']['low'])}—{_fmt_whole_half_up(row['domestic_retail_10k']['high'])}（{_fmt_whole_half_up(row['domestic_retail_10k']['point'])}）",
            f"{_fmt_whole_half_up(row['china_factory_export_10k']['low'])}—{_fmt_whole_half_up(row['china_factory_export_10k']['high'])}（{_fmt_whole_half_up(row['china_factory_export_10k']['point'])}）",
            f"{_fmt_whole_half_up(row['system_inventory_flow_10k']['low'])}—{_fmt_whole_half_up(row['system_inventory_flow_10k']['high'])}（{_fmt_whole_half_up(row['system_inventory_flow_10k']['point'])}）",
            f"{_fmt_whole_half_up(auto_by_month[row['month']]['production_10k']['low'])}—{_fmt_whole_half_up(auto_by_month[row['month']]['production_10k']['high'])}（{_fmt_whole_half_up(auto_by_month[row['month']]['production_10k']['point'])}）",
        ])
    return [
        {
            "entity_key": "industry_total_method",
            "block_key": "nev_history_forecast",
            "block_type": "line_chart",
            "title": "最近12个月实际产销与未来3个月综合预测",
            "subtitle": "单位为万辆；2026年8—10月为综合预测，其余为月度实际。",
            "data": {
                "what": "中国境内新能源乘用车产量、国内零售、出口及库存残差。",
                "time_window": "2025年7月至2026年10月",
                "how_to_read": "产量上升若没有被国内零售和出口吸收，就会转成正的库存残差。",
                "analysis": "7月未结月不混入实际序列；8月从低谷恢复，9—10月增产但库存约束仍在。",
                "chart": {"panels": [
                    _line_panel("产量、国内零售与出口", periods, [
                        {"label": "中国境内产量", "color": "#d94841", "values": prod_values},
                        {"label": "国内零售", "color": "#2f6da4", "values": retail_values},
                        {"label": "中国工厂出口", "color": "#3f8f69", "values": export_values},
                    ], "万辆", "纵轴：万辆"),
                    _line_panel("生产体系库存月度变化", periods, [
                        {"label": "库存变化", "color": "#d18b00", "values": inventory_values},
                    ], "万辆", "纵轴：万辆；正数为增库"),
                ]},
            },
            "print_fallback": {"columns": ["月份", "产量", "批发", "国内零售", "上险", "出口", "库存变化"], "rows": history_rows},
            "evidence_ref_uri_list": [_ev(refs["cpca_june"]), _ev(refs["cada_inventory"]), _ev(refs["model"])],
            "support_status": "supported",
            "red_flag_level": "none",
            "sort_order": 510,
        },
        {
            "entity_key": "upstream_battery_method",
            "block_key": "battery_vs_vehicle_index",
            "block_type": "line_chart",
            "title": "动力电池装车与新能源乘用车产量：同基期指数",
            "subtitle": "2025年7月=100；指数只比较方向和拐点，不混合GWh与车辆单位。",
            "data": {
                "what": "动力电池装车量与新能源乘用车产量的12个月标准化序列。",
                "time_window": "2025年7月至2026年6月",
                "how_to_read": "两条线同期接近，但不能据此证明电池数据稳定领先一个月。",
                "analysis": "同期相关系数0.970，领先一月相关性仅0.180；因此进入校准而非单独预测。",
                "chart": {"panels": [
                    _line_panel("同基期指数", battery_periods, [
                        {"label": "整车产量指数", "color": "#d94841", "values": prod_index},
                        {"label": "动力电池装车指数", "color": "#6f4aa8", "values": battery_index},
                    ], "指数", "纵轴：2025年7月=100"),
                ]},
            },
            "print_fallback": {"columns": ["月份", "整车产量指数", "电池装车指数"], "rows": [[period, f"{prod_index[i]:.1f}", f"{battery_index[i]:.1f}"] for i, period in enumerate(battery_periods)]},
            "evidence_ref_uri_list": [_ev(refs["battery_june"]), _ev(refs["cpca_june"]), _ev(refs["model"])],
            "support_status": "supported",
            "red_flag_level": "none",
            "sort_order": 520,
        },
        {
            "entity_key": "three_method_synthesis",
            "block_key": "three_method_comparison",
            "block_type": "line_chart",
            "title": "三种建模口径与综合排产中值",
            "subtitle": "每条线保留原始方法结果；综合值不是简单等权平均。",
            "data": {
                "what": "行业总量、品牌/工厂、动力电池和综合模型的未来三个月产量中值。",
                "time_window": "2026年8月至10月",
                "how_to_read": "8—9月方法接近；10月品牌法明显更谨慎，是主要模型分歧。",
                "analysis": "综合采用45%/30%/25%权重，把10月中心从总量法174万辆压到169万辆。",
                "chart": {"panels": [_line_panel("逐月产量中值", method_periods, method_series, "万辆", "纵轴：万辆")]},
            },
            "print_fallback": {"columns": ["月份", "综合排产区间（中值）", "环比", "同比", "厂商批发区间（中值）", "国内零售区间（中值）", "中国工厂出口区间（中值）", "库存变化区间（中值）", "国内企业/自主补充口径区间（中值）"], "rows": final_rows},
            "evidence_ref_uri_list": [_ev(refs["cpca_june"]), _ev(refs["battery_june"]), _ev(refs["cada_inventory"]), _ev(refs["model"])],
            "support_status": "supported",
            "red_flag_level": "none",
            "sort_order": 530,
        },
    ]


def _search_plan() -> list[dict[str, Any]]:
    axes = {
        "industry_total": "最近12个月产、批、零、上险、出口、库存与7月高频",
        "brand_factory": "主要生产主体、工厂归属、出口、新车、订单、产线与未来三个月排产",
        "upstream_leading": "高集中度上游节点筛选、12个月序列、领先期与回测",
        "method_synthesis": "三种方法对账、库存桥、自主补充口径与反方情景",
    }
    plan = []
    for axis, topic in axes.items():
        plan.extend([
            {"axis_key": axis, "source_channel": "report", "round": 1, "query": f"萝卜投研与本地研报：{topic}", "status": "completed_with_gap"},
            {"axis_key": axis, "source_channel": "web", "round": 1, "query": f"协会、公司、供应链与公开网页：{topic}", "status": "completed"},
        ])
    plan.extend([
        {"axis_key": "brand_factory", "source_channel": "web", "round": 2, "query": "针对7月高频与主要工厂逐主体补查出口、车型、产线和口径冲突", "gap_trigger": "第一轮没有公开的8—10月逐工厂排产表，且集团/品牌/工厂口径存在冲突。", "status": "completed_with_gap"},
        {"axis_key": "upstream_leading", "source_channel": "web", "round": 2, "query": "针对高集中节点补查连续月度量、出口扣除、领先期、库存污染和反证", "gap_trigger": "第一轮发现集中度高不等于领先，需要用12个月序列回测并排除重复覆盖。", "status": "completed"},
        {"axis_key": "method_synthesis", "source_channel": "report", "round": 2, "query": "补查外资报告的NBS宽口径、全球销量、供应商与轮胎反证", "gap_trigger": "第一轮研报没有逐工厂排产，需要用独立宽口径和上游代理对账而非替代模型。", "status": "completed_with_gap"},
    ])
    return plan


def _prompt_requirements() -> list[dict[str, str]]:
    rows = [
        ("未来三个月中国境内新能源乘用车逐月排产是多少，环比和同比怎样变化？", "three_method_synthesis"),
        ("最近三个月库存怎样变化，最近十二个月处于什么位置，未来三个月库存将怎样变化？", "industry_total_method"),
        ("哪些主要生产企业、集团、工厂和品牌会增产、减产或去库存，内销与中国工厂出口分别怎样？", "brand_factory_method"),
        ("特斯拉上海及外国品牌合资体系在华生产对总量、出口和库存判断贡献多少？", "brand_factory_method"),
        ("哪些高集中度上游原材料或核心硬件适合前推整车排产，筛选依据、集中度和领先期是什么？", "upstream_battery_method"),
        ("行业总量、品牌/工厂自下而上和上游约束校准三个口径分别给出怎样的逐月估算？", "three_method_synthesis"),
        ("三个口径是否相互验证，差异由时间差、库存、出口、利用率或车型结构中的哪些因素造成？", "three_method_synthesis"),
        ("综合三个口径后，全部中国境内生产口径的排产、批发、国内零售、出口和库存区间是什么？", "three_method_synthesis"),
        ("剔除外企及外国品牌合资体系后，国内企业/自主品牌生产口径的逐月数字是多少？", "brand_factory_method"),
        ("最重要的结论、主要上行和下行因素，以及可继续跟踪的高频指标是什么？", "three_method_synthesis"),
        ("最近十二个月产量、批发、零售、上险、出口和库存是否使用统一可比口径并保留客观缺口？", "industry_total_method"),
        ("主要生产主体是否按中国境内生产筛选并覆盖约80%至90%，是否列明品牌、工厂、归属和出口边界？", "brand_factory_method"),
        ("入选上游节点是否提供最近十二个月序列、最近三个月高频信号、回测误差和反证？", "upstream_battery_method"),
        ("最终是否用图表直观对比三个独立口径，而不是让一个口径反向填充另一个口径？", "three_method_synthesis"),
    ]
    return [
        {
            "question": question,
            "output_hint": output_hint,
            "acceptance_criteria": "对应实体必须给出数据、方法、分析、明确结果与证据引用。",
        }
        for question, output_hint in rows
    ]


def build_pack(publication_mode: str = "stage") -> dict[str, Any]:
    intake = parse_markdown_intake_text(INTAKE_PATH.read_text(encoding="utf-8"))
    industry = _read_json(AGENT_PATHS["industry"])
    brand = _read_json(AGENT_PATHS["brand"])
    upstream = _read_json(AGENT_PATHS["upstream"])
    model = _read_json(MODEL_PATH)
    report_review = _read_json(REPORT_REVIEW_PATH)
    model_hash = _sha256(MODEL_PATH)
    model_source = {
        "ref": MODEL_SOURCE_REF,
        "title": "Run18 中国新能源汽车三口径排产与库存冻结模型",
        "publisher": "Industry Demo独立研究模型",
        "source_tier": "C",
        "source_review_status": "pass_with_note",
        "excerpt": "模型分别冻结行业总量、品牌/工厂和动力电池三条计算链；三者共享部分行业底层数据，并复算未来三个月排产、批发、国内零售、中国工厂出口和库存残差。",
        "language": "zh",
        "independence_key": f"sha256:{model_hash}",
        "independence_rationale": "这是绑定输入和输出哈希的内部推断产物，不与外部协会、公司或卖方资料重复计作外部事实。",
        "source_channel": "web",
        "local_path": MODEL_PATH.relative_to(ROOT).as_posix(),
        "policy_evidence_role": "reference",
    }
    payloads = {"industry": industry, "brand": brand, "upstream": upstream}
    web_sources, aliases, by_url = _collect_web_sources(payloads)
    refs = {
        "cpca_june": by_url["https://www.cada.cn/trends/info_91_10533.html"],
        "cpca_may": by_url["https://www.cada.cn/trends/info_91_10514.html"],
        "july_scan_12": by_url["https://www.cada.cn/trends/info_91_10535.html"],
        "july_scan": by_url["https://www.cada.cn/trends/info_91_10540.html"],
        "july_scan_26": by_url["https://k.sina.com.cn/article_5835524730_15bd30a7a0200281ks.html"],
        "july_forecast": by_url["https://www.yicai.com/news/103289988.html"],
        "cada_inventory": aliases[("industry", "cada_dealer_inventory_june")],
        "tesla_june": aliases.get(("brand", "S13"), aliases[("brand", "S01")]),
        "brand_top20": aliases.get(("brand", "S02"), aliases[("brand", "S01")]),
        "battery_june": aliases.get(("upstream", "S25"), aliases[("upstream", "S1")]),
        "battery_concentration_2025": aliases.get(("upstream", "S18"), aliases[("upstream", "S25")]),
        "battery_concentration_2026": aliases.get(("upstream", "S19"), aliases[("upstream", "S25")]),
        "battery_concentration": aliases.get(("upstream", "S18"), aliases[("upstream", "S25")]),
        "lfp_july": aliases.get(("upstream", "S29"), aliases[("upstream", "S25")]),
        "report_barclays": "r-barclays-china-signals-20260716",
        "report_ms_auto": "r-morgan-stanley-global-autos-20260724",
        "report_guosen": "r-guosen-auto-strategy-20260617",
        "report_db_inovance": "r-deutsche-inovance-20260723",
        "report_db_weekly": "r-deutsche-auto-weekly-20260703",
        "report_ms_tyre": "r-morgan-stanley-tyre-20260721",
        "model": MODEL_SOURCE_REF,
    }
    main_sections, entity_sections = _bodies(model, brand, upstream, refs, aliases)
    input_hash = _hash_text("|".join(sorted(item["sha256"] for item in model["input_artifacts"].values())))
    report_hash = _sha256(REPORT_REVIEW_PATH)
    builder = RunPackBuilder(
        slug="china-nev-production-schedule-inventory-20260803",
        display_title="中国新能源汽车未来三个月排产与库存",
        research_question=intake["research_question"],
        problem_statement="中国境内生产的新能源乘用车在2026年8—10月将如何排产、销售、出口和去化库存？",
        intake=intake,
        requested_by="user_research_request",
        run_mode="c_open",
        quality_profile="deep_research",
        public_section_structure_contract=PUBLIC_SECTION_STRUCTURE_CONTRACT,
        homepage_section_min_characters=200,
        homepage_section_max_characters=700,
    )
    for source in [*web_sources, *REPORT_SOURCES, model_source]:
        source_row = dict(source)
        source_row.setdefault("policy_evidence_role", "core_evidence")
        builder.add_source(source_row)
    builder.search_plan = _search_plan()
    builder.modeling_records = [
        {
            "skill_name": "industry_supply_demand_modeling",
            "status": "completed",
            "input_artifact_hash": f"sha256:{input_hash}",
            "output_artifact_hash": f"sha256:{model_hash}",
            "notes": "三条建模口径分别冻结，再用产销库存桥形成综合区间；共享底层数据已显式说明。",
        }
    ]
    builder.independent_model_freezes = [
        {
            "model_ref": "nev_three_method_model_v1",
            "input_hash": f"sha256:{input_hash}",
            "output_hash": f"sha256:{model_hash}",
            "frozen_before_consensus": True,
            "frozen_at": "2026-08-03T12:00:00+08:00",
        }
    ]
    builder.external_reconciliations = [
        {
            "model_ref": "nev_three_method_model_v1",
            "benchmark_ref": "datayes_report_chain_review",
            "artifact_hash": f"sha256:{report_hash}",
            "status": "completed_with_gap",
            "summary": "研报链校准NBS宽口径、CPCA历史、出口和供应商反证，但没有逐工厂8—10月排产表。",
        }
    ]
    builder.data_points = _build_data_points_v2(
        industry, brand, upstream, model, aliases, MODEL_SOURCE_REF
    )
    core_ref = refs["cpca_june"]
    industry_month_refs = [
        aliases[("industry", f"cpca_{str(row['month']).replace('-', '_')}")]
        for row in industry["monthly_observations"]
    ]
    battery_month_ids = {
        "2025-07": "S13", "2025-08": "S12", "2025-09": "S14", "2025-10": "S14",
        "2025-11": "S14", "2025-12": "S14", "2026-01": "S20", "2026-02": "S21",
        "2026-03": "S22", "2026-04": "S23", "2026-05": "S24", "2026-06": "S25",
    }
    battery_month_refs = list(dict.fromkeys(
        aliases[("upstream", source_id)] for source_id in battery_month_ids.values()
    ))
    builder.claims = [
        _claim(key="c01", entity_key="industry_total_method", text="2025年7月至2026年6月新能源乘用车产量从114.7万辆波动至143.9万辆，2025年11月175.7万辆是近12个月高点。", source_ref=refs["model"], excerpt="逐月来源分别绑定后冻结为12个月序列。", claim_type="fact", supporting_source_refs=industry_month_refs),
        _claim(key="c02", entity_key="industry_total_method", text="2026年3—6月按产量减国内零售减中国工厂出口复算，生产体系库存累计减少约16.7万辆。", source_ref=refs["model"], excerpt="四个月同口径产销出口残差逐月相加。", supporting_source_refs=industry_month_refs[-4:]),
        _claim(key="c03", entity_key="brand_factory_method", text="品牌/工厂模型覆盖15个主要生产主体，6月厂商批发合计130.07万辆，占行业批发87.82%。", source_ref=refs["model"], excerpt="15家厂商榜合计除以6月行业批发148.1万辆。", supporting_source_refs=[refs["cpca_june"], refs["brand_top20"]]),
        _claim(key="c04", entity_key="brand_factory_method", text="特斯拉上海必须按中国工厂产量与出口纳入主口径，不能用中国国内零售替代。", source_ref=refs["tesla_june"], excerpt="特斯拉上海同时供应国内与出口。"),
        _claim(key="c05", entity_key="upstream_battery_method", text="动力电池2025年CR3为71.98%、CR5为81.74%，具备较高集中度。", source_ref=refs["battery_concentration_2025"], excerpt="2025年动力电池企业装车份额复算。"),
        _claim(key="c06", entity_key="upstream_battery_method", text="动力电池装车量与新能源乘用车产量同期相关性为0.970，但尝试的领先一月相关性仅0.180。", source_ref=refs["model"], excerpt="12个月逐月输入及回归、领先检验在冻结模型复算。", supporting_source_refs=battery_month_refs),
        _claim(key="c07", entity_key="three_method_synthesis", text="综合模型给出2026年8—10月中国境内新能源乘用车产量中值139.4万、158.5万和169.1万辆。", source_ref=refs["model"], excerpt="三种建模口径按45%/30%/25%合成。"),
        _claim(key="c08", entity_key="three_method_synthesis", text="基准库存残差未来三个月继续为负，但库存区间允许局部增库，库存判断置信度低于产量。", source_ref=refs["model"], excerpt="经销商库存系数与产销出口残差共同约束。"),
    ]
    point_specs = {
        "industry_total_method": [
            (refs["model"], "12个月产量序列", "历史", "64.5—175.7万辆", "逐月来源分别绑定，完整序列显示春节低谷和四季度旺季。"),
            (refs["model"], "12个月国内零售序列", "需求", "46.4—133.7万辆", "逐月来源分别绑定，内需恢复弱于出口。"),
            (refs["model"], "12个月中国工厂出口", "出口", "20.4—49.9万辆", "逐月来源分别绑定，出口是中国工厂产量的重要吸收项。"),
            (refs["cada_inventory"], "6月经销商库存系数", "库存", "1.58个月", "仍高于健康低位，限制主动补库。"),
            (refs["july_scan"], "7月1—26日厂商批发", "高频", "82.0万辆", "确认7月是月度低谷。"),
            (refs["report_barclays"], "NBS宽口径6月产量", "口径对账", "162万辆", "宽于新能源乘用车口径，不与143.9万辆平均。"),
            (refs["model"], "8月总量法预测", "预测", "130—148万辆", "季节修复受库存约束。"),
            (refs["model"], "10月总量法预测", "预测", "158—190万辆", "旺季上沿依赖出口和终端兑现。"),
        ],
        "brand_factory_method": [
            (core_ref, "前15家覆盖率", "覆盖", "87.82%", "按生产主体而非国内零售筛选。"),
            (core_ref, "比亚迪6月基线", "主体", "39.73万辆", "大集团提供绝对量稳定器。"),
            (refs["tesla_june"], "特斯拉上海6月基线", "主体", "8.91万辆", "国内与出口必须合并判断工厂产量。"),
            (refs["report_ms_auto"], "本土与外资结构", "口径", "报告对账", "不把企业国别替代生产地。"),
            (refs["report_guosen"], "5月主要厂商榜", "历史", "逐主体校准", "研报转述同源数据不重复计权。"),
            (refs["model"], "8月品牌法预测", "预测", "132—150万辆", "公司逐一相加后接近总量法。"),
            (refs["model"], "10月品牌法预测", "预测", "150—169万辆", "对大集团增产更谨慎。"),
            (refs["model"], "自主补充口径", "结构", "8月122—130万辆（中值126万）", "只作结构对照，不能替代主口径。"),
        ],
        "upstream_battery_method": [
            (refs["battery_concentration_2025"], "2025年动力电池CR5", "节点筛选", "81.74%", "2025年全年榜单集中度。"),
            (refs["battery_concentration_2026"], "2026年6月动力电池CR5", "节点筛选", "80.34%", "采用来源公布合计；逐项四舍五入相加为80.38%。"),
            (refs["battery_june"], "6月动力电池装车", "同期校准", "76.5GWh", "进入经验回归。"),
            (refs["battery_june"], "6月境内表观动力电池销量", "备货", "107.9GWh", "销量扣出口后仍含商用车和库存。"),
            (refs["battery_june"], "同期相关系数", "回测", "0.970", "适合同期校准。"),
            (refs["battery_june"], "领先一月相关系数", "回测", "0.180", "不能宣称稳定领先。"),
            (refs["lfp_july"], "7月LFP产量预测", "供应约束", "53.66万吨", "供给不短缺但储能污染强。"),
            (refs["report_ms_tyre"], "6月乘用车OE轮胎", "反证", "同比-4%", "包含燃油车，只限制强上修。"),
            (refs["model"], "10月上游法预测", "预测", "155—190万辆", "上沿是压力边界。"),
        ],
        "three_method_synthesis": [
            (refs["model"], "8月三法中值", "对比", "138/141/140万辆", "三法高度一致。"),
            (refs["model"], "9月三法中值", "对比", "160/155/160万辆", "方向一致。"),
            (refs["model"], "10月三法中值", "对比", "174/160/171万辆", "旺季斜率分歧扩大。"),
            (refs["model"], "综合权重", "模型", "45%/30%/25%", "按数据闭合、覆盖和回测分配。"),
            (refs["model"], "8月综合排产", "结果", "129—151万辆", "中值139万辆。"),
            (refs["model"], "9月综合排产", "结果", "147—172万辆", "中值159万辆。"),
            (refs["model"], "10月综合排产", "结果", "155—184万辆", "中值169万辆。"),
            (refs["model"], "三个月库存基准", "库存", "-15/-12/-6万辆", "基准去库、上沿允许局部增库。"),
        ],
    }
    entities = []
    entity_meta = {
        "industry_total_method": ("行业总量口径", "用12个月产销出口库存与7月高频估算整体排产。", "行业总量如何推演未来三个月排产与库存？"),
        "brand_factory_method": ("品牌、集团与工厂口径", "覆盖约88%的主要中国境内生产主体并逐一估算。", "主要生产主体逐个汇总后指向多少排产？"),
        "upstream_battery_method": ("上游原材料与核心硬件口径", "筛选高集中、连续、可回测的动力电池节点，区分同期校准与领先信号。", "哪些上游节点能校准或提前判断整车排产？"),
        "three_method_synthesis": ("三个口径对比与综合结论", "对账三种分别建模但共享部分底层数据的口径，形成主口径与补充口径。", "三种方法如何形成最终可用结果？"),
    }
    section_by_key = {row["entity_key"]: row for row in entity_sections}
    for key in ENTITY_KEYS:
        name, description, question = entity_meta[key]
        specs = point_specs[key]
        points = [_research_point(*spec, order=index) for index, spec in enumerate(specs, start=1)]
        entity_refs = list(dict.fromkeys(spec[0] for spec in specs))
        body = section_by_key[key]["body_markdown"]
        entities.append(_theory_entity(
            key=key,
            name=name,
            description=description,
            question=question,
            methodology="三条方法分别取证和计算，同时披露共享的行业底层数据；复杂关系展示公式、代入值和误差规则。",
            literature="网页链以协会、公司和产业数据为主；研报链用于口径校准、外部反证和历史对账。",
            analysis=body,
            answer=body.split("### 总结", 1)[-1].strip(),
            conclusion=body.split("### 总结", 1)[-1].strip(),
            limitations="7月为未结月估计，工厂排班和库存层级公开不足；结果用区间表达。",
            refs=entity_refs,
            points=points,
        ))
    for entity in entities:
        builder.add_entity(entity)
    builder.entity_sections = entity_sections
    builder.sections = main_sections
    builder.visuals = _visuals(model, upstream, refs)
    pack = builder.build(publication_mode=publication_mode)
    pack["prompt_requirements"] = _prompt_requirements()
    external_sources = [
        row for row in pack["sources"] if row.get("policy_evidence_role") != "reference"
    ]
    independence_counts: dict[str, int] = {}
    for row in external_sources:
        key = str(row["independence_key"])
        independence_counts[key] = independence_counts.get(key, 0) + 1
    duplicate_group_count = len([count for count in independence_counts.values() if count > 1])
    duplicate_extra_source_count = sum(count - 1 for count in independence_counts.values() if count > 1)
    pack["open_search_statistics"] = {
        "all_source_count": len(pack["sources"]),
        "external_source_count": len(external_sources),
        "source_count": len(external_sources),
        "independent_source_group_count": len({row["independence_key"] for row in external_sources}),
        "parallel_data_point_count": len(pack["data_points"]),
        "direct_external_data_point_count": len([
            row for row in pack["data_points"] if row.get("extraction_method") in {"web_fetch", "pdf_direct"}
        ]),
        "inferred_data_point_count": len([
            row for row in pack["data_points"] if row.get("extraction_method") == "inferred"
        ]),
        "report_source_count": len([row for row in external_sources if row["source_channel"] == "report"]),
        "web_source_count": len([row for row in external_sources if row["source_channel"] == "web"]),
        "weak_lead_count": 2,
        "same_origin_duplicate_group_count": duplicate_group_count,
        "same_origin_duplicate_count": duplicate_extra_source_count,
        "unresolved_material_lead_count": 2,
        "unresolved_material_lead_disposition": (
            "小米二期爬坡时间和特斯拉上海检修传闻只进入公司区间边界；"
            "因缺少公司或工厂确认，不作为基准排产事实。"
        ),
    }
    validate_run_pack(pack, publication_mode=publication_mode).raise_for_errors()
    unique_count = len({(
        row["source_ref"], row.get("entity_key", ""), row["metric"], row["unit"], row.get("scope_key", "")
    ) for row in pack["data_points"]})
    if unique_count < 100:
        raise ValueError(f"Run18 平行研究事实不足100，当前{unique_count}")
    for section in pack["sections"]:
        length = _visible_length(section["body_markdown"])
        if not 200 <= length <= 700:
            raise ValueError(f"首页摘要 {section['title']} 可见字符{length}不在200—700")
    for section in pack["entity_sections"]:
        if _visible_length(section["body_markdown"]) < 1200:
            raise ValueError(f"实体正文 {section['title']} 少于1200可见字符")
    return pack


def main() -> int:
    parser = argparse.ArgumentParser(description="构建 Run18 新能源汽车排产与库存 V2 研究包")
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--publication-mode", choices=("stage", "publish"), default="stage")
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    pack = build_pack(publication_mode=args.publication_mode)
    report = validate_run_pack(pack, publication_mode=args.publication_mode)
    report.raise_for_errors()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if not args.validate_only:
        args.output.write_text(json.dumps(pack, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "output": str(args.output),
        "written": not args.validate_only,
        "source_count": len(pack["sources"]),
        "parallel_data_points": len(pack["data_points"]),
        "entity_count": len(pack["entities"]),
        "section_lengths": {row["section_key"]: _visible_length(row["body_markdown"]) for row in pack["sections"]},
        "entity_lengths": {row["entity_key"]: _visible_length(row["body_markdown"]) for row in pack["entity_sections"]},
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
