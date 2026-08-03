from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import zipfile
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Iterable
from zoneinfo import ZoneInfo

from tools.maintenance.build_required_cache_bundle import collect_required_cache
from tools.pipeline.paper_paths import paper_path_violations


ROOT = Path(__file__).resolve().parents[2]
BEIJING = ZoneInfo("Asia/Shanghai")
SCHEMA_VERSION = "industry_demo.viewer_broadcast_bundle.v1"
PACKAGE_ROOT = "industry_demo"
REQUIRED_DIRECTORIES = (
    "data",
    "docs",
    "tools",
    "papers",
    "opportunity_lens",
    "config",
)
ROOT_FILES = ("restart_viewer.bat", "requirements.txt")
LIVE_DATABASES = (
    "data/research.db",
    "data/sentiment.db",
    "data/opportunity_lens.db",
    "data/financial.db",
)
SKIP_PREFIXES = (
    "tools/dynamic/secrets/",
)
SKIP_PARTS = {"__pycache__", ".pytest_cache"}
SKIP_SUFFIXES = (
    ".pyc",
    ".pyo",
    ".db-wal",
    ".db-shm",
    ".db-journal",
    ".sqlite-wal",
    ".sqlite-shm",
    ".sqlite-journal",
    ".lock",
)
STORE_SUFFIXES = {
    ".7z",
    ".docx",
    ".gif",
    ".jpeg",
    ".jpg",
    ".pdf",
    ".png",
    ".pptx",
    ".webp",
    ".xlsx",
    ".xls",
    ".zip",
}
RUN15_PACK = (
    "opportunity_lens/research_outputs/"
    "20260725_chint_pv_profit_quality_run15/run15_pack_stage.json"
)
RUN15_EXPORTS = (
    "opportunity_lens/research_outputs/"
    "20260725_chint_pv_profit_quality_run15/company_financial_profile_export_v1.json",
    "opportunity_lens/research_outputs/"
    "20260725_chint_pv_profit_quality_run15/company_financial_profile_export_bridge_v1.json",
)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _filesystem_path(path: Path) -> Path:
    """Use the Windows extended-length form without changing archive names."""
    if os.name != "nt":
        return path
    raw = os.fspath(path.resolve())
    if raw.startswith("\\\\?\\"):
        return Path(raw)
    if raw.startswith("\\\\"):
        return Path("\\\\?\\UNC\\" + raw[2:])
    return Path("\\\\?\\" + raw)


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _should_skip(relative: str) -> bool:
    normalized = relative.replace("\\", "/")
    if normalized in LIVE_DATABASES:
        return True
    if any(normalized.startswith(prefix) for prefix in SKIP_PREFIXES):
        return True
    if any(part in SKIP_PARTS for part in Path(normalized).parts):
        return True
    return normalized.lower().endswith(SKIP_SUFFIXES)


def _iter_payload_files(root: Path) -> Iterable[tuple[str, Path]]:
    for directory_name in REQUIRED_DIRECTORIES:
        directory = root / directory_name
        if not directory.is_dir():
            raise FileNotFoundError(directory)
        for current, dirnames, filenames in os.walk(directory):
            current_path = Path(current)
            relative_directory = current_path.relative_to(root).as_posix()
            dirnames[:] = sorted(
                name
                for name in dirnames
                if not _should_skip(f"{relative_directory}/{name}/")
            )
            for name in sorted(filenames):
                source = current_path / name
                relative = source.relative_to(root).as_posix()
                if not _should_skip(relative):
                    yield relative, source
    for relative in ROOT_FILES:
        source = root / relative
        if not source.is_file():
            raise FileNotFoundError(source)
        yield relative, source


def _sqlite_snapshot(source: Path, target: Path) -> dict[str, object]:
    target.parent.mkdir(parents=True, exist_ok=True)
    uri = source.resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True, timeout=30)) as source_conn:
        with closing(sqlite3.connect(target)) as target_conn:
            source_conn.backup(target_conn)
            target_conn.commit()
    with closing(sqlite3.connect(target)) as conn:
        integrity = str(conn.execute("PRAGMA integrity_check").fetchone()[0])
        foreign_key_issues = len(conn.execute("PRAGMA foreign_key_check").fetchall())
        table_count = int(
            conn.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
            ).fetchone()[0]
        )
    if integrity != "ok" or foreign_key_issues:
        raise RuntimeError(
            f"SQLite 快照校验失败: {source}; "
            f"integrity={integrity}, foreign_key_issues={foreign_key_issues}"
        )
    return {
        "path": source.relative_to(source.parents[1]).as_posix(),
        "size": target.stat().st_size,
        "sha256": _sha256_file(target),
        "integrity_check": integrity,
        "foreign_key_issues": foreign_key_issues,
        "table_count": table_count,
    }


