from __future__ import annotations

import unittest
import sqlite3
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest import mock

from tools.viewer import app as viewer


class ViewerCompanyVisualsTest(unittest.TestCase):
    def test_valuation_scatter_supports_copper_group_colors_and_roa_axis(self) -> None:
        rows = [
            {
                "company_name": "矿山A",
                "ticker": "1.SH",
                "pb": 2.0,
                "roa": 8.0,
                "market_cap_cny": 100.0,
                "valuation_group_label": "资源矿山 · A股",
                "valuation_color": "#1d4ed8",
                "valuation_symbol": "circle",
            },
            {
                "company_name": "矿山H",
                "ticker": "2.HK",
                "pb": 1.5,
                "roa": 6.0,
                "market_cap_cny": 80.0,
                "valuation_group_label": "资源矿山 · 港股",
                "valuation_color": "#7db4f3",
                "valuation_symbol": "diamond",
            },
        ]
        figure = viewer._valuation_scatter(
            rows, "pb", "PB", ykey="roa", ylabel="ROA (%)"
        )
        self.assertIsNotNone(figure)
        assert figure is not None
        self.assertEqual(figure["layout"]["yaxis"]["title"], "ROA (%)")
        colors = {trace["name"]: trace["marker"]["color"] for trace in figure["data"]}
        self.assertEqual(colors["资源矿山 · A股"], "#1d4ed8")
        self.assertEqual(colors["资源矿山 · 港股"], "#7db4f3")

    def test_peer_product_layer_separates_value_chain_roles(self) -> None:
        self.assertEqual(
            viewer._peer_product_layer("800G/1.6T 光模块；自研光引擎与光芯片"),
            "整机/模块",
        )
        self.assertEqual(viewer._peer_product_layer("DFB/EML 激光器芯片"), "芯片/晶圆")
        self.assertEqual(viewer._peer_product_layer("光器件、光引擎与 FAU"), "器件/零部件")
        self.assertEqual(viewer._peer_product_layer("光通信测试仪器与检测设备"), "制造设备/仪器")
        self.assertIsNone(viewer._peer_product_layer(None))

    def test_peer_product_layer_keeps_pcb_company_out_of_gpu_or_module_layers(self) -> None:
        self.assertEqual(
            viewer._peer_product_layer("高阶HDI、HLC、GPU/OAM/UBB/交换机板、FPC"),
            "PCB/HDI制造",
        )
        self.assertEqual(
            viewer._peer_product_layer("FPC、SLP、IHDI、HLC、光模块与服务器PCB"),
            "PCB/HDI制造",
        )

    def test_peer_product_layer_keeps_battery_companies_together_before_materials(self) -> None:
        self.assertEqual(
            viewer._peer_product_layer("动力电池系统、储能电池系统、电池材料与回收"),
            "锂电池/电池系统",
        )
        self.assertEqual(
            viewer._peer_product_layer("新能源汽车、刀片电池、储能系统及电子部件"),
            "锂电池/电池系统",
        )

    def test_asset_return_peer_summary_uses_same_market_and_explains_premium(self) -> None:
        def row(cid, name, market, pb, roe, roa):
            return {
                "research_company_id": cid,
                "canonical_name": name,
                "market": market,
                "pb": {"value_num": pb},
                "roe": {"value_num": roe},
                "roa": {"value_num": roa},
            }

        summary = viewer._asset_return_peer_summary([
            row(1, "本公司", "A股", 8.0, 12.0, 6.0),
            row(2, "同行甲", "A股", 3.0, 13.0, 7.0),
            row(3, "同行乙", "A股", 4.0, 14.0, 8.0),
            row(4, "海外同行", "美股", 20.0, 30.0, 15.0),
        ], 1)
        self.assertIsNotNone(summary)
        assert summary is not None
        self.assertEqual(summary["scope"], "同市场同行")
        self.assertEqual(summary["peer_count"], 2)
        self.assertEqual(summary["medians"]["pb"], 3.5)
        self.assertIn("估值溢价明显高于资产回报优势", summary["text"])

    def test_asset_return_peer_candidates_require_same_product_layer(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "research.db"
            conn = sqlite3.connect(db_path)
            conn.executescript("""
                CREATE TABLE company(
                    id INTEGER PRIMARY KEY, name TEXT, ticker TEXT,
                    listing_status TEXT, brief_intro TEXT
                );
                CREATE TABLE company_industry(company_id INTEGER, industry_id INTEGER);
                CREATE TABLE company_profile(
                    id INTEGER PRIMARY KEY, company_id INTEGER, industry_id INTEGER,
                    main_products TEXT, brief_intro TEXT
                );
                INSERT INTO company VALUES
                    (1,'模块甲','1.SZ','a_share','光模块厂商'),
                    (2,'模块乙','2.SZ','a_share','光模块厂商'),
                    (3,'芯片丙','3.SZ','a_share','光芯片厂商'),
                    (4,'客户丁','4.US','us','云服务平台');
                INSERT INTO company_industry VALUES(1,9),(2,9),(3,9),(4,9);
                INSERT INTO company_profile VALUES
                    (1,1,9,'800G 光模块',NULL),
                    (2,2,9,'1.6T 光模块',NULL),
                    (3,3,9,'DFB 激光器芯片',NULL);
            """)
            conn.commit()
            conn.close()
            with mock.patch.object(viewer, "DB_PATH", db_path):
                ids, note = viewer._asset_return_peer_candidates(
                    1, 9, {"main_products": "800G 光模块"},
                )
        self.assertEqual(ids, [1, 2])
        self.assertIn("产品层级同为“整机/模块”", note)
        self.assertNotIn(3, ids)
        self.assertNotIn(4, ids)

    def test_q5_hero_reads_structured_conclusions_across_sections_without_truncation(self) -> None:
        raw = """
## 2. 主线一：竞争格局

**结论一：全部 PCB 专用设备市场仍较分散，但直接成像明显更集中。** 展开分析。

## 3. 主线二：行业空间

**结论一：全部 PCB 设备市场仍在增长，但不能把其总量改名为 18 层以上高多层市场。** 展开分析。

## 8. 反方情景：哪些情况会让市场空间和国产替代判断落空

第一，AI 服务器需求可能增长，但 PCB 厂可复用旧设备，新增设备强度低于预期。
"""
        hero = viewer.parse_q5_hero(raw)
        self.assertEqual(hero["conclusions"], [
            "全部 PCB 专用设备市场仍较分散，但直接成像明显更集中",
            "全部 PCB 设备市场仍在增长，但不能把其总量改名为 18 层以上高多层市场",
        ])
        self.assertFalse(any(item.endswith("第一") for item in hero["conclusions"]))
        self.assertFalse(any(item.startswith("反方情景") for item in hero["conclusions"]))

    def test_q5_hero_numbered_fallback_keeps_complete_sentence_not_bare_ordinal(self) -> None:
        raw = """
## 8. 反方情景：哪些情况会让市场空间和国产替代判断落空

第一，AI 服务器和交换机需求可能增长，但 PCB 厂通过提高既有设备稼动率、优化钻孔节拍、增加叠板数或复用旧设备满足需求，新增设备强度低于预期。
"""
        hero = viewer.parse_q5_hero(raw)
        self.assertEqual(len(hero["conclusions"]), 1)
        self.assertIn("新增设备强度低于预期", hero["conclusions"][0])
        self.assertFalse(hero["conclusions"][0].endswith("第一"))

    def test_q5_hero_reads_natural_language_chapter_overview(self) -> None:
        raw = """
## 本章综述

**资源政治不会立刻减少全球供给，而会先改变权益、成本和交付时间。** 项目只有穿过许可、融资和爬坡门槛才形成可售产品。投资判断应落到股东现金而不是名义资源量。

## 1. 问题
"""
        hero = viewer.parse_q5_hero(raw)
        self.assertTrue(hero["has_any"])
        self.assertIn("资源政治不会立刻减少全球供给", hero["core_judgment"])
        self.assertGreaterEqual(len(hero["conclusions"]), 2)
        self.assertTrue(any(
            "股东现金" in item for item in hero["conclusions"]
        ))

    def test_industry_companies_starts_from_membership_and_keeps_profileless_company(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "research.db"
            docs_path = Path(td) / "docs"
            (docs_path / "industries").mkdir(parents=True)
            (docs_path / "industries" / "测试行业_公司透视.md").write_text(
                "# 测试行业公司透视\n\n结构化卡片之外的竞争分析正文。",
                encoding="utf-8",
            )
            conn = sqlite3.connect(db_path)
            conn.executescript("""
                CREATE TABLE industry(id INTEGER PRIMARY KEY, name TEXT);
                CREATE TABLE company(
                    id INTEGER PRIMARY KEY, name TEXT, ticker TEXT, market TEXT,
                    listing_status TEXT, display_mode TEXT, note TEXT, created_at TEXT,
                    brief_intro TEXT, brief_intro_src TEXT,
                    pe_ttm REAL, pe_forward REAL, pb REAL, roe REAL, roa REAL,
                    eps_ttm REAL, bps_mrq REAL, per_share_currency TEXT,
                    financial_metrics_as_of TEXT, financial_metrics_source_id INTEGER,
                    market_cap_value REAL, market_cap_unit TEXT, market_cap_cny REAL,
                    market_cap_usd REAL, valuation_as_of TEXT, valuation_source_id INTEGER
                );
                CREATE TABLE company_industry(company_id INTEGER, industry_id INTEGER);
                CREATE TABLE company_profile(
                    id INTEGER PRIMARY KEY, company_id INTEGER, industry_id INTEGER,
                    global_rank INTEGER, china_rank INTEGER,
                    in_global_table INTEGER, in_china_table INTEGER,
                    is_china_tech_leader INTEGER, listing_status TEXT,
                    summary TEXT, created_at TEXT, last_verified_at TEXT, last_updated TEXT,
                    revenue_series TEXT, net_income_series TEXT, recent_events TEXT,
                    risks TEXT, source_ids TEXT, net_margin REAL,
                    brief_intro TEXT, brief_intro_src TEXT
                );
                CREATE TABLE company_sub_market_share(
                    id INTEGER PRIMARY KEY, company_id INTEGER, industry_id INTEGER,
                    geo TEXT, sub_market TEXT, rank INTEGER, share REAL,
                    source_ids TEXT, credibility TEXT
                );
                INSERT INTO industry VALUES(6, '测试行业');
                INSERT INTO company(
                    id,name,ticker,market,listing_status,display_mode,note,created_at,
                    brief_intro,brief_intro_src,pe_ttm,pb,per_share_currency
                ) VALUES
                    (101,'无画像公司','101.SZ','A股','a_share','full','公司说明',
                     '2026-01-01','公司级简介','official',-3.5,1.5,'CNY'),
                    (102,'有画像公司','102.SZ','A股','a_share','full',NULL,
                     '2026-01-02',NULL,NULL,12.0,2.0,'CNY');
                INSERT INTO company_industry VALUES(101,6),(102,6);
                INSERT INTO company_profile(
                    id,company_id,industry_id,in_global_table,summary,created_at
                ) VALUES
                    (1,102,6,0,'旧画像','2025-01-01'),
                    (2,102,6,1,'最新画像','2026-01-02');
            """)
            conn.commit()
            conn.close()

            with mock.patch.object(viewer, "DB_PATH", db_path), \
                 mock.patch.object(viewer, "DOCS_DIR", docs_path), \
                 mock.patch.object(viewer, "render_template", return_value="ok") as render:
                response = viewer.app.test_client().get("/industry/6/companies")

        self.assertEqual(response.status_code, 200)
        context = render.call_args.kwargs
        profiles = {row["company_id"]: row for row in context["profiles"]}
        self.assertEqual(set(profiles), {101, 102})
        self.assertEqual(profiles[101]["company_name"], "无画像公司")
        self.assertEqual(profiles[101]["summary"], "公司级简介")
        self.assertEqual(profiles[101]["brief_intro_src"], "official")
        self.assertEqual(profiles[101]["listing_status"], "a_share")
        self.assertEqual(profiles[101]["created_at"], "2026-01-01")
        self.assertFalse(profiles[101]["has_profile"])
        self.assertEqual(profiles[101]["fresh_general"]["color"], "gray")
        self.assertEqual(context["fresh_counts"]["gray"], 1)
        self.assertTrue(profiles[102]["has_profile"])
        self.assertEqual([row["company_id"] for row in context["global_tbl"]], [102])
        self.assertTrue(context["company_report"]["exists"])
        self.assertIn("结构化卡片之外的竞争分析正文", context["company_report"]["html"])
        self.assertEqual(context["china_tbl"], [])
        self.assertEqual(context["tech_tbl"], [])
        self.assertEqual(profiles[102]["summary"], "最新画像")
        self.assertEqual(profiles[101]["pe_ttm_display"], "亏损/PE不适用")
        pe_card = next(card for card in profiles[101]["core_metrics"] if card["key"] == "pe_ttm")
        self.assertIsNone(pe_card["display"])
        self.assertEqual(pe_card["reason"], "亏损/PE不适用")
        self.assertEqual(profiles[102]["pe_ttm_display"], "12.00×")

    def test_wrap_markdown_tables_for_scroll_wraps_each_table_independently(self) -> None:
        html = "<p>前文</p><table><tr><td>A</td></tr></table><table><tr><td>B</td></tr></table>"
        wrapped = viewer.wrap_markdown_tables_for_scroll(html)
        self.assertEqual(wrapped.count('class="md-table-wrap"'), 2)
        self.assertEqual(wrapped.count('tabindex="0"'), 2)
        self.assertIn("<table><tr><td>A</td></tr></table>", wrapped)

    def test_price_window_mapping_aligns_yahoo_lunch_bar_and_excludes_weekend(self) -> None:
        tz = timezone(timedelta(hours=8))
        self.assertEqual(
            viewer._window_id_for_price_ts(datetime(2026, 7, 15, 11, 30, tzinfo=tz)),
            "2026-07-15:morning",
        )
        self.assertEqual(
            viewer._window_id_for_price_ts(datetime(2026, 7, 15, 12, 30, tzinfo=tz)),
            "2026-07-15:afternoon",
        )
        self.assertIsNone(
            viewer._window_id_for_price_ts(datetime(2026, 7, 18, 12, 30, tzinfo=tz))
        )
        self.assertEqual(
            viewer._bucket_label(
                "2026-07-15:preopen", "2026-07-15T10:00:00+08:00"
            ),
            "07-15 盘前 10:00",
        )
        self.assertEqual(viewer._bucket_label("2026-07-15:morning"), "07-15 早盘 14:00")

    def test_six_metric_cards_keep_formula_currency_and_missing_state(self) -> None:
        company = {
            "ticker": "000001.SZ",
            "listing_status": "a_share",
            "pe_ttm": -2,
            "pb": 1.25,
            "roe": 12.345,
            "roa": None,
            "eps_ttm": 1.8,
            "bps_mrq": 9.5,
            "per_share_currency": "CNY",
            "market_cap_unit": "亿元人民币",
            "valuation_as_of": "2026-07-14",
            "financial_metrics_as_of": "2026-03-31",
            "valuation_source_id": 1,
            "financial_metrics_source_id": 2,
        }
        cards = viewer._company_metric_cards(company)
        self.assertEqual(len(cards), 6)
        by_key = {card["key"]: card for card in cards}
        self.assertEqual(by_key["pe_ttm"]["reason"], "亏损/PE不适用")
        self.assertEqual(by_key["pb"]["formula"], "市净率 = 股价 / 每股净资产")
        self.assertEqual(by_key["eps_ttm"]["display"], "1.80 CNY/股")
        self.assertNotIn("亿元人民币/股", by_key["bps_mrq"]["display"])
        self.assertEqual(by_key["roa"]["reason"], "尚未建立结构化财务画像")

        pe_omitted_for_loss = viewer._company_metric_cards({
            **company, "pe_ttm": None, "eps_ttm": -0.25,
        })
        loss_by_key = {card["key"]: card for card in pe_omitted_for_loss}
        self.assertEqual(loss_by_key["pe_ttm"]["reason"], "亏损/PE不适用")

        pe_malformed = viewer._company_metric_cards({
            **company, "pe_ttm": "not-a-number", "eps_ttm": 1.0,
        })
        malformed_by_key = {card["key"]: card for card in pe_malformed}
        self.assertEqual(
            malformed_by_key["pe_ttm"]["reason"],
            "尚未建立结构化财务画像",
        )

        bundle_missing_field = viewer._company_metric_cards(
            company,
            financial_bundle={"current_metrics": {}},
        )
        bundle_by_key = {card["key"]: card for card in bundle_missing_field}
        self.assertEqual(
            bundle_by_key["roa"]["reason"],
            "当前结构化数据源未返回该字段",
        )

    def test_company_entry_and_search_use_canonical_company_links(self) -> None:
        rows = [{
            "id": 7, "name": "测试股份", "ticker": "000007.SZ", "market": "A股",
            "listing_status": "a_share", "brief_intro": "测试公司",
            "market_cap_cny": 100.0, "pe_ttm": 12.0, "pb": 1.4,
            "roe": 11.0, "roa": 5.0, "valuation_as_of": "2026-07-22",
            "financial_metrics_as_of": "2026-03-31", "industries": "测试行业",
        }]
        with mock.patch.object(viewer, "_company_search_rows", return_value=rows), \
             mock.patch.object(viewer, "query_all", return_value=[{"market": "A股"}]), \
             mock.patch.object(viewer, "render_template", return_value="ok") as render:
            response = viewer.app.test_client().get("/companies?q=000007")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(render.call_args.kwargs["companies"][0]["id"], 7)

        with mock.patch.object(viewer, "_company_search_rows", return_value=rows):
            payload = viewer.app.test_client().get("/api/companies/search?q=测试").get_json()
        self.assertEqual(payload["results"][0]["url"], "/company/7")
        self.assertEqual(payload["results"][0]["ticker"], "000007.SZ")

    def test_company_index_uses_financial_db_metrics_and_profile_intro(self) -> None:
        rows = [{
            "id": 640, "name": "赣锋锂业", "ticker": "002460.SZ",
            "market": "A股", "listing_status": "listed",
            "brief_intro": "全球资源与锂盐一体化；一级市场估值待 web_fetch(未审计)",
            "pe_ttm": None, "pb": None, "roe": None, "roa": None,
            "valuation_as_of": None, "financial_metrics_as_of": None,
            "industries": "锂,碳酸锂",
        }]
        bundle = {
            640: {
                "security": {"ticker": "002460.SZ"},
                "current_metrics": {
                    "pe_ttm": {
                        "value_num": 27.0096, "provider_label": "Wind",
                        "as_of_date": "2026-07-24",
                    },
                    "pb": {
                        "value_num": 2.2278, "provider_label": "Wind",
                        "as_of_date": "2026-07-24",
                    },
                    "roe": {
                        "value_num": 8.1924, "provider_label": "Wind",
                        "as_of_date": "2026-07-24",
                    },
                    "roa": {
                        "value_num": 4.3563, "provider_label": "Wind",
                        "as_of_date": "2026-07-24",
                    },
                },
            }
        }
        with mock.patch.object(
            viewer, "financial_company_current_metrics_batch",
            return_value=bundle,
        ):
            result = viewer._prepare_company_index_rows(rows)
        self.assertEqual(result[0]["metric_displays"]["pe_ttm"], "27.01×")
        self.assertEqual(result[0]["metric_displays"]["pb"], "2.23×")
        self.assertEqual(result[0]["metric_displays"]["roe"], "8.19%")
        self.assertEqual(result[0]["financial_provider_label"], "Wind")
        self.assertEqual(result[0]["financial_snapshot_as_of"], "2026-07-24")
        self.assertNotIn("web_fetch", result[0]["brief_intro"])
        self.assertIn("公开资料待补充", result[0]["brief_intro"])

    def test_pb_roe_and_pb_roa_figures_fit_independent_periods_and_future_path(self) -> None:
        bundle = {
            "asset_return": {
                "current": {
                    "pb": {"value_num": 1.8},
                    "roe": {"value_num": 13.0},
                    "roa": {"value_num": 6.5},
                },
                "pb_roe_points": [
                    {"period": "2023", "return_value": 10.0, "pb": 1.2, "return_as_of": "2023-12-31", "pb_as_of": "2024-04-30"},
                    {"period": "2024", "return_value": 12.0, "pb": 1.5, "return_as_of": "2024-12-31", "pb_as_of": "2025-04-30"},
                    {"period": "2025", "return_value": 14.0, "pb": 1.9, "return_as_of": "2025-12-31", "pb_as_of": "2026-04-30"},
                ],
                "pb_roa_points": [
                    {"period": "2023", "return_value": 5.0, "pb": 1.2, "return_as_of": "2023-12-31", "pb_as_of": "2024-04-30"},
                    {"period": "2024", "return_value": 6.0, "pb": 1.5, "return_as_of": "2024-12-31", "pb_as_of": "2025-04-30"},
                    {"period": "2025", "return_value": 7.0, "pb": 1.9, "return_as_of": "2025-12-31", "pb_as_of": "2026-04-30"},
                ],
                "pb_history": [
                    {"as_of_date": "2025-01-31", "value_num": 1.2},
                    {"as_of_date": "2025-02-28", "value_num": 1.4},
                    {"as_of_date": "2025-03-31", "value_num": 1.8},
                ],
                "pb_band": {"q20": 1.25, "median": 1.5, "q80": 1.75},
                "pb_price_band": {
                    "rows": [
                        {"date": "2025-01-31", "close": 10.0, "q20_price": 8.0, "median_price": 10.0, "q80_price": 12.0},
                        {"date": "2025-02-28", "close": 11.0, "q20_price": 8.5, "median_price": 10.5, "q80_price": 12.5},
                    ],
                },
                "pe_price_band": {
                    "rows": [
                        {"date": "2025-01-31", "close": 10.0, "q20_price": 7.0, "median_price": 10.0, "q80_price": 13.0},
                        {"date": "2025-02-28", "close": 11.0, "q20_price": 7.5, "median_price": 10.5, "q80_price": 13.5},
                    ],
                },
                "roe_history": [
                    {"fiscal_year": 2024, "value_num": 12.0},
                    {"fiscal_year": 2025, "value_num": 14.0},
                ],
            },
            "forecast_table": [
                {"horizon": "FY1", "internal": {"roe": {"value": 14.5, "fiscal_year": 2026}, "roa": {"value": 7.2}}},
                {"horizon": "FY2", "internal": {"roe": {"value": 15.0, "fiscal_year": 2027}, "roa": {"value": 7.4}}},
                {"horizon": "FY3", "internal": {"roe": {"value": 15.2, "fiscal_year": 2028}, "roa": {"value": 7.5}}},
            ],
        }
        figures = viewer._asset_return_figures(bundle)
        self.assertEqual(figures["pb_roe_model"]["sample_size"], 3)
        self.assertEqual(figures["pb_roa_model"]["sample_size"], 3)
        self.assertIn("roa_coefficient", figures["pb_roa_model"])
        self.assertIn("current_residual", figures["pb_roe_model"])
        self.assertEqual(figures["pb_roe_model"]["response_transform"], "ln(pb)")
        self.assertIn("内部预测路径", {trace.get("name") for trace in figures["pb_roe"]["data"]})
        self.assertIn("历史残差描述带", {trace.get("name") for trace in figures["pb_roa"]["data"]})
        fitted = next(trace for trace in figures["pb_roe"]["data"] if trace.get("name") == "历史经验映射")
        self.assertTrue(all(value > 0 for value in fitted["y"]))
        self.assertEqual(figures["pb_history"]["layout"]["xaxis"]["type"], "date")
        self.assertEqual(figures["roe_path"]["layout"]["xaxis"]["type"], "category")
        self.assertIn("历史中位", {trace.get("name") for trace in figures["pb_history"]["data"]})
        self.assertEqual(figures["pb_price_band"]["layout"]["xaxis"]["title"]["text"], "交易日期")
        self.assertEqual(figures["pb_price_band"]["layout"]["yaxis"]["title"]["text"], "股价（元/股）")
        self.assertEqual(figures["pe_price_band"]["layout"]["xaxis"]["showline"], True)
        self.assertEqual(figures["pb_roe"]["layout"]["yaxis"]["title"]["text"], "市净率 PB（倍）")

    def test_pcb_metric_cards_do_not_fallback_financial_source_and_explain_bps_holdback(self) -> None:
        company = {
            "ticker": "688630.SH",
            "listing_status": "a_share",
            "pe_ttm": 20.0,
            "pb": 3.0,
            "roe": 12.0,
            "roa": 6.0,
            "eps_ttm": 1.0,
            "bps_mrq": None,
            "per_share_currency": "CNY",
            "valuation_as_of": "2026-07-17",
            "financial_metrics_as_of": "2026-03-31",
            "valuation_source_id": 1,
            "financial_metrics_source_id": None,
        }
        cards = viewer._company_metric_cards(
            company,
            {"display_note": "BPS与交易日PB的股本口径对账未通过，暂不展示BPS。"},
            strict_financial_source=True,
        )
        by_key = {card["key"]: card for card in cards}
        self.assertIsNone(by_key["pb"]["source_id"])
        self.assertIsNone(by_key["pb"]["display"])
        self.assertIsNone(by_key["roe"]["source_id"])
        self.assertEqual(by_key["bps_mrq"]["reason"], "股本口径对账未通过，暂不展示")

    def test_pcb_financial_rows_align_by_metric_period_and_keep_status(self) -> None:
        revenue = [
            {"period": "2025", "metric_period": "2025", "value": 12},
            {"period": "2024", "metric_period": "2024", "value": 10},
        ]
        net_income = [
            {"period": "2024", "metric_period": "2024", "value": -1, "change_status": "转亏"},
            {"period": "2026财年第三季度", "metric_period": "2026Q1", "value": 2, "change_status": "扭亏"},
        ]
        rows = viewer._aligned_company_financial_rows(revenue, net_income)
        by_key = {row["key"]: row for row in rows}
        self.assertEqual(by_key["2024"]["revenue"]["value"], 10)
        self.assertEqual(by_key["2024"]["net_income"]["change_status"], "转亏")
        self.assertIsNone(by_key["2025"]["net_income"])
        self.assertEqual(by_key["2026Q1"]["period"], "2026财年第三季度")
        self.assertEqual(by_key["2026Q1"]["net_income"]["change_status"], "扭亏")

    def test_company_financial_figure_uses_stable_unit_in_cross_period_legend(self) -> None:
        revenue = [
            {"period": "2023", "value": 9.61, "cny_yi": 9.61,
             "unit": "亿元人民币（约1.42亿美元）", "original_display": "1.24亿EUR"},
            {"period": "2024", "value": 9.50, "cny_yi": 9.50,
             "unit": "亿元人民币（约1.40亿美元）", "original_display": "1.23亿EUR"},
        ]
        net_income = [
            {"period": "2023", "value": 0.14, "cny_yi": 0.14,
             "unit": "亿元人民币（约0.02亿美元）", "original_display": "0.02亿EUR"},
            {"period": "2024", "value": -0.10, "cny_yi": -0.10,
             "unit": "亿元人民币（约-0.01亿美元）", "original_display": "-0.01亿EUR"},
        ]
        figure = viewer._company_financial_figure(revenue, net_income)
        self.assertIsNotNone(figure)
        traces = {trace["name"]: trace for trace in figure["data"]}
        self.assertEqual(set(traces), {"营收（亿元人民币）", "净利润（亿元人民币）"})
        self.assertNotIn("1.42", str(figure["layout"]))
        self.assertEqual(figure["layout"]["yaxis"]["title"], "营收（亿元人民币）")
        self.assertIn("原报表口径：1.24亿EUR", traces["营收（亿元人民币）"]["customdata"][0])

    def test_pcb_public_text_hides_production_notes_and_keeps_real_actions(self) -> None:
        events = [
            {
                "date": "2026-07-19", "title": "官方资料核验：产品页",
                "summary": "本轮以公司官网发布的官方资料核验主体身份。", "source_id": 1,
            },
            {
                "date": "2025-04-17", "title": "AMADA收购Via Mechanics",
                "summary": "本轮以AMADA发布的官方资料核验主体身份。", "source_id": 2,
            },
            {
                "date": "2026-06-01", "title": "新产线投产",
                "summary": "新产线进入量产。", "source_id": 3,
            },
        ]
        public = viewer._pcb_public_recent_events(events)
        self.assertEqual([row["title"] for row in public], ["AMADA收购Via Mechanics", "新产线投产"])
        self.assertEqual(public[0]["summary"], "")
        self.assertNotIn("官方资料核验", str(public))

        note = viewer._pcb_public_profile_note(
            "当前完整覆盖4/4期。当前BPS与交易日PB的股本口径未完成对账，故暂不展示BPS。"
        )
        self.assertEqual(note, "当前BPS与交易日PB的股本口径未完成对账，故暂不展示BPS。")
        self.assertNotIn("完整覆盖", note)

    def test_pcb_public_coverage_note_is_natural_and_suppresses_complete_state(self) -> None:
        def row(period):
            return {"period": period, "metric_period": period, "value": 1}

        complete = {
            "ticker": "1.SZ", "listing_status": "a_share", "financials_as_of": "2026-03-31",
            "revenue_series_list": [row(p) for p in ("2023", "2024", "2025", "2026Q1")],
            "net_income_series_list": [row(p) for p in ("2023", "2024", "2025", "2026Q1")],
        }
        self.assertIsNone(viewer._pcb_public_coverage_note(complete))
        missing = {**complete, "net_income_series_list": [row("2023"), row("2024")]}
        note = viewer._pcb_public_coverage_note(missing)
        self.assertIn("公开接口未返回2025年、2026年一季度可比损益", note)
        self.assertIn("缺失期间不参与增长比较", note)
        for production_term in ("财务覆盖", "目标公司卡要求", "完整覆盖", "本轮页面"):
            self.assertNotIn(production_term, note)

    def test_integrated_panel_has_only_retail_price_volume_and_hideable_ma(self) -> None:
        cats = [f"2026-07-{day:02d}:morning" for day in range(6, 12)]
        price = {key: {"o": 10, "h": 11, "l": 9, "c": 10.5} for key in cats}
        senti = {key: index / 10 for index, key in enumerate(cats)}
        volume = {key: 10 + index for index, key in enumerate(cats)}
        fig = viewer._panel_fig(
            cats, price, senti, volume,
            draft_map={cats[-1]: {
                "status": "低样本", "source_note": "低样本",
                "sentiment_draft": True, "volume_draft": False,
            }},
        )
        self.assertIsNotNone(fig)
        names = [trace["name"] for trace in fig["data"]]
        self.assertEqual(names, ["股价", "散户净情绪", "散户情绪 MA5", "发帖量", "发帖量 MA5"])
        self.assertNotIn("新闻情绪", " ".join(names))
        ma = {trace["name"]: trace for trace in fig["data"] if "MA5" in trace["name"]}
        self.assertTrue(all(trace["visible"] == "legendonly" for trace in ma.values()))
        self.assertEqual(fig["data"][0]["x"][-1], "07-11 早盘 14:00")
        self.assertEqual(fig["layout"]["xaxis"]["tickvals"][-1], "07-11 早盘 14:00")
        traces = {trace["name"]: trace for trace in fig["data"]}
        self.assertEqual(traces["散户净情绪"]["y"][-1], 0.5)
        self.assertEqual(traces["散户净情绪"]["marker"]["symbol"][-1], "circle-open")
        self.assertEqual(traces["散户净情绪"]["customdata"][-1], "低样本")

    def test_missing_volume_is_not_fabricated_and_no_price_reflows_axes(self) -> None:
        cats = ["2026-07-15:preopen", "2026-07-15:morning"]
        fig = viewer._panel_fig(cats, {}, {cats[0]: 0.2}, {cats[0]: 0}, freq="window")
        traces = {trace["name"]: trace for trace in fig["data"]}
        self.assertEqual(traces["发帖量"]["y"], [0, None])
        self.assertEqual(traces["发帖量 MA5"]["y"], [None, None])
        self.assertEqual(traces["散户情绪 MA5"]["y"], [None, None])
        self.assertNotIn("股价", traces)
        self.assertFalse(fig["layout"]["yaxis"]["visible"])
        self.assertEqual(fig["layout"]["yaxis2"]["domain"], [0.45, 1.0])
        self.assertEqual(fig["layout"]["yaxis3"]["domain"], [0.0, 0.39])
        self.assertEqual(fig["layout"]["yaxis3"]["rangemode"], "tozero")

    def test_partial_v2_appends_to_legacy_instead_of_blanketing_history(self) -> None:
        legacy_window = {
            "bucket_id": "2026-07-14T14:00", "bucket_start": "2026-07-14T14:00:00+08:00",
            "valid_count": 8, "layer_total": 10, "net_sentiment_weighted": 0.4,
            "net_sentiment_plain": 0.3, "net_sentiment": 0.3, "coverage": 0.8,
            "usable": 1, "n_guba": 10,
        }
        v2_window = {
            "window_id": "2026-07-15:preopen", "session_date": "2026-07-15",
            "slot": "preopen", "scheduled_for": "2026-07-15T10:00:00+08:00",
            "window_status": "running", "scored_count": 6, "raw_count": 20,
            "net_weighted": 0.2, "net_plain": 0.1, "coverage": 0.3, "usable": 0,
            "n_guba": 20,
        }
        legacy_daily = {
            "trade_date": "2026-07-14", "valid_count": 8, "net_sentiment_weighted": 0.4,
            "net_sentiment_plain": 0.3, "net_sentiment": 0.3,
        }

        def fake_all(sql, _params=()):
            if "FROM senti_retail_window w" in sql:
                return [dict(v2_window)]
            if "FROM retail_window_ledger" in sql:
                return [{"window_id": v2_window["window_id"],
                         "scheduled_for": v2_window["scheduled_for"], "status": "running"}]
            if "FROM senti_retail_bucket" in sql:
                return [dict(legacy_window)]
            if "FROM heat_volume_bucket" in sql:
                return [{"bucket_id": legacy_window["bucket_id"],
                         "bucket_start": legacy_window["bucket_start"], "retail_count": 10}]
            if "FROM senti_retail_trading_daily" in sql:
                return []
            if "FROM senti_retail_daily" in sql:
                return [dict(legacy_daily)]
            if "FROM heat_volume_daily" in sql:
                return [{"trade_date": "2026-07-14", "retail_count": 10}]
            if "FROM stock_kline" in sql:
                return []
            raise AssertionError(sql)

        with mock.patch.object(viewer, "_senti_table_exists", return_value=True), \
             mock.patch.object(viewer, "senti_all", side_effect=fake_all), \
             mock.patch.object(viewer, "_price_3h", return_value={}), \
             mock.patch.object(viewer, "_price_windows", return_value={
                 "2026-07-15:morning": {"o": 10, "h": 11, "l": 9, "c": 10.5}
             }):
            rows = viewer._company_retail_summary_rows(1)
            panels = viewer._company_panels(1)

        self.assertEqual([row["mode"] for row in rows], ["legacy", "v2"])
        self.assertFalse(rows[-1]["display_ready"])
        self.assertEqual(panels["data_mode"], "hybrid")
        window_traces = {trace["name"]: trace for trace in panels["retail_window"]["data"]}
        self.assertEqual(
            list(window_traces),
            ["散户净情绪", "散户情绪 MA5", "发帖量", "发帖量 MA5"],
        )
        self.assertEqual(window_traces["散户净情绪"]["y"], [0.4, 0.2])
        self.assertEqual(window_traces["散户净情绪"]["marker"]["symbol"],
                         ["circle", "circle-open"])
        self.assertEqual(window_traces["散户净情绪"]["customdata"][-1], "评分进行中")
        self.assertEqual(window_traces["发帖量"]["y"], [10, 20])
        self.assertEqual(window_traces["发帖量"]["marker"]["color"][-1],
                         "rgba(251,191,36,.45)")
        self.assertIsNone(window_traces["散户情绪 MA5"]["y"][0])
        self.assertAlmostEqual(window_traces["散户情绪 MA5"]["y"][1], 0.3)
        self.assertEqual(window_traces["发帖量 MA5"]["y"], [None, 15.0])
        self.assertNotIn("股价", window_traces)
        self.assertEqual(window_traces["散户净情绪"]["x"][-1], "07-15 盘前 10:00")
        daily_traces = {trace["name"]: trace for trace in panels["retail_d"]["data"]}
        self.assertEqual(daily_traces["散户净情绪"]["y"], [0.4])

    def test_partial_auxiliary_source_does_not_downgrade_completed_retail_score(self) -> None:
        v2_window = {
            "window_id": "2026-07-15:preopen", "session_date": "2026-07-15",
            "slot": "preopen", "scheduled_for": "2026-07-15T10:00:00+08:00",
            "window_status": "partial", "scored_count": 8, "raw_count": 10,
            "net_weighted": 0.25, "net_plain": 0.2, "coverage": 0.8,
            "significant": 1, "usable": 0,
            "source_status_json": '{"guba":"complete","score":"complete",'
                                  '"kline":"failed","xinghan":"failed"}',
        }

        def fake_all(sql, _params=()):
            if "FROM senti_retail_window w" in sql:
                return [dict(v2_window)]
            if "FROM retail_window_ledger" in sql:
                return [{"window_id": v2_window["window_id"],
                         "scheduled_for": v2_window["scheduled_for"], "status": "partial"}]
            if "FROM stock_kline" in sql:
                return []
            if any(name in sql for name in (
                "senti_retail_bucket", "heat_volume_bucket", "senti_retail_daily",
                "heat_volume_daily", "senti_retail_trading_daily",
            )):
                return []
            raise AssertionError(sql)

        with mock.patch.object(viewer, "_senti_table_exists", return_value=True), \
             mock.patch.object(viewer, "senti_all", side_effect=fake_all), \
             mock.patch.object(viewer, "_price_3h", return_value={}), \
             mock.patch.object(viewer, "_price_windows", return_value={
                 "2026-07-15:morning": {"o": 10, "h": 11, "l": 9, "c": 10.5}
             }):
            rows = viewer._company_retail_summary_rows(1)
            panels = viewer._company_panels(1)

        self.assertTrue(rows[-1]["display_ready"])
        self.assertTrue(rows[-1]["score_complete"])
        self.assertTrue(rows[-1]["significant"])
        self.assertFalse(rows[-1]["usable"])
        self.assertIs(viewer._latest_retail_summary_row(rows), rows[-1])
        traces = {trace["name"]: trace for trace in panels["retail_window"]["data"]}
        self.assertEqual(traces["散户净情绪"]["y"], [0.25])
        self.assertNotIn("散户净情绪（未完成/低样本）", traces)
        self.assertEqual(traces["发帖量"]["y"], [10])
        self.assertNotIn("发帖量（未完成草稿）", traces)
        self.assertEqual(
            traces["散户净情绪"]["customdata"],
            ["舆情附加源补抓中；股吧与评分已完成"],
        )
        # 尚未实际启动的 morning 价格不得提前制造未来 14:00 类别。
        self.assertEqual(traces["散户净情绪"]["x"], ["07-15 盘前 10:00"])

    def test_completed_low_sample_score_is_not_labeled_incomplete(self) -> None:
        v2_window = {
            "window_id": "2026-07-15:morning", "session_date": "2026-07-15",
            "slot": "morning", "scheduled_for": "2026-07-15T14:00:00+08:00",
            "window_status": "partial", "scored_count": 4, "raw_count": 5,
            "net_weighted": -0.2, "net_plain": -0.25, "coverage": 0.8,
            "significant": 0, "usable": 0,
            "source_status_json": '{"guba":"complete","score":"complete",'
                                  '"xinghan":"failed"}',
        }

        def fake_all(sql, _params=()):
            return [dict(v2_window)] if "FROM senti_retail_window w" in sql else []

        with mock.patch.object(viewer, "_senti_table_exists", return_value=True), \
             mock.patch.object(viewer, "senti_all", side_effect=fake_all):
            rows = viewer._company_retail_summary_rows(1)

        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["score_complete"])
        self.assertFalse(rows[0]["significant"])
        self.assertFalse(rows[0]["display_ready"])
        latest = viewer._latest_retail_summary_row(rows)
        quality_label = (
            None if latest.get("display_ready")
            else ("低样本" if latest.get("score_complete") else "评分进行中")
        )
        self.assertEqual(quality_label, "低样本")

    def test_sentiment_home_uses_scored_v2_window_without_strict_daily_row(self) -> None:
        window = {
            "company_id": 101, "ticker": "000101.SZ",
            "window_id": "2026-07-15:preopen", "session_date": "2026-07-15",
            "slot": "preopen", "scheduled_for": "2026-07-15T10:00:00+08:00",
            "window_status": "partial", "raw_count": 10, "scored_count": 8,
            "net_weighted": 0.25, "net_plain": 0.2, "coverage": 0.8,
            "significant": 1, "usable": 0,
            "source_status_json": '{"guba":"complete","score":"complete",'
                                  '"kline":"failed","xinghan":"failed"}',
        }

        def fake_all(sql, _params=()):
            if "SELECT id,name,ticker FROM research.company" in sql:
                return [{"id": 101, "name": "窗口评分公司", "ticker": "000101.SZ"}]
            if "SELECT id,name,ticker FROM senti_company" in sql:
                return []
            if "FROM company_id_redirect" in sql:
                return []
            if "FROM senti_retail_window w JOIN retail_window_ledger" in sql:
                return [dict(window)]
            if "FROM research.company_industry" in sql:
                return [{"company_id": 101, "ind_id": 6, "ind_name": "测试产业",
                         "role": "主营"}]
            if any(name in sql for name in (
                "heat_volume_bucket", "senti_retail_daily", "heat_volume_daily",
                "senti_retail_trading_daily",
            )):
                return []
            raise AssertionError(sql)

        with mock.patch.object(viewer, "_senti_table_exists", return_value=True), \
             mock.patch.object(viewer, "senti_all", side_effect=fake_all), \
             mock.patch.object(viewer, "render_template", return_value="ok") as render:
            response = viewer.app.test_client().get("/dynamic/sentiment")

        self.assertEqual(response.status_code, 200)
        context = render.call_args.kwargs
        self.assertEqual(context["kpi"]["covered"], 1)
        self.assertEqual(context["kpi"]["with_score"], 1)
        self.assertEqual(context["kpi"]["significant"], 1)
        row = context["rows"][0]
        self.assertEqual(row["company_name"], "窗口评分公司")
        self.assertEqual(row["net_sentiment_weighted"], 0.25)
        self.assertEqual(row["valid_count"], 8)
        self.assertEqual(row["heat_total"], 10)
        self.assertTrue(row["display_ready"])
        self.assertFalse(row["usable"])
        self.assertEqual(row["score_mode"], "v2_window")
        self.assertEqual(row["score_date"], "2026-07-15 盘前 10:00")
        self.assertEqual(row["score_badge"], "窗口评分完成 · 附加源补抓中")

    def test_sentiment_home_marks_scored_but_low_sample_window(self) -> None:
        window = {
            "company_id": 102, "ticker": "000102.SZ",
            "window_id": "2026-07-15:morning", "session_date": "2026-07-15",
            "slot": "morning", "scheduled_for": "2026-07-15T14:00:00+08:00",
            "window_status": "complete", "raw_count": 3, "scored_count": 2,
            "net_weighted": -0.4, "net_plain": -0.5, "coverage": 2 / 3,
            "significant": 0, "usable": 0,
            "source_status_json": '{"guba":"complete","score":"complete"}',
        }
        incomplete_daily = {
            "company_id": 102, "session_date": "2026-07-15", "complete": 0,
            "raw_count": 3, "scored_count": 2, "net_weighted": -0.4,
            "net_plain": -0.5, "coverage": 2 / 3, "significant": 0, "usable": 0,
        }

        def fake_all(sql, _params=()):
            if "SELECT id,name,ticker FROM research.company" in sql:
                return [{"id": 102, "name": "低样本公司", "ticker": "000102.SZ"}]
            if "SELECT id,name,ticker FROM senti_company" in sql:
                return []
            if "FROM company_id_redirect" in sql:
                return []
            if "FROM senti_retail_window w JOIN retail_window_ledger" in sql:
                return [dict(window)]
            if "FROM senti_retail_trading_daily" in sql:
                return [dict(incomplete_daily)]
            if "FROM research.company_industry" in sql:
                return []
            if any(name in sql for name in (
                "heat_volume_bucket", "senti_retail_daily", "heat_volume_daily",
            )):
                return []
            raise AssertionError(sql)

        with mock.patch.object(viewer, "_senti_table_exists", return_value=True), \
             mock.patch.object(viewer, "senti_all", side_effect=fake_all), \
             mock.patch.object(viewer, "render_template", return_value="ok") as render:
            response = viewer.app.test_client().get("/dynamic/sentiment")

        self.assertEqual(response.status_code, 200)
        context = render.call_args.kwargs
        self.assertEqual(context["kpi"]["significant"], 0)
        self.assertEqual(context["kpi"]["with_score"], 1)
        row = context["rows"][0]
        self.assertFalse(row["display_ready"])
        self.assertEqual(row["net_sentiment_weighted"], -0.4)
        self.assertEqual(row["score_badge"], "低样本窗口")
        self.assertEqual(row["score_mode"], "v2_window")

    def test_valuation_visuals_have_comparable_fallbacks(self) -> None:
        rows = [
            {"company_name": "甲", "ticker": "1.SZ", "market": "A股", "pe_ttm": 10, "pb": 2, "roe": 12, "roa": 5, "market_cap_cny": 100, "valuation_as_of": "2026-07-14"},
            {"company_name": "乙", "ticker": "2.SZ", "market": "A股", "pe_ttm": 20, "pb": 3, "roe": 18, "roa": 7, "market_cap_cny": 200, "valuation_as_of": "2026-07-14"},
        ]
        self.assertIsNotNone(viewer._valuation_scatter(rows, "pe_ttm", "PE (TTM)"))
        self.assertIsNotNone(viewer._valuation_scatter(rows, "pb", "PB"))
        self.assertIsNotNone(viewer._valuation_heatmap(rows))

    def test_valuation_route_ranks_eps_bps_only_within_currency_groups(self) -> None:
        base = {
            "industry_id": 6, "listing_status": "a_share", "market": "A股",
            "pe_ttm": 10.0, "pe_forward": None, "pb": 2.0, "ps_ttm": None,
            "ev_ebitda": None, "peg": None, "roe": 12.0, "roa": 5.0,
            "gross_margin": None, "net_margin": 8.0,
            "financial_metrics_as_of": "2026-03-31", "financials_as_of": None,
            "financial_metrics_source_id": 2, "valuation_source_id": 1,
            "market_cap_value": None, "market_cap_unit": None,
            "market_cap_cny": 100.0, "market_cap_usd": 14.0,
            "valuation_as_of": "2026-07-14",
            "forecast_eps_year1": None, "forecast_eps_year2": None,
            "forecast_revenue_year1": None, "forecast_revenue_year2": None,
            "forecast_revenue_unit": None, "forecast_as_of_date": None,
            "forecast_source_id": None, "profile_source_ids": None,
            "private_valuation_value": None, "private_valuation_unit": None,
            "private_round": None, "private_valuation_as_of": None,
        }
        fixtures = [
            {**base, "company_id": 1, "company_name": "人民币高值", "ticker": "1.SZ",
             "eps_ttm": 2.0, "bps_mrq": 20.0, "per_share_currency": "CNY"},
            {**base, "company_id": 2, "company_name": "人民币低值", "ticker": "2.SZ",
             "eps_ttm": 1.0, "bps_mrq": 10.0, "per_share_currency": "CNY"},
            {**base, "company_id": 3, "company_name": "美元公司", "ticker": "US",
             "market": "美股", "listing_status": "us", "eps_ttm": 100.0,
             "bps_mrq": 500.0, "per_share_currency": "USD"},
            {**base, "company_id": 4, "company_name": "港元公司", "ticker": "00004.HK",
             "market": "港股", "listing_status": "hk", "pe_ttm": -9.0, "pb": None,
             "eps_ttm": 50.0, "bps_mrq": 300.0, "per_share_currency": "HKD"},
        ]
        def fake_query_all(sql, _params=()):
            return fixtures if "FROM company_industry ci" in sql else []

        with mock.patch.object(viewer, "query_one", return_value={"id": 6, "name": "测试行业", "tier": 1}), \
             mock.patch.object(viewer, "query_all", side_effect=fake_query_all), \
             mock.patch.object(viewer, "render_template", wraps=viewer.render_template) as render:
            response = viewer.app.test_client().get("/industry/6/valuation")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("同币种组内排序", html)
        self.assertIn("禁止跨币种比较", html)
        self.assertIn("组内序号", html)
        self.assertIn('class="cp-table-scroll val-table-scroll"', html)
        self.assertIn('role="region"', html)
        self.assertIn("可横向滚动", html)
        self.assertIn('class="val-heatmap-scroll"', html)
        self.assertIn('class="val-viz val-heatmap-canvas"', html)
        context = render.call_args.kwargs
        metric_tables = {table["key"]: table for table in context["metric_tables"]}
        for key in ("eps_ttm", "bps_mrq"):
            table = metric_tables[key]
            self.assertTrue(table["grouped_per_share"])
            by_name = {row["name"]: row for row in table["rows"]}
            self.assertEqual(by_name["人民币高值"]["rank"], 1)
            self.assertEqual(by_name["人民币低值"]["rank"], 2)
            self.assertEqual(by_name["美元公司"]["rank"], 1)
            self.assertEqual(by_name["港元公司"]["rank"], 1)
            self.assertEqual(
                {row["comparison_group"] for row in table["rows"]},
                {"CNY", "USD", "HKD"},
            )
        pe_rows = {row["name"] for row in metric_tables["pe_ttm"]["rows"]}
        self.assertNotIn("港元公司", pe_rows)
        self.assertEqual(context["coverage"]["with_valuation"], 3)
        self.assertEqual(context["coverage"]["with_six"], 3)
        loss_card = next(card for card in context["company_cards"] if card["name"] == "港元公司")
        loss_pe = next(metric for metric in loss_card["metrics"] if metric["key"] == "pe_ttm")
        self.assertEqual(loss_pe["display"], "亏损/PE不适用")
        self.assertFalse(loss_pe["has"])

    def test_heatmap_uses_average_rank_for_tied_values(self) -> None:
        rows = [
            {"company_name": name, "pe_ttm": 10, "pb": pb, "roe": 10 + pb, "roa": 5}
            for name, pb in (("甲", 1), ("乙", 2), ("丙", 3))
        ]
        fig = viewer._valuation_heatmap(rows)
        self.assertEqual([row[0] for row in fig["data"][0]["z"]], [50, 50, 50])

    def test_heatmap_supports_pcb_red_palette_without_changing_default(self) -> None:
        rows = [
            {"company_name": name, "pe_ttm": pe, "pb": pb, "roe": 10, "roa": 5}
            for name, pe, pb in (("甲", 10, 1), ("乙", 20, 2), ("丙", 30, 3))
        ]
        default_fig = viewer._valuation_heatmap(rows)
        pcb_fig = viewer._valuation_heatmap(
            rows,
            colorscale=viewer.PCB_VALUATION_HEATMAP_COLORSCALE,
        )
        self.assertEqual(
            default_fig["data"][0]["colorscale"],
            [[0, "#e8f3fb"], [.5, "#7ab5d8"], [1, "#164e78"]],
        )
        self.assertEqual(
            pcb_fig["data"][0]["colorscale"],
            [[0, "#fff1f2"], [.5, "#fca5a5"], [1, "#ef4444"]],
        )

    def test_heatmap_percentile_uses_all_eligible_peers_before_display_cap(self) -> None:
        rows = [
            {
                "company_name": f"公司{i:02d}", "market_cap_cny": 1000 - i,
                "pe_ttm": i + 2, "pb": 2, "roe": 10, "roa": 5,
            }
            for i in range(38)
        ]
        # 两家不会进入 36 家展示区，但仍必须进入同行总体；其中 PE=1 会让
        # 第一家展示公司的 PE 从截断总体的 0 分位变为完整总体的第 1/37 分位。
        rows[-2]["pe_ttm"] = 1
        rows[-1]["pe_ttm"] = 1000
        fig = viewer._valuation_heatmap(rows)
        heatmap = fig["data"][0]
        self.assertEqual(len(heatmap["y"]), 36)
        self.assertAlmostEqual(heatmap["z"][0][0], 100 / 37, places=6)

    def test_heatmap_column_pool_includes_peer_with_only_that_metric(self) -> None:
        rows = [
            {"company_name": "甲", "market_cap_cny": 30, "pe_ttm": 10, "pb": 1},
            {"company_name": "乙", "market_cap_cny": 20, "pe_ttm": 20, "pb": 2},
            {"company_name": "丙", "market_cap_cny": 10, "pe_ttm": 30, "pb": 3},
            # 不满足展示所需的两项指标，但它仍是 PE 分位的有效同行观测。
            {"company_name": "单指标同行", "market_cap_cny": 1, "pe_ttm": 5},
        ]
        fig = viewer._valuation_heatmap(rows)
        heatmap = fig["data"][0]
        self.assertNotIn("单指标同行", heatmap["y"])
        self.assertAlmostEqual(heatmap["z"][0][0], 100 / 3, places=6)

    def test_scatter_uses_true_even_median(self) -> None:
        rows = [
            {"company_name": str(i), "market": "A股", "pe_ttm": x, "roe": y}
            for i, (x, y) in enumerate(((1, 10), (2, 20), (100, 30), (200, 100)))
        ]
        fig = viewer._valuation_scatter(rows, "pe_ttm", "PE")
        shapes = fig["layout"]["shapes"]
        self.assertEqual(shapes[0]["x0"], 51)
        self.assertEqual(shapes[1]["y0"], 25)

    def test_scatter_extreme_roe_has_robust_default_and_full_range_toggle(self) -> None:
        rows = [
            {
                "company_name": f"公司{i}", "ticker": f"{i}.SZ", "market": "A股",
                "pe_ttm": 10 + i, "roe": y, "market_cap_cny": 100 - i,
                "valuation_as_of": "2026-07-14",
            }
            for i, y in enumerate((10, 12, 14, 16, 18, 1787.97))
        ]
        fig = viewer._valuation_scatter(rows, "pe_ttm", "PE")
        self.assertLess(fig["layout"]["yaxis"]["range"][1], 1787.97)
        self.assertIn(1787.97, fig["data"][0]["y"])
        overflow = next(trace for trace in fig["data"] if trace["name"] == "默认范围外（高）")
        self.assertEqual(overflow["customdata"][0][1], 1787.97)
        buttons = fig["layout"]["updatemenus"][0]["buttons"]
        self.assertEqual([button["label"] for button in buttons], ["稳健范围", "完整范围"])
        self.assertGreater(buttons[1]["args"][1]["yaxis.range"][1], 1787.97)
        self.assertFalse(buttons[1]["args"][0]["visible"][-1])

    def test_keyword_sentiment_routes_are_absent(self) -> None:
        rules = {rule.rule for rule in viewer.app.url_map.iter_rules()}
        self.assertNotIn("/dynamic/keyword", rules)
        self.assertFalse(any(rule.startswith("/dynamic/keyword/") for rule in rules))

    def test_retired_hbm_topic_route_and_sentiment_tab_are_absent(self) -> None:
        rules = {rule.rule for rule in viewer.app.url_map.iter_rules()}
        self.assertNotIn("/dynamic/topic/<topic_id>", rules)
        client = viewer.app.test_client()
        self.assertEqual(client.get("/dynamic/topic/hbm-inflection").status_code, 404)
        response = client.get("/dynamic/sentiment")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertNotIn("HBM/存储 供给拐点", html)
        self.assertNotIn("/dynamic/topic/", html)

    def test_plotly_is_vendored_for_intranet_rendering(self) -> None:
        viewer_root = Path(viewer.__file__).resolve().parent
        asset = viewer_root / "static" / "vendor" / "plotly.min.js"
        self.assertTrue(asset.is_file())
        self.assertGreater(asset.stat().st_size, 4_000_000)
        for template in (viewer_root / "templates").glob("*.html"):
            text = template.read_text(encoding="utf-8")
            if "Plotly" not in text and "plotly" not in text.lower():
                continue
            self.assertNotIn("cdn.plot.ly", text, template.name)
            self.assertNotIn("plotly.js-dist", text, template.name)


if __name__ == "__main__":
    unittest.main()
