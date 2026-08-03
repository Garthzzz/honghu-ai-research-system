"""
M1 metric 规范化迁移(2026-05-28)
------------------------------------------------------------
目标:把 327 个 unique metric 收敛到 ~60-80 个 canonical metric
方法:对每个违规 metric 写映射 → 更新 industry_data_point 行
   - entity 信息 → company_id 字段(若有对应 company)
   - 产品代号 / 技术名 / 合作关系 / 口径 → 追加到 note 字段
   - period 后缀(Q1/Q3 等)若已在 metric 中 → 迁到 as_of_date
保留:所有 402 个 data_point,只重新归类
不保留:全部违规的旧 metric 字符串
"""
from __future__ import annotations
import sqlite3, sys, re, json
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'pipeline'))

ROOT = Path(__file__).resolve().parent.parent.parent
DB = ROOT / 'data' / 'research.db'

conn = sqlite3.connect(str(DB))
conn.row_factory = sqlite3.Row

# ---- 1. 读 company name → id 映射 ----
company_by_name = {r['name']: r['id'] for r in conn.execute("SELECT id, name FROM company")}

def cid(name: str) -> int | None:
    """name 查 company_id;别名映射"""
    aliases = {
        '英伟达': 'NVIDIA', '博通': 'Broadcom',
        '甲骨文': 'Oracle', '微软': 'Microsoft',
        '亚马逊': 'Amazon', '谷歌': 'Google',
        '阿里': '阿里巴巴', 'AMD': 'AMD',
        'Lumentum公司': 'Lumentum', 'Coherent公司': 'Coherent',
        'BAT': None,  # 不映射(三家合并指标)
        '住友': 'Sumitomo', '住友电气': 'Sumitomo',
        'AXT公司': 'AXT', '北京通美': '北京通美',
        '联讯仪器': '联讯仪器', '凯格精机': '凯格精机',
        '罗博特科': '罗博特科', '博众精工': '博众精工',
        '瑞松科技': '瑞松科技', '普源精电': '普源精电',
        '华盛昌': '华盛昌', '日联科技': '日联科技',
        '科瑞技术': '科瑞技术', '智立方': '智立方',
        '燕麦科技': '燕麦科技', '易天股份': '易天股份',
        '优利德': '优利德', '鼎阳科技': '鼎阳科技',
        '华兴源创': '华兴源创', '快克智能': '快克智能',
        '猎奇智能': '猎奇智能', 'ASMPT': 'ASMPT', 'MRSI': 'MRSI',
    }
    actual = aliases.get(name, name)
    if actual is None:
        return None
    return company_by_name.get(actual)


# ---- 2. metric 映射表 ----
# 格式: 旧 metric → (新 canonical metric, company_name 或 None, note_prefix 或 None)
# note_prefix 会 prepend 到现有 note(已有 note 就用 ' | ' 拼接)
M = {}
def add(old, new, company=None, note=None):
    M[old] = (new, company, note)

# ============= 中国头部模块厂业绩 =============
for c, prefix in [('中际旭创', '中际旭创'), ('新易盛', '新易盛'), ('天孚通信', '天孚通信')]:
    add(f'{prefix}_Q1营收', '季度营收(亿元)', c)
    add(f'{prefix}_Q1营收_YoY', '季度营收_YoY(%)', c)
    add(f'{prefix}_Q1归母净利', '季度归母净利润(亿元)', c)
    add(f'{prefix}_Q1归母净利_YoY', '季度归母净利润_YoY(%)', c)
    add(f'{prefix}_2025Q3归母净利润', '季度归母净利润(亿元)', c)
    add(f'{prefix}_2025Q3归母净利润同比', '季度归母净利润_YoY(%)', c)

add('中际旭创_中国AI光模块份额', '公司市占率(%)', '中际旭创', '中国 AI 光模块')
add('新易盛_中国AI光模块份额', '公司市占率(%)', '新易盛', '中国 AI 光模块')
add('光迅科技_中国AI光模块份额', '公司市占率(%)', '光迅科技', '中国 AI 光模块')
add('海信宽带_中国AI光模块份额', '公司市占率(%)', None, '海信宽带 / 中国 AI 光模块')
add('海光芯创_中国AI光模块份额', '公司市占率(%)', None, '海光芯创 / 中国 AI 光模块')

add('中际旭创_主营业务光通信收发模块营收', '全年营收(亿元)', '中际旭创', '主营业务光通信收发模块')
add('中际旭创_光模块销量', '公司出货量(万只)', '中际旭创', None)
add('中际旭创_全年毛利率', '整体毛利率(%)', '中际旭创', None)
add('中际旭创_境外营收', '海外业务营收(亿元)', '中际旭创', None)
add('中际旭创_合理价值_广发', '公司目标价(元)', '中际旭创', '广发')
add('中际旭创_2025E_PE_广发', 'PE_FY1', '中际旭创', '广发')
add('新易盛_主要产品营收集中度', '主营产品集中度(%)', '新易盛', None)
add('新易盛_国外业务营收占比', '海外业务占比(%)', '新易盛', None)
add('新易盛_合理价值_广发', '公司目标价(元)', '新易盛', '广发')
add('新易盛_5月涨幅', '公司股价_月涨幅(%)', '新易盛', '2025-05')
add('天孚通信_Q1营收', '季度营收(亿元)', '天孚通信', None)
add('天孚通信_Q1归母净利', '季度归母净利润(亿元)', '天孚通信', None)
add('天孚通信_整体毛利率', '整体毛利率(%)', '天孚通信', None)
add('天孚通信_外销收入占比', '海外业务占比(%)', '天孚通信', None)
add('天孚通信_有源占比', '公司业务结构_有源占比(%)', '天孚通信', None)
add('天孚通信_研发投入', '研发投入(亿元)', '天孚通信', None)
add('天孚通信_合理价值_广发', '公司目标价(元)', '天孚通信', '广发')
add('天孚通信_2025E_PE_东北', 'PE_FY1', '天孚通信', '东北证券')
add('腾景科技_2025E_PE', 'PE_FY1', '腾景科技', '东北证券')
add('源杰科技_2024E_PE', 'PE_FY1', '源杰科技', '东北证券')
add('高盛_中际旭创_目标价', '公司目标价(元)', '中际旭创', '高盛')

