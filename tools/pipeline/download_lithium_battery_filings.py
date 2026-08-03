from __future__ import annotations

"""Download the latest official filings used by the lithium-battery B-track run.

The catalog is intentionally narrow: two current operating anchors per company
where available.  It does not crawl the market and it never writes a database.
Every file is validated as a PDF and recorded with its source URL and SHA256.
"""

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
import fitz


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = (
    ROOT
    / "cache"
    / "lithium_battery_research"
    / "sources"
    / "company_filing_manifest_v1.json"
)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (IndustryDemo lithium-battery research collector)"
}

FILINGS: tuple[dict[str, str], ...] = (
    {
        "company": "宁德时代",
        "ticker": "300750.SZ",
        "period": "2026H1",
        "title": "宁德时代2026年半年度报告",
        "url": (
            "https://file.finance.sina.com.cn/211.154.219.97%3A9494/"
            "MRGG/CNSESZ_STOCK/2026/2026-7/2026-07-25/12462543.PDF"
        ),
        "filename": "2026-07-25_宁德时代_2026年半年度报告.pdf",
    },
    {
        "company": "宁德时代",
        "ticker": "300750.SZ",
        "period": "2025A",
        "title": "宁德时代2025年年度报告",
        "url": "https://static.cninfo.com.cn/finalpage/2026-03-10/1225002214.PDF",
        "filename": "2026-03-10_宁德时代_2025年年度报告.pdf",
    },
    {
        "company": "比亚迪",
        "ticker": "002594.SZ",
        "period": "2026Q1",
        "title": "比亚迪2026年第一季度报告",
        "url": (
            "https://disc.static.szse.cn/disc/disk03/finalpage/2026-04-29/"
            "3412b15e-4812-4410-8308-183b94f48105.PDF"
        ),
        "filename": "2026-04-29_比亚迪_2026年第一季度报告.pdf",
    },
    {
        "company": "比亚迪",
        "ticker": "002594.SZ",
        "period": "2025A",
        "title": "比亚迪2025年年度报告",
        "url": (
            "https://file.finance.sina.com.cn/211.154.219.97%3A9494/"
            "MRGG/CNSESZ_STOCK/2026/2026-3/2026-03-28/12033359.PDF"
        ),
        "filename": "2026-03-28_比亚迪_2025年年度报告.pdf",
    },
    {
        "company": "国轩高科",
        "ticker": "002074.SZ",
        "period": "2026Q1",
        "title": "国轩高科2026年第一季度报告",
        "url": (
            "https://file.finance.sina.com.cn/211.154.219.97%3A9494/"
            "MRGG/CNSESZ_STOCK/2026/2026-4/2026-04-29/12264871.PDF"
        ),
        "filename": "2026-04-29_国轩高科_2026年第一季度报告.pdf",
    },
    {
        "company": "国轩高科",
        "ticker": "002074.SZ",
        "period": "2025A",
        "title": "国轩高科2025年年度报告",
        "url": (
            "https://disc.static.szse.cn/download/disc/disk03/finalpage/"
            "2026-04-29/24ee6bf9-6daa-4f4f-ae46-12dfbe099287.pdf"
        ),
        "filename": "2026-04-29_国轩高科_2025年年度报告.pdf",
    },
    {
        "company": "亿纬锂能",
        "ticker": "300014.SZ",
        "period": "2026Q1",
        "title": "亿纬锂能2026年第一季度报告",
        "url": "https://static.cninfo.com.cn/finalpage/2026-04-25/1225182164.PDF",
        "filename": "2026-04-25_亿纬锂能_2026年第一季度报告.pdf",
    },
    {
        "company": "亿纬锂能",
        "ticker": "300014.SZ",
        "period": "2025A",
        "title": "亿纬锂能2025年年度报告",
        "url": (
            "https://file.finance.sina.com.cn/211.154.219.97%3A9494/"
            "MRGG/CNSESZ_STOCK/2026/2026-3/2026-03-28/12033427.PDF"
        ),
        "filename": "2026-03-28_亿纬锂能_2025年年度报告.pdf",
    },
    {
        "company": "欣旺达",
        "ticker": "300207.SZ",
        "period": "2026Q1",
        "title": "欣旺达2026年第一季度报告",
        "url": (
            "https://disc.static.szse.cn/download/disc/disk03/finalpage/"
            "2026-04-24/aec71c6c-17b9-4e96-9024-0da6ecb8b171.PDF"
        ),
        "filename": "2026-04-24_欣旺达_2026年第一季度报告.pdf",
    },
    {
        "company": "欣旺达",
        "ticker": "300207.SZ",
        "period": "2025A",
        "title": "欣旺达2025年年度报告",
        "url": (
            "https://disc.static.szse.cn/download/disc/disk03/finalpage/"
            "2026-04-24/6fa721fa-cad9-4499-b2cc-a49e32e82f44.PDF"
        ),
        "filename": "2026-04-24_欣旺达_2025年年度报告.pdf",
    },
    {
        "company": "孚能科技",
        "ticker": "688567.SH",
        "period": "2026Q1",
        "title": "孚能科技2026年第一季度报告",
        "url": (
            "https://file.finance.sina.com.cn/211.154.219.97%3A9494/"
            "MRGG/CNSESH_STOCK/2026/2026-4/2026-04-30/12279057.PDF"
        ),
        "filename": "2026-04-30_孚能科技_2026年第一季度报告.pdf",
    },
    {
        "company": "孚能科技",
        "ticker": "688567.SH",
        "period": "2025A",
        "title": "孚能科技2025年年度报告",
        "url": "https://static.cninfo.com.cn/finalpage/2026-04-30/1225258214.PDF",
        "filename": "2026-04-30_孚能科技_2025年年度报告.pdf",
    },
    {
        "company": "鹏辉能源",
        "ticker": "300438.SZ",
        "period": "2026Q1",
        "title": "鹏辉能源2026年第一季度报告",
        "url": (
            "https://www.greatpower.net/vancheerfile/files/2026/4/"
            "20260429095944532.pdf"
        ),
        "filename": "2026-04-29_鹏辉能源_2026年第一季度报告.pdf",
    },
    {
        "company": "鹏辉能源",
        "ticker": "300438.SZ",
        "period": "2025A",
        "title": "鹏辉能源2025年年度报告",
        "url": (
            "https://www.greatpower.net/vancheerfile/files/2026/4/"
            "20260429095829179.pdf"
        ),
        "filename": "2026-04-29_鹏辉能源_2025年年度报告.pdf",
    },
    {
        "company": "中创新航",
        "ticker": "3931.HK",
        "period": "2026Q1",
        "title": "中创新航2026年第一季度报告",
        "url": (
            "https://www1.hkexnews.hk/listedco/listconews/sehk/2026/"
            "0430/2026043001640.pdf"
        ),
        "filename": "2026-04-30_中创新航_2026年第一季度报告.pdf",
    },
    {
        "company": "中创新航",
        "ticker": "3931.HK",
        "period": "2025A",
        "title": "中创新航2025年年度报告",
        "url": (
            "https://www1.hkexnews.hk/listedco/listconews/sehk/2026/"
            "0429/2026042900019.pdf"
        ),
        "filename": "2026-04-29_中创新航_2025年年度报告.pdf",
    },
    {
        "company": "瑞浦兰钧",
        "ticker": "0666.HK",
        "period": "2026H1E",
        "title": "瑞浦兰钧2026年上半年正面盈利预告",
        "url": (
            "https://www1.hkexnews.hk/listedco/listconews/sehk/2026/"
            "0709/2026070901051.pdf"
        ),
        "filename": "2026-07-09_瑞浦兰钧_2026年上半年正面盈利预告.pdf",
    },
    {
        "company": "瑞浦兰钧",
        "ticker": "0666.HK",
        "period": "2025A",
        "title": "瑞浦兰钧2025年年度报告",
        "url": (
            "https://www1.hkexnews.hk/listedco/listconews/sehk/2026/"
            "0429/2026042902781.pdf"
        ),
        "filename": "2026-04-29_瑞浦兰钧_2025年年度报告.pdf",
    },
)


