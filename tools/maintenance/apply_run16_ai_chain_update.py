#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Apply the evidence-backed Run16 AI-chain taxonomy update.

The command is deliberately read-only by default.  It opens ``research.db``
with SQLite ``mode=ro``, resolves companies by the pair ``(name, ticker)`` and
prints the intended changes.  Database writes require ``--apply`` and execute
inside one foreign-key checked transaction.

This adapter updates taxonomy, industry relations and company-to-industry
membership only.  It never writes ``industry_data_point`` and never touches
the financial, sentiment or Opportunity Lens databases.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = ROOT / "data" / "research.db"
SCHEMA_VERSION = "run16.ai_chain_update.v1"
RESEARCH_AS_OF = "2026-08-02"


@dataclass(frozen=True)
class IndustrySpec:
    name: str
    parent: str | None
    level: int
    tier: int
    status: str
    core_dynamic: str


@dataclass(frozen=True)
class CompanySpec:
    name: str
    ticker: str
    primary_industry: str
    role: str
    note: str
    also_parent: str | None = None


@dataclass(frozen=True)
class SourceSpec:
    key: str
    title: str
    publisher: str
    publish_date: str
    url: str
    note: str


@dataclass(frozen=True)
class RelationSpec:
    upstream: str
    downstream: str
    relation_type: str
    source_key: str
    note: str


INDUSTRIES: tuple[IndustrySpec, ...] = (
    IndustrySpec(
        "办公与文档智能", "AI应用", 2, 2, "基础跟踪",
        "以高频文档工作流、订阅提价、企业续费和AI增量毛利验证商业化。",
    ),
    IndustrySpec(
        "金融知识与决策", "AI应用", 2, 2, "基础跟踪",
        "区分市场活跃度带来的基础业务增长与AI对留存、定价和效率的真实增量。",
    ),
    IndustrySpec(
        "教育医疗与公共服务", "AI应用", 2, 2, "基础跟踪",
        "以场景收入、项目回款、现金流和合规成本检验AI在教育、医疗和政务中的兑现。",
    ),
    IndustrySpec(
        "企业管理与工业流程", "AI应用", 2, 2, "基础跟踪",
        "以合同转收入、续费、交付人效和经营现金流判断企业及工业智能体价值。",
    ),
    IndustrySpec(
        "网络安全与IT运营", "AI应用", 2, 2, "基础跟踪",
        "关注安全与IT运营工作流中的AI收费、告警处置效率和新增毛利，而非只看产品发布。",
    ),
    IndustrySpec(
        "创意内容与营销", "AI应用", 2, 2, "基础跟踪",
        "以商业客户付费、生成内容复用率、获客成本、版权责任和增量毛利验证，不把用户量直接当收入。",
    ),
    IndustrySpec(
        "代码开发与软件工程", "AI应用", 2, 2, "基础跟踪",
        "以企业席位、代码采纳率、留存、推理成本和安全合规验证商业化；本轮尚无通过公司级财务门禁的A股核心持仓。",
    ),
    IndustrySpec(
        "智能客服与服务运营", "AI应用", 2, 2, "基础跟踪",
        "以解决率、人工替代、客户续约、合同单价和实施成本验证，而不是按调用量推算收入。",
    ),
    IndustrySpec(
        "企业搜索与知识库", "AI应用", 2, 2, "基础跟踪",
        "以企业数据权限、检索准确率、部署周期、付费席位和续费验证知识工作流壁垒。",
    ),
    IndustrySpec(
        "法律与专业服务", "AI应用", 2, 2, "基础跟踪",
        "以责任边界、专业数据库、可审计输出、客户付费和人效改善验证；本轮只做产业跟踪。",
    ),
    IndustrySpec(
        "电商运营与消费者助手", "AI应用", 2, 2, "基础跟踪",
        "以成交转化、广告回报、退货与售后成本、平台抽佣和复购验证，不以活跃度替代经营结果。",
    ),
    IndustrySpec(
        "机架级系统集成", "AI服务器", 2, 2, "基础跟踪",
        "AI服务器价值从单机向整柜、网络、电源和液冷协同交付迁移。",
    ),
    IndustrySpec(
        "内存与高速互连芯片", "存储", 2, 2, "基础跟踪",
        "覆盖RCD、MRCD、Retimer、CXL和AEC芯片，不把互连芯片误作HBM制造。",
    ),
    IndustrySpec(
        "高速铜互连", "通信", 2, 2, "基础跟踪",
        "DAC、AEC与高速连接器主要承接机架内和短距互连，并与光互连按距离共存。",
    ),
    IndustrySpec(
        "低损耗覆铜板与电子材料", "PCB制造", 2, 2, "基础跟踪",
        "低损耗覆铜板、电子布和铜箔通过材料等级、认证与良率影响高速PCB价值。",
    ),
    IndustrySpec(
        "数据中心建设与运营", "云计算与算力运营", 2, 2, "基础跟踪",
        "按电力指标、预租率、上架率、客户信用、资本成本和自由现金流评估IDC与智算运营。",
    ),
    IndustrySpec(
        "数据中心供电", "电力", 2, 2, "基础跟踪",
        "覆盖PSU、BBU、UPS、HVDC、800VDC、母线和配电，按认证、订单与交付验证需求。",
    ),
    IndustrySpec(
        "智能终端与物理AI", None, 1, 2, "基础跟踪",
        "端侧计算、智能终端和机器人必须以真实出货、部署可靠性与经济回报验证。",
    ),
    IndustrySpec(
        "机器人与工业智能", "智能终端与物理AI", 2, 2, "基础跟踪",
        "以控制器、伺服、传感、系统集成和常态部署承接工业智能与机器人，而非概念送样。",
    ),
)


