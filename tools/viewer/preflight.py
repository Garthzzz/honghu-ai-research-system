from __future__ import annotations

import argparse
import importlib
import json
import sqlite3
import sys
from pathlib import Path


REQUIRED_PATHS = {
    "config/research_workflow.yaml": "A/B/C 共享机器工作流契约",
    "data/research.db": "行研主库",
    "data/sentiment.db": "情绪与供应链库",
    "data/opportunity_lens.db": "Opportunity Lens 数据库",
    "data/financial.db": "公司财务与估值数据库",
    "docs/industries": "行业研究文档",
    "papers": "研报与原文 PDF",
    "opportunity_lens/intake_requests": "Opportunity Lens Request 案例",
    "tools/dynamic/config.yaml": "动态情报展示配置",
    "tools/viewer/templates": "Viewer 页面模板",
    "tools/viewer/static": "Viewer 静态资源",
    "tools/viewer/static/vendor/plotly.min.js": "内网可视化 Plotly 运行时",
    "config/lithium_calculator_models/lithium_company_independent_models_v1.json":
        "碳酸锂计算器独立财务模型",
    "config/lithium_calculator_models/lithium_external_reconciliation_v1.json":
        "碳酸锂计算器外部对账模型",
    "config/lithium_calculator_project_ledger.json": "碳酸锂逐项目资源台账",
    "config/copper_calculator_models/copper_calculator_model_v1.json":
        "铜矿项目、财务与估值计算器冻结模型",
    "config/battery_calculator_models/battery_calculator_model_v1.json":
        "锂电池业务、现金流与估值计算器冻结模型",
    "tools/viewer/templates/battery_calculator.html":
        "锂电池单公司计算器页面",
    "tools/viewer/templates/battery_industry_comparison.html":
        "锂电池行业比较与情景分析页面",
    "docs/industries/锂电池.md": "锂电池行业主文档",
    "docs/industries/锂电池_Q5_综述.md": "锂电池行业核心结论",
}

REQUIRED_MODULES = {
    "flask": "Flask",
    "frontmatter": "python-frontmatter",
    "markdown": "markdown",
    "markupsafe": "MarkupSafe",
    "plotly": "plotly",
    "yaml": "PyYAML",
}

DATABASE_TABLES = {
    "data/research.db": ("industry", "source", "company"),
    "data/sentiment.db": ("senti_raw", "stock_kline", "funda_semi_nodes"),
    "data/opportunity_lens.db": ("opportunity_run", "opportunity_source", "opportunity_entity"),
    "data/financial.db": ("financial_security", "financial_observation", "financial_model_run"),
}

REQUIRED_ROUTES = {
    "/tools": "工具选择页",
    "/tools/lithium-calculator": "碳酸锂计算器",
    "/tools/copper-calculator": "铜计算器",
    "/tools/battery-calculator": "锂电池计算器",
    "/industry/lithium-battery/comparison": "锂电池行业比较",
}


def _resolve_root(value: str | Path | None) -> Path:
    if value is not None:
        return Path(value).expanduser().resolve()
    return Path(__file__).resolve().parents[2]


def check_required_paths(root: Path) -> list[str]:
    return [
        f"缺少 {relative}（{purpose}）"
        for relative, purpose in REQUIRED_PATHS.items()
        if not (root / Path(relative)).exists()
    ]


def check_python_modules() -> list[str]:
    missing: list[str] = []
    for module_name, package_name in REQUIRED_MODULES.items():
        try:
            importlib.import_module(module_name)
        except Exception as exc:
            missing.append(f"缺少 Python 依赖 {package_name}（import {module_name}: {exc}）")
    return missing


def check_databases(root: Path) -> list[str]:
    failures: list[str] = []
    for relative, required_tables in DATABASE_TABLES.items():
        path = (root / relative).resolve()
        if not path.is_file():
            continue
        conn: sqlite3.Connection | None = None
        try:
            uri = f"file:{path.as_posix()}?mode=ro"
            conn = sqlite3.connect(uri, uri=True, timeout=5)
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
            available = {str(row[0]) for row in rows}
            missing = sorted(set(required_tables) - available)
            if missing:
                failures.append(f"{relative} 缺少关键表: {', '.join(missing)}")
        except Exception as exc:
            failures.append(f"{relative} 无法只读打开: {exc}")
        finally:
            if conn is not None:
                conn.close()
    return failures