def _zip_info(archive_name: str, source: Path) -> zipfile.ZipInfo:
    stat = source.stat()
    modified = datetime.fromtimestamp(stat.st_mtime)
    year = min(max(modified.year, 1980), 2107)
    info = zipfile.ZipInfo(
        archive_name,
        (
            year,
            modified.month,
            modified.day,
            modified.hour,
            modified.minute,
            modified.second,
        ),
    )
    info.compress_type = (
        zipfile.ZIP_STORED
        if source.suffix.lower() in STORE_SUFFIXES
        else zipfile.ZIP_DEFLATED
    )
    info.external_attr = (stat.st_mode & 0xFFFF) << 16
    return info


def _add_file(
    archive: zipfile.ZipFile,
    *,
    relative: str,
    source: Path,
) -> dict[str, object]:
    archive_name = f"{PACKAGE_ROOT}/{relative}"
    filesystem_source = _filesystem_path(source)
    digest = hashlib.sha256()
    size = 0
    with filesystem_source.open("rb") as source_handle, archive.open(
        _zip_info(archive_name, filesystem_source),
        "w",
    ) as target_handle:
        for chunk in iter(lambda: source_handle.read(1024 * 1024), b""):
            target_handle.write(chunk)
            digest.update(chunk)
            size += len(chunk)
    return {
        "path": relative,
        "size": size,
        "sha256": digest.hexdigest(),
    }


def _read_run15_summary(root: Path) -> dict[str, object]:
    payload = json.loads((root / RUN15_PACK).read_text(encoding="utf-8"))
    factor_count = sum(
        len(entity.get("factor_scores") or [])
        for entity in payload.get("entities", [])
    )
    return {
        "pack_path": RUN15_PACK,
        "pack_schema_version": payload.get("pack_schema_version"),
        "workflow_contract_version": payload.get("workflow_contract_version"),
        "display_title": payload.get("display_title"),
        "source_count": len(payload.get("sources", [])),
        "data_point_count": len(payload.get("data_points", [])),
        "entity_count": len(payload.get("entities", [])),
        "section_count": len(payload.get("sections", [])),
        "factor_count": factor_count,
        "pack_sha256": _sha256_file(root / RUN15_PACK),
        "financial_exports": [
            {
                "path": relative,
                "sha256": _sha256_file(root / relative),
            }
            for relative in RUN15_EXPORTS
        ],
    }


def _read_browser_audit(root: Path, browser_audit: Path | None) -> dict[str, object]:
    if browser_audit is None:
        return {"included": False}
    resolved = browser_audit.resolve()
    payload = json.loads(resolved.read_text(encoding="utf-8"))
    return {
        "included": False,
        "source_path": resolved.relative_to(root).as_posix(),
        "sha256": _sha256_file(resolved),
        "verdict": payload.get("verdict"),
        "issue_count": len(payload.get("issues", [])),
        "route_count": len(payload.get("routes", [])),
        "pack_hash": payload.get("pack_hash"),
        "ui_bundle_hash": payload.get("ui_bundle_hash"),
        "generated_at": payload.get("generated_at"),
    }