COMPANIES: tuple[CompanySpec, ...] = (
    CompanySpec("金山办公", "688111.SH", "办公与文档智能", "平台龙头", "高频办公工作流与企业订阅承接AI商业化；AI增量收入仍需单列验证。", "AI应用"),
    CompanySpec("合合信息", "688615.SH", "办公与文档智能", "文档智能优选", "文档识别、抽取和企业工作流直接，但需区分传统OCR与大模型增量收入。", "AI应用"),
    CompanySpec("同花顺", "300033.SZ", "金融知识与决策", "金融知识服务龙头", "数据、流量和券商连接形成壁垒；AI增量必须与资本市场活跃度分开。", "AI应用"),
    CompanySpec("科大讯飞", "002230.SZ", "教育医疗与公共服务", "场景AI龙头", "教育、医疗与政企场景收入证据较强，但估值需受自由现金流和补贴口径约束。", "AI应用"),
    CompanySpec("鼎捷数智", "300378.SZ", "企业管理与工业流程", "工业智能优选", "工业智能体已有合同验证，仍需跟踪合同转收入、毛利和交付人效。", "AI应用"),
    CompanySpec("深信服", "300454.SZ", "网络安全与IT运营", "安全与IT运营候选", "安全及IT运营具有刚需工作流；AI收入未单列，按ROE和现金流约束估值。", "AI应用"),
    CompanySpec("工业富联", "601138.SH", "机架级系统集成", "AI机架与服务器制造龙头", "承接GPU与ASIC服务器、整柜和系统集成交付，同时关注客户集中和低毛利。"),
    CompanySpec("中际旭创", "300308.SZ", "光模块", "高速光互连龙头", "800G与1.6T兑现度高，长期关注扩产、ASP、客户集中及CPO价值分配。"),
    CompanySpec("沪电股份", "002463.SZ", "高多层PCB板", "AI服务器与交换机PCB龙头", "高多层板与海外产能承接AI需求，需跟踪认证、良率与扩产后价格。"),
    CompanySpec("北方华创", "002371.SZ", "半导体设备", "前道设备龙头", "AI、先进存储和国产化共同驱动设备需求，但AI传导间接且受设备周期约束。"),
    CompanySpec("澜起科技", "688008.SH", "内存与高速互连芯片", "内存互连龙头", "RCD、MRCD、Retimer与CXL承接服务器升级，明确不归为HBM制造。"),
    CompanySpec("海光信息", "688041.SH", "算力芯片", "国产CPU与DCU龙头", "国产算力需求与软件生态共同决定收入，需约束供应链、性能生态和估值风险。"),
    CompanySpec("英维克", "002837.SZ", "液冷", "液冷与热管理龙头", "覆盖冷板、CDU和系统验证，具体AI与数据中心收入仍需拆分。"),
    CompanySpec("中恒电气", "002364.SZ", "数据中心供电", "数据中心电源候选", "覆盖多代HVDC、配电和服务器电源；订单、客户与AI收入规模仍需验证。"),
    CompanySpec("润泽科技", "300442.SZ", "数据中心建设与运营", "IDC与智算运营候选", "按投运、上架、客户、电力资源、债务和自由现金流评估，不等同公有云平台。"),
    CompanySpec("生益科技", "600183.SH", "低损耗覆铜板与电子材料", "低损耗覆铜板龙头", "高端材料认证承接AI服务器与高速网络，需与普通覆铜板周期分开。"),
    CompanySpec("立讯精密", "002475.SZ", "高速铜互连", "高速连接与铜互连候选", "高速铜缆、连接、电源和终端形成跨链承接，但送样不等于规模订单。"),
    CompanySpec("汇川技术", "300124.SZ", "机器人与工业智能", "工业自动化与物理AI龙头", "工控基本盘提供现金流，机器人和具身智能只按真实部署与经济性计入。", "智能终端与物理AI"),
)


