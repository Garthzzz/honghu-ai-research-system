from __future__ import annotations

"""Download the 2025 annual report and 2026 Q1 report for lithium companies.

Sina Finance mirrors the exchange filings and exposes the original PDF payload.
The script keeps the landing page, mirrored PDF URL and SHA256 in a manifest so
the local research source can be audited and replaced by the exchange original
without changing the filing identity.
"""

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.pipeline.paper_paths import proposed_paper_path

OUTPUT_DIR = ROOT / "papers" / "锂" / "company_filings"
MANIFEST_PATH = ROOT / "cache" / "lithium_research" / "company_filing_manifest.json"
BASE = "https://vip.stock.finance.sina.com.cn"
HEADERS = {"User-Agent": "Mozilla/5.0 (IndustryDemo research filing collector)"}
COMPANIES = {
    "002460": "赣锋锂业",
    "002192": "融捷股份",
    "002240": "盛新锂能",
    "000792": "盐湖股份",
    "001203": "大中矿业",
    "002497": "雅化集团",
    "300390": "天华新能",
    "002466": "天齐锂业",
    "603399": "永杉锂业",
    "002738": "中矿资源",
    "000408": "藏格矿业",
    "600773": "西藏城投",
    "002756": "永兴材料",
}
TARGETS = (
    ("ndbg", "2025年年度报告", "2025年年度报告"),
    ("yjdbg", "2026年一季度报告", "2026年第一季度报告"),
)


def _sha256(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _decode(response: requests.Response) -> str:
    return response.content.decode("gb18030", errors="ignore")


def _listing_url(ticker: str, page_type: str) -> str:
    return (
        f"{BASE}/corp/go.php/vCB_Bulletin/stockid/{ticker}/"
        f"page_type/{page_type}.phtml"
    )


def _select_detail(
    ticker: str,
    page_type: str,
    primary_phrase: str,
    alternate_phrase: str,
) -> tuple[str, str] | None:
    listing = _listing_url(ticker, page_type)
    response = requests.get(listing, headers=HEADERS, timeout=30)
    response.raise_for_status()
    soup = BeautifulSoup(_decode(response), "html.parser")
    candidates: list[tuple[int, str, str]] = []
    for anchor in soup.find_all("a", href=True):
        title = " ".join(anchor.get_text(" ", strip=True).split())
        if primary_phrase not in title and alternate_phrase not in title:
            continue
        if "摘要" in title or "H股公告" in title or "英文版" in title:
            continue
        score = 2 if primary_phrase in title else 1
        candidates.append((score, title, urljoin(BASE, str(anchor["href"]))))
    if not candidates:
        return None
    _, title, detail_url = max(candidates, key=lambda item: item[0])
    return title, detail_url


def _pdf_url(detail_url: str) -> str:
    response = requests.get(detail_url, headers=HEADERS, timeout=30)
    response.raise_for_status()
    text = _decode(response)
    urls = re.findall(r"https?://[^\"'<>\s]+?\.PDF", text, flags=re.IGNORECASE)
    if not urls:
        raise RuntimeError(f"报告详情页未找到 PDF：{detail_url}")
    return urls[0]


def collect(output_dir: Path = OUTPUT_DIR) -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, object]] = []
    for ticker, company in COMPANIES.items():
        for page_type, primary, alternate in TARGETS:
            item: dict[str, object] = {
                "ticker": ticker,
                "company": company,
                "report_type": page_type,
                "listing_url": _listing_url(ticker, page_type),
            }
            try:
                selected = _select_detail(
                    ticker, page_type, primary, alternate
                )
                if selected is None:
                    item["status"] = "not_found"
                    rows.append(item)
                    continue
                title, detail_url = selected
                pdf_url = _pdf_url(detail_url)
                response = requests.get(pdf_url, headers=HEADERS, timeout=90)
                response.raise_for_status()
                raw = response.content
                if not raw.startswith(b"%PDF"):
                    raise RuntimeError("下载内容不是 PDF")
                suffix = "2025年年度报告" if page_type == "ndbg" else "2026年第一季度报告"
                path = output_dir / f"{ticker}_{company}_{suffix}.pdf"
                path = proposed_paper_path(path, project_root=ROOT)
                path.write_bytes(raw)
                item.update(
                    {
                        "status": "downloaded",
                        "title": title,
                        "detail_url": detail_url,
                        "pdf_url": pdf_url,
                        "local_path": str(path.relative_to(ROOT)).replace("\\", "/"),
                        "size_bytes": len(raw),
                        "sha256": _sha256(raw),
                    }
                )
            except Exception as exc:  # noqa: BLE001 - retain per-filing audit result
                item.update(
                    {
                        "status": "failed",
                        "error_type": type(exc).__name__,
                        "error_message": str(exc)[:240],
                    }
                )
            rows.append(item)
    return {
        "schema_version": "lithium.company_filings.v1",
        "collected_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_note": (
            "PDF 为交易所披露文件的新浪财经镜像；manifest 保留详情页和 PDF URL，"
            "研究中按公司法定披露处理，镜像站本身不构成第二条独立证据。"
        ),
        "rows": rows,
        "summary": {
            "downloaded": sum(row.get("status") == "downloaded" for row in rows),
            "not_found": sum(row.get("status") == "not_found" for row in rows),
            "failed": sum(row.get("status") == "failed" for row in rows),
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--manifest", type=Path, default=MANIFEST_PATH)
    args = parser.parse_args(argv)
    result = collect(args.output_dir.resolve())
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    return 0 if result["summary"]["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