def _readme_legacy(version: str) -> str:
    return f"""# Industry Demo 内网广播包

版本：{version}

本包包含 Viewer 的完整运行闭包：`data/`、`docs/`、`tools/`、`papers/`、
`opportunity_lens/`、`config/`、被配置或四库引用的必要 `cache/`、
`restart_viewer.bat` 与 `requirements.txt`。
四个 SQLite 文件均由 SQLite backup API 生成一致性快照，未直接复制 WAL 状态。

## 已有内网实例：使用增量安装，避免丢失评论和日常数据

不要把本包的 `data/` 直接覆盖到正在运营的虚拟机。内网评论位于
`research.db.analyst_note`，新闻、情绪、行情和调度状态也在四个 live 数据库中。

1. 停止 Viewer 和所有会写库的计划任务。
2. 解压本包。
3. 在解压后的 `industry_demo` 目录执行：

   `python -m tools.maintenance.apply_run15_broadcast --target-root "现有内网项目根目录"`

该命令复制 Viewer 代码、配置、文档、研报和 Opportunity Lens 研究文件，但不会
覆盖目标机四个数据库；随后只把 Run15 与正泰电器财务模型增量写入目标数据库。
执行前会对目标机 `opportunity_lens.db` 和 `financial.db` 创建事务一致的临时回退
快照，执行后自动运行 Viewer preflight。

4. 预检通过后，在目标项目根目录执行 `restart_viewer.bat`。
5. 验收 `/opportunity-lens/run/15` 与 `/company/632`。

## 全新安装

只有目标目录没有任何运营数据时，才可以直接使用本包完整的 `industry_demo/`
目录。启动前执行：

`python tools/viewer/preflight.py --root .`

## 状态说明

Run15 已通过确定性合同、证据、来源、去重、单位/范围门禁和桌面/移动浏览器审计。
由于当前没有独立 reviewer 或人工 reviewer 签名，它在数据库中保持
`under_review / reviewable`，本包不把它伪装成正式发布状态。
"""


def _readme(version: str, *, full_replace: bool = False) -> str:
    if full_replace:
        return f"""# Industry Demo 内网全量覆盖广播包

版本：{version}

本包包含 Viewer 的完整运行闭包：`data/`、`docs/`、`tools/`、`papers/`、
`opportunity_lens/`、`config/`、被配置或四库引用的必要 `cache/`、
`restart_viewer.bat` 和 `requirements.txt`。
四个 SQLite 文件均通过 SQLite backup API 生成一致性快照，没有直接复制
WAL 运行状态。

## 部署方式：完整目录替换

本版本按用户明确要求覆盖目标机全部内容，不保留目标机旧评论、日常抓取状态或
旧数据库。不要运行 `tools.maintenance.apply_run15_broadcast`；该工具只适用于
早期 Run15 增量包，不能安装本版本新增的完整行业数据库。

1. 把压缩包解压到新的临时目录，不要直接解压到旧 `C:\\industry_demo` 内。
2. 在解压目录直接双击或从 CMD 运行：

   `INSTALL_FULL_REPLACE.cmd`

安装器会先核验包内锂电池代码、模型和数据库，停止旧 Viewer，将完整目录原子替换
到 `C:\\industry_demo`，运行新版预检和 `restart_viewer.bat`，再验证版本指纹及核心
路由。安装失败会恢复旧目录。

3. 验收 `/research`、`/industry/29`、`/industry-chain`、
   `/tools/battery-calculator` 和 `/industry/lithium-battery/comparison`。

本包内的 `BROADCAST_MANIFEST.json` 记录四库快照、文件清单和 SHA256。
"""
    return f"""# Industry Demo 内网广播包

版本：{version}

本包包含 Viewer 的完整运行闭包：`data/`、`docs/`、`tools/`、`papers/`、
`opportunity_lens/`、`config/`、被配置或四库引用的必要 `cache/`、
`restart_viewer.bat` 和 `requirements.txt`。
四个 SQLite 文件均通过 SQLite backup API 生成一致性快照，没有直接复制
WAL 运行状态。

## 已有内网实例：增量安装并保留评论与日常数据

不要把本包的 `data/` 直接覆盖到正在运营的虚拟机。内网评论位于
`research.db.analyst_note`，新闻、情绪、行情和调度状态也保存在四个 live
数据库中。

1. 停止 Viewer 和所有可能写库的计划任务。
2. 解压本包。
3. 在解压后的 `industry_demo` 目录执行：

   `python -m tools.maintenance.apply_run15_broadcast --target-root "现有内网项目根目录"`

该命令复制 Viewer 代码、配置、文档、研报和 Opportunity Lens 研究文件，但不会
覆盖目标机四个数据库；随后只把 Run15 与正泰电器财务模型增量写入目标数据库。
执行前会为目标机 `opportunity_lens.db` 和 `financial.db` 创建事务一致的临时回退
快照，执行后自动运行 Viewer preflight。

4. 预检通过后，在目标项目根目录执行 `restart_viewer.bat`。
5. 验收 `/opportunity-lens/run/15` 和 `/company/632`。

## 全新安装

只有目标目录不存在任何运营数据时，才可以直接使用本包完整的
`industry_demo/` 目录。启动前执行：

`python tools/viewer/preflight.py --root .`

## 状态说明

Run15 已通过确定性合同、证据、来源、去重、单位、范围门禁，以及桌面端和移动端
浏览器审计。由于当前没有独立 reviewer 或人工 reviewer 签名，它在数据库中保持
`under_review / reviewable`；本包没有把它伪装成正式发布状态。
"""


