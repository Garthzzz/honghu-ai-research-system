from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import fitz


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PAPERS = ROOT / "papers" / "HDI"
DEFAULT_CACHE = ROOT / "cache" / "hdi_research"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _extract_pdf(path: Path, output: Path) -> tuple[int, int]:
    document = fitz.open(path)
    chunks: list[str] = []
    character_count = 0
    try:
        for page_number, page in enumerate(document, start=1):
            text = page.get_text("text", sort=True).replace("\x00", " ")
            character_count += len(text)
            chunks.append(f"\n\n===== PAGE {page_number} =====\n\n{text}")
    finally:
        document.close()
    output.write_text("".join(chunks).strip() + "\n", encoding="utf-8")
    return page_number if chunks else 0, character_count


def build_index(papers_dir: Path, cache_dir: Path, *, force: bool = False) -> dict[str, Any]:
    text_dir = cache_dir / "extracted_text"
    text_dir.mkdir(parents=True, exist_ok=True)
    index_path = cache_dir / "pdf_extraction_index.json"
    old_rows: dict[str, dict[str, Any]] = {}
    if index_path.is_file():
        payload = json.loads(index_path.read_text(encoding="utf-8"))
        old_rows = {str(row["relative_path"]): row for row in payload.get("files", [])}

    rows: list[dict[str, Any]] = []
    total_pages = 0
    total_characters = 0
    failures: list[dict[str, str]] = []
    for path in sorted(papers_dir.glob("*.pdf"), key=lambda item: item.name.lower()):
        relative = path.relative_to(ROOT).as_posix()
        digest = _sha256(path)
        output = text_dir / f"{digest[:20]}.txt"
        old = old_rows.get(relative, {})
        try:
            if (
                not force
                and output.is_file()
                and old.get("sha256") == digest
                and int(old.get("page_count") or 0) > 0
            ):
                page_count = int(old["page_count"])
                character_count = int(old.get("character_count") or len(output.read_text(encoding="utf-8")))
                cache_status = "reused"
            else:
                page_count, character_count = _extract_pdf(path, output)
                cache_status = "extracted"
            rows.append(
                {
                    "relative_path": relative,
                    "name": path.name,
                    "sha256": digest,
                    "size_bytes": path.stat().st_size,
                    "page_count": page_count,
                    "character_count": character_count,
                    "text_path": output.relative_to(ROOT).as_posix(),
                    "cache_status": cache_status,
                }
            )
            total_pages += page_count
            total_characters += character_count
        except Exception as exc:
            failures.append(
                {
                    "relative_path": relative,
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                }
            )

    result = {
        "schema_version": "hdi_research.pdf_corpus.v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "papers_dir": papers_dir.relative_to(ROOT).as_posix(),
        "pdf_count": len(rows),
        "total_pages": total_pages,
        "total_characters": total_characters,
        "failure_count": len(failures),
        "files": rows,
        "failures": failures,
    }
    cache_dir.mkdir(parents=True, exist_ok=True)
    index_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (cache_dir / "pdf_extraction_summary.json").write_text(
        json.dumps(
            {
                key: result[key]
                for key in (
                    "schema_version",
                    "generated_at_utc",
                    "pdf_count",
                    "total_pages",
                    "total_characters",
                    "failure_count",
                )
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="HDI B轨本地PDF逐页文本与哈希索引")
    parser.add_argument("--papers", type=Path, default=DEFAULT_PAPERS)
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    result = build_index(args.papers.resolve(), args.cache.resolve(), force=args.force)
    print(
        json.dumps(
            {
                "pdf_count": result["pdf_count"],
                "total_pages": result["total_pages"],
                "total_characters": result["total_characters"],
                "failure_count": result["failure_count"],
            },
            ensure_ascii=False,
        )
    )
    return 1 if result["failure_count"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
