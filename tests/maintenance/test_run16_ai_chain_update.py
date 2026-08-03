from __future__ import annotations

import hashlib
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

import yaml

from tools.maintenance.apply_run16_ai_chain_update import (
    COMPANIES,
    INDUSTRIES,
    _connect,
    apply_update,
    build_plan,
)


ROOT = Path(__file__).resolve().parents[2]


SCHEMA = """
CREATE TABLE industry(
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 name TEXT NOT NULL UNIQUE,
 parent_id INTEGER,
 level INTEGER NOT NULL DEFAULT 1,
 tier INTEGER NOT NULL DEFAULT 3,
 status TEXT NOT NULL DEFAULT '仅记录',
 core_dynamic TEXT,
 last_updated TEXT,
 created_at TEXT,
 FOREIGN KEY(parent_id) REFERENCES industry(id) ON DELETE SET NULL
);
CREATE TABLE company(
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 name TEXT NOT NULL UNIQUE,
 ticker TEXT,
 market TEXT
);
CREATE TABLE company_industry(
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 company_id INTEGER NOT NULL,
 industry_id INTEGER NOT NULL,
 role TEXT,
 revenue_share REAL,
 note TEXT,
 FOREIGN KEY(company_id) REFERENCES company(id) ON DELETE CASCADE,
 FOREIGN KEY(industry_id) REFERENCES industry(id) ON DELETE CASCADE,
 UNIQUE(company_id,industry_id)
);
CREATE TABLE source(
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 title TEXT NOT NULL,
 source_type TEXT NOT NULL,
 publisher TEXT,
 publish_date TEXT,
 quality_tier INTEGER NOT NULL DEFAULT 3,
 is_forward_looking INTEGER NOT NULL DEFAULT 0,
 url TEXT,
 note TEXT,
 value_layer TEXT,
 source_url TEXT,
 source_subtype TEXT,
 fetch_method TEXT,
 domain TEXT,
 language TEXT,
 is_primary_source INTEGER,
 source_credibility TEXT,
 source_channel TEXT
);
CREATE TABLE industry_relation(
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 upstream_id INTEGER NOT NULL,
 downstream_id INTEGER NOT NULL,
 relation_type TEXT NOT NULL,
 source_id INTEGER,
 note TEXT,
 FOREIGN KEY(upstream_id) REFERENCES industry(id) ON DELETE CASCADE,
 FOREIGN KEY(downstream_id) REFERENCES industry(id) ON DELETE CASCADE,
 FOREIGN KEY(source_id) REFERENCES source(id) ON DELETE SET NULL,
 UNIQUE(upstream_id,downstream_id,relation_type)
);
"""


BASE_INDUSTRIES = (
    (1, "光模块"),
    (6, "通信"),
    (7, "存储"),
    (8, "大模型"),
    (9, "算力芯片"),
    (10, "半导体设备"),
    (11, "云服务器厂商"),
    (12, "液冷"),
    (13, "电力"),
    (14, "AI应用"),
    (15, "AI服务器"),
    (20, "PCB制造"),
    (22, "高多层PCB板"),
)