# ============= 设备厂业绩 =============
for c in ['联讯仪器','凯格精机','罗博特科','博众精工','瑞松科技','普源精电']:
    add(f'{c}_营收_YoY', '季度营收_YoY(%)', c)
    add(f'{c}_归母净利_YoY', '季度归母净利润_YoY(%)', c)
add('联讯仪器_毛利率', '整体毛利率(%)', '联讯仪器')
add('联讯仪器_净利率', '公司净利率(%)', '联讯仪器')

# ============= CSP CapEx =============
for c, prefix in [
    ('Amazon','Amazon'),('Microsoft','Microsoft'),('Meta','Meta'),('Google','Google'),
    ('阿里巴巴','阿里巴巴'),('腾讯','腾讯')]:
    add(f'{prefix}_CapEx', 'CapEx(亿美元)', c)
    add(f'{prefix}_CapEx_YoY', 'CapEx_YoY(%)', c)
    add(f'{prefix}_季度CapEx', 'CapEx(亿美元)' if c not in ('阿里巴巴','腾讯') else 'CapEx(亿元)', c)
    add(f'{prefix}_CapEx_2026', 'CapEx(亿美元)', c, '2026 指引')
add('谷歌_季度CapEx_下限_2024Q4', 'CapEx(亿美元)', 'Google', '24Q4 下限')
add('谷歌_2026计划资本开支', 'CapEx(亿美元)', 'Google', '2026 计划')
add('谷歌_CapEx_YoY', 'CapEx_YoY(%)', 'Google', None)
add('微软_FY25Q2资本开支', 'CapEx(亿美元)', 'Microsoft', 'FY25Q2')
add('微软_CapEx_YoY', 'CapEx_YoY(%)', 'Microsoft', None)
add('亚马逊_2026计划资本开支', 'CapEx(亿美元)', 'Amazon', '2026 计划')
add('亚马逊AWS_未完成订单', '公司订单backlog(亿美元)', 'Amazon', 'AWS')
add('BAT_2025Q3总资本开支', '中国主要厂商_CapEx合计(亿元)', None, 'BAT 三家合计')
add('腾讯_CapEx_YoY', 'CapEx_YoY(%)', '腾讯', None)
add('阿里_3年AI计划投入', '多年AI投入计划(亿元)', '阿里巴巴', '3 年累计')

add('北美4CSP_CapEx_2026', '北美CSP_CapEx合计(亿美元)', None, '4 家:AMZN+MSFT+GOOG+META')
add('北美4大云厂_CapEx', '北美CSP_CapEx合计(亿美元)', None, '4 大')
add('北美4大云厂_前3季CapEx_YoY', '北美CSP_CapEx_YoY(%)', None, '24Q1-Q3 5 家')
add('北美八大CSP_Capex', '北美CSP_CapEx合计(亿美元)', None, '8 大,慧博口径')
add('北美四大CSP_CapEx', '北美CSP_CapEx合计(亿美元)', None, '4 大')
add('北美四大CSP_CapEx_YoY', '北美CSP_CapEx_YoY(%)', None, '4 大')
add('五大CSP_CapEx', '北美CSP_CapEx合计(亿美元)', None, '5 大,汇丰口径')
add('八大CSP_CapEx_TrendForce', '北美CSP_CapEx合计(亿美元)', None, '8 大,TrendForce')
add('八大CSP_CapEx_YoY_TrendForce', '北美CSP_CapEx_YoY(%)', None, '8 大,TrendForce')
add('国内云服务三大厂_CapEx_2025_YoY', '中国主要厂商_CapEx_YoY(%)', None, '三大云厂')
add('中国4大云厂_CapEx', '中国主要厂商_CapEx合计(亿元)', None, '4 大')
add('北美巨头_占全球AI光模块采购需求', '客户采购集中度(%)', None, '北美 4 巨头+NVIDIA / AI 光模块')

# ============= NVIDIA =============
add('NVIDIA_FY26Q1_数据中心_YoY', '数据中心营收_YoY(%)', 'NVIDIA', None)
add('NVIDIA_FY26Q1_整体营收_YoY', '季度营收_YoY(%)', 'NVIDIA', None)
add('NVIDIA_H20出口管制_影响', '单产品出口管制影响(亿美元)', 'NVIDIA', 'H20')
add('NVIDIA_CPO投资_Coherent', 'CPO战略投资金额(亿美元)', 'NVIDIA', 'NVIDIA 投 Coherent 2026-03-02')
add('NVIDIA_CPO投资_Lumentum', 'CPO战略投资金额(亿美元)', 'NVIDIA', 'NVIDIA 投 Lumentum 2026-03-02')
add('NVIDIA_数据中心_季度营收占比', '数据中心业务营收占比(%)', 'NVIDIA', None)
add('NVIDIA_Quantum-X800_Q3450_光引擎数', '光引擎数(个)', 'NVIDIA', 'Quantum-X800 Q3450 IB CPO 交换机')
add('NVIDIA_Quantum-X800_Q3450_光纤数', '光纤数(根)', 'NVIDIA', 'Quantum-X800 Q3450 IB CPO')
add('NVIDIA_Quantum-X800_Q3450_MPO端口', '单产品端口数', 'NVIDIA', 'Quantum-X800 Q3450 MPO')
add('Quantum-X_单switch带宽', '单switch带宽(Tbps)', 'NVIDIA', 'Quantum-X Photonics + Spectrum-X Photonics')
add('NVIDIA加速器_出货量', 'GPU出货量(千台)', 'NVIDIA', None)