def _full_replace_cmd() -> str:
    return """@echo off\r
chcp 65001 >nul\r
setlocal\r
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Install-IndustryDemo.ps1" %*\r
set "RC=%ERRORLEVEL%"\r
if not "%RC%"=="0" echo 安装失败，错误码 %RC%。\r
pause\r
exit /b %RC%\r
"""


def _full_replace_powershell() -> str:
    return r"""param(
    [string]$TargetRoot = "C:\industry_demo"
)

$ErrorActionPreference = "Stop"
$packageRoot = [System.IO.Path]::GetFullPath($PSScriptRoot)
$payload = [System.IO.Path]::GetFullPath((Join-Path $packageRoot "industry_demo"))
$target = [System.IO.Path]::GetFullPath($TargetRoot)
$targetParent = Split-Path -Parent $target
$targetLeaf = Split-Path -Leaf $target

if ($targetLeaf -ne "industry_demo" -or [string]::IsNullOrWhiteSpace($targetParent)) {
    throw "目标目录必须是名为 industry_demo 的非根目录，当前为 $target"
}
if ($packageRoot.StartsWith($target + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "广播包不能解压在活动目录 $target 内。请解压到桌面或 C:\industry_demo_install 后重新运行。"
}
if (-not (Test-Path -LiteralPath $payload -PathType Container)) {
    throw "缺少包内 payload：$payload"
}

$required = @(
    "BROADCAST_MANIFEST.json",
    "restart_viewer.bat",
    "data\research.db",
    "data\financial.db",
    "tools\viewer\app.py",
    "tools\viewer\templates\battery_calculator.html",
    "tools\viewer\templates\battery_industry_comparison.html",
    "config\battery_calculator_models\battery_calculator_model_v1.json",
    "cache\REQUIRED_CACHE_BUNDLE_MANIFEST.json"
)
foreach ($relative in $required) {
    $path = Join-Path $payload $relative
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "广播包缺少活动依赖：$relative"
    }
}

$manifest = Get-Content -LiteralPath (Join-Path $payload "BROADCAST_MANIFEST.json") -Raw -Encoding UTF8 | ConvertFrom-Json
$model = Get-Content -LiteralPath (Join-Path $payload "config\battery_calculator_models\battery_calculator_model_v1.json") -Raw -Encoding UTF8 | ConvertFrom-Json
if ($manifest.deployment_mode.existing_vm -ne "full_replace_all_files_and_databases") {
    throw "这不是全量替换包。"
}
if ($model.schemaVersion -ne "battery_calculator.model.v1" -or $model.companies.Count -lt 1) {
    throw "锂电池计算器模型无效。"
}

Write-Host "即将安装版本: $($manifest.version)"
Write-Host "活动目标目录: $target"
Write-Host "包内必要 cache: $($manifest.required_cache.file_count) 个文件"

$targetNeedle = $target.TrimEnd("\") + "\"
$pausedTasks = @()
$stage = "停止旧 Viewer"

function Get-TargetProcesses {
    @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        if ($_.ProcessId -eq $PID) {
            return $false
        }
        $commandLine = [string]$_.CommandLine
        $executablePath = [string]$_.ExecutablePath
        return (
            $commandLine.IndexOf(
                $targetNeedle,
                [System.StringComparison]::OrdinalIgnoreCase
            ) -ge 0 -or
            $executablePath.StartsWith(
                $targetNeedle,
                [System.StringComparison]::OrdinalIgnoreCase
            )
        )
    })
}

function Stop-TargetProcesses {
    for ($attempt = 1; $attempt -le 5; $attempt++) {
        $processes = @(Get-TargetProcesses)
        if ($processes.Count -eq 0) {
            return
        }
        foreach ($process in $processes) {
            Write-Host "停止项目后台进程 PID=$($process.ProcessId): $($process.Name)"
            Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue
        }
        Start-Sleep -Seconds 1
    }
    $remaining = @(Get-TargetProcesses)
    if ($remaining.Count -gt 0) {
        $remainingText = (
            $remaining |
            ForEach-Object { "$($_.ProcessId):$($_.Name)" }
        ) -join ", "
        throw ("仍有项目后台进程未退出: " + $remainingText)
    }
}

function Pause-TargetScheduledTasks {
    try {
        $tasks = @(Get-ScheduledTask -ErrorAction Stop | Where-Object {
            $task = $_
            @($task.Actions | Where-Object {
                $actionText = ([string]$_.Execute) + " " + ([string]$_.Arguments)
                $actionText.IndexOf(
                    $targetNeedle,
                    [System.StringComparison]::OrdinalIgnoreCase
                ) -ge 0
            }).Count -gt 0
        })
        foreach ($task in $tasks) {
            if ([string]$task.State -ne "Disabled") {
                Write-Host "临时暂停计划任务: $($task.TaskPath)$($task.TaskName)"
                Disable-ScheduledTask `
                    -TaskName $task.TaskName `
                    -TaskPath $task.TaskPath `
                    -ErrorAction Stop | Out-Null
                $script:pausedTasks += @{
                    TaskName = $task.TaskName
                    TaskPath = $task.TaskPath
                }
            }
        }
    }
    catch {
        Write-Warning "无法完整枚举或暂停计划任务，将继续停止活动项目进程: $($_.Exception.Message)"
    }
}

function Resume-TargetScheduledTasks {
    foreach ($task in $script:pausedTasks) {
        try {
            Enable-ScheduledTask `
                -TaskName $task.TaskName `
                -TaskPath $task.TaskPath `
                -ErrorAction Stop | Out-Null
            Write-Host "已恢复计划任务: $($task.TaskPath)$($task.TaskName)"
        }
        catch {
            Write-Warning "恢复计划任务失败: $($task.TaskPath)$($task.TaskName)"
        }
    }
}

Pause-TargetScheduledTasks
Get-NetTCPConnection -LocalPort 8080 -State Listen -ErrorAction SilentlyContinue |
    Select-Object -ExpandProperty OwningProcess -Unique |
    ForEach-Object {
        Write-Host "停止旧 Viewer PID=$_"
        Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue
    }
Start-Sleep -Seconds 2
Stop-TargetProcesses

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$rollback = Join-Path $targetParent ("industry_demo.rollback_" + $stamp)
$installed = $false
try {
    $stage = "准备回退目录"
    if (Test-Path -LiteralPath $rollback) {
        throw "回退目录已存在：$rollback"
    }
    if (Test-Path -LiteralPath $target) {
        $stage = "释放旧目录文件锁并移动旧目录"
        $moved = $false
        for ($attempt = 1; $attempt -le 8; $attempt++) {
            try {
                Move-Item -LiteralPath $target -Destination $rollback -ErrorAction Stop
                $moved = $true
                break
            }
            catch {
                if ($attempt -eq 8) {
                    throw
                }
                Write-Host "旧目录仍被占用，等待后重试 ($attempt/8)"
                Stop-TargetProcesses
                Start-Sleep -Seconds 1
            }
        }
        if (-not $moved) {
            throw "旧目录未成功移动到回退位置。"
        }
    }
    $stage = "安装新版目录"
    Move-Item -LiteralPath $payload -Destination $target
    $installed = $true

    $stage = "运行新版预检并启动 Viewer"
    $env:VIEWER_NO_PAUSE = "1"
    & cmd.exe /d /c ('"' + (Join-Path $target "restart_viewer.bat") + '"')
    if ($LASTEXITCODE -ne 0) {
        throw "restart_viewer.bat 失败，错误码 $LASTEXITCODE"
    }

    $stage = "验收核心页面"
    $routes = @(
        @{Path="/research"; Signal="锂电池"},
        @{Path="/industry/29"; Signal="锂电池"},
        @{Path="/tools"; Signal="锂电池业务与估值计算器"},
        @{Path="/tools/battery-calculator"; Signal="锂电池业务、现金流与估值计算器"},
        @{Path="/industry/lithium-battery/comparison"; Signal="锂电池行业比较与情景分析"}
    )
    foreach ($item in $routes) {
        $response = Invoke-WebRequest -UseBasicParsing -Uri ("http://127.0.0.1:8080" + $item.Path) -TimeoutSec 20
        if ($response.StatusCode -ne 200 -or -not ([string]$response.Content).Contains($item.Signal)) {
            throw "安装后页面验收失败：$($item.Path)"
        }
    }
    $stage = "核验发布版本和功能指纹"
    $health = Invoke-RestMethod -Uri "http://127.0.0.1:8080/api/health" -TimeoutSec 20
    if (
        $health.release_version -ne $manifest.version -or
        -not $health.active_features.battery_calculator_route -or
        -not $health.active_features.battery_comparison_route -or
        $null -eq $health.active_features.battery_industry_id
    ) {
        throw "安装后版本指纹或锂电池依赖验收失败。"
    }

    $stage = "清理临时回退目录"
    if (Test-Path -LiteralPath $rollback) {
        Remove-Item -LiteralPath $rollback -Recurse -Force
    }
    Resume-TargetScheduledTasks
    Write-Host "安装成功：$($health.release_version)"
    Write-Host "Viewer：http://127.0.0.1:8080/"
    exit 0
}
catch {
    $failureMessage = "安装阶段失败 [$stage]: $($_.Exception.Message)"
    Get-NetTCPConnection -LocalPort 8080 -State Listen -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique |
        ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }
    if ($installed -and (Test-Path -LiteralPath $target)) {
        Remove-Item -LiteralPath $target -Recurse -Force
    }
    if (Test-Path -LiteralPath $rollback) {
        Move-Item -LiteralPath $rollback -Destination $target
    }
    Resume-TargetScheduledTasks
    if (Test-Path -LiteralPath (Join-Path $target "restart_viewer.bat")) {
        $env:VIEWER_NO_PAUSE = "1"
        & cmd.exe /d /c ('"' + (Join-Path $target "restart_viewer.bat") + '"')
    }
    Write-Host $failureMessage -ForegroundColor Red
    exit 1
}
"""


