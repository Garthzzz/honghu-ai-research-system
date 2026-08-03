# 萝卜投科研报源：安全登录、检索、下载与研究管线

## 1. 功能边界

本连接器只使用 Playwright 操作 `https://r.datayes.com/` 的正常网页界面，不调用、
逆向或绕过站点 API，不处理验证码，也不突破账号可见权限。它服务于 A/B 行研和
C 轨 Opportunity Lens 的 `report` 搜索链；开放网络 `web` 链仍必须独立执行。

活动入口：

```powershell
python -m tools.research_sources.datayes_reports --help
```

## 2. 凭据与登录态

账号密码通过本机 Tk 遮罩窗口直接写入 Windows Credential Manager，后端必须是
`keyring.backends.Windows.WinVaultKeyring`。密码不经过聊天、命令行参数、环境
变量、项目文件或日志。

```powershell
python -m tools.research_sources.datayes_reports configure-credentials
python -m tools.research_sources.datayes_reports credential-status
python -m tools.research_sources.datayes_reports login
python -m tools.research_sources.datayes_reports status
```

`login` 从 Credential Manager 填入账号密码，并只在包含密码框的登录表单中自动
提交；脚本连续确认登录墙消失后自动关闭窗口。验证码或额外安全确认仍由用户在
可见浏览器中完成，不自动识别或绕过。浏览器 profile 位于：

```text
tools/dynamic/secrets/datayes_profile_v2
```

该目录被 `.gitignore` 和广播包构建器排除，并使用收紧后的 Windows ACL。程序和
审计只检查“凭据是否配置、登录态是否有效”，不得输出账号、cookie、localStorage
或密码。

## 3. 检索合同

| 研究对象 | 标题检索词 | 时间范围 | 页数 | 组合目标 |
|---|---|---:|---:|---|
| 公司 | 公司名 | 研究截止日前 183 天 | 不设硬门槛 | 1—2 份外资＋1—2 份国内推荐 |
| 行业 | 行业名、行业名＋深度、行业名＋行业深度 | 研究截止日前 366 天 | 至少 20 页 | 1—2 份外资＋1—2 份国内推荐 |

示例：

```powershell
python -m tools.research_sources.datayes_reports search `
  --query "正泰电器" --papers-subdir "光伏" --scope company `
  --as-of-date 2026-08-01 --domestic-target 2 --foreign-target 2

python -m tools.research_sources.datayes_reports download `
  --query "碳酸锂 深度" --papers-subdir "碳酸锂" --scope industry `
  --as-of-date 2026-08-01 --domestic-target 2 --foreign-target 2
```

配额是“必须真实尝试并审计”的研究门槛，不是造数门槛。若公开可见报告不足、权限
不足或页面结构变化，命令以 shortfall 状态退出，保存实际成功项和失败原因；研究
正文说明真实缺口，不能把普通搜索结果伪装成“推荐研报”或把聚合站重复项当多源。
站内“推荐”标签是不能按标题二次筛选的全站推荐流；若其中没有相关国内报告，连接器
可另行下载标题检索命中的近期国内深度报告作为回退材料，但 manifest 会明确写成
`search_result`，且该回退不满足“平台推荐”严格配额。

## 4. 下载与来源清单

下载文件先进入 `cache/datayes_reports/downloads/` 临时目录，随后依次检查：

1. 文件头必须为 PDF；
2. PyMuPDF 能正常打开；
3. 行业报告实际页数不少于 20；
4. 计算文件 SHA256；
5. 通过 `tools/pipeline/paper_paths.py` 生成 Windows 安全文件名；
6. 原子移动到 `papers/<行业>/`。

每批下载同时生成：

```text
papers/<行业>/_source_manifests/datayes_<scope>_<token>.json
```

清单记录 PDF 路径、哈希、页数、底层券商、发布日期、详情页、搜索词、国内/外资
分类、推荐类型及 `independence_key`。清单严禁包含账号、cookie 或密码。

## 5. A/B/C 上下游接线

### A/B

1. `ResearchBrief.search_plan` 的每个问题轴仍分别生成 `report` 和 `web` 任务；
2. `report_provider_contract` 登记 `datayes_playwright` 的时效、页数和配额；
3. 报告下载后由 `research_pdf_corpus.py` 做逐页文本与哈希索引；
4. claims 引用 PDF 时，`ingest_research.py` 调用
   `paper_source_manifest.enrich_claim_sources()` 补齐券商、发布日期、详情页、
   `source_channel=report` 和来源层级；
5. 只有被 data point 或 key argument 实际引用的报告才进入 `research.db.source`，
   下载储备本身不自动制造研究事实；
6. 新数据点仍必须走 `db_writer.write_data_point()`，不得直接 INSERT。

### C 轨 Opportunity Lens

1. 同一 `_source_manifests` 作为 source producer 的 provenance seed；
2. `independence_key` 按底层券商＋标题＋发布日期计算，萝卜投研不是独立发布方；
3. producer 必须从 PDF 提取本轮真正使用的原文与中文译意，再写 run pack source；
   可调用 `RunPackBuilder.add_paper_manifest_source()`，该入口会复核 PDF SHA256，
   英文材料缺少 `excerpt_zh` 时拒绝转换，并始终以 `pending` 等待 evidence reviewer；
4. 卖方研报属于二手研究证据，不能替代公告、监管披露、专利、公司/客户/供应商等
   原始证据；
5. 公司 FY1—FY3 卖方预测只纳入研究截止日前最近两个季度发布的报告，并在独立
   模型冻结后用于外部对账；
6. C pack、DB、审计 cache 和广播包均不得复制 Credential Manager 或 profile。

## 6. 维护与失败处理

- 登录失效：重新运行 `login`，不要把 cookie 手工复制到配置。
- UI 改版：先运行 `probe-ui` 生成脱敏结构，再修选择器和测试。
- 验证码：只能由用户在可见浏览器完成，不自动识别或绕过。
- 下载按钮失效：记录详情页 path 和错误类型，不尝试逆向接口。
- 标题/券商/日期不能核验：候选不进入正式配额。
- 定时任务：默认不配置。萝卜投研只按具体研究请求运行，避免高频访问和无目标下载。

## 7. 规范—代码对账

| 要求 | 配置/规范 | 实现 | 验收 |
|---|---|---|---|
| Windows 凭据库 | `research_workflow.yaml` | `credential_dialog/store_credentials` | 后端必须为 `WinVaultKeyring` |
| 无 API、正常网页 | 本文与 AGENTS | Playwright locator/click/download | 代码无 requests/XHR 路径 |
| 标题检索 | `search_field=title_only` | `_set_title_only/_execute_title_search` | 找不到“标题”模式即阻塞 |
| 时效/页数 | 183/366 天、行业 20 页 | `ReportSearchRequest/_validate_pdf` | 单元测试与真实下载复核 |
| 国内/外资配额 | 各 1—2 份 | `select_candidates` | 国内标题回退可下载但不冒充平台推荐，shortfall 不伪装通过 |
| Windows 安全路径 | AGENTS paper 路径合同 | `normalize_new_paper_file` | 广播路径预检 |
| A/B 来源入库 | workflow V2 | `enrich_claim_sources`＋统一 ingest | 只登记被引用来源 |
| C 轨 provenance | MODULE_CONTEXT | `_source_manifests` | 底层券商独立性键 |