# ============= AAOI =============
add('AAOI_单季营收', '季度营收(百万美元)', 'AAOI', None)
add('AAOI_单季营收_YoY', '季度营收_YoY(%)', 'AAOI', None)
add('AAOI_单季营收_QoQ', '季度营收_QoQ(%)', 'AAOI', None)
add('AAOI_单季净亏损', '季度归母净利润(百万美元)', 'AAOI', None)
add('AAOI_数据中心业务_单季营收', '业务线营收(百万美元)', 'AAOI', '数据中心业务')
add('AAOI_数据中心_200G400G_单季营收', '产品线营收(百万美元)', 'AAOI', '数据中心 200G/400G')
add('AAOI_有线电视业务_单季营收', '业务线营收(百万美元)', 'AAOI', '有线电视 / HFC')
add('AAOI_400G高端光模块_未来几年累计', '多年产品累计营收预期(百万美元)', 'AAOI', '400G 高端模块')
add('AAOI_员工人数', '公司员工数(人)', 'AAOI', None)
add('AAOI_客户份额_Microsoft', '公司客户份额(%)', 'AAOI', '客户:Microsoft')
add('AAOI_客户份额_ATX', '公司客户份额(%)', 'AAOI', '客户:ATX')
add('AAOI_LPO模块速率', '单通道速率(Gbps)', 'AAOI', '1.6T OSFP DR8 LPO 模块')

# ============= Coherent / Lumentum / AXT =============
add('Coherent_FY26Q1营收', '季度营收(十亿美元)', 'Coherent', None)
add('Coherent_数据中心_YoY', '数据中心营收_YoY(%)', 'Coherent', None)
add('Coherent_6英寸晶圆_产能提升幅度', '产能提升幅度(%)', 'Coherent', '6 英寸 InP 晶圆 / 2026 年底翻倍')
add('Lumentum_光芯片产能_扩产幅度', '产能提升幅度(%)', 'Lumentum', '光芯片产能 / 未来几季扩 40%')
add('AXT_InP衬底_单订单', '单笔订单金额(万美元)', 'AXT', 'InP 衬底 / 创历史新高')
add('CoreWeave_25Q1营收_YoY', '季度营收_YoY(%)', 'CoreWeave', None)
add('Oracle_GPU采购计划', 'GPU采购金额(亿美元)', 'Oracle', 'GB200 / 星际之门项目')
add('xAI_GPU规划', 'GPU规划总量(万张)', 'xAI', None)

# ============= Broadcom 产品参数(全部 entity → note)=============
add('Broadcom_Bailly_CPO速率', 'CPO速率(Tbps)', 'Broadcom', 'Bailly / 51.2Tbps Tomahawk 5 + 8 个 6.4T 硅光引擎')
add('Broadcom_Bailly_功耗下降', '单产品功耗下降(%)', 'Broadcom', 'Bailly vs 传统可插拔')
add('Broadcom_TH6_Davisson_光引擎数', '光引擎数(个)', 'Broadcom', 'Tomahawk6 Davisson / 6.4T 光引擎')
add('Broadcom_TH6_Davisson_端口数', '单产品端口数', 'Broadcom', 'Tomahawk6 Davisson')
add('Broadcom_Tomahawk5_Bailly_CPO容量', 'CPO容量(Tbps)', 'Broadcom', 'Tomahawk5 Bailly')
add('Broadcom_Tomahawk6_Davisson_CPO容量', 'CPO容量(Tbps)', 'Broadcom', 'Tomahawk6 Davisson')
add('Broadcom_Tomahawk4_Humboldt_CPO_Gen1_启动年', '产品启动年', 'Broadcom', 'Tomahawk4 Humboldt CPO Gen1')
add('Broadcom_Sian2_BCM85822_DSP速率', 'DSP速率(Tbps)', 'Broadcom', 'Sian2 BCM85822')
add('Broadcom_Sian3_DSP速率', 'DSP速率(Tbps)', 'Broadcom', 'Sian3')
add('Broadcom_Sian3_DSP_工艺节点', '制程节点(nm)', 'Broadcom', 'Sian3 DSP')
add('Broadcom_Taurus_BCM83640_DSP速率', 'DSP速率(Tbps)', 'Broadcom', 'Taurus BCM83640 / 1.6T monolithic 3nm')
add('Broadcom_Taurus_BCM83640_发布', '产品发布日期', 'Broadcom', 'Taurus BCM83640')
add('Broadcom_200G_VCSEL_CW_laser_发布日期', '产品发布日期', 'Broadcom', '200G VCSEL CW laser')
add('Broadcom_Meta_MTIA初始承诺算力', '合作初始算力承诺(单位)', 'Broadcom', 'Broadcom × Meta MTIA')
add('Broadcom_Meta合作延长截止年', '合作截止年', 'Broadcom', 'Broadcom × Meta')
add('Broadcom_累计出货_100G_lane通道数', '公司累计出货通道数(亿条)', 'Broadcom', '100G lane')

# ============= NVL576 / 集群案例 =============
add('NVL576_B200_集群功耗_DSP', '单集群功耗(kW)', None, 'NVL576 B200 / DSP 方案')
add('NVL576_B200_集群功耗_CPO', '单集群功耗(kW)', None, 'NVL576 B200 / CPO 方案')
add('大规模AI集群_DSP_CPO节省', '集群功耗节省(%)', None, '30528 GPU 集群 DSP→CPO')
add('华为昇腾910C_单系统光模块需求', '单系统光模块需求(只)', '华为', '昇腾 910C CloudMatrix 384 节点 / 400G')

