from __future__ import annotations

from pathlib import Path
import json
import re

from flask import g

from tools.opportunity_lens.db import connect, table_counts

from helpers import FixtureDBTestCase, make_test_app


ROOT = Path(__file__).resolve().parents[2]


class ViewerSmokeTests(FixtureDBTestCase):
    def setUp(self):
        super().setUp()
        self.app = make_test_app(self.db_path, self.export_root)
        self.client = self.app.test_client()

    def test_read_only_pages_get_200(self):
        conn = connect(self.db_path)
        factor_id = conn.execute("SELECT id FROM opportunity_factor_score ORDER BY id LIMIT 1").fetchone()["id"]
        slot_id = conn.execute("SELECT id FROM opportunity_metric_slot ORDER BY id LIMIT 1").fetchone()["id"]
        target_id = conn.execute("SELECT id FROM opportunity_entity_investment_target ORDER BY id LIMIT 1").fetchone()["id"]
        conn.close()
        for path in [
            "/opportunity-lens",
            "/opportunity-lens/run/1",
            "/opportunity-lens/run/1/entities",
            "/opportunity-lens/entity/1",
            f"/opportunity-lens/target/{target_id}",
            f"/opportunity-lens/factor/{factor_id}",
            f"/opportunity-lens/metric-slot/{slot_id}",
            "/opportunity-lens/run/1/audit",
            "/opportunity-lens/run/1/supplement",
            "/opportunity-lens/run/1/export",
        ]:
            with self.subTest(path=path):
                res = self.client.get(path)
                self.assertEqual(res.status_code, 200)
                self.assertIn(b"opp-page", res.data)

    def test_run_scoped_entity_name_link_resolves_to_numeric_detail(self):
        conn = connect(self.db_path)
        entity = conn.execute(
            """
            SELECT e.id, e.display_name
            FROM opportunity_entity_maturation em
            JOIN opportunity_entity e ON e.id=em.entity_id
            WHERE em.run_id=1
            ORDER BY e.id
            LIMIT 1
            """
        ).fetchone()
        conn.close()

        response = self.client.get(
            f"/opportunity-lens/run/1/entity-name/{entity['display_name']}",
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith(f"/opportunity-lens/entity/{entity['id']}"))

    def test_legacy_pack_keeps_historical_pages_and_routes(self):
        conn = connect(self.db_path)
        conn.execute(
            "UPDATE opportunity_run_manifest SET pack_schema_version=? WHERE run_id=1",
            ("opportunity_lens.run_pack.legacy",),
        )
        factor_id = conn.execute(
            "SELECT id FROM opportunity_factor_score WHERE run_id=1 ORDER BY id LIMIT 1"
        ).fetchone()["id"]
        slot_id = conn.execute(
            "SELECT id FROM opportunity_metric_slot WHERE run_id=1 ORDER BY id LIMIT 1"
        ).fetchone()["id"]
        conn.commit()
        conn.close()

        run_html = self.client.get("/opportunity-lens/run/1").get_data(as_text=True)
        self.assertEqual(len(re.findall(r'class="opp-kpi(?:\s[^\"]*)?"', run_html)), 4)
        self.assertIn("观点数据总览", run_html)
        self.assertIn("opp-insight-panel", run_html)
        self.assertIn("机会线索不改变核心 14 因子评分", run_html)
        for path in (
            f"/opportunity-lens/factor/{factor_id}",
            f"/opportunity-lens/metric-slot/{slot_id}",
            "/opportunity-lens/run/1/audit",
            "/opportunity-lens/run/1/supplement",
            "/opportunity-lens/run/1/export",
        ):
            with self.subTest(path=path):
                response = self.client.get(path, follow_redirects=False)
                self.assertEqual(response.status_code, 200)
                self.assertIsNone(response.headers.get("Location"))

    def test_get_smoke_has_no_db_side_effects(self):
        before = self.counts()
        self.client.get("/opportunity-lens/run/1")
        self.client.get("/api/opportunity-lens/run/1/visuals")
        self.client.get("/api/opportunity-lens/export/1/status")
        after = self.counts()
        self.assertEqual(before, after)

    def test_index_template_keeps_the_open_column_and_labels_it_for_readers(self):
        template = (
            ROOT / "tools" / "viewer" / "templates" / "opportunity_lens" / "index.html"
        ).read_text(encoding="utf-8")
        self.assertIn("<th>操作</th>", template)
        self.assertIn('aria-label="机会透镜研究列表，可横向查看"', template)
        self.assertIn("<td><a href=\"/opportunity-lens/run/{{ run.id }}\">打开</a></td>", template)

    def test_index_keeps_historical_runs_visible(self):
        html = self.client.get("/opportunity-lens").get_data(as_text=True)
        # 历史研究必须继续可见，不能因新 run 的发布筛选而从入口消失。
        self.assertNotIn("还没有可展示的机会透镜研究", html)
        self.assertIn("合成 HBM 载板供需失衡扫描", html)
        self.assertIn('<td><a href="/opportunity-lens/run/1">打开</a></td>', html)

    def test_run_page_restores_shared_shell_without_repeating_entity_bodies(self):
        res = self.client.get("/opportunity-lens/run/1")
        html = res.get_data(as_text=True)
        self.assertIn("<h1>仅用于机会透镜验证的合成 fixture。</h1>", html)
        self.assertIn("这是合成示例，不是真实完整扫描结果", html)
        self.assertIn("研究报告", html)
        self.assertIn("研究概览", html)
        self.assertIn("研究对象", html)
        self.assertEqual(len(re.findall(r'class="opp-kpi(?:\s[^"]*)?"', html)), 4)
        self.assertIn("研究对象评分与验证优先级", html)
        template = (
            ROOT
            / "tools"
            / "viewer"
            / "templates"
            / "opportunity_lens"
            / "run_v2.html"
        ).read_text(encoding="utf-8")
        self.assertIn("不重复粘贴专题全文", template)
        self.assertIn("opp-entity-report-link", template)
        self.assertNotIn("查看完整研究问题与验收要求", html)
        self.assertNotIn("opp-intake-question-body", html)
        self.assertNotIn("机会线索不改变核心 14 因子评分", html)
        self.assertNotIn("opp-heat-code", html)
        self.assertIn("--score:", html)

    def test_v2_run_moves_entity_profiles_before_report_and_removes_duplicate_object_table(self):
        template = (
            ROOT
            / "tools"
            / "viewer"
            / "templates"
            / "opportunity_lens"
            / "run_v2.html"
        ).read_text(encoding="utf-8")
        profile_panel = template.index("{% for section in entity_profile_sections %}")
        report_panel = template.index('id="opp-research-report"')
        self.assertLess(profile_panel, report_panel)
        self.assertIn("{% for section in report_sections %}", template)
        self.assertNotIn("<h2>研究对象</h2>", template)
        self.assertNotIn('_entity_table_v2.html', template)

    def test_v2_entity_renders_public_section_once_and_keeps_profile_internal(self):
        template = (
            ROOT
            / "tools"
            / "viewer"
            / "templates"
            / "opportunity_lens"
            / "entity_v2.html"
        ).read_text(encoding="utf-8")
        self.assertIn("{% for section in entity.sections %}", template)
        self.assertNotIn("entity.research_profile", template)
        self.assertNotIn("limitations_markdown", template)

    def test_v2_run_does_not_rank_or_chart_unrated_entities(self):
        conn = connect(self.db_path)
        conn.execute(
            "UPDATE opportunity_composite_score "
            "SET score_status='insufficient_evidence', "
            "rating_status='unrated_insufficient_evidence', "
            "score_quality_label='unrated_insufficient_evidence' "
            "WHERE run_id=1"
        )
        conn.execute(
            "UPDATE opportunity_run_stats SET scored_entity_count=0 WHERE run_id=1"
        )
        slot_id = conn.execute(
            "SELECT id FROM opportunity_metric_slot WHERE run_id=1 ORDER BY id LIMIT 1"
        ).fetchone()["id"]
        conn.execute(
            "UPDATE opportunity_metric_slot SET slot_label=?, value_status='not_found_after_search', "
            "slot_score=NULL WHERE id=?",
            ("三个月价格变化", slot_id),
        )
        conn.commit()
        conn.close()

        html = self.client.get("/opportunity-lens/run/1").get_data(as_text=True)
        self.assertIn("证据不足，暂不评级", html)
        self.assertIn("当前主要缺少可直接复算的", html)
        self.assertIn("三个月价格变化", html)
        self.assertIn("只限制机会评分，不代表整份研究报告没有证据", html)
        self.assertIn("不会用向中性收敛后的数值冒充正式排名", html)
        self.assertNotIn("当前评分最高的研究对象", html)
        self.assertNotIn("研究对象评分与验证优先级", html)
        self.assertNotIn("风险与关注度评分", html)
        self.assertNotIn("个实体已评分", html)

    def test_opportunity_markdown_renders_tables_and_evidence_refs(self):
        renderer = self.app.jinja_env.filters["opp_markdown"]
        html = str(
            renderer(
                "| 排名 | 对象 | 证据 |\n"
                "|---:|---|---|\n"
                "| 1 | 高阶硅片 | 价格上涨 10%-25% ^evidence:ab://research.data_point/11115 |\n"
            )
        )
        self.assertIn("<table", html)
        self.assertIn("opp-src-ref", html)
        self.assertIn('data-opp-evidence="ab://research.data_point/11115"', html)
        self.assertIn("[11115]", html)
        self.assertNotIn("| 排名 |", html)
        monitor_html = str(
            renderer(
                "| 优先级 | 监控信号 | 证实/证伪条件 | 预计变化/监控时间 | 研究响应 | 交易操作框架 | 证据 |\n"
                "|---|---|---|---|---|---|---|\n"
                "| 高 | EIA 周报发布 | 库存下降证实 | 2026-07-08 | 复核库存 | 观察月差 | ^evidence:opp://source/1 |\n"
            )
        )
        self.assertIn("opp-monitor-table", monitor_html)
        self.assertLess(monitor_html.index("预计变化/监控时间"), monitor_html.index("证实/证伪条件"))
        self.assertIn("事件/监控信号", monitor_html)
        chained_html = str(renderer("资金流和持仓相互验证 ^src:1^src:2"))
        self.assertIn('data-opp-evidence="opp://source/1"', chained_html)
        self.assertIn('data-opp-evidence="opp://source/2"', chained_html)
        self.assertNotIn('data-opp-evidence="1^src:2"', chained_html)
        self.assertNotIn('data-opp-evidence="opp://source/1^src:2"', chained_html)
        source_ref_html = str(
            renderer("来源列 `source_ref:semi_2025_annual` ^evidence:source_ref:semi_2025_annual")
        )
        self.assertIn('data-opp-evidence="source_ref:semi_2025_annual"', source_ref_html)
        self.assertNotIn("<code>source_ref:semi_2025_annual</code>", source_ref_html)
        self.assertIn("来源", source_ref_html)
        inline_renderer = self.app.jinja_env.filters["opp_inline_evidence"]
        inline_html = str(inline_renderer("source tier ^src:1 and `opp://source/2` <script>x</script>"))
        self.assertIn('data-opp-evidence="opp://source/1"', inline_html)
        self.assertIn('data-opp-evidence="opp://source/2"', inline_html)
        self.assertIn("&lt;script&gt;x&lt;/script&gt;", inline_html)
        self.assertNotIn("`opp://source/2`", inline_html)
        inline_source_ref_html = str(
            inline_renderer("`source_ref:semi_2025_annual` ^evidence:source_ref:semi_2025_annual")
        )
        self.assertIn('data-opp-evidence="source_ref:semi_2025_annual"', inline_source_ref_html)
        self.assertNotIn("`source_ref:semi_2025_annual`", inline_source_ref_html)
        label_renderer = self.app.jinja_env.filters["opp_label"]
        self.assertEqual(label_renderer("high_priority_for_followup"), "高优先级跟进")
        self.assertEqual(label_renderer("etf_valuation"), "ETF 估值拥挤证据")

    def test_opportunity_lens_static_guards_katex_and_wide_tables(self):
        base_html = (ROOT / "tools" / "viewer" / "templates" / "base.html").read_text(encoding="utf-8")
        lens_js = (ROOT / "tools" / "viewer" / "static" / "opportunity_lens_v2.js").read_text(encoding="utf-8")
        lens_css = (ROOT / "tools" / "viewer" / "static" / "opportunity_lens_v2.css").read_text(encoding="utf-8")
        lens_head = (ROOT / "tools" / "viewer" / "templates" / "opportunity_lens" / "_head_v2.html").read_text(encoding="utf-8")

        # Opportunity Lens publishes standalone $$ blocks and relies on the
        # global KaTeX auto-renderer.  Ignoring the page or evidence drawer
        # would leave raw LaTeX visible and contradict the browser audit.
        self.assertIn("ignoredClasses: ['no-katex']", base_html)
        self.assertNotIn("'opp-page'", base_html)
        self.assertNotIn("'opp-drawer'", base_html)
        self.assertIn("installScrollMirrors", lens_js)
        self.assertIn("opp-scroll-mirror", lens_js)
        self.assertIn("opp-scroll-assist", lens_js)
        self.assertIn("data-opp-column-label", lens_js)
        self.assertIn("已到达表格最右列", lens_js)
        self.assertIn("向右查看这张表格的后续列", lens_js)
        self.assertIn("opp-portfolio-row-concentrated", lens_js)
        self.assertIn("opp-portfolio-row-balanced", lens_js)
        self.assertIn("opp-portfolio-row-defensive", lens_js)
        self.assertIn(".opp-scroll-mirror", lens_css)
        self.assertIn(".opp-scroll-assist", lens_css)
        self.assertIn(".opp-portfolio-comparison-table", lens_css)
        self.assertIn(".opp-responsive-table td:before", lens_css)
        self.assertIn("content:attr(data-opp-column-label)", lens_css)
        self.assertIn("scrollbar-gutter:auto", lens_css)
        self.assertNotIn("scrollbar-gutter:stable", lens_css)
        self.assertIn(".opp-responsive-table thead tr{display:block!important;width:1px!important;height:1px!important;overflow:hidden!important}", lens_css)
        self.assertIn(".opp-responsive-table thead th{display:block!important;box-sizing:border-box!important;width:1px!important", lens_css)
        self.assertIn("overflow:visible;border:0;scrollbar-gutter:auto", lens_css)
        self.assertIn(".opp-page .katex", lens_css)
        self.assertIn("grid-template-columns:minmax(0,1fr)", lens_css)
        self.assertIn("overflow-x:hidden;overflow-x:clip", lens_css)
        self.assertIn("OPP_DISPLAY_LABELS", lens_head)
        self.assertIn("window.OPP_DISPLAY_LABELS", lens_js)
        self.assertIn("function humanDate", lens_js)
        self.assertIn('machine-formatted date in the public evidence drawer', lens_js)
        self.assertIn("Number(dayNumber) + '日'", lens_js)
        self.assertIn("return humanized", lens_js)
        self.assertIn("function humanFreshnessWarning", lens_js)
        self.assertIn("S: '最高证明力：监管披露、政府或标准组织原文'", lens_js)
        self.assertIn("D: '弱信号：只作研究线索，不支撑核心结论'", lens_js)
        self.assertIn("humanDate(linkedSource.event_date)", lens_js)
        self.assertIn("normalizedText(text) === normalizedText(originalText)", lens_js)
        self.assertIn("record.source_excerpt_display || record.source_excerpt", lens_js)
        self.assertIn("record.excerpt_display || record.excerpt", lens_js)
        self.assertNotIn("抓取日期", lens_js)
        self.assertNotIn("pass_with_note:", lens_js)

    def test_internal_trace_pages_remain_available_as_read_only_detail_pages(self):
        conn = connect(self.db_path)
        factor_row = conn.execute(
            "SELECT id, factor_code FROM opportunity_factor_score ORDER BY id LIMIT 1"
        ).fetchone()
        slot_row = conn.execute(
            "SELECT id, slot_key FROM opportunity_metric_slot ORDER BY id LIMIT 1"
        ).fetchone()
        factor_id = factor_row["id"]
        slot_id = slot_row["id"]
        conn.close()

        for path in (
            f"/opportunity-lens/factor/{factor_id}",
            f"/opportunity-lens/metric-slot/{slot_id}",
        ):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertIsNone(response.headers.get("Location"))
            self.assertIn("opp-page", response.get_data(as_text=True))

        factor_html = self.client.get(
            f"/opportunity-lens/factor/{factor_id}"
        ).get_data(as_text=True)
        slot_html = self.client.get(
            f"/opportunity-lens/metric-slot/{slot_id}"
        ).get_data(as_text=True)
        self.assertIn("研究因子", factor_html)
        self.assertIn("研究指标", slot_html)
        self.assertNotIn("指标槽", factor_html)
        self.assertNotIn("指标槽", slot_html)
        self.assertNotIn("核心 14 因子", factor_html)
        self.assertNotIn(str(factor_row["factor_code"]), factor_html)
        self.assertNotIn(str(slot_row["slot_key"]), factor_html)
        self.assertNotIn(str(slot_row["slot_key"]), slot_html)

    def test_v2_trace_pages_translate_internal_statuses_and_metric_slot_wording(self):
        conn = connect(self.db_path)
        slot_id = int(
            conn.execute(
                "SELECT id FROM opportunity_metric_slot WHERE run_id=1 ORDER BY id LIMIT 1"
            ).fetchone()["id"]
        )
        conn.execute(
            "UPDATE opportunity_metric_slot SET value_status='not_found_after_search' WHERE id=?",
            (slot_id,),
        )
        conn.execute("DELETE FROM opportunity_slot_data_point_link WHERE slot_id=?", (slot_id,))
        conn.commit()
        conn.close()

        html = self.client.get(f"/opportunity-lens/metric-slot/{slot_id}").get_data(as_text=True)
        self.assertIn("研究指标追踪", html)
        self.assertIn("检索后仍无直接数据", html)
        self.assertIn("这个研究指标目前没有直接数据点支持", html)
        self.assertNotIn("not_found_after_search", html)
        self.assertNotIn("指标槽", html)
        self.assertIn("<span>分数</span><b>证据不足</b>", html)
        self.assertNotIn("<span>分数</span><b>42.0</b>", html)

        label_renderer = self.app.jinja_env.filters["opp_label"]
        text_renderer = self.app.jinja_env.filters["opp_inline_evidence"]
        with self.app.test_request_context("/opportunity-lens/run/1"):
            g.opp_viewer_v2 = True
            self.assertEqual(
                label_renderer("stale_but_usable"),
                "历史数据可用于背景，但时效有限",
            )
            rendered = str(
                text_renderer(
                    "historical_status_not_currently_verified；pending_current_update；PE_TTM"
                )
            )
            self.assertIn("仅有历史披露，当前进度待一手资料更新", rendered)
            self.assertIn("当前进度尚待一手资料更新", rendered)
            self.assertIn("滚动市盈率（PE-TTM）", rendered)
            self.assertNotIn("historical_status_not_currently_verified", rendered)
            self.assertNotIn("pending_current_update", rendered)

        with self.app.test_request_context("/opportunity-lens/run/1"):
            g.opp_viewer_v2 = False
            self.assertEqual(label_renderer("not_found_after_search"), "not_found_after_search")

    def test_unscored_v2_factor_hides_internal_weight_score_and_gate_label(self):
        conn = connect(self.db_path)
        factor = conn.execute(
            "SELECT id,factor_trace_json FROM opportunity_factor_score WHERE run_id=1 ORDER BY id LIMIT 1"
        ).fetchone()
        trace = json.loads(factor["factor_trace_json"] or "{}")
        trace["evidence_weighting"] = {
            "minimum_required_groups": 3,
            "available_group_count": 5,
            "weighted_evidence_score": 50.0,
            "gate_verdict": "pass",
            "items": [
                {
                    "evidence_ref": "opp://source/1",
                    "credibility_weight": 0.85,
                    "numeric_weight": 0.9,
                    "direction": "mixed",
                    "weighted_contribution": 0.0,
                    "reason": "测试证据。",
                }
            ],
        }
        conn.execute(
            """
            UPDATE opportunity_factor_score
            SET score_status='insufficient_evidence',score_raw=NULL,score_adjusted=NULL,
                factor_trace_json=?
            WHERE id=?
            """,
            (json.dumps(trace, ensure_ascii=False), factor["id"]),
        )
        conn.commit()
        conn.close()

        html = self.client.get(f"/opportunity-lens/factor/{factor['id']}").get_data(as_text=True)
        self.assertIn("已满足证据数量要求", html)
        self.assertNotIn("加权方向分", html)
        self.assertNotIn("闸门结论", html)
        self.assertNotIn("权重贡献", html)
        self.assertNotIn('data-opp-evidence="None"', html)

    def test_entity_page_has_research_profile_and_targets(self):
        html = self.client.get("/opportunity-lens/entity/1").get_data(as_text=True)
        self.assertIn("公司研究、证据与投资含义", html)
        self.assertIn("研究对象", html)
        self.assertIn("证据和数据", html)
        self.assertIn("分析", html)
        self.assertIn("总结", html)
        self.assertIn("相关标的与投资含义", html)
        self.assertIn("为什么相关", html)
        self.assertIn("当前判断", html)
        self.assertIn("<b>证实后：</b>", html)
        self.assertNotIn("标的质量", html)
        self.assertNotIn("优先级/状态", html)
        self.assertIn("<h2>证据和数据</h2>", html)
        self.assertIn("<h2>因子与评分</h2>", html)
        self.assertIn("<h2>来源</h2>", html)
        self.assertIn("<b>证伪后：</b>", html)
        self.assertIn("投资研究建议", html)
        self.assertNotIn("不是个性化交易建议", html)
        self.assertNotIn("核心 14 因子", html)
        self.assertIn("合成示例载板公司", html)
        self.assertNotIn("关键证据与判断", html)
        self.assertNotIn("证据权重", html)

    def test_entity_api_exposes_sections_data_points_claims_and_targets(self):
        payload = self.client.get("/api/opportunity-lens/entity/1").get_json()
        entity = payload["data"]
        self.assertTrue(entity["sections"])
        self.assertTrue(entity["data_points"])
        self.assertTrue(entity["claims"])
        self.assertTrue(entity["investment_targets"])
        self.assertIn("entity_research_brief", entity)
        target = entity["investment_targets"][0]
        self.assertIn("target_link", target)
        self.assertIn("investment_view", target)
        self.assertIn("target_priority", target)
        self.assertIn("confirmed_scenario_action", target)
        self.assertIn("falsified_scenario_action", target)
        self.assertIn("target_detail_link", target)
        self.assertIn("target_profile_markdown", target)

    def test_target_page_and_api_expose_dedicated_research(self):
        conn = connect(self.db_path)
        target_row = conn.execute(
            "SELECT id, target_priority FROM opportunity_entity_investment_target ORDER BY id LIMIT 1"
        ).fetchone()
        target_id = target_row["id"]
        conn.close()
        html = self.client.get(f"/opportunity-lens/target/{target_id}").get_data(as_text=True)
        self.assertIn("标的介绍", html)
        self.assertIn("与研究实体和主问题的关系", html)
        self.assertIn("深入研究", html)
        self.assertIn("条件化投资建议", html)
        self.assertIn("<h2>关键数据</h2>", html)
        self.assertIn("opp-target-kpis", html)
        self.assertNotIn("入库数据点", html)
        self.assertNotIn("可信度 100%", html)
        self.assertNotIn("关键数据和来源", html)
        self.assertNotIn("财务和市场数据", html)
        self.assertNotIn("不是个性化交易建议", html)
        if target_row["target_priority"] == "P1":
            self.assertIn("<b>高优先级</b>", html)
            self.assertNotIn("<b>P1</b>", html)
        elif target_row["target_priority"] == "P2":
            self.assertIn("<b>中优先级</b>", html)
            self.assertNotIn("<b>P2</b>", html)

        payload = self.client.get(f"/api/opportunity-lens/target/{target_id}").get_json()
        target = payload["data"]
        self.assertTrue(target["target_data_points"])
        self.assertIn("conditional_investment_recommendation", target)
        self.assertIn("parent_research_relation_markdown", target)


if __name__ == "__main__":
    import unittest

    unittest.main()
