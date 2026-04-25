from __future__ import annotations

import queue
import subprocess
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk

from .pipeline import run_asr_pipeline


class DialogWindow:
    def __init__(self, root: tk.Tk, repo_root: str | Path) -> None:
        self.root = root
        self.repo_root = Path(repo_root)
        self.events: queue.Queue[tuple[str, str | dict]] = queue.Queue()

        self.root.title("Legacy 树莓派离线语音识别窗口")
        self.root.geometry("980x760")
        self.root.minsize(860, 620)

        self.model_dir_var = tk.StringVar(
            value=str(self.repo_root / "models" / "vosk-model-small-cn-0.22")
        )
        self.audio_path_var = tk.StringVar(
            value=str(self.repo_root / "sample_audio" / "demo_cn.wav")
        )
        self.grammar_file_var = tk.StringVar()
        self.phrase_hints_var = tk.StringVar(
            value=str(self.repo_root / "sample_audio" / "demo_cn_phrase_hints.json")
        )
        self.run_tag_var = tk.StringVar(value="dialog_run")
        self.record_seconds_var = tk.StringVar(value="5")

        self._build_layout()
        self.root.after(150, self._poll_events)

    def _build_layout(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1)

        config_frame = ttk.LabelFrame(self.root, text="Legacy 运行配置", padding=12)
        config_frame.grid(row=0, column=0, sticky="nsew", padx=12, pady=(12, 6))
        config_frame.columnconfigure(1, weight=1)

        self._add_path_row(config_frame, 0, "模型目录", self.model_dir_var, True)
        self._add_path_row(config_frame, 1, "音频文件", self.audio_path_var, False)
        self._add_path_row(config_frame, 2, "Grammar 文件", self.grammar_file_var, False)
        self._add_path_row(config_frame, 3, "短语提示文件", self.phrase_hints_var, False)

        ttk.Label(config_frame, text="运行标签").grid(row=4, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(config_frame, textvariable=self.run_tag_var).grid(
            row=4, column=1, sticky="ew", pady=(8, 0)
        )

        record_frame = ttk.Frame(config_frame)
        record_frame.grid(row=5, column=0, columnspan=3, sticky="ew", pady=(12, 0))
        ttk.Label(record_frame, text="录音秒数").pack(side="left")
        ttk.Entry(record_frame, textvariable=self.record_seconds_var, width=8).pack(
            side="left", padx=(8, 12)
        )
        ttk.Button(record_frame, text="录音并填入音频路径", command=self._record).pack(side="left")

        chat_frame = ttk.LabelFrame(self.root, text="Legacy 日志", padding=12)
        chat_frame.grid(row=1, column=0, sticky="nsew", padx=12, pady=6)
        chat_frame.columnconfigure(0, weight=1)
        chat_frame.rowconfigure(0, weight=1)

        self.chat_text = scrolledtext.ScrolledText(chat_frame, wrap="word", state="disabled")
        self.chat_text.grid(row=0, column=0, sticky="nsew")

        ttk.Button(self.root, text="开始识别", command=self._run_pipeline).grid(
            row=2, column=0, sticky="w", padx=12, pady=(0, 12)
        )

    def _add_path_row(
        self,
        parent: ttk.Frame,
        row: int,
        label: str,
        variable: tk.StringVar,
        is_directory: bool,
    ) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=(0, 8))
        ttk.Entry(parent, textvariable=variable).grid(row=row, column=1, sticky="ew", pady=(0, 8))
        ttk.Button(
            parent,
            text="浏览",
            command=lambda: self._browse(variable, is_directory=is_directory),
        ).grid(row=row, column=2, sticky="ew", padx=(8, 0), pady=(0, 8))

    def _browse(self, variable: tk.StringVar, *, is_directory: bool) -> None:
        current = variable.get().strip()
        if is_directory:
            selected = filedialog.askdirectory(initialdir=current or str(self.repo_root))
        else:
            selected = filedialog.askopenfilename(
                initialdir=str(Path(current).parent) if current else str(self.repo_root)
            )
        if selected:
            variable.set(selected)

    def _append_message(self, speaker: str, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.chat_text.configure(state="normal")
        self.chat_text.insert(tk.END, f"[{timestamp}] {speaker}: {message}\n\n")
        self.chat_text.configure(state="disabled")
        self.chat_text.see(tk.END)

    def _record(self) -> None:
        try:
            seconds = int(self.record_seconds_var.get().strip())
        except ValueError:
            messagebox.showerror("输入错误", "录音秒数需要是整数。")
            return
        output_wav = self.repo_root / "sample_audio" / "live_record.wav"
        threading.Thread(
            target=self._record_worker,
            args=(output_wav, seconds),
            daemon=True,
        ).start()

    def _record_worker(self, output_wav: Path, seconds: int) -> None:
        script_path = self.repo_root / "scripts" / "record_audio.sh"
        completed = subprocess.run(
            ["bash", str(script_path), str(output_wav), str(seconds)],
            cwd=self.repo_root,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            self.events.put(("error", completed.stderr.strip() or completed.stdout.strip()))
            return
        self.events.put(
            ("recorded", {"audio_path": str(output_wav), "message": completed.stdout.strip()})
        )

    def _run_pipeline(self) -> None:
        output_dir = self.repo_root / "artifacts" / (self.run_tag_var.get().strip() or "dialog_run")
        threading.Thread(
            target=self._pipeline_worker,
            args=(output_dir,),
            daemon=True,
        ).start()

    def _pipeline_worker(self, output_dir: Path) -> None:
        try:
            result = run_asr_pipeline(
                input_wav=self.audio_path_var.get().strip(),
                output_dir=output_dir,
                model_dir=self.model_dir_var.get().strip(),
                grammar_file=self.grammar_file_var.get().strip() or None,
                phrase_hints_file=self.phrase_hints_var.get().strip() or None,
            )
        except Exception as exc:
            self.events.put(("error", str(exc)))
            return
        self.events.put(("done", result))

    def _poll_events(self) -> None:
        try:
            while True:
                event, payload = self.events.get_nowait()
                if event == "error":
                    messagebox.showerror("运行失败", str(payload))
                    self._append_message("系统", str(payload))
                elif event == "recorded":
                    if isinstance(payload, dict) and isinstance(payload.get("audio_path"), str):
                        self.audio_path_var.set(payload["audio_path"])
                    self._append_message(
                        "系统",
                        str(payload.get("message", "录音完成。"))
                        if isinstance(payload, dict)
                        else str(payload),
                    )
                elif event == "done":
                    result = payload if isinstance(payload, dict) else {}
                    transcript = result.get("asr_result", {}).get("transcript", "未识别到文本。")
                    self._append_message("你", transcript)
                    self._append_message(
                        "系统", f"Legacy 结果已保存到 {result.get('output_dir', '')}"
                    )
        except queue.Empty:
            pass
        finally:
            self.root.after(150, self._poll_events)


def launch_dialog_window(repo_root: str | Path) -> None:
    root = tk.Tk()
    DialogWindow(root, repo_root)
    root.mainloop()
