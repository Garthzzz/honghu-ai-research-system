from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE_PATH = ROOT / "tools" / "migration" / "application_superadmin_local.py"


def _gui_source() -> str:
    source = SOURCE_PATH.read_text(encoding="utf-8")
    module = ast.parse(source)
    gui = next(
        node
        for node in module.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "gui"
    )
    return ast.get_source_segment(source, gui) or ""


def test_local_superadmin_window_is_resizable_and_scrollable() -> None:
    source = _gui_source()

    assert 'root.geometry("620x540")' in source
    assert "root.minsize(520, 440)" in source
    assert "root.resizable(True, True)" in source
    assert "tk.Canvas(content_shell" in source
    assert "tk.Scrollbar(content_shell" in source
    assert 'frame.bind("<Configure>", update_scroll_region)' in source
    assert 'canvas.bind("<Configure>", fit_form_width)' in source


def test_local_superadmin_actions_are_fixed_outside_scrolling_form() -> None:
    source = _gui_source()

    action_pack = 'action_bar.pack(side="bottom", fill="x")'
    content_pack = 'content_shell.pack(side="top", fill="both", expand=True)'
    assert action_pack in source
    assert content_pack in source
    assert source.index(action_pack) < source.index(content_pack)
    assert "tk.Button(\n        action_bar,\n        text=\"确认重置并保存\"" in source
    assert "tk.Button(\n        action_bar,\n        text=\"取消\"" in source
    assert 'root.bind("<Escape>"' in source


def test_local_superadmin_password_fields_remain_masked_by_default() -> None:
    source = _gui_source()

    assert 'first_entry = tk.Entry(frame, textvariable=first, show="•")' in source
    assert 'second_entry = tk.Entry(frame, textvariable=second, show="•")' in source
    assert 'tk.Checkbutton(frame, text="显示密码"' in source
