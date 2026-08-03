from __future__ import annotations

"""萝卜投研网页研报连接器。

本模块只通过 Playwright 驱动用户可见网页，不调用或逆向站点 API。账号和密码
由 Windows Credential Manager 保存，并仅在可见登录表单中临时填充；项目复用
位于 ``tools/dynamic/secrets`` 下的本机 Chromium profile。任何日志、manifest 和
``papers`` 文件都不得包含 cookie、localStorage、账号或密码。
"""

import argparse
import hashlib
import json
import logging
import os
import re
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urljoin, urlsplit
from uuid import uuid4

import fitz

from tools.pipeline.paper_paths import normalize_new_paper_file, sanitize_filename
from tools.pipeline.paper_source_manifest import (
    SCHEMA_VERSION as SOURCE_MANIFEST_SCHEMA,
    hash_file,
    write_manifest,
)


ROOT = Path(__file__).resolve().parents[2]
BASE_URL = "https://r.datayes.com/"
REPORT_SEARCH_URL = urljoin(BASE_URL, "/fastreport/reportSearch")
KEYRING_SERVICE = "industry_demo.datayes"
KEYRING_USERNAME_ENTRY = "__username__"
DEFAULT_PROFILE_DIR = ROOT / "tools" / "dynamic" / "secrets" / "datayes_profile_v2"
DEFAULT_AUDIT_ROOT = ROOT / "cache" / "datayes_reports"
LOGGER = logging.getLogger("industry_demo.datayes_reports")
SYSTEM_BROWSER_CANDIDATES = (
    Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
)

_LOGIN_URL_TOKENS = ("login", "signin", "passport", "auth")
_SENSITIVE_TEXT = (
    re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    re.compile(r"(?<!\d)1\d{10}(?!\d)"),
)
_DATE_PATTERN = re.compile(r"(?<!\d)(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})日?(?!\d)")
_COMPACT_DATE_PATTERN = re.compile(r"(?<!\d)(20\d{2})(\d{2})(\d{2})(?!\d)")
_PAGE_PATTERN = re.compile(r"(?<!\d)(\d{1,4})\s*页")
_REPORT_HREF_PATTERN = re.compile(r"(report|research|yanbao|detail)", re.IGNORECASE)
_DOWNLOAD_TEXT_PATTERN = re.compile(r"^(下载|下载报告|报告下载|PDF下载|下载PDF)$", re.IGNORECASE)
_FOREIGN_PUBLISHERS = (
    "Goldman Sachs", "Morgan Stanley", "Citi", "Citigroup", "J.P. Morgan",
    "JPMorgan", "UBS", "Nomura", "Macquarie", "HSBC", "Barclays",
    "BofA", "Bank of America", "Deutsche Bank", "Jefferies", "Bernstein",
    "Daiwa", "Mizuho", "Societe Generale", "Credit Suisse", "花旗", "高盛",
    "摩根士丹利", "摩根大通", "瑞银", "野村", "麦格理", "汇丰", "巴克莱",
    "美银", "德意志银行", "杰富瑞", "大和", "瑞穗",
)
_DOMESTIC_PUBLISHERS = (
    "中信证券", "华泰证券", "国泰君安", "海通证券", "申万宏源", "广发证券",
    "招商证券", "国信证券", "中金公司", "中国银河", "兴业证券", "东方证券",
    "光大证券", "长江证券", "浙商证券", "天风证券", "方正证券", "民生证券",
    "东吴证券", "中泰证券", "国金证券", "华创证券", "开源证券", "西部证券",
    "信达证券", "东北证券", "财通证券", "国联民生", "中银证券", "国盛证券",
)
_SEARCH_INPUT_SELECTORS = (
    ".ant-select-auto-complete input.ant-select-selection-search-input:visible",
    ".ant-select:has-text('输入关键词') input.ant-select-selection-search-input:visible",
    "input[placeholder*='关键词']:visible",
)


@dataclass(frozen=True)
class AuthProbe:
    """登录态的非敏感检查结果。

    Attributes:
        authenticated: 是否已越过登录墙；布尔值，无账号或 cookie 内容。
        current_path: 当前站内 URL path，不含 query、fragment 或凭据。
        login_form_visible: 页面是否出现密码输入框或明确登录表单。
        checked_at_utc: UTC ISO-8601 时间戳。
    """

    authenticated: bool
    current_path: str
    login_form_visible: bool
    checked_at_utc: str


@dataclass(frozen=True)
class ReportSearchRequest:
    """一次授权研报搜索的稳定输入合同。

    Attributes:
        query: 标题检索关键词；公司名或“行业名＋深度”等文本。
        papers_subdir: ``papers/`` 下的目标行业目录名，不是绝对路径。
        report_scope: ``company`` 或 ``industry``。
        as_of_date: 北京时间研究截止日，格式 YYYY-MM-DD。
        domestic_target: 国内推荐报告目标数，允许 1—2。
        foreign_target: 外资报告目标数，允许 1—2。
    """

    query: str
    papers_subdir: str
    report_scope: str
    as_of_date: str
    domestic_target: int = 2
    foreign_target: int = 2

    def __post_init__(self) -> None:
        query = str(self.query or "").strip()
        subdir = str(self.papers_subdir or "").strip().strip("/\\")
        scope = str(self.report_scope or "").strip().lower()
        if not query:
            raise ValueError("DataYes query 不能为空")
        if not subdir or Path(subdir).is_absolute() or ".." in Path(subdir).parts:
            raise ValueError("papers_subdir 必须是 papers/ 下的安全相对目录")
        if scope not in {"company", "industry"}:
            raise ValueError("report_scope 必须是 company 或 industry")
        date.fromisoformat(self.as_of_date)
        if self.domestic_target not in {1, 2} or self.foreign_target not in {1, 2}:
            raise ValueError("国内和外资报告目标数必须为 1 或 2")
        object.__setattr__(self, "query", query)
        object.__setattr__(self, "papers_subdir", subdir)
        object.__setattr__(self, "report_scope", scope)

    @property
    def cutoff_date(self) -> date:
        """允许的最早发布日期；公司 183 天，行业 366 天。"""

        window_days = 183 if self.report_scope == "company" else 366
        return date.fromisoformat(self.as_of_date) - timedelta(days=window_days)

    @property
    def minimum_pages(self) -> int:
        """行业报告至少 20 页；公司报告不设页数门槛。"""

        return 20 if self.report_scope == "industry" else 0


@dataclass(frozen=True)
class ReportCandidate:
    """从正常网页 UI 提取的候选研报元数据。"""

    title: str
    publisher: str
    publish_date: str
    page_count: int | None
    detail_url: str
    publisher_origin: str
    recommendation_type: str
    query: str

    @property
    def independence_key(self) -> str:
        """按底层券商、标题和发布日期生成证据独立性键。"""

        parts = [self.publisher, self.title, self.publish_date]
        normalized = [re.sub(r"\W+", "", part, flags=re.UNICODE).casefold() for part in parts]
        return "sell_side:" + ":".join(normalized)


