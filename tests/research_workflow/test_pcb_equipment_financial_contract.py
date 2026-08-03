import json
import sqlite3

from tools.pipeline.apply_pcb_equipment_research import (
    _official_profile_event,
    _profile_display_note,
    _profile_financial_context,
    _profile_source_keys,
    _series,
    ensure_sub_market_shares,
)
from tools.pipeline.collect_pcb_equipment_financials import (
    normalize_snapshot_payload,
)
from tools.pipeline.prepare_pcb_equipment_research import financial_claims
from tools.pipeline.pcb_equipment_research_data import (
    COMPANY_EVENT_SOURCE_KEYS,
    COMPANY_IDENTITIES,
    SOURCES,
)


def _amount(local_yi, cny_yi=None, usd_yi=None):
    return {
        "local_yi": local_yi,
        "cny_yi": local_yi if cny_yi is None else cny_yi,
        "usd_yi": usd_yi,
    }


def _legacy_company(*, key="zhengye", name="正业科技", market="A股", currency="CNY"):
    return {
        "key": key,
        "name": name,
        "ticker": "300410.SZ" if market == "A股" else "TEST",
        "market": market,
        "scope": "测试口径",
        "market_snapshot": {"source": "tushare" if market == "A股" else "yfinance"},
        "financial_series": {
            "source": "tushare" if market == "A股" else "yfinance",
            "currency": currency,
            "fx_to_cny": 1.0 if currency == "CNY" else 7.0,
            "fx_as_of": "2026-07-19",
            "periods": [
                {
                    "period": "2024",
                    "end_date": "20241231",
                    "statement_basis": "fiscal_year",
                    "source": "provider statement",
                    "currency": currency,
                    "revenue": _amount(10.0, 70.0 if currency != "CNY" else 10.0, 10.0 if currency != "CNY" else 1.43),
                    "net_income": _amount(-1.0, -7.0 if currency != "CNY" else -1.0, -1.0 if currency != "CNY" else -0.14),
                    "gross_margin": 35.0,
                    "net_margin": -8.0,
                    "net_income_yoy": -150.0,
                    "operating_cash_flow": _amount(1.2, 8.4 if currency != "CNY" else 1.2, 1.2 if currency != "CNY" else 0.17),
                    "rd_expense": _amount(0.8, 5.6 if currency != "CNY" else 0.8, 0.8 if currency != "CNY" else 0.11),
                    "rd_ratio": 8.0,
                    "capex": _amount(0.5, 3.5 if currency != "CNY" else 0.5, 0.5 if currency != "CNY" else 0.07),
                },
                {
                    "period": "2025",
                    "end_date": "20251231",
                    "statement_basis": "fiscal_year",
                    "source": "provider statement",
                    "currency": currency,
                    "revenue": _amount(12.0, 84.0 if currency != "CNY" else 12.0, 12.0 if currency != "CNY" else 1.71),
                    "net_income": _amount(1.2, 8.4 if currency != "CNY" else 1.2, 1.2 if currency != "CNY" else 0.17),
                    "gross_margin": 36.0,
                    "net_margin": 15.0,
                    "net_income_yoy": -220.0,
                    "operating_cash_flow": _amount(1.4, 9.8 if currency != "CNY" else 1.4, 1.4 if currency != "CNY" else 0.20),
                    "rd_expense": _amount(0.9, 6.3 if currency != "CNY" else 0.9, 0.9 if currency != "CNY" else 0.13),
                    "rd_ratio": 7.5,
                    "capex": _amount(0.6, 4.2 if currency != "CNY" else 0.6, 0.6 if currency != "CNY" else 0.09),
                },
            ],
            "coverage": {},
        },
    }


def _normalize_company(company):
    payload = normalize_snapshot_payload(
        {
            "schema_version": "pcb_equipment.company_financial_snapshot.v1",
            "companies": [company],
        }
    )
    return payload["companies"][0]


def test_frozen_snapshot_preserves_provider_yoy_but_generator_outputs_state_only():
    company = _normalize_company(_legacy_company())
    row = next(
        item
        for item in company["financial_series"]["periods"]
        if item["period"] == "2025"
    )
    meta = row["net_income_yoy_meta"]
    assert meta["provider_original_value_pct"] == -220.0
    assert meta["provider_original_is_comparison_input"] is False
    assert meta["state"] == "turnaround"
    assert row["net_income_yoy"] is None

    claims = financial_claims({"companies": [company]})
    matches = [
        claim
        for claim in claims
        if claim["metric"] == "正业科技净利润同比变化"
        and claim["period"] == "2025"
    ]
    assert len(matches) == 1
    assert matches[0]["value_num"] is None
    assert matches[0]["value_text"] == "扭亏"
    assert "provider原始同比=-220.0%" in matches[0]["note"]
    assert "绝不作为增长率" in matches[0]["note"]


def test_net_margin_is_rebuilt_and_gross_margin_keeps_period_basis():
    company = _normalize_company(_legacy_company())
    row = next(
        item
        for item in company["financial_series"]["periods"]
        if item["period"] == "2025"
    )
    assert row["provider_net_margin_original_pct"] == 15.0
    assert row["net_margin"] == 10.0
    assert "净利润÷营业收入" in row["net_margin_meta"]["formula"]
    assert row["net_margin_meta"]["period"] == "2025"
    assert row["gross_margin"] == 36.0
    assert row["gross_margin_meta"]["period"] == "2025"
    assert "grossprofit_margin" in row["gross_margin_meta"]["basis"]


