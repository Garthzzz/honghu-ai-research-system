#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""P4 翻译(本期 CC session 版):译文 CC 生成,按 id 注入;字面翻译,专有名词保留英文,带原文。
   写 voice_post.content_text_zh / news_item.title_zh,translated_by='cc_session_2026-06-04'。"""
import sqlite3, sys, io
from pathlib import Path
from datetime import date
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
DB = Path(__file__).resolve().parent.parent.parent / "data" / "research.db"
BY = f"cc_session_{date.today().isoformat()}"

VOICE = {
 2:"我们需要改变对华和 GPU 的政策。",
 3:"在我看来,这很说明中国半导体的现实。(转 Qwen@Alibaba:快,更快,Qwen,Qwen3.5 创纪录……)",
 4:"Composer 2.5 在 CursorBench 编程评测中呈帕累托占优,这很重要——而这只是补充训练/RL 几周后的结果。",
 5:"非常喜欢这次讨论,尤其关于 SpaceX 和 NVIDIA 的部分。Anthropic 首季度 EBIT 转正似乎被低估了。",
 6:"很高兴听到 Starcloud 用 SpaceX 发射。对所有质疑在轨算力的人——他们已把一台 H100 送上太空。",
 8:"NVIDIA 的'AI 超大规模厂商'收入在 4 月季度(剔除中国)同比增长 191%;Broadcom 指引同比增长 143%……",
 9:"各类芯片(GPU 或 ASIC)按预期可用寿命可融资的利率,将对需求产生实际影响。",
 10:"不再担心 Meta 基础设施。回复很得体,我诚恳道歉。(转 Andrew:说得对,我对 3D torus 描述有误。)",
 11:"因 Google 网络架构一个晦涩观点,去和在 Meta 做 AI 基础设施的人争论,本不在我今天计划内,但确实发生了。",
 12:"妙。偶尔我也忍不住。(转 Grok:你没说错。Google 的 TPU ICI——含新的 Boardfly/Dragonfly……)",
 15:"想就我在 @SohnIdeaContest 讨论里的观点再展开一下,也感谢 @atelicinvest 的贡献。",
 16:"在 Sohn 与好友 Jas Khaira 的访谈很有趣,是个好公益,推荐捐赠。",
 17:"台湾每年约 10 万新生儿,而 TSMC 每年需在台湾招 1 万人,且只增不减。持续扩张……",
 18:"把已淘汰 GPU 卖给中国的理由:卖给他们比美国本土更落后的 GPU,会降低他们自研出更先进芯片的概率。",
 20:"Sarah 是名人堂级 CFO,与 Colette Kress、David Zinsner、Amy Hood 并列。Susan Li 或将加入,虽早但起点极高。",
 23:"AI 暗输出:不可见输出的可见成本——为何 AI 日益增长的输出将成为史上最难的经济测量问题之一。",
 25:"Anthropic 增长与 Bedrock 结构推升 AWS 利润率,同业落后;Amazon 的 Bedrock 结构与 Anthropic 交易条款叠加,显示更强运营……",
 26:"我对 @SemiAnalysis 印象深刻。我自认是涉猎广泛的系统工程师,从芯片到各层级寻找价值。",
 27:"深入 800VDC 革命(第一部分):四阶段 800VDC 过渡、电源机柜经济性、SST、单 MW 设备含量、供应商影响。",
 30:"精彩观点。(转 Patrick OShaughnessy:Gavin Baker:'我一直乐观地认为晶圆的根本性短缺……')",
}
NEWS = {
 1:"[新闻] 台积电谈 Terafab:晶圆代工无捷径;据报确认下一代 NVIDIA LPU 项目,与 Samsung 竞争",
 6:"[新闻] TSMC 一季度利润预计增约 50% 创纪录;Meta–Broadcom AI 芯片据报瞄准 2nm、CoWoS-L,2027 上半年",
 14:"[新闻] HBM4 策略分化:Samsung 据报冲刺 80% 的 1c DRAM 良率,SK hynix 削减 30% 出货",
 16:"[洞察] NVIDIA 20 亿美元入股 Marvell:对 CPO 与 AI 互联的战略意义?",
 18:"[新闻] 据斯坦福报告,中国 AI 性能差距据报收窄至接近美国;Anthropic 仅领先 2.7%",
 25:"在 Cloudflare 上发布 Claude 托管 Agent",
 41:"xAI 的 Colossus 2——全球首座吉瓦级数据中心、独特 RL 方法论、融资",
 44:"Amazon 的 AI 复兴:AWS 与 Anthropic 的多吉瓦 Trainium 扩张",
 46:"GPT-5 为广告变现与超级应用铺路",
 50:"Meta 超级智能——领先算力、人才与数据",
 177:"[新闻] 据 TrendForce,NVIDIA、Apple 据报以六位数薪酬争抢韩国 HBM、NAND 人才",
 371:"据 TrendForce,Google 高速互联架构将推动 800G+ 光模块份额到 2026 年超 60%",
 377:"[新闻] 据 TrendForce,AI 拉动高速互联,NVIDIA、Google、AWS 提振光模块需求",
 2:"[新闻] TSMC N3 因 AI 需求趋紧;Arizona 二厂 3nm 于 2027 下半年量产,熊本 2028",
 3:"[新闻] TSMC 二季度营收预计环比增 10% 至 402 亿美元;毛利率升至 65.5%–67.5%,资本开支处于 520–560 亿美元上限",
 5:"[新闻] 特斯拉 AI5 据报采用 SK hynix 内存、Samsung LPDDR5X;Samsung SF2T 工艺在 AI6 前应用",
 8:"[新闻] Intel 据报未来数周向员工通报 TeraFab 参与情况,关键代工细节仍有限",
 9:"[新闻] 马斯克确认 AI5 流片,但错误的 TSMC 标签引发社媒混淆",
 10:"[新闻] 中国 2025 年从新加坡、马来西亚进口芯片设备据报创纪录;美国占比降至 2017 年来最低",
 11:"[新闻] ASML 因存储、逻辑需求上调 2026 销售预期至 360–400 亿欧元;韩国份额达 45%",
 12:"[洞察] 内存现货价更新:DRAM 现货卖方在 4 月中定价前坚挺,DDR4 微降 0.48%",
 13:"[新闻] 中国初创公司 Dishan 据报研发 2nm AI 芯片进入原型验证;代工产能获取尚不确定",
 15:"[新闻] 韩国在玻璃基板标准上挑战 Intel,Absolics、Samsung 加速商业化",
 17:"[新闻] 华为在横向折叠屏竞赛中据报领先 Samsung 与 Apple,瞄准 4 月 Pura X Max 发布",
 19:"[新闻] Samsung 2nm 良率据报约 55%,低于量产门槛;高通或转向 TSMC",
 20:"[新闻] Samsung 据报因 AI 热潮将 HBM4 逻辑芯片价格上调 40–50%;4nm 满产",
 22:"我们如何构建 Cloudflare 的数据平台及其上的 AI Agent",
 26:"Project Glasswing:Mythos 向我们展示了什么",
 27:"我们的计费管线突然变慢,元凶是 ClickHouse 中一个隐藏瓶颈",
 28:"Browser Run:现已运行于 Cloudflare Containers,更快更可扩展",
 29:"当'空闲'并非空闲:一个 Linux 内核优化如何变成 QUIC bug",
 30:"为未来而构建",
 31:"Cloudflare 如何应对'Copy Fail'Linux 漏洞",
 32:"当 DNSSEC 出错:我们如何应对 .de 顶级域故障",
 33:"Code Orange:Fail Small 完成,Cloudflare 网络更稳健",
 35:"Cloudflare IPsec 的后量子加密正式可用",
 36:"Agent 现可创建 Cloudflare 账户、购买域名并部署",
 38:"让 Rust Workers 更可靠:wasm-bindgen 中的 panic 与 abort 恢复",
 39:"超越'机器人 vs 人类'",
 43:"华为昇腾产能爬坡:晶圆库存、TSMC 持续生产,HBM 是瓶颈",
 45:"H100 vs GB200 NVL72 训练基准——功耗、TCO 与可靠性分析,软件随时间改进",
 47:"攀越内存墙:HBM 的崛起与路线图",
 48:"机器人自动驾驶等级",
 49:"Intel 18A 细节与成本、DRAM 4F2 vs 3D 的未来、背面供电是否采用、中国的 FlipFET、数字孪生……",
 138:"韩国的 AI 存储主导地位或许不够——ASEAN+3 宏观经济研究办公室",
 139:"Micron 市值触及 1 万亿美元,AI HBM 需求重塑投资者预期——simplywall.st",
 140:"哈佛芯片专家对 AI 存储投资者的警告:'这也会过去'——Fortune",
 141:"Camtek 获得逾 1.05 亿美元先进 AI 与 HBM 半导体设备订单——grafa.com",
 142:"SK hynix 发布'iHBM'散热架构,在源头冷却 AI 内存——HBM 内部集成冷却元件",
 143:"SK hynix 为 AI 系统发布散热集成 HBM——upi.com",
}

def main():
    con = sqlite3.connect(str(DB)); cur = con.cursor()
    now = __import__("datetime").datetime.now().isoformat(timespec="seconds")
    nv = nn = 0
    for vid, zh in VOICE.items():
        if cur.execute("SELECT 1 FROM voice_post WHERE id=?", (vid,)).fetchone():
            cur.execute("UPDATE voice_post SET content_text_zh=?, translated_at=?, translated_by=? WHERE id=?",
                        (zh, now, BY, vid)); nv += cur.rowcount
    for nid, zh in NEWS.items():
        if cur.execute("SELECT 1 FROM news_item WHERE id=?", (nid,)).fetchone():
            cur.execute("UPDATE news_item SET title_zh=?, translated_at=?, translated_by=? WHERE id=?",
                        (zh, now, BY, nid)); nn += cur.rowcount
    con.commit()
    print(f"翻译写入:voice {nv} / news {nn}")
    print("  voice 译完:", cur.execute("SELECT COUNT(*) FROM voice_post WHERE content_text_zh IS NOT NULL").fetchone()[0])
    print("  news 译完:", cur.execute("SELECT COUNT(*) FROM news_item WHERE title_zh IS NOT NULL").fetchone()[0])
    con.close(); print("TRANSLATE CC DONE")

if __name__ == "__main__":
    main()