# ============= 单 GPU 配比 =============
add('1.6T_per_GPU_GB300', '单GPU光模块配比(只)', None, '1.6T × GB300 代次')
add('1.6T_per_GPU_Rubin', '单GPU光模块配比(只)', None, '1.6T × Rubin 代次')
add('3.2T_per_GPU_Rubin_Ultra', '单GPU光模块配比(只)', None, '3.2T × Rubin Ultra')
add('3.2T_per_GPU_Feynman', '单GPU光模块配比(只)', None, '3.2T × Feynman')
add('单GPU光模块配比_NVIDIA', '单GPU光模块配比(只)', 'NVIDIA', None)
add('单GPU光模块配比_均值', '单GPU光模块配比_均值(只)', None, '加速器配比均值')
add('单GPU配比_B300代', '单GPU光模块配比(只)', None, 'B300 代次,慧博口径 1:4.5-1:8')
add('optical_transceivers_per_GPU_typical', '单GPU光模块配比(只)', None, '行业典型值')

# ============= 上游 InP / EML =============
add('InP衬底_Sumitomo份额', '公司市占率(%)', 'Sumitomo', 'InP 衬底全球市场')
add('InP衬底_北京通美份额', '公司市占率(%)', '北京通美', 'InP 衬底全球市场')
add('InP衬底_全球CR3', 'CR3', None, 'InP 衬底')
add('InP衬底_海外主供应商', '海外主供应商列表', None, 'InP 衬底 / Sumitomo+北京通美+JX')
add('全球InP衬底_市场规模', 'TAM_USD', None, '全球 InP 衬底,Yole 口径')
add('全球InP衬底_销量', '全行业出货量(万片)', None, 'InP 衬底,折 2 英寸')
add('国内高纯铟_CR4', 'CR4', None, '国内高纯铟')
add('EML_全球供应商数', '供应商数(家)', None, 'EML 全球(Lumentum+Coherent+住友+三菱+博通)')
add('EML外延_海外寡头', '海外寡头列表', None, 'EML 外延')
add('EML_800G_总成本', '单模块成本(USD)', None, 'EML 800G 模块')
add('MOCVD_交货周期', '设备交货周期(月)', None, 'MOCVD / EML 扩产')
add('CW光源_海外主供应商', '海外主供应商列表', None, 'CW 光源 / 住友电气占半')
add('InP_6英寸_光芯片产量提升倍数', '产量提升倍数', None, 'InP 6 英寸 vs 3 英寸')
add('InP_6英寸_成本下降幅度', '成本下降幅度(%)', None, 'InP 6 英寸 vs 3 英寸')