SOURCES: tuple[SourceSpec, ...] = (
    SourceSpec(
        "nvidia_fy27_q1", "英伟达公布2027财年第一季度业绩", "NVIDIA", "2026-05-20",
        "https://investor.nvidia.com/news/press-release-details/2026/NVIDIA-Announces-Financial-Results-for-First-Quarter-Fiscal-2027/default.aspx",
        "Run16用于核验AI计算与数据中心需求；公司正式披露。",
    ),
    SourceSpec(
        "microsoft_fy26_q3", "微软2026财年第三季度业绩电话会", "Microsoft", "2026-04-29",
        "https://www.microsoft.com/en-us/investor/events/fy-2026/earnings-fy-2026-q3",
        "Run16用于核验云端资本开支、AI商业化及基础设施毛利约束；公司正式披露。",
    ),
    SourceSpec(
        "alphabet_2025_q4", "Alphabet 2025年第四季度业绩电话会", "Alphabet", "2026-02-04",
        "https://abc.xyz/investor/events/event-details/2026/2025-Q4-Earnings-Call-2026-Dr_C033hS6/default.aspx",
        "Run16用于核验服务器、网络和数据中心资本开支结构；公司正式披露。",
    ),
    SourceSpec(
        "arista_2026_q1", "Arista公布2026年第一季度业绩", "Arista Networks", "2026-05-05",
        "https://investors.arista.com/Communications/Press-Releases-and-Events/Press-Release-Detail/2026/Arista-Networks-Inc--Reports-First-Quarter-2026-Financial-Results/default.aspx",
        "Run16用于核验交换、光学和热管理协同；公司正式披露。",
    ),
    SourceSpec(
        "iea_energy_ai_2026", "能源与人工智能的关键问题", "International Energy Agency", "2026-04-16",
        "https://www.iea.org/reports/key-questions-on-energy-and-ai",
        "Run16用于核验数据中心用电、变压器、并网和审批约束；国际机构研究。",
    ),
    SourceSpec(
        "cbre_dc_2026", "2026全球数据中心趋势", "CBRE", "2026-06-17",
        "https://www.cbre.com/insights/reports/global-data-center-trends-2026",
        "Run16用于核验数据中心容量、空置率和地区电力约束；市场研究。",
    ),
    SourceSpec(
        "schneider_2026_q1", "施耐德电气2026年第一季度收入", "Schneider Electric", "2026-04-30",
        "https://www.se.com/ww/en/assets/pdf/release-q1-revenues-2026",
        "Run16用于核验数据中心供电、配电、液冷和能源管理需求；公司正式披露。",
    ),
    SourceSpec(
        "industrial_foxconn_2025", "工业富联2025年年度报告", "工业富联", "2026-03-31",
        "https://money.finance.sina.com.cn/corp/view/vCB_AllBulletinDetail.php?id=11990023&stockid=601138",
        "Run16用于核验AI服务器与机架制造承接；公司年度报告。",
    ),
    SourceSpec(
        "shengyi_2025", "生益科技2025年年度报告", "生益科技", "2026-04-25",
        "https://money.finance.sina.com.cn/corp/view/vCB_AllBulletinDetail.php?id=12198074&stockid=600183",
        "Run16用于核验低损耗覆铜板与AI服务器、高速网络需求；公司年度报告。",
    ),
    SourceSpec(
        "zhongheng_2025", "中恒电气2025年年度报告", "中恒电气", "2026-04-21",
        "https://disc.static.szse.cn/download/disc/disk03/finalpage/2026-04-21/d0543cb8-6de6-4606-9add-49a587d32b30.PDF",
        "Run16用于核验数据中心HVDC、配电和服务器电源产品；公司年度报告。",
    ),
)