def check_active_feature_data(root: Path) -> list[str]:
    """Reject a mixed old/new deployment that passes table-only checks."""
    failures: list[str] = []
    model_path = (
        root
        / "config"
        / "battery_calculator_models"
        / "battery_calculator_model_v1.json"
    )
    try:
        model = json.loads(model_path.read_text(encoding="utf-8"))
        if model.get("schemaVersion") != "battery_calculator.model.v1":
            failures.append("锂电池计算器模型 schemaVersion 不兼容")
        companies = model.get("companies")
        if not isinstance(companies, list) or len(companies) < 1:
            failures.append("锂电池计算器模型没有可用公司")
    except Exception as exc:
        failures.append(f"锂电池计算器模型无法读取: {type(exc).__name__}: {exc}")

    research_path = (root / "data" / "research.db").resolve()
    if research_path.is_file():
        conn: sqlite3.Connection | None = None
        try:
            conn = sqlite3.connect(
                f"file:{research_path.as_posix()}?mode=ro",
                uri=True,
                timeout=5,
            )
            row = conn.execute(
                "SELECT id FROM industry WHERE name = ?",
                ("锂电池",),
            ).fetchone()
            if row is None:
                failures.append("research.db 缺少锂电池行业记录，疑似仍是旧数据库")
            else:
                industry_id = int(row[0])
                point_count = int(
                    conn.execute(
                        "SELECT COUNT(*) FROM industry_data_point WHERE industry_id = ?",
                        (industry_id,),
                    ).fetchone()[0]
                )
                company_count = int(
                    conn.execute(
                        "SELECT COUNT(DISTINCT company_id) "
                        "FROM company_industry WHERE industry_id = ?",
                        (industry_id,),
                    ).fetchone()[0]
                )
                if point_count < 1:
                    failures.append("research.db 的锂电池行业没有结构化数据点")
                if company_count < 1:
                    failures.append("research.db 的锂电池行业没有关联公司")
        except Exception as exc:
            failures.append(f"锂电池行业数据闭包检查失败: {type(exc).__name__}: {exc}")
        finally:
            if conn is not None:
                conn.close()
    return failures


def check_paper_paths(root: Path) -> list[str]:
    root_text = str(root)
    if root_text not in sys.path:
        sys.path.insert(0, root_text)
    from tools.pipeline.paper_paths import paper_path_violations

    violations = paper_path_violations(root / "papers", project_root=root)
    if not violations:
        return []
    examples = [
        path.relative_to(root).as_posix()
        for path in violations[:5]
    ]
    return [
        "papers/ 存在 Windows 不安全文件名或超长相对路径："
        f"共 {len(violations)} 个，示例 {examples}；"
        "请运行 python -m tools.maintenance.migrate_paper_paths"
    ]


def check_viewer_import(root: Path) -> list[str]:
    root_text = str(root)
    if root_text not in sys.path:
        sys.path.insert(0, root_text)
    try:
        module = importlib.import_module("tools.viewer.app")
        if not hasattr(module, "app"):
            return ["tools.viewer.app 未导出 Flask app"]
        routes = {rule.rule for rule in module.app.url_map.iter_rules()}
        missing_routes = [
            f"{route}（{purpose}）"
            for route, purpose in REQUIRED_ROUTES.items()
            if route not in routes
        ]
        if missing_routes:
            return [
                "Viewer 缺少活动功能路由，疑似代码未完整覆盖: "
                + "、".join(missing_routes)
            ]
    except Exception as exc:
        return [f"Viewer 导入失败: {type(exc).__name__}: {exc}"]
    return []


def run_preflight(root: Path) -> list[str]:
    failures = check_required_paths(root)
    if failures:
        return failures
    failures.extend(check_python_modules())
    if failures:
        return failures
    failures.extend(check_databases(root))
    if failures:
        return failures
    failures.extend(check_active_feature_data(root))
    if failures:
        return failures
    failures.extend(check_paper_paths(root))
    if failures:
        return failures
    failures.extend(check_viewer_import(root))
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description="Industry Viewer 只读启动预检")
    parser.add_argument("--root", help="项目根目录；默认从本文件位置推导")
    args = parser.parse_args()
    root = _resolve_root(args.root)
    failures = run_preflight(root)
    if failures:
        print(f"预检失败：{root}")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print(f"  预检通过：{root}")
    print("  四个数据库、工作流契约、页面资源、Python 依赖和 Flask 导入均正常")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