# ============= 行业聚合(口径剥离到 note)=============
add('800G_shipment_units', '全行业出货量(M units)', None, '800G,Goldman 口径')
add('1.6T_shipment_units', '全行业出货量(M units)', None, '1.6T')
add('3.2T_shipment_units', '全行业出货量(M units)', None, '3.2T')
add('800G_above_total_shipment_units', '全行业出货量(M units)', None, '800G+')
add('800G_above_CAGR_2026_2028', '全行业CAGR_3Y(%)', None, '800G+ 价值 TAM 2026-2028')
add('800G_above_demand_CAGR_2026_2028', '全行业CAGR_3Y(%)', None, '800G+ 出货量 2026-2028')
add('800G_above_shipment_revision_pct', '预测上调幅度(%)', None, '800G+ 出货预测上调')
add('800G_and_above_TAM_USD', 'TAM_USD', None, '800G+ 价值 TAM,高盛口径')
add('800G_出货量增速_LightCounting口径', '全行业出货量_YoY(%)', None, '800G,LightCounting')
add('800G_量产状态', '量产状态(文字)', None, '800G')
add('800G_1.6T光芯片_贴片精度', '贴片精度(μm)', None, '800G/1.6T 光芯片')
add('800G光芯片_贴片精度要求', '贴片精度(μm)', None, '800G 光芯片')
add('1.6T光芯片_贴片精度要求', '贴片精度(μm)', None, '1.6T 光芯片')
add('800G模块_设备投入_100万支', '设备投入(亿元)', None, '800G 模块 100 万支产能')
add('800G模块_采样示波器_带宽', '测试带宽要求(GBaud)', None, '800G 模块 / 误码仪')
add('1.6T模块_采样示波器_带宽', '测试带宽要求(GBaud)', None, '1.6T 模块 / 误码仪')
add('100G以上_以太网光模块_市场规模', 'TAM_USD', None, '100G+ 以太网光模块,LightCounting')
add('全球以太网光模块_LightCounting口径_800G+1.6T', 'TAM_USD', None, 'LightCounting 800G+1.6T 以太网')
add('全球光模块市场规模_中商口径', 'TAM_USD', None, '中商口径')
add('全球光模块_CAGR_5Y_中商口径', '全行业CAGR_5Y(%)', None, '中商口径')
add('全球光模块_市场规模', 'TAM_USD', None, 'Yole 全球光模块 2027 247 亿')
add('全球数通光模块_市场规模', 'TAM_USD', None, 'Yole 数通光模块')
add('全球光收发器_市场规模', 'TAM_USD', None, '光收发器 / LightCounting+海通')
add('全球光收发器_CAGR_2022_2027', '全行业CAGR_5Y(%)', None, '光收发器 22-27,LightCounting 11%')
add('全球光模块封测设备_CAGR', '全行业CAGR_5Y(%)', None, '光模块封测设备')
add('全球光模块封测设备市场规模', 'TAM_USD', None, '光模块封测设备')
add('全球光芯片_市场规模', 'TAM_USD', None, '全球光芯片,源杰招股书')
add('全球光芯片_CAGR_2024_2030', '全行业CAGR_5Y(%)', None, '光芯片 2024-2030 44%')
add('全球硅光模块_市场规模', 'TAM_USD', None, 'Yole 硅光模块 2029 103 亿')
add('全球硅光模块_5Y_CAGR', '全行业CAGR_5Y(%)', None, 'Yole 硅光 45%')
add('全球硅光模块_销量', '全行业出货量(万只)', None, 'Yole 硅光销量')
add('全球高速光芯片_2024_YoY', '全行业出货量_YoY(%)', None, '全球高速光芯片,和弦口径')
add('全球云计算_市场规模', '云计算TAM_USD', None, '世界云计算')
add('全球云计算_CAGR_2022_2030', '全行业CAGR_5Y(%)', None, '云计算 22-30 17.43%')
add('数通光模块_出货量', '全行业出货量(M units)', None, '数通光模块')
add('数通光模块_CAGR_23_29', '全行业CAGR_5Y(%)', None, '数通光模块 23-29,Yole 31%')
add('硅光_市场份额_LightCounting口径', '技术路线渗透率(%)', None, '硅光 / LightCounting')
add('硅光_占光模块比例', '技术路线渗透率(%)', None, '硅光占比')
add('硅光_出货量', '全行业出货量(万只)', None, '硅光出货')
add('硅光_出货量_CAGR_23_29', '全行业CAGR_5Y(%)', None, '硅光 23-29 通道 98%')
add('硅光_vs_EML_成本节省比例', '技术路线成本节省(%)', None, '硅光 vs EML')
add('硅光_800G_CW光源单价', '单元件价格(USD)', None, '硅光 800G CW 光源')
add('硅光_800G_DSP成本', '单元件成本(USD)', None, '硅光 800G DSP')
add('硅光_800G_硅光芯片成本', '单元件成本(USD)', None, '硅光 800G 芯片')
add('硅光_800G_总成本', '单模块成本(USD)', None, '硅光 800G 总')
add('硅光产业_当前阶段', '技术成熟度阶段', None, '硅光产业')
add('硅光模块_成本节省', '技术路线成本节省(%)', None, '硅光模块 vs 传统')
add('硅光模块_功耗优化', '单模块功耗下降(%)', None, '硅光 vs 传统')
add('硅光模块_体积缩小', '产品体积下降(%)', None, '硅光 vs 传统')
add('硅光模块_组件数', '产品组件数(个)', None, '硅光模块')
add('硅光芯片_设计_主导厂商', '主导厂商列表', None, '硅光芯片设计')
add('硅光_5G基站_功耗下降', '单模块功耗下降(%)', None, '硅光 5G 基站前传')
add('SiPh_penetration_overall_volume', '技术路线渗透率(%)', None, '硅光整体出货占比')
add('SiPh_penetration_800G_volume', '技术路线渗透率(%)', None, '硅光 800G 渗透')
add('SiPh_penetration_1.6T_volume', '技术路线渗透率(%)', None, '硅光 1.6T 渗透')
add('SiPh_penetration_3.2T_volume', '技术路线渗透率(%)', None, '硅光 3.2T 渗透')
add('SiPh_penetration_800G_above_value', '技术路线渗透率(%)', None, '硅光 800G+ 价值占比')
add('SiPh_share_800G_above_units', '技术路线渗透率(%)', None, '硅光 800G+ 出货占比,高盛')
add('硅光CPO_总带宽_HVM', '单产品带宽(Gbps)', None, '硅光 HVM 当前可插拔')
add('硅光CPO_总带宽_CPO时代', '单产品带宽(Gbps)', None, '硅光 CPO 时代')
add('硅光CPO_能效_HVM', '单产品能效(pJ/bit)', None, '硅光 HVM')
add('硅光CPO_能效_CPO时代', '单产品能效(pJ/bit)', None, '硅光 CPO')
add('TFLN_功耗节省', '技术路线功耗节省(%)', None, 'TFLN 调制器')
add('TAM_revision_value_pct', '预测上调幅度(%)', None, '高盛 800G+ TAM 上调')
add('Below_400G_shipment_share', '低速光模块占比(%)', None, '400G 以下')
add('Global_Optical_Module_TAM_USD', 'TAM_USD', None, '全球光模块,LightCounting')
add('Global_Server_Revenue_USD', '全球服务器营收(亿美元)', None, '所有服务器')
add('Global_Total_Shipment', '全行业出货量(M units)', None, '全球光模块')
add('Nvidia_AI_chips_units', 'GPU出货量(千台)', 'NVIDIA', None)
add('Nvidia_rack_AI_servers_units', 'AI服务器出货量(units)', 'NVIDIA', 'NVIDIA AI 服务器机柜')
add('AI_training_server_revenue_YoY', 'AI服务器营收_YoY(%)', None, 'AI 训练服务器')
add('AI_training_server_shipment_YoY', 'AI服务器出货量_YoY(%)', None, 'AI 训练服务器')
add('AI加速器_总出货量', 'AI加速器总出货量(千台)', None, '汇丰口径 NVIDIA+ASIC')
add('ASIC_share_in_total_AI_chips', 'ASIC_占AI加速器比例(%)', None, 'ASIC 在 AI 加速器份额')
add('ASIC_占AI加速器比例', 'ASIC_占AI加速器比例(%)', None, None)
add('General_server_shipment_YoY', '通用服务器出货量_YoY(%)', None, None)
add('AI数据中心_电力延迟项目占比', 'AI数据中心电力延迟项目占比(%)', None, None)
add('AI集群_以太网光模块_2024_YoY', '全行业出货量_YoY(%)', None, 'AI 集群以太网光模块,LightCounting')
add('AI集群_以太网光模块_2025_YoY_预期', '全行业出货量_YoY(%)', None, 'AI 集群以太网 2025 预期')

