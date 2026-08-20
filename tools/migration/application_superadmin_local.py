from __future__ import annotations

import argparse
import getpass
from pathlib import Path

from tools.data_platform.application_accounts import normalize_subject, password_hash
from tools.data_platform.postgres_runtime import (
    build_catalog_connection_factory,
    load_postgres_runtime_catalog,
)


def reset(runtime: Path, subject: str, password: str, confirmation: str, reason: str) -> None:
    subject = normalize_subject(subject)
    if password != confirmation:
        raise ValueError("两次输入的密码不一致")
    encoded = password_hash(subject, password)
    factory = build_catalog_connection_factory(
        load_postgres_runtime_catalog(runtime), role="migration"
    )
    with factory() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT application_identity.local_reset_superadmin_v1(%s,%s,%s)",
                (subject, encoded, reason.strip()),
            )
            if cursor.fetchone() is None:
                raise RuntimeError("本机超管重置没有返回结果")


def console(runtime: Path, subject: str) -> int:
    print("本工具只在 VM 本机重置应用超管密码；输入不会显示、记录或写入命令行。")
    first = getpass.getpass("新密码：")
    second = getpass.getpass("再次输入：")
    reason = input("重置原因：").strip()
    reset(runtime, subject, first, second, reason)
    print("应用超管密码已重置，全部旧会话已撤销。")
    return 0


def gui(runtime: Path, subject: str) -> int:
    import tkinter as tk
    from tkinter import messagebox

    root = tk.Tk()
    root.title("泓湖研究平台 · 本机超管密码")
    root.geometry("620x540")
    root.minsize(520, 440)
    root.resizable(True, True)

    # The VM can use display scaling above 100%. Keep the actions outside the
    # scrolling form so Save and Cancel are always visible even at high DPI.
    action_bar = tk.Frame(root, padx=20, pady=14, bd=0)
    action_bar.pack(side="bottom", fill="x")
    tk.Frame(root, height=1, bg="#d8dde5").pack(side="bottom", fill="x")

    content_shell = tk.Frame(root)
    content_shell.pack(side="top", fill="both", expand=True)
    canvas = tk.Canvas(content_shell, highlightthickness=0, bd=0)
    scrollbar = tk.Scrollbar(content_shell, orient="vertical", command=canvas.yview)
    canvas.configure(yscrollcommand=scrollbar.set)
    scrollbar.pack(side="right", fill="y")
    canvas.pack(side="left", fill="both", expand=True)

    frame = tk.Frame(canvas, padx=24, pady=20)
    frame_window = canvas.create_window((0, 0), window=frame, anchor="nw")

    def update_scroll_region(_event=None):
        canvas.configure(scrollregion=canvas.bbox("all"))

    def fit_form_width(event):
        canvas.itemconfigure(frame_window, width=event.width)

    def scroll_form(event):
        if event.delta:
            canvas.yview_scroll(int(-event.delta / 120), "units")

    frame.bind("<Configure>", update_scroll_region)
    canvas.bind("<Configure>", fit_form_width)
    canvas.bind("<Enter>", lambda _event: canvas.bind_all("<MouseWheel>", scroll_form))
    canvas.bind("<Leave>", lambda _event: canvas.unbind_all("<MouseWheel>"))

    tk.Label(frame, text="本机超管密码重置", font=("Microsoft YaHei UI", 16, "bold")).pack(anchor="w")
    tk.Label(
        frame,
        text="只修改研究平台应用账号，不授予 Windows、VM 或数据库系统权限。",
        fg="#666",
        wraplength=520,
        justify="left",
    ).pack(anchor="w", pady=(6, 18))
    tk.Label(frame, text=f"账号：{subject}").pack(anchor="w")
    first = tk.StringVar()
    second = tk.StringVar()
    reason = tk.StringVar()
    visible = tk.BooleanVar(value=False)
    tk.Label(frame, text="新密码").pack(anchor="w", pady=(12, 3))
    first_entry = tk.Entry(frame, textvariable=first, show="•")
    first_entry.pack(fill="x")
    tk.Label(frame, text="确认密码").pack(anchor="w", pady=(10, 3))
    second_entry = tk.Entry(frame, textvariable=second, show="•")
    second_entry.pack(fill="x")

    def toggle():
        show = "" if visible.get() else "•"
        first_entry.configure(show=show)
        second_entry.configure(show=show)

    tk.Checkbutton(frame, text="显示密码", variable=visible, command=toggle).pack(anchor="w")
    tk.Label(frame, text="重置原因").pack(anchor="w", pady=(8, 3))
    tk.Entry(frame, textvariable=reason).pack(fill="x")
    tk.Label(
        frame,
        text="保存后新密码立即生效，该账号的旧会话会全部撤销。",
        fg="#666",
        wraplength=520,
        justify="left",
    ).pack(anchor="w", pady=(14, 6))

    def submit():
        try:
            reset(runtime, subject, first.get(), second.get(), reason.get())
        except Exception as exc:
            first.set("")
            second.set("")
            messagebox.showerror("未完成", str(exc))
            return
        first.set("")
        second.set("")
        messagebox.showinfo("已完成", "密码已重置，全部旧会话已撤销。")
        root.destroy()

    tk.Button(
        action_bar,
        text="确认重置并保存",
        command=submit,
        bg="#9f3029",
        fg="white",
        activebackground="#81251f",
        activeforeground="white",
        font=("Microsoft YaHei UI", 10, "bold"),
        padx=18,
        pady=8,
    ).pack(side="right")
    tk.Button(
        action_bar,
        text="取消",
        command=root.destroy,
        padx=18,
        pady=8,
    ).pack(side="right", padx=(0, 10))

    root.bind("<Escape>", lambda _event: root.destroy())
    root.bind("<Return>", lambda _event: submit())
    first_entry.focus_set()
    root.mainloop()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="VM-local application superadmin password reset")
    parser.add_argument("--runtime", required=True, type=Path)
    parser.add_argument("--subject", default="research-operator")
    parser.add_argument("--console", action="store_true")
    args = parser.parse_args()
    runtime = args.runtime.resolve(); subject = normalize_subject(args.subject)
    return console(runtime, subject) if args.console else gui(runtime, subject)


if __name__ == "__main__":
    raise SystemExit(main())