def test_overseas_series_exposes_local_cny_and_usd_views():
    company = _normalize_company(
        _legacy_company(key="mks", name="MKS Instruments", market="美股", currency="USD")
    )
    encoded = _series(company, "revenue", 814)
    rows = json.loads(encoded)
    latest = next(row for row in rows if row["period"] == "2025")
    assert latest["local_currency"] == "USD"
    assert latest["local_yi"] == 12.0
    assert latest["cny_yi"] == 84.0
    assert latest["usd_yi"] == 12.0
    assert latest["original_display"] == "12.0亿USD"


def test_profile_context_uses_metric_period_not_market_or_quote_date():
    company = _normalize_company(_legacy_company())
    company["market_snapshot"]["financial_metrics_as_of"] = "2026-03-31"
    context = _profile_financial_context(company)
    assert context["metric_period"] == "2025"
    assert context["metric_end_date"] == "2025-12-31"
    assert context["financials_as_of"] == "2025-12-31"
    assert "缺少2023、2026Q1" in context["coverage_note"]


def test_kla_csun_and_ta_liang_have_company_specific_coverage_notes():
    examples = {
        "kla": ("KLA", "FY2026Q3"),
        "csun": ("志圣工业", "2025全年"),
        "ta_liang": ("大量科技", "2026Q1"),
    }
    for key, (name, expected) in examples.items():
        company = _legacy_company(key=key, name=name, market="其他", currency="USD")
        normalized = _normalize_company(company)
        note = normalized["financial_series"]["coverage"]["company_note"]
        assert expected in note


def test_only_real_dated_company_actions_enter_recent_events_and_amada_uses_acquisition_source():
    source_ids = {spec.key: index for index, spec in enumerate(SOURCES, start=1)}
    for item in COMPANY_IDENTITIES:
        events = _official_profile_event(item, _profile_source_keys(item), source_ids)
        if item["name"] not in COMPANY_EVENT_SOURCE_KEYS:
            assert events == []
            continue
        assert len(events) == 1
        assert events[0]["source_id"]
        assert events[0]["date"] != "未标明"
        assert "官方资料核验" not in events[0]["title"]
        assert "官方资料核验" not in events[0]["summary"]

    amada = next(item for item in COMPANY_IDENTITIES if item["name"] == "AMADA")
    assert _profile_source_keys(amada)[0] == "amada_via"
    event = _official_profile_event(amada, _profile_source_keys(amada), source_ids)[0]
    assert event["source_id"] == source_ids["amada_via"]
    assert event["date"] == "2025-04-17"


def test_profile_display_note_is_conditioned_by_entity_type():
    context = {
        "metric_period": "2025",
        "metric_end_date": "2025-12-31",
        "latest_displayed_series_date": "2026-03-31",
        "coverage_note": "覆盖2023年至2026年一季度。",
    }
    market = {"trade_date": "2026-07-17"}
    a_share = _profile_display_note(
        {"group": "独立上市", "market": "A股"}, "listed", market, context
    )
    overseas = _profile_display_note(
        {"group": "海外上市", "market": "美股"}, "listed", market, context
    )
    private = _profile_display_note(
        {"group": "德国私营主体", "market": "其他"}, "private", {}, context
    )
    brand = _profile_display_note(
        {"group": "集团品牌", "market": "其他"}, "subsidiary_or_brand", {}, context
    )
    assert "A股2026年一季度损益为年初至期末累计口径" in a_share
    assert "海外上市公司的损益" not in a_share
    assert "海外上市公司的损益和资产负债数据按该公司自身财年" in overseas
    assert "A股2026年一季度" not in overseas
    assert "私营主体没有可核验的独立公开财务" in private
    assert "归属母公司或集团" in brand
    assert "净利率" not in private
    assert "净利率" not in brand


def test_strict_sub_market_share_rows_and_profile_fields_are_synchronized():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE company_profile(
          company_id INTEGER, industry_id INTEGER,
          global_share REAL, global_share_as_of TEXT, global_rank INTEGER,
          china_share REAL, china_share_as_of TEXT, china_rank INTEGER,
          global_share_sub_market TEXT, china_share_sub_market TEXT,
          is_china_tech_leader INTEGER, in_global_table INTEGER, in_china_table INTEGER
        );
        CREATE TABLE company_sub_market_share(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          company_id INTEGER, industry_id INTEGER, sub_market TEXT, geo TEXT,
          share REAL, share_as_of TEXT, rank INTEGER, source_ids TEXT,
          source_excerpt_ref TEXT, credibility TEXT, display_note TEXT
        );
        """
    )
    conn.executemany(
        "INSERT INTO company_profile(company_id,industry_id) VALUES(?,23)",
        [(1,), (2,)],
    )
    ensure_sub_market_shares(
        conn,
        23,
        {"大族数控": 1, "芯碁微装": 2},
        {"hans_h": 701, "cfmee_h": 702},
    )
    shares = conn.execute(
        """
        SELECT company_id,sub_market,geo,share,share_as_of,rank,source_ids
        FROM company_sub_market_share ORDER BY company_id,geo
        """
    ).fetchall()
    assert len(shares) == 3
    assert {
        (row["company_id"], row["sub_market"], row["geo"], row["share"], row["share_as_of"], row["rank"])
        for row in shares
    } == {
        (1, "全部PCB专用设备", "中国", 10.1, "2024", 1),
        (1, "全部PCB专用设备", "全球", 6.5, "2024", 1),
        (2, "PCB直接成像设备", "全球", 18.8, "2025", None),
    }
    profiles = {
        row["company_id"]: row
        for row in conn.execute("SELECT * FROM company_profile")
    }
    assert profiles[1]["global_share"] == 6.5
    assert profiles[1]["china_share"] == 10.1
    assert profiles[1]["global_share_sub_market"] == "全部PCB专用设备"
    assert profiles[2]["global_share"] == 18.8
    assert profiles[2]["global_rank"] is None
    assert profiles[2]["global_share_sub_market"] == "PCB直接成像设备"