@dataclass(frozen=True)
class DownloadedReport:
    """已通过 PDF、页数、路径和哈希验证的下载结果。"""

    relative_path: str
    sha256: str
    size_bytes: int
    page_count: int
    candidate: ReportCandidate
    downloaded_at_utc: str


def credential_status() -> dict[str, Any]:
    """检查 Windows Credential Manager 中是否同时存在账号和密码。

    Returns:
        只包含 backend 名称和 ``configured`` 布尔值；不返回账号或密码。
    """

    import keyring

    backend = type(keyring.get_keyring())
    username = keyring.get_password(KEYRING_SERVICE, KEYRING_USERNAME_ENTRY)
    password = keyring.get_password(KEYRING_SERVICE, username) if username else None
    return {
        "backend": f"{backend.__module__}.{backend.__name__}",
        "configured": bool(username and password),
    }


def store_credentials(username: str, password: str) -> None:
    """把萝卜投研账号密码写入系统凭据库。

    Args:
        username: 萝卜投研登录名；不写入项目文件或日志。
        password: 明文只在当前进程内存中短暂存在，随后交给 keyring。

    Returns:
        None。Windows 后端必须是 ``WinVaultKeyring``，否则拒绝保存。
    """

    import keyring

    clean_username = str(username or "").strip()
    if not clean_username or not password:
        raise ValueError("账号和密码不能为空")
    backend = type(keyring.get_keyring())
    if "Windows" not in backend.__module__ or backend.__name__ != "WinVaultKeyring":
        raise RuntimeError(f"当前 keyring 不是 Windows Credential Manager: {backend}")
    keyring.set_password(KEYRING_SERVICE, KEYRING_USERNAME_ENTRY, clean_username)
    keyring.set_password(KEYRING_SERVICE, clean_username, password)


def load_credentials() -> tuple[str, str]:
    """从 Windows Credential Manager 取回登录凭据供 Playwright 填表。

    Returns:
        ``(username, password)``；仅在调用进程内存使用，不得记录或序列化。
    """

    import keyring

    username = keyring.get_password(KEYRING_SERVICE, KEYRING_USERNAME_ENTRY)
    password = keyring.get_password(KEYRING_SERVICE, username) if username else None
    if not username or not password:
        raise RuntimeError("Windows Credential Manager 尚未配置萝卜投研凭据")
    return username, password


