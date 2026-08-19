from __future__ import annotations

from tools.viewer import app as viewer


def _member() -> dict:
    return {
        "member_id": 1,
        "company_id": 635,
        "security_id": 616,
        "canonical_name": "紫金矿业",
        "canonical_ticker": "601899.SH",
        "market": "上海",
        "board": "铜资源",
        "display_order": 1,
        "revision": 1,
        "current_policy_revision": 1,
        "researcher_ratio_threshold": 1.0,
        "ai_ratio_threshold": 1.0,
        "max_snapshot_age_hours": 48,
        "researcher_version": {
            "ceiling_value": 15379,
            "currency": "CNY",
            "valuation_date": "2026-08-19",
        },
        "latest_ai_version": None,
        "published_ai_version": None,
        "ai_alert_version": None,
        "previous_ai_version": None,
        "market_snapshot": None,
        "valuation_history": [],
        "researcher_ratio": None,
        "ai_ratio": None,
        "researcher_alert": False,
        "ai_alert": False,
        "researcher_comparison_note": "暂无市值快照",
        "ai_comparison_note": "暂无估值版本",
        "ai_change_pct": None,
    }


def test_tracker_page_links_existing_company_and_shows_truthful_missing_ai(monkeypatch) -> None:
    class FakeRepository:
        def watchlist(self):
            return [_member()]

    monkeypatch.setattr(viewer, "VALUATION_TRACKER_REPOSITORY", FakeRepository())
    response = viewer.app.test_client().get("/tools/valuation-tracker")
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "市值空间与估值跟踪" in html
    assert "601899.SH" in html
    assert "/company/635#asset-return-valuation" in html
    assert "暂无上一期 AI 估值" in html
    assert "待建模" in html
    assert "估值方法名称（每行一项）" in html
    assert "沿用公司详情页既有经营分析" not in html


def test_tracker_database_conflicts_are_http_409() -> None:
    class Conflict(Exception):
        sqlstate = "40001"

    with viewer.app.app_context():
        response, status = viewer._user_content_error(Conflict("stale"))
    assert status == 409
    assert response.get_json()["code"] == "valuation_tracker_conflict"


def test_plain_http_mutation_fails_before_repository(monkeypatch) -> None:
    class FailRepository:
        def edit_valuation(self, *_args, **_kwargs):
            raise AssertionError("repository must not be reached")

    monkeypatch.setattr(viewer, "VALUATION_TRACKER_REPOSITORY", FailRepository())
    response = viewer.app.test_client().post(
        "/api/valuation-tracker/member/1/valuation", json={}
    )
    assert response.status_code in {401, 403, 503}
    assert response.get_json()["ok"] is False


def test_tracker_renders_exact_seven_card_pool_without_n_plus_one(monkeypatch) -> None:
    calls = 0

    class FakeRepository:
        def watchlist(self):
            nonlocal calls
            calls += 1
            members = []
            for index in range(7):
                item = _member()
                item.update({
                    "member_id": index + 1,
                    "company_id": 700 + index,
                    "security_id": 800 + index,
                    "canonical_name": f"公司{index + 1}",
                    "canonical_ticker": f"00000{index + 1}.SZ",
                })
                members.append(item)
            return members

    monkeypatch.setattr(viewer, "VALUATION_TRACKER_REPOSITORY", FakeRepository())
    response = viewer.app.test_client().get("/tools/valuation-tracker")
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert calls == 1
    assert html.count('class="vt-card') >= 7
    for index in range(7):
        assert f"/company/{700 + index}#asset-return-valuation" in html