def build_bundle(
    root: Path,
    *,
    output: Path,
    version: str,
    browser_audit: Path | None = None,
    full_replace: bool = False,
) -> dict[str, object]:
    root = root.resolve()
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    missing = [
        relative
        for relative in (*LIVE_DATABASES, RUN15_PACK, *RUN15_EXPORTS)
        if not (root / relative).is_file()
    ]
    if missing:
        raise FileNotFoundError(f"广播闭包缺少文件: {missing}")

    unsafe_papers = paper_path_violations(root / "papers", project_root=root)
    if unsafe_papers:
        examples = [
            path.relative_to(root).as_posix()
            for path in unsafe_papers[:5]
        ]
        raise RuntimeError(
            "广播包构建前发现超长或不兼容的研报路径；"
            "请先运行 python -m tools.maintenance.migrate_paper_paths。"
            f" 当前 {len(unsafe_papers)} 个，示例：{examples}"
        )

    created_at = datetime.now(BEIJING)
    staging = (root / "cache" / f"broadcast_build_{created_at:%Y%m%d_%H%M%S}").resolve()
    cache_root = (root / "cache").resolve()
    if cache_root not in staging.parents:
        raise RuntimeError(f"临时目录越界: {staging}")
    if staging.exists():
        raise FileExistsError(staging)
    snapshots = staging / "sqlite"
    staging.mkdir(parents=True)
    try:
        database_results: list[dict[str, object]] = []
        snapshot_sources: dict[str, Path] = {}
        for relative in LIVE_DATABASES:
            source = root / relative
            target = snapshots / relative
            result = _sqlite_snapshot(source, target)
            result["path"] = relative
            database_results.append(result)
            snapshot_sources[relative] = target

        sources = dict(_iter_payload_files(root))
        required_cache_paths, required_cache_manifest = collect_required_cache(root)
        for cache_path in required_cache_paths:
            relative = cache_path.relative_to(root).as_posix()
            if relative in sources:
                raise RuntimeError(f"必要 cache 与基础广播闭包路径重复: {relative}")
            sources[relative] = cache_path
        sources.update(snapshot_sources)
        file_records: list[dict[str, object]] = []
        with zipfile.ZipFile(
            output,
            "w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=6,
            allowZip64=True,
        ) as archive:
            for relative in sorted(sources):
                file_records.append(
                    _add_file(archive, relative=relative, source=sources[relative])
                )
            release_manifest = {
                "schema_version": SCHEMA_VERSION,
                "version": version,
                "created_at": created_at.isoformat(timespec="seconds"),
                "source_root": str(root),
                "package_root": PACKAGE_ROOT,
                "required_directories": list(REQUIRED_DIRECTORIES),
                "root_files": list(ROOT_FILES),
                "required_cache": {
                    "included": True,
                    "selection_policy": (
                        "config_and_live_database_references_plus_durable_models"
                    ),
                    "manifest_path": "cache/REQUIRED_CACHE_BUNDLE_MANIFEST.json",
                    "file_count": required_cache_manifest["file_count"],
                    "content_bytes": required_cache_manifest["content_bytes"],
                    "database_values_scanned": required_cache_manifest[
                        "database_values_scanned"
                    ],
                    "durable_model_directories": required_cache_manifest[
                        "durable_model_directories"
                    ],
                },
                "installer": (
                    {
                        "included": True,
                        "entrypoint": "INSTALL_FULL_REPLACE.cmd",
                        "powershell": "Install-IndustryDemo.ps1",
                        "target_root_default": r"C:\industry_demo",
                        "post_install_route_validation": True,
                        "rollback_on_failure": True,
                    }
                    if full_replace
                    else {"included": False}
                ),
                "deployment_mode": (
                    {
                        "existing_vm": "full_replace_all_files_and_databases",
                        "clean_install": "use_bundled_sqlite_snapshots",
                        "preserves_target_live_data": False,
                    }
                    if full_replace
                    else {
                        "existing_vm": "incremental_preserve_live_databases",
                        "clean_install": "use_bundled_sqlite_snapshots",
                        "preserves_target_live_data": True,
                    }
                ),
                "databases": database_results,
                "run15": _read_run15_summary(root),
                "browser_audit": _read_browser_audit(root, browser_audit),
                "file_count": len(file_records),
                "content_bytes": sum(int(record["size"]) for record in file_records),
                "files": file_records,
            }
            archive.writestr(
                f"{PACKAGE_ROOT}/BROADCAST_MANIFEST.json",
                json.dumps(release_manifest, ensure_ascii=False, indent=2) + "\n",
            )
            archive.writestr(
                f"{PACKAGE_ROOT}/BROADCAST_README.md",
                _readme(version, full_replace=full_replace),
            )
            archive.writestr(
                f"{PACKAGE_ROOT}/cache/REQUIRED_CACHE_BUNDLE_MANIFEST.json",
                json.dumps(required_cache_manifest, ensure_ascii=False, indent=2)
                + "\n",
            )
            if full_replace:
                archive.writestr(
                    "INSTALL_FULL_REPLACE.cmd",
                    _full_replace_cmd(),
                )
                archive.writestr(
                    "Install-IndustryDemo.ps1",
                    b"\xef\xbb\xbf"
                    + _full_replace_powershell().encode("utf-8"),
                )

        result = {
            **release_manifest,
            "archive_path": str(output),
            "archive_size": output.stat().st_size,
            "archive_sha256": _sha256_file(output),
        }
        _write_json(output.with_suffix(output.suffix + ".manifest.json"), result)
        return result
    finally:
        if staging.exists():
            resolved = staging.resolve()
            if cache_root not in resolved.parents:
                raise RuntimeError(f"拒绝清理越界目录: {resolved}")
            shutil.rmtree(resolved)


def main() -> int:
    parser = argparse.ArgumentParser(description="生成 Industry Demo 内网 Viewer 广播包")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--version", required=True)
    parser.add_argument("--browser-audit", type=Path)
    parser.add_argument(
        "--full-replace",
        action="store_true",
        help="生成覆盖目标机全部文件和四库的完整替换包",
    )
    args = parser.parse_args()
    root = args.root.resolve()
    output = args.output
    if output is None:
        stamp = datetime.now(BEIJING).strftime("%Y%m%d_%H%M%S")
        output = root / "broadcast_packages" / f"industry_demo_run15_{stamp}.zip"
    result = build_bundle(
        root,
        output=output,
        version=args.version,
        browser_audit=args.browser_audit,
        full_replace=args.full_replace,
    )
    print(
        json.dumps(
            {
                "archive_path": result["archive_path"],
                "archive_size": result["archive_size"],
                "archive_sha256": result["archive_sha256"],
                "file_count": result["file_count"],
                "databases": result["databases"],
                "run15": result["run15"],
                "browser_audit": result["browser_audit"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
