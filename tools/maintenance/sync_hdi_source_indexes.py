#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Ensure every public HDI body citation has a readable source-index entry."""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DOC_DIR = ROOT / "docs" / "industries"
DB_PATH = ROOT / "data" / "research.db"
SOURCE_HEADING = "## 来源索引"
SOURCE_REF_RE = re.compile(r"\^src:(\d+)")


def main() -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    source_rows = {
        str(row["id"]): row
        for row in conn.execute(
            """
            SELECT id, title, publisher, publish_date, quality_tier
            FROM source
            """
        )
    }
    changed: list[tuple[str, list[str]]] = []
    for path in sorted(DOC_DIR.glob("HDI板*.md")):
        text = path.read_text(encoding="utf-8")
        if SOURCE_HEADING not in text:
            raise RuntimeError(f"{path.name} 缺少来源索引")
        body, index = text.split(SOURCE_HEADING, 1)
        body_ids = set(SOURCE_REF_RE.findall(body))
        index_ids = set(SOURCE_REF_RE.findall(index))
        missing = sorted(body_ids - index_ids, key=int)
        if not missing:
            continue
        lines: list[str] = []
        for source_id in missing:
            row = source_rows.get(source_id)
            if row is None:
                raise RuntimeError(f"{path.name} 引用了不存在的 source #{source_id}")
            lines.append(
                f"- ^src:{source_id} {row['title']}（{row['publisher']}，"
                f"{row['publish_date']}，来源等级 T{row['quality_tier']}）"
            )
        updated = text.rstrip() + "\n" + "\n".join(lines) + "\n"
        path.write_text(updated, encoding="utf-8")
        changed.append((path.name, missing))
    for name, source_ids in changed:
        print(f"{name}: added {','.join(source_ids)}")
    print(f"changed_documents={len(changed)}")


if __name__ == "__main__":
    main()