class Run16AIChainUpdateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / "research.db"
        conn = sqlite3.connect(self.db)
        conn.executescript(SCHEMA)
        conn.executemany(
            "INSERT INTO industry(id,name,level,tier,status) VALUES(?,?,1,1,'深度跟踪')",
            BASE_INDUSTRIES,
        )
        for index, spec in enumerate(COMPANIES, start=100):
            company_id = 777 if spec.name == "汇川技术" else index
            conn.execute(
                "INSERT INTO company(id,name,ticker,market) VALUES(?,?,?,'A股')",
                (company_id, spec.name, spec.ticker),
            )
        # Reproduce the stale-id hazard from the real database.  Correct
        # resolution must still map 汇川技术 to 777, never to 279.
        conn.execute(
            "INSERT INTO company(id,name,ticker,market) VALUES(279,'三花智控','002050.SZ','A股')"
        )
        conn.commit()
        conn.close()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_default_connection_is_read_only_and_plan_resolves_identity(self) -> None:
        before = hashlib.sha256(self.db.read_bytes()).hexdigest()
        with closing(_connect(self.db, apply=False)) as conn:
            plan = build_plan(conn)
        after = hashlib.sha256(self.db.read_bytes()).hexdigest()
        self.assertEqual(before, after)
        self.assertTrue(plan["ready_to_apply"])
        self.assertEqual(plan["counts"]["companies_resolved"], 18)
        mapping = next(
            row
            for row in plan["company_memberships"]
            if row["company"] == "汇川技术"
            and row["industry"] == "机器人与工业智能"
        )
        self.assertEqual(mapping["resolved_company_id"], 777)
        self.assertTrue(any("id=279" in item for item in plan["warnings"]))

    def test_apply_is_transactional_and_idempotent(self) -> None:
        with closing(_connect(self.db, apply=True)) as conn:
            first = apply_update(conn)
        self.assertEqual(first["verification"]["status"], "GREEN")
        conn = sqlite3.connect(self.db)
        first_counts = {
            "industry": conn.execute("SELECT COUNT(*) FROM industry").fetchone()[0],
            "source": conn.execute("SELECT COUNT(*) FROM source").fetchone()[0],
            "membership": conn.execute("SELECT COUNT(*) FROM company_industry").fetchone()[0],
            "relation": conn.execute("SELECT COUNT(*) FROM industry_relation").fetchone()[0],
        }
        cloud = conn.execute("SELECT name FROM industry WHERE id=11").fetchone()[0]
        app = conn.execute("SELECT name FROM industry WHERE id=14").fetchone()[0]
        robot_id = conn.execute(
            "SELECT id FROM industry WHERE name='机器人与工业智能'"
        ).fetchone()[0]
        owner = conn.execute(
            "SELECT company_id FROM company_industry WHERE industry_id=?", (robot_id,)
        ).fetchone()[0]
        conn.close()
        self.assertEqual(cloud, "云计算与算力运营")
        self.assertEqual(app, "AI应用")
        self.assertEqual(owner, 777)

        with closing(_connect(self.db, apply=True)) as conn:
            second = apply_update(conn)
        self.assertEqual(second["verification"]["status"], "GREEN")
        conn = sqlite3.connect(self.db)
        second_counts = {
            "industry": conn.execute("SELECT COUNT(*) FROM industry").fetchone()[0],
            "source": conn.execute("SELECT COUNT(*) FROM source").fetchone()[0],
            "membership": conn.execute("SELECT COUNT(*) FROM company_industry").fetchone()[0],
            "relation": conn.execute("SELECT COUNT(*) FROM industry_relation").fetchone()[0],
        }
        conn.close()
        self.assertEqual(first_counts, second_counts)

    def test_missing_identity_blocks_before_any_write(self) -> None:
        conn = sqlite3.connect(self.db)
        conn.execute("DELETE FROM company WHERE name='汇川技术'")
        conn.commit()
        conn.close()
        with closing(_connect(self.db, apply=True)) as conn:
            with self.assertRaisesRegex(RuntimeError, "汇川技术|300124"):
                apply_update(conn)
        conn = sqlite3.connect(self.db)
        cloud = conn.execute("SELECT name FROM industry WHERE id=11").fetchone()[0]
        new_count = conn.execute(
            "SELECT COUNT(*) FROM industry WHERE name IN ({})".format(
                ",".join("?" for _ in INDUSTRIES)
            ),
            tuple(spec.name for spec in INDUSTRIES),
        ).fetchone()[0]
        conn.close()
        self.assertEqual(cloud, "云服务器厂商")
        self.assertEqual(new_count, 0)

    def test_viewer_configuration_has_five_nonempty_value_chains(self) -> None:
        config = yaml.safe_load(
            (ROOT / "tools" / "dynamic" / "config.yaml").read_text(encoding="utf-8")
        )
        directions = config["ai_chain_directions"]
        self.assertEqual(
            [row["name"] for row in directions],
            ["算力生成", "数据搬运", "物理承载", "能源供给", "软件变现"],
        )
        self.assertTrue(all(row["industries"] for row in directions))
        cloud = next(row for row in config["industries_final"] if row["db_id"] == 11)
        self.assertEqual(cloud["name"], "云计算与算力运营")
        self.assertIn("云服务器厂商", cloud["aliases"])


if __name__ == "__main__":
    unittest.main()
