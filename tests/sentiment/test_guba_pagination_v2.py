from __future__ import annotations

import sys
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "sentiment"))

import eastmoney_guba


def row(pid: str, activity: str) -> dict:
    return {
        "href": f"/news,300001,{pid}.html",
        "tm": activity,
        "title": pid,
        "read": "1",
        "reply": "0",
    }


class FakePage:
    def __init__(self, pages):
        self.pages = list(pages)

    def goto(self, *_args, **_kwargs):
        return None

    def wait_for_timeout(self, _value):
        return None

    def eval_on_selector_all(self, *_args):
        return self.pages.pop(0) if self.pages else []


class GubaPaginationV2Test(unittest.TestCase):
    def test_api_second_precision_is_accepted_without_fabricating_time(self):
        parsed = eastmoney_guba.parse_time("2026-07-15 15:36:21")
        self.assertEqual(parsed[3], "2026-07-15T15:36+08:00")

    def test_server_rendered_rows_parse_without_browser_javascript(self):
        html = """<table class="default_list"><tr class="listitem">
          <td><div>1.2万</div></td><td><div>7</div></td>
          <td><div><a href="//caifuhao.eastmoney.com/news/20260715145821092351940">标题 A</a></div></td>
          <td><a>作者</a></td><td><div>07-15 14:58</div></td>
        </tr></table>"""
        self.assertEqual(eastmoney_guba._parse_server_rows(html), [{
            "read": "1.2万", "reply": "7", "title": "标题 A",
            "href": "//caifuhao.eastmoney.com/news/20260715145821092351940",
            "tm": "07-15 14:58",
        }])
        self.assertEqual(
            eastmoney_guba._empty_server_page_reason(
                '<table class="default_list"><tr><th>标题</th></tr></table>'
            ),
            "empty",
        )
        self.assertEqual(
            eastmoney_guba._empty_server_page_reason(
                '<table class="default_list"><tr><th>标题</th></tr><tr><td>新结构</td></tr></table>'
            ),
            "selector_drift",
        )
        self.assertEqual(eastmoney_guba._empty_server_page_reason("身份核实"), "challenge")

    def test_reaching_activity_boundary_proves_window_complete(self):
        page = FakePage([
            [row("202607151000000001", "07-15 10:00")],
            [row("202607141500000001", "07-14 15:00")],
        ])
        with mock.patch.object(eastmoney_guba.time, "sleep"):
            posts, bad, error = eastmoney_guba._fetch_page_sequence(
                page, "300001", pages=8,
                window_start=datetime(2026, 7, 14, 16, 0, tzinfo=eastmoney_guba.TZ),
            )
        self.assertEqual(len(posts), 2)
        self.assertEqual(bad, 0)
        self.assertIsNone(error)

    def test_page_cap_without_boundary_is_explicitly_truncated(self):
        page = FakePage([
            [row("202607151000000001", "07-15 10:00")],
            [row("202607150900000001", "07-15 09:00")],
        ])
        with mock.patch.object(eastmoney_guba.time, "sleep"):
            _posts, _bad, error = eastmoney_guba._fetch_page_sequence(
                page, "300001", pages=2,
                window_start=datetime(2026, 7, 14, 16, 0, tzinfo=eastmoney_guba.TZ),
            )
        self.assertEqual(error, "truncated:max_pages=2")

    def test_empty_first_page_is_not_misreported_as_complete(self):
        page = FakePage([[]])
        with mock.patch.object(eastmoney_guba.time, "sleep"):
            posts, bad, error = eastmoney_guba._fetch_page_sequence(
                page, "300001", pages=2,
                window_start=datetime(2026, 7, 14, 16, 0, tzinfo=eastmoney_guba.TZ),
            )
        self.assertEqual(posts, [])
        self.assertEqual(bad, 0)
        self.assertEqual(error, "empty:first_page")

    def test_partial_activity_times_cannot_prove_boundary(self):
        page = FakePage([[
            row("202607141500000001", "07-14 15:00"),
            row("202607141400000001", "not-a-time"),
        ]])
        with mock.patch.object(eastmoney_guba.time, "sleep"):
            _posts, _bad, error = eastmoney_guba._fetch_page_sequence(
                page, "300001", pages=1,
                window_start=datetime(2026, 7, 14, 16, 0, tzinfo=eastmoney_guba.TZ),
            )
        self.assertEqual(error, "truncated:max_pages=1")

    def test_repeated_pinned_post_does_not_mask_the_time_boundary(self):
        pinned = row("202607151000000001", "07-15 10:00")
        page = FakePage([
            [pinned, row("202607150900000001", "07-15 09:00")],
            [pinned, row("202607141500000001", "07-14 15:00")],
        ])
        with mock.patch.object(eastmoney_guba.time, "sleep"):
            posts, _bad, error = eastmoney_guba._fetch_page_sequence(
                page, "300001", pages=2,
                window_start=datetime(2026, 7, 14, 16, 0, tzinfo=eastmoney_guba.TZ),
            )
        self.assertEqual(len(posts), 3)
        self.assertIsNone(error)


if __name__ == "__main__":
    unittest.main()