RELATIONS: tuple[RelationSpec, ...] = (
    RelationSpec("机架级系统集成", "云计算与算力运营", "配套", "alphabet_2025_q4", "云厂资本开支中的服务器、网络与数据中心共同决定机架系统需求。"),
    RelationSpec("通信", "云计算与算力运营", "配套", "arista_2026_q1", "AI集群网络承接云厂训练与推理容量扩张。"),
    RelationSpec("光模块", "云计算与算力运营", "配套", "arista_2026_q1", "高速光学与交换系统协同支撑云端AI集群。"),
    RelationSpec("低损耗覆铜板与电子材料", "PCB制造", "供应", "shengyi_2025", "低损耗材料通过等级、认证和良率影响高速PCB性能与价值。"),
    RelationSpec("数据中心供电", "数据中心建设与运营", "配套", "schneider_2026_q1", "电源、配电和能源管理共同决定数据中心可交付容量。"),
    RelationSpec("液冷", "数据中心建设与运营", "配套", "schneider_2026_q1", "高密度机架推动液冷与机房系统协同设计和交付。"),
    RelationSpec("数据中心建设与运营", "云计算与算力运营", "配套", "cbre_dc_2026", "电力、建设、预租和上架共同约束云端算力容量兑现。"),
    RelationSpec("电力", "数据中心建设与运营", "供应", "iea_energy_ai_2026", "发电、输变电和并网能力决定数据中心投产节奏。"),
    RelationSpec("大模型", "AI应用", "供应", "microsoft_fy26_q3", "模型和云服务为应用提供推理能力，应用价值仍需通过收费和现金流验证。"),
)


def _connect(path: Path, *, apply: bool) -> sqlite3.Connection:
    if apply:
        conn = sqlite3.connect(path)
    else:
        conn = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
        conn.execute("PRAGMA query_only=ON")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _rows_by_name(conn: sqlite3.Connection, table: str) -> dict[str, sqlite3.Row]:
    return {str(row["name"]): row for row in conn.execute(f"SELECT * FROM {table}")}


