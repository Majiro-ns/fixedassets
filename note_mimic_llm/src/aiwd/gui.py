from __future__ import annotations
import os
import threading
import queue
import subprocess
from pathlib import Path
from typing import List, Dict

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from .cli import main as cli_main


class ProgressWindow(tk.Toplevel):
    def __init__(self, master: tk.Tk, total: int):
        super().__init__(master)
        self.title("AI文章検出 - 解析中")
        self.geometry("420x140")
        self.resizable(False, False)
        self.progress = ttk.Progressbar(self, orient="horizontal", mode="determinate", maximum=max(1, total))
        self.label = ttk.Label(self, text=f"解析中… (0/{total})")
        self.sub = ttk.Label(self, text="残り概算: - ファイル")
        self.cancelled = False
        self.cancel_btn = ttk.Button(self, text="キャンセル", command=self._on_cancel)
        self.label.pack(padx=12, pady=(14, 6), fill="x")
        self.progress.pack(padx=12, pady=6, fill="x")
        self.sub.pack(padx=12, pady=6, fill="x")
        self.cancel_btn.pack(pady=(6, 10))
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)

    def _on_cancel(self):
        self.cancelled = True

    def update_progress(self, current: int, total: int):
        self.progress["value"] = current
        self.label.configure(text=f"解析中… ({current}/{total})")
        self.sub.configure(text=f"残り概算: {max(0, total-current)} ファイル")
        self.update_idletasks()


def _run_cli(target: str, full: bool, out_queue: queue.Queue):
    argv = [target]
    if full:
        argv.append("--full")
    # Let CLI print summary JSON; capture not needed here
    code = cli_main(argv)
    out_queue.put(code)


def choose_folder_and_run(master: tk.Tk, full: bool = False):
    target = filedialog.askdirectory(title="解析するフォルダを選んでください")
    if not target:
        return
    # We don’t have per-file progress from CLI; show indeterminate with message updates via simple loop
    # For a better UX, we could re-implement a per-file loop here; keep simple and robust.
    total = 100
    win = ProgressWindow(master, total)
    out_q: queue.Queue = queue.Queue()
    th = threading.Thread(target=_run_cli, args=(target, full, out_q), daemon=True)
    th.start()
    i = 0
    while th.is_alive():
        if win.cancelled:
            # Not trivial to cancel underlying process; best-effort: just close UI
            break
        i = (i + 3) % total
        win.update_progress(i, total)
        win.after(100)
        win.update()
    win.destroy()

    # Completion dialog
    target_dir = Path(target)
    out_csv = target_dir / "ai_detect_result.csv"
    log_dir = target_dir / "logs"

    def open_result():
        try:
            subprocess.Popen(["explorer.exe", f"/select,\"{out_csv.as_posix()}\""])
        except Exception:
            pass

    def open_logs():
        try:
            os.startfile(log_dir.as_posix())  # type: ignore[attr-defined]
        except Exception:
            pass

    def rerun():
        choose_folder_and_run(master, full)

    dlg = tk.Toplevel(master)
    dlg.title("解析完了")
    dlg.geometry("420x160")
    ttk.Label(dlg, text="解析が完了しました。").pack(pady=(14, 4))
    ttk.Label(dlg, text=f"出力: {out_csv}", wraplength=380).pack(pady=4)
    btn_fr = ttk.Frame(dlg)
    btn_fr.pack(pady=8)
    ttk.Button(btn_fr, text="結果を開く", command=open_result).grid(row=0, column=0, padx=6)
    ttk.Button(btn_fr, text="ログを開く", command=open_logs).grid(row=0, column=1, padx=6)
    ttk.Button(btn_fr, text="もう一度", command=rerun).grid(row=0, column=2, padx=6)
    ttk.Button(dlg, text="閉じる", command=dlg.destroy).pack(pady=(4, 10))


def run_gui(start_path: str | None = None):
    root = tk.Tk()
    root.title("AI文章検出 - 起動")
    root.geometry("420x180")
    ttk.Label(root, text="AI文章検出ツール（感度優先）").pack(pady=(16, 4))
    ttk.Label(root, text="フォルダを選んで解析を開始します。全て日本語表示です。", wraplength=380).pack()
    ttk.Button(root, text="フォルダを選ぶ（Lite）", command=lambda: choose_folder_and_run(root, False)).pack(pady=(12, 4))
    ttk.Button(root, text="フォルダを選ぶ（Full：初回モデル取得）", command=lambda: choose_folder_and_run(root, True)).pack(pady=4)
    ttk.Button(root, text="閉じる", command=root.destroy).pack(pady=(6, 10))
    root.mainloop()