# ============= CPO 行业聚合 =============
add('CPO_share_800G_above_units', '技术路线渗透率(%)', None, 'CPO 占 800G+,高盛')
add('CPO_占800G_1.6T端口比例', '技术路线渗透率(%)', None, 'CPO 占 800G+1.6T,LightCounting')
add('CPO_市场规模', 'TAM_USD', None, 'CPO IDTechEx')
add('CPO_市场规模_国金', 'TAM_USD', None, 'CPO 国金/ASE 口径')
add('CPO_市场规模_2028上量', 'CPO 上量节点(文字)', None, '2028 开始上量')
add('CPO_CAGR_2025_2035', '全行业CAGR_5Y(%)', None, 'CPO 25-35,IDTechEx 28.9%')
add('CPO_未来三年渗透率', '技术路线渗透率(%)', None, 'CPO 未来 3 年定性')
add('CPO_功耗节省_vs_DSP', '技术路线功耗节省(%)', None, 'CPO vs DSP / 西部口径')
add('CPO_功耗节省_vs_DSP_国金', '技术路线功耗节省(%)', None, 'CPO vs DSP / 国金口径')
add('CPO_每800G功耗', '单模块功耗(W)', None, 'CPO 每 800G NVIDIA Q3450')
add('CPO_MTBF', '单产品MTBF(万小时)', None, 'CPO 模块')
add('CPO_单故障影响端口数', '单故障影响端口数', None, 'CPO')
add('CPO_光引擎单套成本', '单元件成本(万美元)', None, 'CPO 光引擎含 FAU')
add('CPO_光模块成本节省', '技术路线成本节省(%)', None, 'CPO vs 可插拔 / 光模块成本')
add('CPO_网络成本节省', '技术路线成本节省(%)', None, 'CPO vs 可插拔 / 网络成本')
add('CPO_集群总成本节省', '技术路线成本节省(%)', None, 'CPO vs 可插拔 / 总成本')
add('CPO_Scale_out_总功耗节省', '技术路线功耗节省(%)', None, 'CPO Scale-out 三层网络')
add('CPO_全球首发时点', '技术首发时点', None, 'CPO NVIDIA 2025-03')
add('CPO_供应链中国厂商参与环节', 'CPO供应链中国参与环节', None, '名单文字')
add('可插拔模块_MTBF', '单产品MTBF(万小时)', None, '传统可插拔')
add('LPO_功耗下降_vs_DSP', '技术路线功耗节省(%)', None, 'LPO vs DSP 海通')
add('LPO_功耗节省', '技术路线功耗节省(%)', None, 'LPO 50%')
add('LPO_DSP成本节省_400G', '技术路线成本节省(%)', None, 'LPO vs DSP / 400G BOM')
add('XPO_单模块带宽', '单产品带宽(Tbps)', None, 'XPO MSA Arista')
add('XPO_面板密度提升倍数', '面板密度提升倍数', None, 'XPO vs 1600G-OSFP')

# ============= LightCounting / Yole 数据 =============
add('LightCounting_2026_DC全TAM', 'TAM_USD', None, 'LightCounting 全 DC 光模块 2026')
add('LightCounting_800G_2026出货', '全行业出货量(M units)', None, 'LightCounting 800G 2026')
add('LightCounting_1.6T_2026出货', '全行业出货量(M units)', None, 'LightCounting 1.6T 2026')
add('Ethernet光模块_2026_YoY', '全行业出货量_YoY(%)', None, 'Ethernet 光模块,LightCounting')

# ============= 1.6T 内容(已合规,加 note 即可)=============
add('1.6T_EML_laser_content_per_module', '单模块上游元件含量(US$)', None, '1.6T EML 激光器')
add('1.6T_SiPh_laser_content_per_module', '单模块上游元件含量(US$)', None, '1.6T SiPh 激光器')
add('1.6T_全层总需求_units', '全行业出货量(M units)', None, '1.6T 全层,汇丰口径')
add('800G_全层总需求_units', '全行业出货量(M units)', None, '800G 全层,汇丰口径')
add('高速光模块_总需求_units', '全行业出货量(万只)', None, '高速光模块,汇丰口径')
add('ASP_1.6T_USD', '速率单价(USD)', None, '1.6T 模块')
add('ASP_3.2T_USD', '速率单价(USD)', None, '3.2T 模块')
add('ASP_800G_USD', '速率单价(USD)', None, '800G 模块')

# ============= 产业链结构 =============
add('光模块_占系统设备成本', '上游成本占比(%)', None, '光模块占系统设备')
add('光器件_占光模块总成本', '上游成本占比(%)', None, '光器件')
add('光芯片_占光器件成本', '上游成本占比(%)', None, '光芯片占光器件')
add('光芯片_占光模块成本_高端', '上游成本占比(%)', None, '光芯片占高端光模块')
add('电路芯片_占光模块成本', '上游成本占比(%)', None, '电路芯片(DSP/TIA/驱动)')
add('陶瓷插芯_占连接器应用比例', '细分应用占比(%)', None, '陶瓷插芯应用于光纤连接器')
add('光芯片厂_衬底BOM占比', '上游成本占比(%)', None, '衬底占光芯片厂 BOM,源杰口径')
add('光接入网_5Y_CAGR_LightCounting', '全行业CAGR_5Y(%)', None, '光接入网,LightCounting')

# ============= 设备 =============
add('光模块设备_耦合_价值量占比', '设备环节价值量占比(%)', None, '耦合')
add('光模块设备_测试_价值量占比', '设备环节价值量占比(%)', None, '测试')
add('光模块设备_贴片_价值量占比', '设备环节价值量占比(%)', None, '贴片')
add('光模块设备_封装_价值量占比', '设备环节价值量占比(%)', None, '封装')
add('光模块设备_耦合_国产市占率', '国产市占率(%)', None, '光模块设备耦合环节')
add('光模块设备_测试_国产市占率', '国产市占率(%)', None, '光模块设备测试环节')
add('猎奇智能_贴片设备_全球市占', '公司市占率(%)', '猎奇智能', '光模块贴片设备全球')
add('光模块设备行业_营收_YoY', '行业整体营收_YoY(%)', None, '光模块设备行业 26Q1')
add('光模块设备行业_归母净利_YoY', '行业整体归母净利_YoY(%)', None, '光模块设备 26Q1')
add('光模块设备行业_整体毛利率', '行业整体毛利率(%)', None, '光模块设备 26Q1')
add('光模块设备行业_整体净利率', '行业整体净利率(%)', None, '光模块设备 26Q1')
add('光模块设备行业_整体营收', '行业整体营收(亿元)', None, '光模块设备 26Q1')
add('光模块设备行业_归母净利', '行业整体归母净利(亿元)', None, '光模块设备 26Q1')
add('光模块设备行业_费用率合计', '行业整体费用率合计(%)', None, '光模块设备 26Q1')
add('光模块设备行业_研发费用率', '行业整体研发费用率(%)', None, '光模块设备 26Q1')
add('光模块设备_CR5利润集中度', 'CR5利润集中度(%)', None, '光模块设备 26Q1')