def _resolve_company(
    conn: sqlite3.Connection, spec: CompanySpec
) -> tuple[sqlite3.Row | None, list[str]]:
    errors: list[str] = []
    by_name = conn.execute(
        "SELECT id,name,ticker,market FROM company WHERE name=?", (spec.name,)
    ).fetchall()
    by_ticker = conn.execute(
        "SELECT id,name,ticker,market FROM company WHERE upper(ticker)=upper(?)",
        (spec.ticker,),
    ).fetchall()
    if len(by_name) != 1:
        errors.append(f"公司名称未唯一解析：{spec.name}，命中{len(by_name)}条")
    if len(by_ticker) != 1:
        errors.append(f"证券代码未唯一解析：{spec.ticker}，命中{len(by_ticker)}条")
    if errors:
        return None, errors
    name_row, ticker_row = by_name[0], by_ticker[0]
    if int(name_row["id"]) != int(ticker_row["id"]):
        errors.append(
            f"公司身份冲突：{spec.name}解析为id={name_row['id']}，"
            f"{spec.ticker}解析为{ticker_row['name']} id={ticker_row['id']}"
        )
        return None, errors
    if str(name_row["ticker"] or "").upper() != spec.ticker.upper():
        errors.append(
            f"公司ticker冲突：{spec.name} live={name_row['ticker']} expected={spec.ticker}"
        )
        return None, errors
    return name_row, errors


def _source_id(conn: sqlite3.Connection, url: str) -> int | None:
    row = conn.execute(
        "SELECT id FROM source WHERE url=? OR source_url=? ORDER BY id LIMIT 1",
        (url, url),
    ).fetchone()
    return int(row["id"]) if row else None


def build_plan(conn: sqlite3.Connection) -> dict[str, Any]:
    blockers: list[str] = []
    warnings: list[str] = []
    industry_by_name = _rows_by_name(conn, "industry")

    old_cloud = industry_by_name.get("云服务器厂商")
    new_cloud = industry_by_name.get("云计算与算力运营")
    if old_cloud and new_cloud and int(old_cloud["id"]) != int(new_cloud["id"]):
        blockers.append("旧云服务器厂商与新云计算与算力运营同时存在且id不同，不能自动合并")
    cloud_row = new_cloud or old_cloud
    if not cloud_row:
        blockers.append("缺少兼容行业id=11对应的云服务器厂商节点")
    elif int(cloud_row["id"]) != 11:
        blockers.append(f"云节点id={cloud_row['id']}，预期兼容id=11")
    app_row = industry_by_name.get("AI应用")
    if not app_row or int(app_row["id"]) != 14:
        blockers.append("AI应用必须保留兼容industry_id=14")

    planned_industries: list[dict[str, Any]] = []
    available_names = set(industry_by_name)
    available_names.discard("云服务器厂商")
    available_names.add("云计算与算力运营")
    for spec in INDUSTRIES:
        if spec.parent and spec.parent not in available_names:
            blockers.append(f"新行业{spec.name}的父节点不存在：{spec.parent}")
        existing = industry_by_name.get(spec.name)
        planned_industries.append(
            {
                "name": spec.name,
                "parent": spec.parent,
                "action": "unchanged" if existing else "create",
                "existing_id": int(existing["id"]) if existing else None,
            }
        )
        available_names.add(spec.name)

    resolved_companies: dict[str, dict[str, Any]] = {}
    company_actions: list[dict[str, Any]] = []
    for spec in COMPANIES:
        row, errors = _resolve_company(conn, spec)
        blockers.extend(errors)
        if not row:
            continue
        resolved_companies[spec.name] = dict(row)
        for industry_name in filter(None, (spec.primary_industry, spec.also_parent)):
            ind = industry_by_name.get(industry_name)
            existing = None
            if ind:
                existing = conn.execute(
                    "SELECT id,role,note FROM company_industry WHERE company_id=? AND industry_id=?",
                    (int(row["id"]), int(ind["id"])),
                ).fetchone()
            company_actions.append(
                {
                    "company": spec.name,
                    "ticker": spec.ticker,
                    "resolved_company_id": int(row["id"]),
                    "industry": industry_name,
                    "action": "update" if existing else "create",
                    "role": spec.role if industry_name == spec.primary_industry else "AI应用核心候选",
                }
            )

    source_actions = [
        {
            "key": spec.key,
            "title": spec.title,
            "action": "unchanged" if _source_id(conn, spec.url) else "create",
        }
        for spec in SOURCES
    ]

    relation_actions: list[dict[str, Any]] = []
    for spec in RELATIONS:
        up = industry_by_name.get(spec.upstream)
        down = industry_by_name.get(spec.downstream)
        existing = None
        if up and down:
            existing = conn.execute(
                """SELECT id FROM industry_relation
                   WHERE upstream_id=? AND downstream_id=? AND relation_type=?""",
                (int(up["id"]), int(down["id"]), spec.relation_type),
            ).fetchone()
        relation_actions.append(
            {
                "upstream": spec.upstream,
                "downstream": spec.downstream,
                "relation_type": spec.relation_type,
                "source_key": spec.source_key,
                "action": "update" if existing else "create",
            }
        )

    # Preserve this explicit warning even after the company is onboarded: it
    # documents why this adapter never trusts the stale universe company_id.
    stale = conn.execute("SELECT name,ticker FROM company WHERE id=279").fetchone()
    if stale and (stale["name"] != "汇川技术" or str(stale["ticker"] or "").upper() != "300124.SZ"):
        warnings.append(
            "旧Run16 universe把汇川技术写为company_id=279；live id=279实际为"
            f"{stale['name']} {stale['ticker']}。本脚本已忽略旧id并按名称+ticker解析。"
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "research_as_of": RESEARCH_AS_OF,
        "mode": "dry_run",
        "database": str(Path(conn.execute("PRAGMA database_list").fetchone()["file"])),
        "compatibility": {
            "cloud_industry_id": int(cloud_row["id"]) if cloud_row else None,
            "cloud_current_name": str(cloud_row["name"]) if cloud_row else None,
            "cloud_target_name": "云计算与算力运营",
            "ai_application_industry_id": int(app_row["id"]) if app_row else None,
        },
        "counts": {
            "companies_expected": len(COMPANIES),
            "companies_resolved": len(resolved_companies),
            "industries": len(planned_industries),
            "company_memberships": len(company_actions),
            "sources": len(source_actions),
            "relations": len(relation_actions),
        },
        "industries": planned_industries,
        "company_memberships": company_actions,
        "sources": source_actions,
        "relations": relation_actions,
        "warnings": warnings,
        "blockers": list(dict.fromkeys(blockers)),
        "ready_to_apply": not blockers,
    }


