"""为本次 Opportunity Lens 资料包生成可审计的 23 份 PDF 筛选台账。"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PDF_DIR = ROOT / "papers" / "比亚迪 立讯精密 光模块"
TEXT_DIR = ROOT / "cache" / "opportunity_lens" / "byd_luxshare_20260718" / "local_pdf_text"
OUT_DIR = (
    ROOT
    / "opportunity_lens"
    / "research_outputs"
    / "20260718_byd_luxshare_optical_module_competition_deep_run"
)

KEYWORDS = (
    "光模块",
    "800G",
    "1.6T",
    "3.2T",
    "高速互联",
    "硅光",
    "CPO",
    "LPO",
    "LRO",
    "NPO",
    "比亚迪电子",
    "立讯精密",
    "中际旭创",
    "新易盛",
)

# 人工审阅后的用途。core 表示可进入背景/模型，但卖方结论仍需一手核验；
# seed 表示只保留线索；duplicate 表示不重复计为来源；off_scope 表示已读但不进入正文。
DECISIONS = {
    1: ("seed", "晨会纪要只作线索，未提供可独立核验的新一手证据。"),
    2: ("core", "用于 AI 基础设施需求与区域产业背景，关键数字需回到原始披露。"),
    3: ("core", "用于比亚迪电子业务结构、估值和市场预期，不证明光模块认证。"),
    4: ("core", "用于立讯通信业务和光模块市场预期，产品/出货说法逐条回到官方。"),
    5: ("core", "用于比亚迪电子 AI 数据中心产品线和财务预期。"),
    6: ("core", "用于四大云厂资本开支线索，并由云厂 IR 独立核验。"),
    7: ("core", "用于立讯 800G/1.6T 出货与收入情景，明确标记为分析师预测。"),
    8: ("core", "用于服务器、液冷、电源、高速互联一体化线索，不等同光模块能力。"),
    9: ("core", "用于光学厂商跨界、技术路线和竞争机制背景。"),
    10: ("core", "用于立讯 2026H2 后光模块放量的市场预期；与第 11 份同源聚类。"),
    11: ("duplicate_translation", "与第 10 份为同日同机构同一底层报告的另一语言/版本，不计独立来源。"),
    12: ("seed", "亚太科技追踪用于发现新增线索，不单独支持核心结论。"),
    13: ("core", "用于立讯港股发行材料和公开业务边界核验。"),
    14: ("seed", "用于比亚迪集团资本与战略背景，不证明比亚迪电子光模块能力。"),
    15: ("exact_duplicate", "与第 14 份 SHA256 完全一致，不重复读取或计数。"),
    16: ("core", "用于比亚迪电子最新业务和财务预期，光互联表述仍需官方核验。"),
    17: ("core", "用于 NPO 标准与产业路线线索，由 MSA/成员官方资料核验。"),
    18: ("core", "用于苹果供应商向 AI 基础设施迁移的市场预期与反方约束。"),
    19: ("core", "用于服务器、AI 基础设施和电子元器件综合背景。"),
    20: ("seed", "用于比亚迪股份财务与战略优先级，不直接映射光模块能力。"),
    21: ("core", "用于 2026 年技术路线和产业交易逻辑背景，由官方技术资料复核。"),
    22: ("core", "用于行业现状、龙头产销量和财务线索，原始数字回到年报。"),
    23: ("off_scope_auxiliary", "800VDC 是数据中心供电架构旁证，与光模块进入概率关系间接。"),
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _index_from_name(name: str) -> int:
    match = re.match(r"(\d{2})_", name)
    if not match:
        raise ValueError(f"提取文本缺少两位序号：{name}")
    return int(match.group(1))


def build_inventory() -> dict:
    pdfs = sorted(PDF_DIR.glob("*.pdf"), key=lambda path: path.name.lower())
    texts = sorted(TEXT_DIR.glob("*.txt"), key=lambda path: _index_from_name(path.name))
    if len(pdfs) != 23 or len(texts) != 23:
        raise RuntimeError(f"预期 23 PDF/23 text，实际 {len(pdfs)}/{len(texts)}")
    pdf_by_stem = {path.stem: path for path in pdfs}
    rows = []
    for text_path in texts:
        index = _index_from_name(text_path.name)
        original_stem = text_path.stem.split("_", 1)[1]
        pdf_path = pdf_by_stem.get(original_stem)
        if not pdf_path:
            raise FileNotFoundError(f"找不到对应 PDF：{text_path.name}")
        text = text_path.read_text(encoding="utf-8", errors="replace")
        status, reason = DECISIONS[index]
        rows.append(
            {
                "index": index,
                "filename": pdf_path.name,
                "relative_path": pdf_path.relative_to(ROOT).as_posix(),
                "extracted_text_path": text_path.relative_to(ROOT).as_posix(),
                "pdf_sha256": _sha256(pdf_path),
                "pdf_bytes": pdf_path.stat().st_size,
                "text_characters": len(text),
                "keyword_hits": {keyword: text.lower().count(keyword.lower()) for keyword in KEYWORDS},
                "screening_status": status,
                "screening_reason": reason,
                "evidence_policy": (
                    "卖方材料仅作线索、预测或市场预期；关键产品、客户、认证、产能和财务事实"
                    "必须回到公司/客户/供应商/标准组织/监管原文。"
                ),
            }
        )
    digest_counts = Counter(row["pdf_sha256"] for row in rows)
    return {
        "inventory_version": "byd_luxshare_local_material_screening.v1",
        "pdf_count": len(rows),
        "unique_sha256_count": len(digest_counts),
        "exact_duplicate_groups": [
            [row["index"] for row in rows if row["pdf_sha256"] == digest]
            for digest, count in digest_counts.items()
            if count > 1
        ],
        "status_count": dict(Counter(row["screening_status"] for row in rows)),
        "materials": rows,
    }


def main() -> None:
    inventory = build_inventory()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    json_path = OUT_DIR / "local_material_screening.json"
    json_path.write_text(json.dumps(inventory, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "# 本地资料包筛选台账",
        "",
        f"- PDF：{inventory['pdf_count']} 份",
        f"- 唯一 SHA256：{inventory['unique_sha256_count']} 份",
        f"- 精确重复组：{inventory['exact_duplicate_groups']}",
        "",
        "| # | 状态 | 文件 | 判定 |",
        "|---:|---|---|---|",
    ]
    for row in inventory["materials"]:
        lines.append(
            f"| {row['index']} | {row['screening_status']} | {row['filename'].replace('|', '/')} | "
            f"{row['screening_reason'].replace('|', '/')} |"
        )
    (OUT_DIR / "local_material_screening.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {json_path}")
    print(
        f"pdf={inventory['pdf_count']} unique_sha={inventory['unique_sha256_count']} "
        f"duplicates={inventory['exact_duplicate_groups']}"
    )


if __name__ == "__main__":
    main()
