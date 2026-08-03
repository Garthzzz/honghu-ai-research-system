#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""生成「星瀚舆情监测专题配置清单」(交厂商配 subject_id)。
按研究库产业分组列出 104 只 A 股 + 监测关键词(名/简称/代码),并给 config 回填模板。
只读 research.db / sentiment.db,产出 docs/星瀚监测专题清单.md。"""
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
rc = sqlite3.connect(f"file:{(ROOT/'data'/'research.db').as_posix()}?mode=ro", uri=True); rc.row_factory = sqlite3.Row
sc = sqlite3.connect(str(ROOT / "data" / "sentiment.db")); sc.row_factory = sqlite3.Row

comp_ind = {}
for r in rc.execute("SELECT ci.company_id, i.id ind_id, i.name ind_name, ci.role "
                    "FROM company_industry ci JOIN industry i ON i.id=ci.industry_id"):
    comp_ind.setdefault(r["company_id"], []).append((r["ind_id"], r["ind_name"], r["role"]))
alias = {}
for r in sc.execute("SELECT company_id, alias FROM company_alias WHERE alias_type IN ('name','nick','code') ORDER BY id"):
    alias.setdefault(r["company_id"], []).append(r["alias"])
comps = rc.execute("SELECT id,name,ticker FROM company WHERE ticker LIKE '%.SZ' OR ticker LIKE '%.SH' "
                   "OR ticker LIKE '%.SS' OR ticker LIKE '%.BJ' ORDER BY id").fetchall()

groups = {}
for c in comps:
    inds = sorted(comp_ind.get(c["id"], []), key=lambda x: (0 if (x[2] or "")[:2] in ("主营", "核心") else 1, x[0]))
    key = (inds[0][0], inds[0][1]) if inds else (9999, "未分类")
    groups.setdefault(key, []).append(c)

L = ["# 星瀚舆情监测专题配置清单(交厂商配置 subject_id)", "",
     "> **用途**:智慧星光/istarshine 按本清单在后台建「按行业监测专题」,把每只股票的监测关键词(公司名 + 简称 + 股票代码)",
     "> 配进对应专题;建好后把每个行业专题的 **subject_id** 回填到 `config.yaml → sentiment_layers.industry_subjects`",
     "> (key = 研究库 industry_id)。**监测源需覆盖:雪球、微博、新浪/网易/凤凰/今日头条新闻、微信**(对应散户层 + 新闻层)。", "",
     f"> 共 **{len(comps)} 只 A 股 / {len(groups)} 个行业专题**。一只股票可属多产业,此处按主产业归组(归因时仍按全别名闭集匹配,多产业自动多归)。", ""]
for key in sorted(groups):
    gid, gn = key
    cs = groups[key]
    L += [f"## 行业专题:{gn}(industry_id={gid},{len(cs)} 只)→ subject_id:`____待配置____`", "",
          "| 公司 | 代码 | 监测关键词(名/简称/代码,任一命中即归属) |", "|---|---|---|"]
    for c in cs:
        kws = " / ".join(dict.fromkeys(alias.get(c["id"], [c["name"]])))
        L.append(f"| {c['name']} | {c['ticker']} | {kws} |")
    L.append("")

L += ["---", "", "## config.yaml 回填模板(拿到 subject_id 后填)", "", "```yaml",
      "sentiment_layers:", "  industry_subjects:"]
for key in sorted(groups):
    gid, gn = key
    L.append(f'    {gid}: ""   # {gn}  ← 填该行业专题 subject_id')
L += ["```", "",
      "填好后,三层抓取自动对本 104 股加密:雪球/微博(散户)+ 新浪/网易/凤凰/今日头条/微信(新闻),",
      "且按专题精准计费(替代当前全局池 `id=\"\"` 的零星命中)。"]

out = ROOT / "docs" / "星瀚监测专题清单.md"
out.write_text("\n".join(L), encoding="utf-8")
print(f"written {out} | {len(comps)} stocks / {len(groups)} industries")
