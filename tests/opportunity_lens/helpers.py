from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from flask import Flask

from tools.opportunity_lens.db import connect, table_counts
from tools.opportunity_lens.fixture_loader import load_synthetic_fixture
from tools.viewer.opportunity_lens_blueprint import opportunity_lens_bp

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_DIR = ROOT / "tools" / "viewer" / "templates"
STATIC_DIR = ROOT / "tools" / "viewer" / "static"


class FixtureDBTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)
        self.db_path = self.tmp_path / "opportunity_lens.db"
        self.export_root = self.tmp_path / "exports"
        self.run_id = load_synthetic_fixture(self.db_path, reset=True)

    def tearDown(self):
        self.tmp.cleanup()

    def counts(self):
        conn = connect(self.db_path)
        try:
            return table_counts(conn)
        finally:
            conn.close()


def make_test_app(db_path: Path, export_root: Path | None = None) -> Flask:
    app = Flask(__name__, template_folder=str(TEMPLATE_DIR), static_folder=str(STATIC_DIR))
    app.config.update(
        TESTING=True,
        OPPORTUNITY_LENS_DB_PATH=db_path,
        OPPORTUNITY_LENS_EXPORT_ROOT=export_root or (db_path.parent / "exports"),
    )

    def dummy(**_kwargs):
        return ""

    for endpoint, rule in [
        ("index", "/"),
        ("hypotheses_index", "/hypotheses"),
        ("events_index", "/events"),
        ("research_home", "/research"),
        ("companies_index", "/companies"),
        ("ai_macro_chain", "/ai-chain"),
        ("data_points_index", "/data_points"),
        ("dynamic_sentiment", "/dynamic/sentiment"),
        ("incremental_index", "/incremental"),
        ("sources_index", "/sources"),
        ("tools_index", "/tools"),
        ("lithium_calculator", "/tools/lithium-calculator"),
        ("copper_calculator", "/tools/copper-calculator"),
        ("api_health", "/api/health"),
        ("industry_detail", "/industry/<int:industry_id>"),
    ]:
        app.add_url_rule(rule, endpoint, dummy)

    @app.context_processor
    def nav_context():
        return {"nav_industries": [], "nav_deep_count": 0, "error": None}

    app.register_blueprint(opportunity_lens_bp)
    return app