# ============= 中国 / 其他 =============
add('中国厂商_全球前十光模块_席位数', '中国厂商前十席位数(席)', None, '全球前十光模块')
add('中国光纤陶瓷插芯_销量', '行业销量(亿只)', None, '中国光纤陶瓷插芯')
add('中国光纤陶瓷插芯_销售额', '行业销售额(亿元)', None, '中国光纤陶瓷插芯')
add('国内激光芯片厂_毛利率', '行业代表性公司毛利率(%)', None, '国内激光芯片(杰科技口径)')
add('龙头模块厂_毛利率', '行业头部公司毛利率(%)', None, '一级龙头模块厂')
add('龙头模块厂_净利率', '行业头部公司净利率(%)', None, '一级龙头模块厂')
add('全球光模块供应商Top1', '全球供应商Top1(名称)', None, '光模块')
add('全球光模块供应商Top3', '全球供应商Top3(名称)', None, '光模块')

# ============= 晶圆代工 =============
add('GlobalFoundries_晶圆代工市占率', '公司市占率(%)', None, 'GlobalFoundries / 硅光晶圆代工')
add('Tower_晶圆代工市占率', '公司市占率(%)', None, 'Tower / 硅光晶圆代工')
add('台积电_晶圆代工市占率', '公司市占率(%)', None, '台积电 / 硅光晶圆代工')
add('三星_晶圆代工市占率', '公司市占率(%)', None, '三星 / 硅光晶圆代工')
add('中芯国际_晶圆代工市占率', '公司市占率(%)', None, '中芯国际 / 硅光晶圆代工')
add('SOI_晶圆尺寸', 'SOI 晶圆尺寸(mm)', None, '硅光 SOI 平台')

# ============= 全球 AI CapEx =============
add('全球AI资本支出', '全球AI资本支出(亿美元)', None, '汇丰 2030 预测')
add('全球AI资本支出_累计', '全球AI资本支出_累计(亿美元)', None, '2026-2030 累计 / 灼识')

# ============= Token / DSP / Credo =============
add('火山引擎日均Token调用量', 'Token调用量(万亿/日)', None, '火山引擎')
add('Credo_DSP聚焦速率', '公司聚焦速率(Gbps)', 'Credo', None)
add('DSP_主导厂商', '主导厂商列表', None, 'DSP')
add('片上激光器_未来主流方案', '主流方案(文字)', None, '片上激光器 / 异质键合')
add('薄膜铌酸锂_HVM时点', '商业化 HVM 时点', None, '薄膜铌酸锂 3.2T')
add('薄膜铌酸锂_调制器_市场空间', 'TAM_USD', None, '薄膜铌酸锂调制器 / 华泰')
add('薄膜铌酸锂_调制器_CAGR_2029_2031', '全行业CAGR_3Y(%)', None, '薄膜铌酸锂 29-31 271%')
add('铌酸锂调制器_3dB带宽', '调制器3dB带宽(GHz)', None, '铌酸锂调制器')

# ============= 通信板块 =============
add('SW通信指数_最近一年涨幅', 'SW通信指数_累计涨幅(%)', None, '近 1 年')
add('通信行业_PE_TTM', 'PE_TTM', None, '申万通信 / 广发 2025-01')
add('通信行业_PE_TTM_5月', 'PE_TTM', None, '申万通信 / 国信 2025-05')
add('光模块光器件_5月涨幅', '细分板块月涨幅(%)', None, '光模块光器件 / 国信 5 月')

print(f"映射表行数:{len(M)}")
print()