def _sha256(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


HK_PDF_IDENTITY_MARKERS = {
    "3931.HK": ("CALB Group Co., Ltd.", "Stock Code: 3931"),
    "0666.HK": ("REPT BATTERO", "Stock Code: 0666"),
}


def _validate_pdf_identity(raw: bytes, filing: dict[str, Any]) -> None:
    """Reject a valid PDF that belongs to a different HKEX issuer."""
    markers = HK_PDF_IDENTITY_MARKERS.get(str(filing.get("ticker")))
    if not markers:
        return
    with fitz.open(stream=raw, filetype="pdf") as document:
        text = "\n".join(
            document[index].get_text("text")
            for index in range(min(10, len(document)))
        )
    missing = [marker for marker in markers if marker.lower() not in text.lower()]
    if missing:
        raise RuntimeError(
            "PDF证券身份校验失败，缺少标识：" + " / ".join(missing)
        )


def collect(manifest_path: Path = DEFAULT_MANIFEST) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    session = requests.Session()
    session.headers.update(HEADERS)
    for filing in FILINGS:
        row: dict[str, Any] = dict(filing)
        target_dir = ROOT / "papers" / "锂电池" / filing["company"]
        target_dir.mkdir(parents=True, exist_ok=True)
        path = target_dir / filing["filename"]
        try:
            response = session.get(filing["url"], timeout=120)
            response.raise_for_status()
            raw = response.content
            if not raw.startswith(b"%PDF"):
                raise RuntimeError("下载内容不是PDF")
            _validate_pdf_identity(raw, filing)
            path.write_bytes(raw)
            row.update(
                {
                    "status": "downloaded",
                    "local_path": path.relative_to(ROOT).as_posix(),
                    "size_bytes": len(raw),
                    "sha256": _sha256(raw),
                }
            )
        except Exception as exc:  # noqa: BLE001 - preserve per-source failure
            row.update(
                {
                    "status": "failed",
                    "error_type": type(exc).__name__,
                    "error_message": str(exc)[:300],
                }
            )
        rows.append(row)
    result = {
        "schema_version": "lithium_battery.company_filings.v1",
        "collected_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_note": (
            "文件均为交易所、巨潮、公司官网或交易所披露镜像中的法定披露；"
            "镜像不构成额外独立证据。"
        ),
        "rows": rows,
        "summary": {
            "downloaded": sum(row["status"] == "downloaded" for row in rows),
            "failed": sum(row["status"] == "failed" for row in rows),
        },
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    args = parser.parse_args()
    result = collect(args.manifest.resolve())
    print(json.dumps(result["summary"], ensure_ascii=False))
    return 0 if result["summary"]["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