def _ensure_source(conn: sqlite3.Connection, spec: SourceSpec) -> int:
    existing = _source_id(conn, spec.url)
    if existing is not None:
        return existing
    cursor = conn.execute(
        """INSERT INTO source(
               title,source_type,publisher,publish_date,quality_tier,
               is_forward_looking,url,note,value_layer,source_url,
               source_subtype,fetch_method,domain,language,is_primary_source,
               source_credibility,source_channel
           ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            spec.title, "website_material", spec.publisher, spec.publish_date, 1,
            0, spec.url, spec.note, "主题专项", spec.url, "官方网页",
            "web_fetch", spec.url.split("/", 3)[2],
            "zh" if spec.publisher in {"工业富联", "生益科技", "中恒电气"} else "en",
            1,
            "primary_confirmed", "web",
        ),
    )
    return int(cursor.lastrowid)


def _industry_id(conn: sqlite3.Connection, name: str) -> int:
    row = conn.execute("SELECT id FROM industry WHERE name=?", (name,)).fetchone()
    if not row:
        raise RuntimeError(f"行业未解析：{name}")
    return int(row["id"])


def _upsert_industries(conn: sqlite3.Connection) -> None:
    cloud = conn.execute(
        "SELECT id,name FROM industry WHERE id=11"
    ).fetchone()
    if not cloud or cloud["name"] not in ("云服务器厂商", "云计算与算力运营"):
        raise RuntimeError("兼容industry_id=11不是预期云节点")
    conn.execute(
        """UPDATE industry
              SET name='云计算与算力运营', tier=2, status='基础跟踪',
                  core_dynamic=?, last_updated=?
            WHERE id=11""",
        (
            "云端IaaS、GPU云与训练/推理服务必须同时检验利用率、单位成本、资本开支和自由现金流。",
            RESEARCH_AS_OF,
        ),
    )
    for spec in INDUSTRIES:
        parent_id = _industry_id(conn, spec.parent) if spec.parent else None
        existing = conn.execute(
            "SELECT id,parent_id FROM industry WHERE name=?", (spec.name,)
        ).fetchone()
        if existing and existing["parent_id"] != parent_id:
            raise RuntimeError(
                f"行业父级冲突：{spec.name} live_parent={existing['parent_id']} target={parent_id}"
            )
        conn.execute(
            """INSERT INTO industry(
                   name,parent_id,level,tier,status,core_dynamic,last_updated
               ) VALUES(?,?,?,?,?,?,?)
               ON CONFLICT(name) DO UPDATE SET
                   parent_id=excluded.parent_id,
                   level=excluded.level,
                   tier=excluded.tier,
                   status=excluded.status,
                   core_dynamic=excluded.core_dynamic,
                   last_updated=excluded.last_updated""",
            (
                spec.name, parent_id, spec.level, spec.tier, spec.status,
                spec.core_dynamic, RESEARCH_AS_OF,
            ),
        )


def _upsert_memberships(conn: sqlite3.Connection) -> None:
    for spec in COMPANIES:
        row, errors = _resolve_company(conn, spec)
        if errors or not row:
            raise RuntimeError("；".join(errors) or f"未解析公司：{spec.name}")
        targets = [(spec.primary_industry, spec.role, spec.note)]
        if spec.also_parent:
            targets.append(
                (
                    spec.also_parent,
                    "AI应用核心候选" if spec.also_parent == "AI应用" else spec.role,
                    f"{spec.primary_industry}细分归属；{spec.note}",
                )
            )
        for industry_name, role, note in targets:
            conn.execute(
                """INSERT INTO company_industry(company_id,industry_id,role,revenue_share,note)
                   VALUES(?,?,?,?,?)
                   ON CONFLICT(company_id,industry_id) DO UPDATE SET
                       role=excluded.role,
                       note=excluded.note""",
                (int(row["id"]), _industry_id(conn, industry_name), role, None, note),
            )


def _upsert_relations(
    conn: sqlite3.Connection, source_ids: dict[str, int]
) -> None:
    for spec in RELATIONS:
        conn.execute(
            """INSERT INTO industry_relation(
                   upstream_id,downstream_id,relation_type,source_id,note
               ) VALUES(?,?,?,?,?)
               ON CONFLICT(upstream_id,downstream_id,relation_type) DO UPDATE SET
                   source_id=excluded.source_id,
                   note=excluded.note""",
            (
                _industry_id(conn, spec.upstream),
                _industry_id(conn, spec.downstream),
                spec.relation_type,
                source_ids[spec.source_key],
                spec.note,
            ),
        )


def _verify(conn: sqlite3.Connection) -> dict[str, Any]:
    issues: list[str] = []
    integrity = str(conn.execute("PRAGMA integrity_check").fetchone()[0])
    fk = [tuple(row) for row in conn.execute("PRAGMA foreign_key_check")]
    cloud = conn.execute("SELECT id,name FROM industry WHERE id=11").fetchone()
    app = conn.execute("SELECT id,name FROM industry WHERE id=14").fetchone()
    if not cloud or cloud["name"] != "云计算与算力运营":
        issues.append("industry_id=11未保留为云计算与算力运营")
    if not app or app["name"] != "AI应用":
        issues.append("industry_id=14未保留为AI应用")
    expected_industries = {spec.name for spec in INDUSTRIES}
    found_industries = {
        row["name"]
        for row in conn.execute(
            f"SELECT name FROM industry WHERE name IN ({','.join('?' for _ in expected_industries)})",
            tuple(sorted(expected_industries)),
        )
    }
    missing_industries = sorted(expected_industries - found_industries)
    if missing_industries:
        issues.append(f"缺少行业节点：{missing_industries}")
    mapped_companies: list[str] = []
    for spec in COMPANIES:
        row, errors = _resolve_company(conn, spec)
        if errors or not row:
            issues.extend(errors or [f"未解析公司：{spec.name}"])
            continue
        ind_id = _industry_id(conn, spec.primary_industry)
        membership = conn.execute(
            "SELECT id FROM company_industry WHERE company_id=? AND industry_id=?",
            (int(row["id"]), ind_id),
        ).fetchone()
        if not membership:
            issues.append(f"公司主归属缺失：{spec.name} -> {spec.primary_industry}")
        else:
            mapped_companies.append(spec.name)
    if integrity != "ok":
        issues.append(f"integrity_check={integrity}")
    if fk:
        issues.append(f"foreign_key_check={fk[:5]}")
    return {
        "status": "GREEN" if not issues else "RED",
        "integrity_check": integrity,
        "foreign_key_issues": fk,
        "industry_id_11": dict(cloud) if cloud else None,
        "industry_id_14": dict(app) if app else None,
        "new_industries": len(found_industries),
        "mapped_companies": len(mapped_companies),
        "issues": issues,
    }


def apply_update(conn: sqlite3.Connection) -> dict[str, Any]:
    before = build_plan(conn)
    if before["blockers"]:
        raise RuntimeError("存在阻断项，未写库：" + "；".join(before["blockers"]))
    conn.execute("BEGIN IMMEDIATE")
    try:
        _upsert_industries(conn)
        source_ids = {spec.key: _ensure_source(conn, spec) for spec in SOURCES}
        _upsert_memberships(conn)
        _upsert_relations(conn, source_ids)
        verification = _verify(conn)
        if verification["status"] != "GREEN":
            raise RuntimeError("写入后验证失败：" + "；".join(verification["issues"]))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    after = build_plan(conn)
    after["mode"] = "apply"
    after["verification"] = verification
    after["ready_to_apply"] = not after["blockers"]
    return after


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run16 AI产业链与重点公司归属更新；默认只读dry-run。"
    )
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument(
        "--apply", action="store_true",
        help="显式写入research.db；缺少该参数时始终只读。",
    )
    parser.add_argument(
        "--json", action="store_true", help="仅输出JSON，便于自动化验收。"
    )
    parser.add_argument(
        "--output", type=Path,
        help="把完整JSON结果原子写入指定文件；不改变数据库写入模式。",
    )
    return parser


def _human_summary(result: dict[str, Any]) -> str:
    counts = result["counts"]
    lines = [
        f"模式：{'写入' if result['mode'] == 'apply' else '只读 dry-run'}",
        f"公司身份：{counts['companies_resolved']}/{counts['companies_expected']}",
        f"行业节点计划：{counts['industries']}；公司归属计划：{counts['company_memberships']}",
        f"来源计划：{counts['sources']}；关系计划：{counts['relations']}",
        f"兼容ID：云节点={result['compatibility']['cloud_industry_id']}，AI应用={result['compatibility']['ai_application_industry_id']}",
    ]
    if result["warnings"]:
        lines.append("警告：")
        lines.extend(f"- {item}" for item in result["warnings"])
    if result["blockers"]:
        lines.append("阻断项：")
        lines.extend(f"- {item}" for item in result["blockers"])
    else:
        lines.append("结果：身份与结构检查通过，可显式使用 --apply。")
    if result.get("verification"):
        lines.append(f"事务后验证：{result['verification']['status']}")
    return "\n".join(lines)


def main(argv: Iterable[str] | None = None) -> int:
    args = _parser().parse_args(list(argv) if argv is not None else None)
    if not args.db.is_file():
        raise FileNotFoundError(args.db)
    with closing(_connect(args.db, apply=args.apply)) as conn:
        result = apply_update(conn) if args.apply else build_plan(conn)
    serialized = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        output = args.output if args.output.is_absolute() else ROOT / args.output
        output.parent.mkdir(parents=True, exist_ok=True)
        temp = output.with_suffix(output.suffix + ".tmp")
        try:
            temp.write_text(serialized, encoding="utf-8")
            temp.replace(output)
        finally:
            temp.unlink(missing_ok=True)
    if args.json:
        print(serialized, end="")
    else:
        print(_human_summary(result))
    return 0 if not result["blockers"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