def credential_dialog() -> bool:
    """显示本机遮罩输入框并将凭据直接写入 Windows Credential Manager。"""

    import tkinter as tk
    from tkinter import messagebox

    result = {"saved": False}
    root = tk.Tk()
    root.title("萝卜投研安全登录配置")
    root.geometry("460x230")
    root.resizable(False, False)
    root.attributes("-topmost", True)
    frame = tk.Frame(root, padx=24, pady=20)
    frame.pack(fill="both", expand=True)
    tk.Label(
        frame,
        text="凭据将写入 Windows Credential Manager，\n不会写入项目文件、日志或聊天。",
        justify="left",
    ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 14))
    tk.Label(frame, text="账号").grid(row=1, column=0, sticky="e", padx=(0, 10), pady=6)
    username_entry = tk.Entry(frame, width=38)
    username_entry.grid(row=1, column=1, sticky="w", pady=6)
    tk.Label(frame, text="密码").grid(row=2, column=0, sticky="e", padx=(0, 10), pady=6)
    password_entry = tk.Entry(frame, width=38, show="●")
    password_entry.grid(row=2, column=1, sticky="w", pady=6)

    def save() -> None:
        try:
            store_credentials(username_entry.get(), password_entry.get())
        except Exception as exc:
            messagebox.showerror("保存失败", str(exc), parent=root)
            return
        password_entry.delete(0, tk.END)
        result["saved"] = True
        messagebox.showinfo("保存成功", "凭据已存入 Windows Credential Manager。", parent=root)
        root.destroy()

    tk.Button(frame, text="安全保存", command=save, width=16).grid(
        row=3,
        column=1,
        sticky="e",
        pady=(18, 0),
    )
    username_entry.focus_set()
    root.mainloop()
    return bool(result["saved"])


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    """原子写入 UTF-8 JSON。

    Args:
        path: 项目内目标文件路径。
        payload: 可 JSON 序列化对象，不得含凭据或浏览器存储值。

    Returns:
        None。
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".{uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _parse_date(text: str) -> str | None:
    """从 UI 文本提取 YYYY-MM-DD 发布日期。"""

    match = _DATE_PATTERN.search(text)
    if not match:
        match = _COMPACT_DATE_PATTERN.search(text)
    if not match:
        return None
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3))).isoformat()
    except ValueError:
        return None


def _parse_page_count(text: str) -> int | None:
    """从 UI 文本提取 PDF 页数，单位为页。"""

    match = _PAGE_PATTERN.search(text)
    return int(match.group(1)) if match else None


def classify_publisher(publisher: str, context_text: str = "") -> str | None:
    """将底层券商分成 domestic/foreign；无法判断时返回 None。"""

    combined = f"{publisher} {context_text}".casefold()
    if any(name.casefold() in combined for name in _FOREIGN_PUBLISHERS):
        return "foreign"
    if any(name.casefold() in combined for name in _DOMESTIC_PUBLISHERS):
        return "domestic"
    if re.search(r"(?:证券|期货|研究所|研究院)$", publisher.strip()):
        return "domestic"
    if "外资研报" in context_text or "海外研报" in context_text:
        return "foreign"
    return None


def _extract_publisher(text: str) -> str:
    """优先从已知券商表提取发布方，避免把聚合站当发布方。"""

    for name in (*_FOREIGN_PUBLISHERS, *_DOMESTIC_PUBLISHERS):
        if name.casefold() in text.casefold():
            return name
    patterns = (
        re.compile(
            r"20\d{2}[-/.年]\d{1,2}[-/.月]\d{1,2}日?\s+"
            r"([^|｜·\n]{2,30}?(?:证券|期货|研究所|研究院|Research))(?=\s)"
        ),
        re.compile(r"(?:机构|券商|发布方|来源)[:：]\s*([^|｜·\n]{2,30})"),
        re.compile(r"([^|｜·\n]{2,20}(?:证券|期货|研究所|研究院|Research))"),
    )
    for pattern in patterns:
        match = pattern.search(text)
        if match:
            return re.sub(r"\s+", " ", match.group(1)).strip()
    return "待核验券商"


def _first_visible_locator(page: Any, selectors: Iterable[str]) -> Any | None:
    """返回第一个可见 locator，不点击、不读取输入值。"""

    for selector in selectors:
        locator = page.locator(selector)
        for index in range(min(locator.count(), 10)):
            candidate = locator.nth(index)
            try:
                if candidate.is_visible():
                    return candidate
            except Exception:
                continue
    return None


def _set_title_only(page: Any) -> bool:
    """在 UI 中选择标题检索；找不到时返回 False 并由调用方阻塞。"""

    mode = _first_visible_locator(page, (".option-select:visible",))
    if mode is not None:
        try:
            if "标题" in re.sub(r"\s+", "", mode.inner_text() or ""):
                return True
            mode.click(timeout=5_000)
            title_option = _first_visible_locator(
                page,
                (
                    ".ant-select-item-option:visible:has-text('标题')",
                    "[role='option']:visible:has-text('标题')",
                ),
            )
            if title_option is not None:
                title_option.click(timeout=5_000)
                return True
        except Exception:
            pass
    candidates = (
        page.get_by_text("标题", exact=True),
        page.get_by_role("radio", name=re.compile("标题")),
        page.get_by_role("option", name=re.compile("标题")),
        page.locator("label:has-text('标题'):visible"),
    )
    for locator in candidates:
        for index in range(min(locator.count(), 8)):
            element = locator.nth(index)
            try:
                if element.is_visible():
                    element.click(timeout=5_000)
                    return True
            except Exception:
                continue
    return False


def _execute_title_search(page: Any, query: str) -> None:
    """通过可见搜索框执行一次标题检索。"""

    search_input = _first_visible_locator(page, _SEARCH_INPUT_SELECTORS)
    if search_input is None:
        raise RuntimeError("萝卜投研页面未找到可见研报搜索框")
    if not _set_title_only(page):
        raise RuntimeError("萝卜投研页面未能确认“标题”检索模式")
    search_input.fill(query)
    search_input.press("Enter")
    page.wait_for_timeout(3_000)


def _candidate_from_anchor(
    anchor: Any,
    query: str,
    *,
    forced_recommendation_type: str | None = None,
) -> ReportCandidate | None:
    """从一个结果/推荐链接及其近邻容器提取候选。"""

    href = anchor.get_attribute("href") or ""
    title = re.sub(r"\s+", " ", anchor.inner_text() or "").strip()
    if not href or len(title) < 5 or not _REPORT_HREF_PATTERN.search(href):
        return None
    container_text = title
    try:
        container = anchor.locator("xpath=ancestor::*[contains(@class,'report-item-box')][1]")
        if not container.count():
            container = anchor.locator(
                "xpath=ancestor::*[self::li or self::article or @role='listitem' or contains(@class,'card')][1]"
            )
        if container.count():
            container_text = re.sub(r"\s+", " ", container.first.inner_text()).strip()
    except Exception:
        pass
    publish_date = _parse_date(container_text)
    if not publish_date:
        return None
    publisher = _extract_publisher(container_text)
    origin = classify_publisher(publisher, container_text)
    if forced_recommendation_type == "foreign_sell_side":
        origin = "foreign"
    if origin is None:
        return None
    if forced_recommendation_type:
        recommendation_type = forced_recommendation_type
    elif "外资研报" in container_text or "海外研报" in container_text:
        recommendation_type = "foreign_sell_side"
    elif "推荐" in container_text or "相关研报" in container_text:
        recommendation_type = "domestic_recommended" if origin == "domestic" else "foreign_sell_side"
    else:
        recommendation_type = "search_result"
    return ReportCandidate(
        title=title,
        publisher=publisher,
        publish_date=publish_date,
        page_count=_parse_page_count(container_text),
        detail_url=urljoin(BASE_URL, href),
        publisher_origin=origin,
        recommendation_type=recommendation_type,
        query=query,
    )


def _collect_candidates(
    page: Any,
    query: str,
    *,
    forced_recommendation_type: str | None = None,
) -> list[ReportCandidate]:
    """从当前搜索或详情页收集可复核候选，并按底层报告去重。"""

    anchors = page.locator("a:visible")
    rows: list[ReportCandidate] = []
    seen: set[str] = set()
    for index in range(min(anchors.count(), 400)):
        try:
            candidate = _candidate_from_anchor(
                anchors.nth(index),
                query,
                forced_recommendation_type=forced_recommendation_type,
            )
        except Exception:
            continue
        if candidate is None or candidate.independence_key in seen:
            continue
        seen.add(candidate.independence_key)
        rows.append(candidate)
    return rows


def _collect_report_tab(
    page: Any,
    *,
    label: str,
    query: str,
    recommendation_type: str,
) -> list[ReportCandidate]:
    """切换研报页的公开标签并采集逐条结果。"""

    tabs = page.locator(".ant-tabs-tab-btn:visible")
    target = None
    for index in range(min(tabs.count(), 12)):
        item = tabs.nth(index)
        try:
            if re.sub(r"\s+", "", item.inner_text() or "") == label:
                target = item
                break
        except Exception:
            continue
    if target is None:
        LOGGER.warning("report_tab missing label=%s", label)
        return []
    target.click(timeout=5_000)
    page.wait_for_timeout(2_000)
    if _first_visible_locator(page, _SEARCH_INPUT_SELECTORS) is not None:
        _execute_title_search(page, query)
    else:
        LOGGER.info("report_tab has_no_title_search label=%s", label)
    return _collect_candidates(
        page,
        query,
        forced_recommendation_type=recommendation_type,
    )


def _eligible(candidate: ReportCandidate, request: ReportSearchRequest) -> bool:
    """应用发布日期、标题相关性和行业页数门槛。"""

    published = date.fromisoformat(candidate.publish_date)
    as_of = date.fromisoformat(request.as_of_date)
    if published < request.cutoff_date or published > as_of:
        return False
    query_tokens = [token for token in re.split(r"[\s+]+", request.query) if token and token != "深度"]
    if query_tokens and not any(token.casefold() in candidate.title.casefold() for token in query_tokens):
        return False
    if request.minimum_pages and candidate.page_count is not None and candidate.page_count < request.minimum_pages:
        return False
    return True


def select_candidates(
    candidates: Iterable[ReportCandidate],
    request: ReportSearchRequest,
) -> tuple[list[ReportCandidate], dict[str, int]]:
    """按外资/国内推荐配额选择，不以主搜索结果冒充推荐报告。"""

    eligible = [candidate for candidate in candidates if _eligible(candidate, request)]
    eligible.sort(key=lambda item: item.publish_date, reverse=True)
    foreign = [item for item in eligible if item.publisher_origin == "foreign"]
    domestic_recommended = [
        item for item in eligible
        if item.publisher_origin == "domestic" and item.recommendation_type == "domestic_recommended"
    ]
    domestic_title_results = [
        item for item in eligible
        if item.publisher_origin == "domestic" and item.recommendation_type == "search_result"
    ]
    domestic_title_results.sort(
        key=lambda item: (
            int(any(token in item.title for token in ("行业深度", "深度报告", "年度策略", "中期策略"))),
            -int(any(token in item.title for token in ("日报", "早报", "晨报"))),
            item.page_count or 0,
            item.publish_date,
        ),
        reverse=True,
    )
    domestic_shortfall = max(0, request.domestic_target - len(domestic_recommended))
    domestic_fallback = domestic_title_results[:domestic_shortfall]
    selected = [
        *foreign[: request.foreign_target],
        *domestic_recommended[: request.domestic_target],
        *domestic_fallback,
    ]
    selected = list({item.independence_key: item for item in selected}.values())
    summary = {
        "eligible_count": len(eligible),
        "foreign_available": len(foreign),
        "foreign_selected": min(len(foreign), request.foreign_target),
        "domestic_recommended_available": len(domestic_recommended),
        "domestic_recommended_selected": min(len(domestic_recommended), request.domestic_target),
        "domestic_title_fallback_available": len(domestic_title_results),
        "domestic_title_fallback_selected": len(domestic_fallback),
        "domestic_reference_selected": min(len(domestic_recommended), request.domestic_target)
        + len(domestic_fallback),
    }
    return selected, summary


def _validate_pdf(path: Path, *, minimum_pages: int) -> tuple[int, int, str]:
    """验证下载确为可打开 PDF，并返回页数、字节数和 SHA256。"""

    if not path.is_file() or path.stat().st_size < 1_024:
        raise ValueError(f"下载文件过小或不存在: {path}")
    with path.open("rb") as handle:
        if handle.read(5) != b"%PDF-":
            raise ValueError(f"下载结果不是 PDF: {path}")
    document = fitz.open(path)
    try:
        page_count = int(document.page_count)
    finally:
        document.close()
    if page_count < max(1, minimum_pages):
        raise ValueError(f"PDF 页数 {page_count} 未达到门槛 {minimum_pages}: {path}")
    return page_count, path.stat().st_size, hash_file(path)


def _finalize_download(
    staging_path: Path,
    *,
    candidate: ReportCandidate,
    request: ReportSearchRequest,
) -> DownloadedReport:
    """验证、原子移动并执行 Windows 安全文件名规范化。"""

    actual_pages, size_bytes, digest = _validate_pdf(
        staging_path,
        minimum_pages=request.minimum_pages,
    )
    papers_dir = (ROOT / "papers" / request.papers_subdir).resolve()
    papers_root = (ROOT / "papers").resolve()
    if papers_root not in papers_dir.parents:
        raise ValueError(f"目标 papers 目录越界: {papers_dir}")
    papers_dir.mkdir(parents=True, exist_ok=True)
    raw_name = sanitize_filename(
        f"{candidate.publish_date}_{candidate.publisher}_{candidate.title}.pdf"
    )
    target = papers_dir / raw_name
    if target.exists():
        if hash_file(target) == digest:
            staging_path.unlink(missing_ok=True)
            final = target
        else:
            token = hashlib.sha256(candidate.independence_key.encode("utf-8")).hexdigest()[:8]
            target = target.with_name(f"{target.stem}__{token}{target.suffix}")
            os.replace(staging_path, target)
            final = normalize_new_paper_file(target, project_root=ROOT)
    else:
        os.replace(staging_path, target)
        final = normalize_new_paper_file(target, project_root=ROOT)
    return DownloadedReport(
        relative_path=final.relative_to(ROOT).as_posix(),
        sha256=digest,
        size_bytes=size_bytes,
        page_count=actual_pages,
        candidate=candidate,
        downloaded_at_utc=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )


def _merge_candidates(*groups: Iterable[ReportCandidate]) -> list[ReportCandidate]:
    """按底层报告独立性键合并候选，保留信息更完整的一项。"""

    rows: dict[str, ReportCandidate] = {}
    for group in groups:
        for candidate in group:
            existing = rows.get(candidate.independence_key)
            if existing is None:
                rows[candidate.independence_key] = candidate
                continue
            existing_score = int(existing.page_count is not None) + int(existing.recommendation_type != "search_result")
            candidate_score = int(candidate.page_count is not None) + int(candidate.recommendation_type != "search_result")
            if candidate_score > existing_score:
                rows[candidate.independence_key] = candidate
    return list(rows.values())


def discover_candidates(
    request: ReportSearchRequest,
    *,
    profile_dir: str | Path | None = None,
    max_seed_details: int = 4,
) -> tuple[list[ReportCandidate], dict[str, Any]]:
    """经正常网页标题搜索并从详情页推荐区扩展候选。

    Args:
        request: 搜索范围、时效和配额合同。
        profile_dir: secrets 下的登录 profile。
        max_seed_details: 最多打开的主搜索结果数，单位为报告详情页，默认 4。

    Returns:
        去重后的候选列表，以及不含账号信息的检索审计摘要。
    """

    from playwright.sync_api import sync_playwright

    _configure_logging()
    profile = _resolve_profile_dir(profile_dir)
    with sync_playwright() as playwright:
        context = _launch_context(playwright, profile, headless=True)
        try:
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(BASE_URL, wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_timeout(2_000)
            auth = probe_authentication(page)
            if not auth.authenticated:
                raise PermissionError("萝卜投研登录态无效，请先执行 login")
            query_variants = [request.query]
            if request.report_scope == "industry":
                broad_query = re.sub(r"行业深度|深度", "", request.query).strip()
                broad_query = re.sub(r"\s+", " ", broad_query)
                if broad_query and broad_query not in query_variants:
                    query_variants.append(broad_query)
            main_groups: list[list[ReportCandidate]] = []
            recommendation_groups: list[list[ReportCandidate]] = []
            foreign_groups: list[list[ReportCandidate]] = []
            search_url_path = urlsplit(REPORT_SEARCH_URL).path
            for query in query_variants:
                page.goto(REPORT_SEARCH_URL, wait_until="domcontentloaded", timeout=60_000)
                page.wait_for_timeout(2_000)
                _execute_title_search(page, query)
                search_url_path = urlsplit(page.url).path
                main_groups.append(_collect_candidates(page, query))
                recommendation_groups.append(
                    _collect_report_tab(
                        page,
                        label="推荐",
                        query=query,
                        recommendation_type="domestic_recommended",
                    )
                )
                foreign_groups.append(
                    _collect_report_tab(
                        page,
                        label="外资研报",
                        query=query,
                        recommendation_type="foreign_sell_side",
                    )
                )
            main_candidates = _merge_candidates(*main_groups)
            recommendation_candidates = _merge_candidates(*recommendation_groups)
            foreign_candidates = _merge_candidates(*foreign_groups)
            related_groups: list[list[ReportCandidate]] = []
            seed_candidates = _merge_candidates(
                recommendation_candidates,
                foreign_candidates,
                main_candidates,
            )
            seed_candidates.sort(
                key=lambda item: (
                    int(_eligible(item, request)),
                    item.page_count or 0,
                    item.publish_date,
                ),
                reverse=True,
            )
            for seed in seed_candidates[: max(0, int(max_seed_details))]:
                try:
                    page.goto(seed.detail_url, wait_until="domcontentloaded", timeout=60_000)
                    page.wait_for_timeout(2_000)
                    related_groups.append(_collect_candidates(page, request.query))
                except Exception as exc:
                    LOGGER.warning(
                        "detail_discovery failed: url_path=%s error=%s",
                        urlsplit(seed.detail_url).path,
                        type(exc).__name__,
                    )
            candidates = _merge_candidates(
                recommendation_candidates,
                foreign_candidates,
                main_candidates,
                *related_groups,
            )
            selected, quota = select_candidates(candidates, request)
            audit = {
                "schema_version": "datayes.search_audit.v1",
                "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "request": asdict(request),
                "cutoff_date": request.cutoff_date.isoformat(),
                "minimum_pages": request.minimum_pages,
                "search_mode": "title_only",
                "search_queries_executed": query_variants,
                "search_url_path": search_url_path,
                "main_candidate_count": len(main_candidates),
                "domestic_recommendation_candidate_count": len(recommendation_candidates),
                "foreign_tab_candidate_count": len(foreign_candidates),
                "all_candidate_count": len(candidates),
                "selected_count": len(selected),
                "quota": quota,
                "quota_satisfied": (
                    quota["foreign_selected"] >= request.foreign_target
                    and quota["domestic_recommended_selected"] >= request.domestic_target
                ),
                "candidates": [asdict(item) | {"independence_key": item.independence_key} for item in candidates],
                "selected_independence_keys": [item.independence_key for item in selected],
            }
            token = hashlib.sha256(
                f"{request.query}|{request.as_of_date}|{time.time_ns()}".encode("utf-8")
            ).hexdigest()[:12]
            _atomic_write_json(DEFAULT_AUDIT_ROOT / f"search_{token}.json", audit)
            return candidates, audit
        finally:
            context.close()


def _find_download_control(page: Any) -> Any | None:
    """寻找正常网页中的可见 PDF 下载控件。"""

    locators = (
        page.locator(".intro-box .report-download:visible"),
        page.locator(".report-detail-content-container .report-download:visible"),
        page.get_by_role("button", name=_DOWNLOAD_TEXT_PATTERN),
        page.get_by_role("link", name=_DOWNLOAD_TEXT_PATTERN),
        page.locator("a[download]:visible"),
        page.locator("button:has-text('下载'):visible"),
        page.locator("a:has-text('下载'):visible"),
    )
    for locator in locators:
        for index in range(min(locator.count(), 20)):
            element = locator.nth(index)
            try:
                if element.is_visible():
                    return element
            except Exception:
                continue
    return None


def _download_candidate(
    page: Any,
    candidate: ReportCandidate,
    request: ReportSearchRequest,
    *,
    staging_dir: Path,
) -> DownloadedReport:
    """点击详情页下载按钮并完成 PDF 验证与 papers 落盘。"""

    page.goto(candidate.detail_url, wait_until="domcontentloaded", timeout=60_000)
    page.wait_for_timeout(1_500)
    control = _find_download_control(page)
    if control is None:
        raise RuntimeError(f"详情页未找到可见下载控件: {urlsplit(candidate.detail_url).path}")
    staging_dir.mkdir(parents=True, exist_ok=True)
    with page.expect_download(timeout=45_000) as download_info:
        control.click(timeout=10_000)
    download = download_info.value
    suggested = sanitize_filename(download.suggested_filename or "report.pdf")
    if Path(suggested).suffix.lower() != ".pdf":
        suggested = f"{Path(suggested).stem}.pdf"
    staging_path = staging_dir / f"{uuid4().hex}_{suggested}"
    download.save_as(str(staging_path))
    return _finalize_download(
        staging_path,
        candidate=candidate,
        request=request,
    )


def _manifest_entry(report: DownloadedReport, request: ReportSearchRequest) -> dict[str, Any]:
    """把下载结果转换为 A/B/C 共用来源元数据。"""

    candidate = report.candidate
    return {
        "relative_path": report.relative_path,
        "sha256": report.sha256,
        "size_bytes": report.size_bytes,
        "page_count": report.page_count,
        "title": candidate.title,
        "publisher": candidate.publisher,
        "publish_date": candidate.publish_date,
        "source_url": candidate.detail_url,
        "report_scope": request.report_scope,
        "publisher_origin": candidate.publisher_origin,
        "recommendation_type": candidate.recommendation_type,
        "query": candidate.query,
        "search_field": "title_only",
        "fetch_method": "playwright_datayes",
        "downloaded_at_utc": report.downloaded_at_utc,
        "source_type": "卖方深度" if report.page_count >= 20 else "卖方周报",
        "value_layer": "双层" if request.report_scope == "company" else "深度框架",
        "quality_tier": 2,
        "source_credibility": "sell_side_secondary",
        "is_primary_source": False,
        # DataYes 仅是聚合入口；外资原文默认按英文登记，若下载后核验为中文版，
        # producer 应在实际引用时用显式 language 覆盖清单默认值。
        "language": "en" if candidate.publisher_origin == "foreign" else "zh",
        "aggregator": "萝卜投研",
        "aggregator_domain": "r.datayes.com",
        "independence_key": candidate.independence_key,
        "independence_rationale": "按底层券商、报告标题和发布日期去重；萝卜投研仅为聚合入口。",
    }


def download_selected_reports(
    request: ReportSearchRequest,
    *,
    profile_dir: str | Path | None = None,
) -> dict[str, Any]:
    """发现并下载满足配额的报告，写入 papers 来源清单。

    Args:
        request: 标题、范围、时效、页数与国内/外资配额。
        profile_dir: secrets 下的登录 profile。

    Returns:
        下载成功、失败与配额结果；配额不足仍保存真实成功项，但状态为 shortfall。
    """

    from playwright.sync_api import sync_playwright

    candidates, search_audit = discover_candidates(request, profile_dir=profile_dir)
    selected, quota = select_candidates(candidates, request)
    profile = _resolve_profile_dir(profile_dir)
    run_token = hashlib.sha256(
        f"{request.query}|{request.as_of_date}|{time.time_ns()}".encode("utf-8")
    ).hexdigest()[:12]
    staging_dir = DEFAULT_AUDIT_ROOT / "downloads" / run_token
    downloaded: list[DownloadedReport] = []
    failures: list[dict[str, str]] = []
    with sync_playwright() as playwright:
        context = _launch_context(playwright, profile, headless=True)
        try:
            page = context.pages[0] if context.pages else context.new_page()
            for candidate in selected:
                try:
                    downloaded.append(
                        _download_candidate(
                            page,
                            candidate,
                            request,
                            staging_dir=staging_dir,
                        )
                    )
                except Exception as exc:
                    failures.append({
                        "independence_key": candidate.independence_key,
                        "detail_path": urlsplit(candidate.detail_url).path,
                        "error_type": type(exc).__name__,
                        "message": str(exc)[:300],
                    })
                    LOGGER.error(
                        "download_candidate failed: detail_path=%s error=%s",
                        urlsplit(candidate.detail_url).path,
                        type(exc).__name__,
                    )
        finally:
            context.close()
    entries = [_manifest_entry(item, request) for item in downloaded]
    domestic_downloaded = sum(
        entry["publisher_origin"] == "domestic"
        and entry["recommendation_type"] == "domestic_recommended"
        for entry in entries
    )
    domestic_title_fallback_downloaded = sum(
        entry["publisher_origin"] == "domestic"
        and entry["recommendation_type"] == "search_result"
        for entry in entries
    )
    domestic_reference_downloaded = domestic_downloaded + domestic_title_fallback_downloaded
    foreign_downloaded = sum(entry["publisher_origin"] == "foreign" for entry in entries)
    quota_satisfied = (
        domestic_downloaded >= request.domestic_target
        and foreign_downloaded >= request.foreign_target
    )
    manifest_payload = {
        "schema_version": SOURCE_MANIFEST_SCHEMA,
        "provider": "datayes_playwright",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "request": asdict(request),
        "selection_contract": {
            "search_field": "title_only",
            "cutoff_date": request.cutoff_date.isoformat(),
            "minimum_pages": request.minimum_pages,
            "domestic_recommended_target": request.domestic_target,
            "foreign_sell_side_target": request.foreign_target,
            "allow_domestic_title_search_fallback": True,
            "fallback_satisfies_platform_recommendation_quota": False,
        },
        "quota": {
            **quota,
            "domestic_recommended_downloaded": domestic_downloaded,
            "domestic_title_fallback_downloaded": domestic_title_fallback_downloaded,
            "domestic_reference_downloaded": domestic_reference_downloaded,
            "foreign_downloaded": foreign_downloaded,
            "quota_satisfied": quota_satisfied,
        },
        "search_audit_summary": {
            "all_candidate_count": search_audit["all_candidate_count"],
            "selected_count": search_audit["selected_count"],
        },
        "entries": entries,
        "failures": failures,
    }
    manifest_dir = ROOT / "papers" / request.papers_subdir / "_source_manifests"
    manifest_path = manifest_dir / f"datayes_{request.report_scope}_{run_token}.json"
    write_manifest(
        manifest_path,
        project_root=ROOT,
        payload=manifest_payload,
    )
    summary = {
        "status": "complete" if quota_satisfied and not failures else "shortfall",
        "manifest_path": manifest_path.relative_to(ROOT).as_posix(),
        "downloaded_count": len(downloaded),
        "download_succeeded": bool(downloaded) and not failures,
        "failure_count": len(failures),
        "quota_satisfied": quota_satisfied,
        "domestic_recommended_downloaded": domestic_downloaded,
        "domestic_title_fallback_downloaded": domestic_title_fallback_downloaded,
        "domestic_reference_downloaded": domestic_reference_downloaded,
        "foreign_downloaded": foreign_downloaded,
    }
    _atomic_write_json(DEFAULT_AUDIT_ROOT / f"download_{run_token}.json", summary)
    return summary


def _configure_logging() -> None:
    """将运行日志写入 cache，不向终端输出账号相关页面文本。"""

    DEFAULT_AUDIT_ROOT.mkdir(parents=True, exist_ok=True)
    if LOGGER.handlers:
        return
    handler = logging.FileHandler(
        DEFAULT_AUDIT_ROOT / "datayes_browser.log",
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    LOGGER.addHandler(handler)
    LOGGER.setLevel(logging.INFO)


def _resolve_profile_dir(profile_dir: str | Path | None = None) -> Path:
    """解析登录 profile，强制限制在 secrets 目录内。

    Args:
        profile_dir: 可选 profile 目录；必须位于
            ``tools/dynamic/secrets``，路径单位为本机绝对文件系统路径。

    Returns:
        已创建的绝对 profile 目录。
    """

    secrets_root = (ROOT / "tools" / "dynamic" / "secrets").resolve()
    target = Path(profile_dir or DEFAULT_PROFILE_DIR).resolve()
    if target != secrets_root and secrets_root not in target.parents:
        raise ValueError(f"DataYes profile 必须位于 secrets 目录内: {target}")
    target.mkdir(parents=True, exist_ok=True)
    return target


def harden_profile_acl(profile_dir: Path) -> bool:
    """在 Windows 上收紧 profile ACL。

    Args:
        profile_dir: 已解析的 secrets 子目录。

    Returns:
        ACL 命令是否成功；非 Windows 返回 True。此函数不读取目录内容。
    """

    if os.name != "nt":
        return True
    user = subprocess.run(
        ["whoami"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    ).stdout.strip()
    command = [
        "icacls",
        str(profile_dir),
        "/inheritance:r",
        "/grant:r",
        f"{user}:(OI)(CI)F",
        "*S-1-5-18:(OI)(CI)F",
        "*S-1-5-32-544:(OI)(CI)F",
        "/q",
    ]
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        LOGGER.error("harden_profile_acl failed: returncode=%s", completed.returncode)
        return False
    # 旧实现曾递归关闭每个文件的继承，导致普通文件只有“可继承给子项”的
    # ACE 而自身没有权限。对既有子项显式补 FullControl；空 profile 时该命令
    # 可以无匹配失败，新建文件仍会继承上面的根目录 ACL。
    existing = subprocess.run(
        [
            "icacls",
            str(profile_dir / "*"),
            "/grant:r",
            f"{user}:F",
            "*S-1-5-18:F",
            "*S-1-5-32-544:F",
            "/t",
            "/c",
            "/q",
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if existing.returncode not in {0, 2}:
        LOGGER.warning(
            "harden_profile_acl existing item repair incomplete: returncode=%s",
            existing.returncode,
        )
    return True


def _browser_proxy() -> dict[str, str] | None:
    """把本机 HTTP(S) 代理传给 Chromium，不记录代理凭据。"""

    value = str(os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY") or "").strip()
    if not value:
        return None
    parts = urlsplit(value)
    if parts.scheme not in {"http", "https", "socks5"} or not parts.hostname:
        return None
    server = f"{parts.scheme}://{parts.hostname}"
    if parts.port:
        server += f":{parts.port}"
    result = {"server": server}
    if parts.username:
        result["username"] = parts.username
    if parts.password:
        result["password"] = parts.password
    return result


def _launch_context(playwright: Any, profile_dir: Path, *, headless: bool) -> Any:
    """启动复用登录态的 Chromium persistent context。

    Args:
        playwright: ``sync_playwright`` 已启动实例。
        profile_dir: secrets 下的本机 profile 目录。
        headless: True 为后台执行，False 为用户可见浏览器。

    Returns:
        Playwright BrowserContext；viewport 为 1440×1000 CSS pixels。
    """

    options: dict[str, Any] = {
        "user_data_dir": str(profile_dir),
        "headless": headless,
        "accept_downloads": True,
        "locale": "zh-CN",
        "timezone_id": "Asia/Shanghai",
        "viewport": {"width": 1440, "height": 1000},
        "args": ["--disable-blink-features=AutomationControlled"],
    }
    system_browser = next((path for path in SYSTEM_BROWSER_CANDIDATES if path.is_file()), None)
    if system_browser is not None:
        options["executable_path"] = str(system_browser)
    proxy = _browser_proxy()
    if proxy:
        options["proxy"] = proxy
    context = playwright.chromium.launch_persistent_context(**options)
    context.add_init_script(
        "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
    )
    return context


def _is_login_form(page: Any) -> bool:
    """只用 DOM 类型和 URL 判断登录墙，不读取输入值。"""

    path = urlsplit(page.url or "").path.lower()
    if any(token in path for token in _LOGIN_URL_TOKENS):
        return True
    try:
        if page.locator("input[type='password']:visible").count() > 0:
            return True
        login_text = page.get_by_text(re.compile(r"^(登录|立即登录|账号登录)$"))
        return login_text.count() > 0 and page.locator("input:visible").count() > 0
    except Exception:
        return False


def _has_login_entry(page: Any) -> bool:
    """检查是否仍存在明确可见的登录入口。"""

    locators = (
        page.get_by_role("button", name=re.compile(r"^(登录|立即登录)$")),
        page.get_by_role("link", name=re.compile(r"^(登录|立即登录)$")),
        page.get_by_text(re.compile(r"^(登录|立即登录)$")),
    )
    for locator in locators:
        for index in range(min(locator.count(), 10)):
            try:
                if locator.nth(index).is_visible():
                    return True
            except Exception:
                continue
    return False


def _open_login_form(page: Any) -> None:
    """若首页只有登录入口，则通过可见控件打开登录表单。"""

    if _is_login_form(page):
        return
    locators = (
        page.get_by_role("button", name=re.compile(r"登录")),
        page.get_by_role("link", name=re.compile(r"登录")),
        page.get_by_text(re.compile(r"^(登录|立即登录)$")),
    )
    for locator in locators:
        for index in range(min(locator.count(), 10)):
            element = locator.nth(index)
            try:
                if element.is_visible():
                    element.click(timeout=5_000)
                    page.wait_for_timeout(1_000)
                    return
            except Exception:
                continue


def _fill_login_from_keyring(page: Any) -> bool:
    """从 Windows Credential Manager 取凭据并填入可见登录表单。

    Returns:
        是否完成账号和密码填充。函数不记录输入值；验证码仍由用户处理。
    """

    _open_login_form(page)
    password = _first_visible_locator(page, ("input[type='password']:visible",))
    username = _first_visible_locator(
        page,
        (
            "input[placeholder*='账号']:visible",
            "input[placeholder*='手机']:visible",
            "input[placeholder*='邮箱']:visible",
            "input[type='email']:visible",
            "input[type='tel']:visible",
            "input[type='text']:visible",
        ),
    )
    if username is None or password is None:
        return False
    credential_username, credential_password = load_credentials()
    username.fill(credential_username)
    password.fill(credential_password)
    return True


def _submit_login_form(page: Any) -> bool:
    """只提交包含可见密码框的登录表单，避免误点页面其他按钮。

    Returns:
        是否通过表单内登录按钮、提交控件或密码框回车触发了提交。
    """

    password = _first_visible_locator(page, ("input[type='password']:visible",))
    if password is None:
        return False
    form = password.locator("xpath=ancestor::form[1]")
    if form.count():
        controls = (
            form.first.get_by_role(
                "button",
                name=re.compile(r"^(登录|立即登录|账号登录)$"),
            ),
            form.first.locator("button[type='submit']:visible"),
            form.first.locator("input[type='submit']:visible"),
        )
        for locator in controls:
            for index in range(min(locator.count(), 6)):
                element = locator.nth(index)
                try:
                    if element.is_visible() and element.is_enabled():
                        element.click(timeout=5_000)
                        return True
                except Exception:
                    continue
    # 某些单页应用没有 form 标签；凭据已成功填充时，密码框回车仍限定在登录上下文。
    try:
        password.press("Enter")
        return True
    except Exception:
        return False


def _has_security_challenge(page: Any) -> bool:
    """识别常见验证码或安全校验提示，不读取表单输入值。"""

    patterns = re.compile(r"验证码|安全验证|滑块|请完成验证|captcha", re.IGNORECASE)
    try:
        challenge = page.get_by_text(patterns)
        for index in range(min(challenge.count(), 20)):
            if challenge.nth(index).is_visible():
                return True
    except Exception:
        return False
    return False


def _write_login_diagnostic(page: Any, *, submitted: bool) -> None:
    """写入不含字段值和页面正文的登录控件诊断。"""

    try:
        password_count = page.locator("input[type='password']:visible").count()
        checkbox_count = page.locator("input[type='checkbox']:visible").count()
        agreement_visible = page.get_by_text(
            re.compile(r"用户协议|服务协议|隐私政策|我已阅读|同意")
        ).count() > 0
        payload = {
            "schema_version": "datayes.login_diagnostic.v1",
            "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "current_path": urlsplit(page.url or BASE_URL).path or "/",
            "submitted": bool(submitted),
            "login_form_visible": _is_login_form(page),
            "login_entry_visible": _has_login_entry(page),
            "security_challenge_visible": _has_security_challenge(page),
            "password_input_count": int(password_count),
            "checkbox_count": int(checkbox_count),
            "agreement_text_visible": bool(agreement_visible),
        }
        _atomic_write_json(DEFAULT_AUDIT_ROOT / "login_diagnostic.json", payload)
    except Exception as exc:
        LOGGER.warning("login_diagnostic failed error=%s", type(exc).__name__)


def probe_authentication(page: Any) -> AuthProbe:
    """生成不含账号、cookie 和 query 的登录态检查结果。"""

    login_form_visible = _is_login_form(page)
    login_entry_visible = _has_login_entry(page)
    path = urlsplit(page.url or BASE_URL).path or "/"
    return AuthProbe(
        authenticated=not login_form_visible and not login_entry_visible,
        current_path=path,
        login_form_visible=login_form_visible,
        checked_at_utc=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )


def interactive_login(
    *,
    profile_dir: str | Path | None = None,
    timeout_seconds: int = 900,
) -> AuthProbe:
    """用 Credential Manager 凭据登录，必要时等待用户完成安全校验。

    Args:
        profile_dir: secrets 下的 Chromium profile 路径。
        timeout_seconds: 等待登录或安全校验完成的秒数，默认 900 秒。

    Returns:
        最后一次非敏感登录态探测结果。连续确认登录成功后自动关闭浏览器。
    """

    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import sync_playwright

    _configure_logging()
    profile = _resolve_profile_dir(profile_dir)
    if not harden_profile_acl(profile):
        raise RuntimeError("DataYes profile ACL 收紧失败，拒绝继续保存登录态")
    last_probe = AuthProbe(False, "/", True, datetime.now(timezone.utc).isoformat())
    deadline = time.monotonic() + max(60, int(timeout_seconds))
    with sync_playwright() as playwright:
        context = _launch_context(playwright, profile, headless=False)
        try:
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(BASE_URL, wait_until="domcontentloaded", timeout=60_000)
            submitted = False
            if _is_login_form(page) or not probe_authentication(page).authenticated:
                if _fill_login_from_keyring(page):
                    submitted = _submit_login_form(page)
            else:
                # 部分首页先显示登录按钮，点击后再判断是否需要填充。
                _open_login_form(page)
                if _is_login_form(page):
                    if _fill_login_from_keyring(page):
                        submitted = _submit_login_form(page)
            LOGGER.info("interactive_login browser_opened submitted=%s", submitted)
            page.wait_for_timeout(2_000)
            _write_login_diagnostic(page, submitted=submitted)
            consecutive_authenticated = 0
            challenge_logged = False
            while time.monotonic() < deadline:
                try:
                    pages = context.pages
                    if not pages:
                        break
                    page = pages[-1]
                    last_probe = probe_authentication(page)
                    if last_probe.authenticated:
                        consecutive_authenticated += 1
                        if consecutive_authenticated >= 4:
                            break
                    else:
                        consecutive_authenticated = 0
                    if _has_security_challenge(page) and not challenge_logged:
                        LOGGER.info("interactive_login security_challenge_visible")
                        challenge_logged = True
                    page.wait_for_timeout(750)
                except PlaywrightError:
                    break
        finally:
            try:
                context.close()
            except PlaywrightError:
                pass
    LOGGER.info("interactive_login browser_closed authenticated=%s", last_probe.authenticated)
    return last_probe


def authentication_status(
    *,
    profile_dir: str | Path | None = None,
) -> AuthProbe:
    """后台访问首页并检查登录态，不打印或导出账号信息。"""

    from playwright.sync_api import sync_playwright

    _configure_logging()
    profile = _resolve_profile_dir(profile_dir)
    with sync_playwright() as playwright:
        context = _launch_context(playwright, profile, headless=True)
        try:
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(BASE_URL, wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_timeout(2_000)
            return probe_authentication(page)
        finally:
            context.close()


def _scrub_text(value: str) -> str:
    """移除可能的邮箱、手机号和超长文本，仅用于 UI 结构探测。"""

    text = re.sub(r"\s+", " ", str(value or "")).strip()
    for pattern in _SENSITIVE_TEXT:
        text = pattern.sub("[redacted]", text)
    return text[:120]


def probe_ui(
    *,
    profile_dir: str | Path | None = None,
    output: str | Path | None = None,
) -> dict[str, Any]:
    """记录非敏感 UI 结构，供站点改版后修订选择器。

    Args:
        profile_dir: secrets 下的 Chromium profile 路径。
        output: cache 下 JSON 路径；默认 ``cache/datayes_reports/ui_probe.json``。

    Returns:
        输入框、按钮和站内链接的截断结构，不包含输入值或浏览器存储。
    """

    from playwright.sync_api import sync_playwright

    _configure_logging()
    profile = _resolve_profile_dir(profile_dir)
    target = Path(output or DEFAULT_AUDIT_ROOT / "ui_probe.json").resolve()
    if ROOT.resolve() not in target.parents:
        raise ValueError("UI probe 只能写入项目目录")
    with sync_playwright() as playwright:
        context = _launch_context(playwright, profile, headless=True)
        try:
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(REPORT_SEARCH_URL, wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_timeout(3_000)
            probe = probe_authentication(page)
            inputs = page.locator("input:visible")
            input_rows = []
            for index in range(min(inputs.count(), 40)):
                element = inputs.nth(index)
                parent_text = ""
                try:
                    parent_text = _scrub_text(element.locator("xpath=parent::*").inner_text())
                except Exception:
                    pass
                input_rows.append({
                    "type": element.get_attribute("type"),
                    "placeholder": _scrub_text(element.get_attribute("placeholder") or ""),
                    "aria_label": _scrub_text(element.get_attribute("aria-label") or ""),
                    "id": _scrub_text(element.get_attribute("id") or ""),
                    "name": _scrub_text(element.get_attribute("name") or ""),
                    "class": _scrub_text(element.get_attribute("class") or ""),
                    "parent_text": parent_text,
                })
            buttons = page.locator("button:visible,[role='button']:visible")
            button_rows = []
            for index in range(min(buttons.count(), 80)):
                text = _scrub_text(buttons.nth(index).inner_text())
                if text and text != "[redacted]":
                    button_rows.append(text)
            anchors = page.locator("a:visible")
            anchor_rows = []
            for index in range(min(anchors.count(), 120)):
                element = anchors.nth(index)
                href = element.get_attribute("href") or ""
                path = urlsplit(href).path if href.startswith("http") else href.split("?", 1)[0]
                text = _scrub_text(element.inner_text())
                if text or path:
                    anchor_rows.append({"text": text, "path": path[:160]})
            payload = {
                "schema_version": "datayes.ui_probe.v1",
                "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "auth": asdict(probe),
                "inputs": input_rows,
                "buttons": list(dict.fromkeys(button_rows)),
                "anchors": anchor_rows,
            }
            _atomic_write_json(target, payload)
            return payload
        finally:
            context.close()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="萝卜投研 Playwright 研报连接器")
    parser.add_argument("--profile-dir", type=Path)
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("configure-credentials", help="把账号密码保存到 Windows Credential Manager")
    subparsers.add_parser("credential-status", help="只检查系统凭据是否已配置")
    login = subparsers.add_parser(
        "login",
        help="用 Windows Credential Manager 凭据登录；安全验证由用户完成",
    )
    login.add_argument("--timeout-seconds", type=int, default=900)
    subparsers.add_parser("status", help="检查登录态，不输出账号信息")
    probe = subparsers.add_parser("probe-ui", help="生成脱敏 UI 结构")
    probe.add_argument("--output", type=Path)
    search = subparsers.add_parser("search", help="执行标题搜索并输出脱敏候选审计")
    download = subparsers.add_parser("download", help="搜索并下载满足配额的研报")
    for command in (search, download):
        command.add_argument("--query", required=True)
        command.add_argument("--papers-subdir", required=True)
        command.add_argument("--scope", choices=("company", "industry"), required=True)
        command.add_argument("--as-of-date", default=date.today().isoformat())
        command.add_argument("--domestic-target", type=int, choices=(1, 2), default=2)
        command.add_argument("--foreign-target", type=int, choices=(1, 2), default=2)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.command == "configure-credentials":
        saved = credential_dialog()
        print(json.dumps({"configured": saved}, ensure_ascii=False))
        return 0 if saved else 2
    if args.command == "credential-status":
        result = credential_status()
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result["configured"] else 2
    if args.command == "login":
        result = interactive_login(
            profile_dir=args.profile_dir,
            timeout_seconds=args.timeout_seconds,
        )
        print(json.dumps(asdict(result), ensure_ascii=False))
        return 0 if result.authenticated else 2
    if args.command == "status":
        result = authentication_status(profile_dir=args.profile_dir)
        print(json.dumps(asdict(result), ensure_ascii=False))
        return 0 if result.authenticated else 2
    if args.command == "probe-ui":
        payload = probe_ui(profile_dir=args.profile_dir, output=args.output)
        print(json.dumps({"auth": payload["auth"], "input_count": len(payload["inputs"]), "button_count": len(payload["buttons"]), "anchor_count": len(payload["anchors"])}, ensure_ascii=False))
        return 0 if payload["auth"]["authenticated"] else 2
    if args.command in {"search", "download"}:
        request = ReportSearchRequest(
            query=args.query,
            papers_subdir=args.papers_subdir,
            report_scope=args.scope,
            as_of_date=args.as_of_date,
            domestic_target=args.domestic_target,
            foreign_target=args.foreign_target,
        )
        if args.command == "search":
            _candidates, audit = discover_candidates(request, profile_dir=args.profile_dir)
            summary = {
                "status": "complete" if audit["quota_satisfied"] else "shortfall",
                "all_candidate_count": audit["all_candidate_count"],
                "selected_count": audit["selected_count"],
                "quota": audit["quota"],
                "quota_satisfied": audit["quota_satisfied"],
            }
            print(json.dumps(summary, ensure_ascii=False))
            return 0 if audit["quota_satisfied"] else 3
        summary = download_selected_reports(request, profile_dir=args.profile_dir)
        print(json.dumps(summary, ensure_ascii=False))
        return 0 if summary["quota_satisfied"] and not summary["failure_count"] else 3
    parser.error(f"不支持的命令: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