# ---- 3. 应用迁移 ----
# 查所有 data_point,看哪些 metric 不在映射中也不在 canonical 中
CANONICAL = {'TAM_USD','TAM_CNY','TAM_units','CR5','CR10','HHI','国产化率(%)',
    '全行业CAGR_5Y(%)','全行业CAGR_3Y(%)','渗透率(%)','全行业出货量(万只)','全行业出货量(百万只)','全行业出货量(M units)',
    '全行业出货量_YoY(%)','平均ASP_USD','平均ASP_CNY','全行业市场规模(亿美元)','全行业市场规模(亿元)',
    '季度营收(亿元)','季度营收(亿美元)','季度营收(百万美元)','季度营收(十亿美元)','季度营收_YoY(%)','季度营收_QoQ(%)',
    '半年度营收(亿元)','全年营收(亿元)','季度归母净利润(亿元)','季度归母净利润(亿美元)','季度归母净利润(百万美元)',
    '季度归母净利润_YoY(%)','半年度归母净利润(亿元)','全年归母净利润(亿元)','整体毛利率(%)','单产品毛利率(%)',
    '海外业务占比(%)','海外业务营收(亿元)','主营产品集中度(%)','单一客户营收占比(%)','研发投入(亿元)','研发投入占比(%)',
    '产能(units)','产能(万只)','产能利用率(%)','公司市占率(%)','公司出货量(万只)','公司ASP_USD','公司净利率(%)',
    'CapEx(亿美元)','CapEx(亿元)','CapEx_YoY(%)','经营性现金流(亿元)','存货周转天数',
    '单GPU光模块配比(只)','单GPU光模块配比_均值(只)','技术路线渗透率(%)','技术路线良率(%)','技术路线功耗节省(%)','技术路线成本节省(%)',
    '单模块功耗(W)','单模块功耗下降(%)','单模块成本(USD)','单模块ASP(USD)','速率单价(USD)','客户认证完成时点','制程节点(nm)',
    'CPO速率(Tbps)','CPO容量(Tbps)','光引擎数(个)','光纤数(根)','单产品端口数','产品启动年','产品发布日期','单产品功耗下降(%)','DSP速率(Tbps)',
    '北美CSP_CapEx合计(亿美元)','北美CSP_CapEx_YoY(%)','中国主要厂商_CapEx合计(亿元)','中国主要厂商_CapEx_YoY(%)',
    'AI服务器出货量_YoY(%)','GPU出货量(units)','GPU出货量(千台)','AI加速器总出货量(千台)','Token调用量(亿次/日)','Token调用量(万亿/日)','Token调用量_YoY(%)',
    '上游成本占比(%)','下游需求占比(%)','PE_TTM','PE_FY1','PB','PS_TTM','市值(亿元)','市值(亿美元)','北上资金持仓变化(%)',
    # 扩展通用
    'AI服务器营收_YoY(%)','AI服务器出货量(units)','通用服务器出货量_YoY(%)','AI数据中心电力延迟项目占比(%)',
    '数据中心营收_YoY(%)','数据中心业务营收占比(%)','单switch带宽(Tbps)','业务线营收(百万美元)','产品线营收(百万美元)',
    '多年产品累计营收预期(百万美元)','公司员工数(人)','公司客户份额(%)','单通道速率(Gbps)','单笔订单金额(万美元)',
    'GPU采购金额(亿美元)','GPU规划总量(万张)','CPO战略投资金额(亿美元)','单产品出口管制影响(亿美元)',
    '公司订单backlog(亿美元)','多年AI投入计划(亿元)','合作初始算力承诺(单位)','合作截止年','公司累计出货通道数(亿条)',
    '单集群功耗(kW)','集群功耗节省(%)','单系统光模块需求(只)','产能提升幅度(%)','产量提升倍数','成本下降幅度(%)',
    '供应商数(家)','海外主供应商列表','海外寡头列表','设备交货周期(月)','量产状态(文字)','贴片精度(μm)',
    '设备投入(亿元)','测试带宽要求(GBaud)','单产品带宽(Gbps)','单产品能效(pJ/bit)',
    '面板密度提升倍数','单产品MTBF(万小时)','单故障影响端口数','单元件成本(USD)','单元件成本(万美元)','单元件价格(USD)',
    '技术成熟度阶段','主导厂商列表','低速光模块占比(%)','预测上调幅度(%)','客户采购集中度(%)','调制器3dB带宽(GHz)','商业化 HVM 时点',
    '行业销量(亿只)','行业销售额(亿元)','行业代表性公司毛利率(%)','行业头部公司毛利率(%)','行业头部公司净利率(%)',
    '中国厂商前十席位数(席)','全球供应商Top1(名称)','全球供应商Top3(名称)','技术首发时点','CPO供应链中国参与环节','技术路线月涨幅(%)','细分板块月涨幅(%)',
    'SW通信指数_累计涨幅(%)','SOI 晶圆尺寸(mm)','全球AI资本支出(亿美元)','全球AI资本支出_累计(亿美元)',
    'CR3','CR4','云计算TAM_USD','单产品体积下降(%)','产品体积下降(%)','产品组件数(个)','公司聚焦速率(Gbps)','单模块上游元件含量(US$)',
    '公司净利率(%)','公司股价_月涨幅(%)','公司目标价(元)','公司业务结构_有源占比(%)','ASIC_占AI加速器比例(%)',
    '设备环节价值量占比(%)','行业整体营收_YoY(%)','行业整体归母净利_YoY(%)','行业整体毛利率(%)','行业整体净利率(%)',
    '行业整体营收(亿元)','行业整体归母净利(亿元)','行业整体费用率合计(%)','行业整体研发费用率(%)','CR5利润集中度(%)',
    '国产市占率(%)','细分应用占比(%)','全球服务器营收(亿美元)',
}

# 实际迁移
rows = list(conn.execute("SELECT id, metric, note FROM industry_data_point"))
migrated = 0
skipped = []
not_mapped = set()

for r in rows:
    old = r['metric']
    if old in M:
        new, comp, npfx = M[old]
        cur_note = r['note'] or ''
        if npfx:
            new_note = f'{npfx} | {cur_note}' if cur_note else npfx
        else:
            new_note = cur_note
        comp_id = cid(comp) if comp else None
        conn.execute(
            "UPDATE industry_data_point SET metric=?, company_id=?, note=? WHERE id=?",
            (new, comp_id, new_note, r['id'])
        )
        migrated += 1
    elif old not in CANONICAL:
        not_mapped.add(old)

conn.commit()

# 报告
print(f"[OK] 迁移 {migrated} 个 data_point")
print(f"[INFO] 未映射且不在 canonical: {len(not_mapped)} 个 metric")
for nm in sorted(not_mapped):
    print(f"  - {nm}")

# 迁移后统计
print()
print("=== 迁移后 metric 总数:", conn.execute("SELECT COUNT(DISTINCT metric) FROM industry_data_point").fetchone()[0])
# 检查违规
ENTITY_PREFIXES = ['NVIDIA','Coherent','Broadcom','Google','中际旭创','新易盛','天孚通信','光迅',
                   'Lumentum','AAOI','Marvell','联讯','凯格','罗博','博众','瑞松','普源','快克',
                   '华盛昌','日联','科瑞','智立方','燕麦','易天','优利德','鼎阳','华兴源创','杰科技',
                   '源杰','AXT','Microsoft','Amazon','Meta','阿里','腾讯','OpenAI','xAI','Oracle',
                   '甲骨文','CoreWeave','微软','亚马逊','谷歌','华为','NVL','GB300','Rubin','Trainium',
                   'TPU','Sumitomo','JX','住友','北京通美']
illegal = []
for r in conn.execute("SELECT DISTINCT metric FROM industry_data_point"):
    for p in ENTITY_PREFIXES:
        if p in r[0]:
            illegal.append(r[0]); break
print(f"含 entity 违规 metric: {len(illegal)} 个")
for m in illegal:
    print(f"  RESIDUAL: {m}")

conn.close()
EOF
