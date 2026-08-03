from __future__ import annotations

"""Search the extracted HDI PDF corpus while preserving original filenames."""

import argparse
import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
INDEX = ROOT / "cache" / "hdi_research" / "pdf_extraction_index.json"


def _records() -> list[dict[str, object]]:
    payload = json.loads(INDEX.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        rows = payload.get("files") or payload.get("records") or []
    else:
        rows = payload
    if not isinstance(rows, list):
        raise ValueError("HDI PDF extraction index has no record list")
    return [dict(row) for row in rows]


def search(query: str, *, file_pattern: str | None, limit: int) -> list[dict[str, object]]:
    needle = re.compile(query, re.IGNORECASE)
    file_re = re.compile(file_pattern, re.IGNORECASE) if file_pattern else None
    results: list[dict[str, object]] = []
    for record in _records():
        name = str(
            record.get("source_name")
            or record.get("filename")
            or record.get("name")
            or record.get("source_path")
            or ""
        )
        if file_re and not file_re.search(name):
            continue
        text_path = Path(str(record.get("text_path") or ""))
        if not text_path.is_absolute():
            text_path = ROOT / text_path
        if not text_path.is_file():
            continue
        text = text_path.read_text(encoding="utf-8", errors="replace")
        matches = list(needle.finditer(text))
        if not matches:
            continue
        snippets: list[str] = []
        for match in matches[:3]:
            start = max(0, match.start() - 180)
            end = min(len(text), match.end() + 260)
            snippet = re.sub(r"\s+", " ", text[start:end]).strip()
            snippets.append(snippet)
        results.append(
            {
                "source_name": name,
                "match_count": len(matches),
                "snippets": snippets,
            }
        )
    results.sort(key=lambda row: (-int(row["match_count"]), str(row["source_name"])))
    return results[:limit]


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query", help="Python regular expression")
    parser.add_argument("--file", dest="file_pattern")
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()
    print(
        json.dumps(
            search(args.query, file_pattern=args.file_pattern, limit=args.limit),
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
