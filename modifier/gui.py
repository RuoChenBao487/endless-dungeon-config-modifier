"""Desktop window for the 16.0 configuration and runtime modifier."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from .config import (
    OPTION_SPECS,
    OptionSpec,
    defaults,
    load_config,
    validate_config,
    write_config,
)
from .launcher import GAME_ROOT, ManagedGame, start_game


TOOL_ROOT = Path(__file__).resolve().parents[1]
PROFILE_PATH = TOOL_ROOT / "profiles" / "last_modifiers.json"


def _console_python() -> Path:
    executable = Path(sys.executable)
    if executable.name.lower() == "pythonw.exe":
        candidate = executable.with_name("python.exe")
        if candidate.exists():
            return candidate
    return executable


class NumericControl(ttk.Frame):
    def __init__(
        self,
        parent: tk.Misc,
        spec: OptionSpec,
        value: float | int,
        on_change,
    ):
        super().__init__(parent, style="Field.TFrame", padding=(0, 2))
        self.spec = spec
        self._on_change = on_change
        self.var = tk.DoubleVar(value=float(value))
        self.columnconfigure(1, weight=1)

        ttk.Label(
            self,
            text=spec.title,
            style="Field.TLabel",
            width=12,
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            self,
            text=spec.scope,
            style="Scope.TLabel",
        ).grid(row=0, column=3, sticky="e", padx=(8, 0))

        self.scale = ttk.Scale(
            self,
            from_=spec.minimum,
            to=spec.maximum,
            variable=self.var,
            command=self._scale_changed,
            length=110,
        )
        self.scale.grid(row=0, column=1, sticky="ew", padx=(8, 0))

        fmt = "%.0f" if spec.kind == "int" else "%.2f"
        self.spinbox = ttk.Spinbox(
            self,
            from_=spec.minimum,
            to=spec.maximum,
            increment=spec.step,
            textvariable=self.var,
            width=8,
            format=fmt,
            command=self._spin_changed,
        )
        self.spinbox.grid(row=0, column=2, sticky="e", padx=(8, 0))
        self.spinbox.bind("<FocusOut>", self._spin_changed)
        self.spinbox.bind("<Return>", self._spin_changed)
        self.var.trace_add("write", self._variable_changed)

    def _scale_changed(self, _value=None) -> None:
        if self.spec.kind == "int":
            self.var.set(round(self.var.get()))

    def _spin_changed(self, _event=None) -> None:
        value = self.var.get()
        value = min(self.spec.maximum, max(self.spec.minimum, value))
        if self.spec.kind == "int":
            value = round(value)
        self.var.set(value)

    def _variable_changed(self, *_args) -> None:
        self._on_change()

    def set_value(self, value: float | int) -> None:
        self.var.set(float(value))

    def value(self) -> float | int:
        raw = self.var.get()
        if self.spec.kind == "int":
            return int(round(raw))
        return round(raw, 4)


class DSLTab(ttk.Frame):
    def __init__(self, parent: tk.Misc):
        super().__init__(parent, padding=18)
        self.columnconfigure(1, weight=1)
        self.rowconfigure(3, weight=1)

        ttk.Label(self, text="规则文件", style="Section.TLabel").grid(
            row=0, column=0, sticky="w", padx=(0, 10))
        self.file_var = tk.StringVar(value="examples/world.dungeon")
        ttk.Entry(self, textvariable=self.file_var).grid(
            row=0, column=1, sticky="ew")
        ttk.Button(self, text="选择", command=self._choose_file).grid(
            row=0, column=2, padx=(8, 0))

        actions = ttk.Frame(self)
        actions.grid(row=1, column=0, columnspan=3, sticky="w", pady=(12, 0))
        self.action_buttons: list[ttk.Button] = []
        for text, action in (
            ("检查", "check"),
            ("编译 JSON", "compile"),
            ("模拟十万房间", "simulate"),
        ):
            button = ttk.Button(
                actions, text=text,
                command=lambda name=action: self._run_action(name))
            button.pack(side="left", padx=(0, 8))
            self.action_buttons.append(button)
        ttk.Button(actions, text="清空输出", command=self._clear).pack(
            side="left")

        ttk.Label(self, text="输出", style="Section.TLabel").grid(
            row=2, column=0, columnspan=3, sticky="w", pady=(16, 6))
        self.output = ScrolledText(
            self,
            wrap="word",
            width=1,
            height=1,
            font=("Consolas", 10),
            background="#151b1d",
            foreground="#dce6e2",
            insertbackground="#ffffff",
            relief="flat",
            padx=12,
            pady=10,
        )
        self.output.grid(row=3, column=0, columnspan=3, sticky="nsew")

    def _choose_file(self) -> None:
        selected = filedialog.askopenfilename(
            parent=self,
            title="选择规则文件",
            initialdir=str(TOOL_ROOT / "examples"),
            filetypes=(("Dungeon DSL", "*.dungeon"), ("所有文件", "*.*")),
        )
        if selected:
            self.file_var.set(selected)

    def _clear(self) -> None:
        self.output.delete("1.0", "end")

    def _write(self, text: str) -> None:
        self.output.insert("end", text)
        if text and not text.endswith("\n"):
            self.output.insert("end", "\n")
        self.output.see("end")

    def _run_action(self, action: str) -> None:
        source = Path(self.file_var.get().strip())
        if not source.is_absolute():
            source = TOOL_ROOT / source
        if not source.is_file():
            messagebox.showerror("规则配置", "规则文件不存在。", parent=self)
            return
        if action == "check":
            command = ["check", str(source)]
        elif action == "compile":
            command = ["compile", str(source), "-o", "build/world.json"]
        else:
            command = [
                "simulate", str(source), "--rooms", "100000", "--seed", "42",
            ]
        executable = _console_python()
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        for button in self.action_buttons:
            button.state(["disabled"])
        self.update_idletasks()
        try:
            result = subprocess.run(
                [str(executable), "-B", "-m", "dungeon_dsl", *command],
                cwd=TOOL_ROOT,
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=flags,
                timeout=120,
            )
            self.output.insert("end", f"$ {action}\n")
            if result.stdout:
                self._write(result.stdout.rstrip())
            if result.stderr:
                self._write(result.stderr.rstrip())
            self._write(f"退出代码：{result.returncode}\n")
        except Exception as error:
            self._write(f"执行失败：{error}\n")
        finally:
            for button in self.action_buttons:
                button.state(["!disabled"])


class ConfigModifierApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("配置与自定义修改文件 · 无尽地牢 16.0")
        self.geometry("1080x780")
        self.minsize(1000, 720)
        self.configure(background="#eeeae1")
        self._manager: ManagedGame | None = None
        self._last_log_path: Path | None = None
        self._change_job: str | None = None
        self._ready = False
        self.controls: dict[str, NumericControl] = {}

        self._configure_styles()
        self._build_layout()
        self._load_values(load_config(PROFILE_PATH))
        self._ready = True
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _configure_styles(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TFrame", background="#eeeae1")
        style.configure("Page.TFrame", background="#f8f5ee")
        style.configure("Field.TFrame", background="#f8f5ee")
        style.configure("Field.TLabel", background="#f8f5ee",
                        foreground="#26302d", font=("Microsoft YaHei UI", 10))
        style.configure("Scope.TLabel", background="#f8f5ee",
                        foreground="#74817c", font=("Microsoft YaHei UI", 8))
        style.configure("Title.TLabel", background="#eeeae1",
                        foreground="#192522",
                        font=("Microsoft YaHei UI", 17, "bold"))
        style.configure("Subtitle.TLabel", background="#eeeae1",
                        foreground="#69746f",
                        font=("Microsoft YaHei UI", 9))
        style.configure("Section.TLabel", background="#f8f5ee",
                        foreground="#26302d",
                        font=("Microsoft YaHei UI", 10, "bold"))
        style.configure("Status.TLabel", background="#eeeae1",
                        foreground="#52605b",
                        font=("Microsoft YaHei UI", 9))
        style.configure("TNotebook", background="#eeeae1", borderwidth=0)
        style.configure("TNotebook.Tab", padding=(18, 8),
                        font=("Microsoft YaHei UI", 9, "bold"))
        style.configure("TLabelframe", background="#f8f5ee",
                        bordercolor="#d3cdc1", relief="solid")
        style.configure("TLabelframe.Label", background="#f8f5ee",
                        foreground="#34413d",
                        font=("Microsoft YaHei UI", 10, "bold"))
        style.configure("Accent.TButton", padding=(16, 8),
                        font=("Microsoft YaHei UI", 10, "bold"))
        style.map("Accent.TButton",
                  background=[("!disabled", "#1d6d63"),
                              ("disabled", "#aeb8b4")],
                  foreground=[("!disabled", "#ffffff"),
                              ("disabled", "#eef1ef")])
        style.configure("TButton", padding=(10, 6))

    def _build_layout(self) -> None:
        outer = ttk.Frame(self, padding=(20, 16, 20, 12))
        outer.pack(fill="both", expand=True)

        header = ttk.Frame(outer)
        header.pack(fill="x", pady=(0, 12))
        ttk.Label(
            header,
            text="配置与自定义修改文件",
            style="Title.TLabel",
        ).pack(side="left")
        ttk.Label(
            header,
            text="16.0 · 会话隔离",
            style="Subtitle.TLabel",
        ).pack(side="left", padx=(14, 0), pady=(8, 0))

        notebook = ttk.Notebook(outer)
        notebook.pack(fill="both", expand=True)
        modifier_tab = ttk.Frame(notebook, style="Page.TFrame", padding=18)
        dsl_tab = DSLTab(notebook)
        notebook.add(modifier_tab, text="会话修改")
        notebook.add(dsl_tab, text="规则配置")

        modifier_tab.columnconfigure(0, weight=1)
        modifier_tab.columnconfigure(1, weight=1)
        modifier_tab.rowconfigure(1, weight=1)
        self._build_controls(modifier_tab)
        self._build_launcher(modifier_tab)

        self.status_var = tk.StringVar(value="未启动")
        ttk.Label(
            outer,
            textvariable=self.status_var,
            style="Status.TLabel",
        ).pack(fill="x", pady=(10, 0))

    def _build_controls(self, parent: ttk.Frame) -> None:
        combat = ttk.LabelFrame(parent, text="战斗与玩家", padding=14)
        combat.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        resources = ttk.LabelFrame(parent, text="资源与环境", padding=14)
        resources.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        combat.columnconfigure(0, weight=1)
        resources.columnconfigure(0, weight=1)

        for spec in OPTION_SPECS:
            if spec.group == "combat":
                row = sum(1 for item in OPTION_SPECS[:OPTION_SPECS.index(spec)]
                          if item.group == "combat")
                control = NumericControl(combat, spec, 1.0, self._on_change)
                control.grid(row=row, column=0, sticky="ew", pady=3)
                self.controls[spec.key] = control
            else:
                row = sum(1 for item in OPTION_SPECS[:OPTION_SPECS.index(spec)]
                          if item.group == "resources")
                control = NumericControl(resources, spec, 1.0, self._on_change)
                control.grid(row=row, column=0, sticky="ew", pady=3)
                self.controls[spec.key] = control

    def _build_launcher(self, parent: ttk.Frame) -> None:
        launcher = ttk.LabelFrame(parent, text="16.0 启动", padding=14)
        launcher.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(14, 0))
        launcher.columnconfigure(1, weight=1)

        ttk.Label(launcher, text="游戏目录").grid(
            row=0, column=0, sticky="w", padx=(0, 10))
        self.game_dir_var = tk.StringVar(value=str(GAME_ROOT))
        ttk.Entry(launcher, textvariable=self.game_dir_var).grid(
            row=0, column=1, sticky="ew")
        ttk.Button(launcher, text="浏览", command=self._choose_game_dir).grid(
            row=0, column=2, padx=(8, 0))

        options = ttk.Frame(launcher)
        options.grid(row=1, column=0, columnspan=3, sticky="w", pady=(10, 0))
        self.inherit_var = tk.BooleanVar(value=True)
        self.preserve_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            options, text="复制当前存档快照",
            variable=self.inherit_var,
        ).pack(side="left")
        ttk.Checkbutton(
            options, text="保留临时会话",
            variable=self.preserve_var,
        ).pack(side="left", padx=(18, 0))

        buttons = ttk.Frame(launcher)
        buttons.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(12, 0))
        self.launch_button = ttk.Button(
            buttons,
            text="以修改模式启动游戏",
            style="Accent.TButton",
            command=self._launch,
        )
        self.launch_button.pack(side="left")
        ttk.Button(buttons, text="恢复默认", command=self._reset).pack(
            side="left", padx=(8, 0))
        self.log_button = ttk.Button(
            buttons, text="查看日志",
            command=self._open_log,
            state="disabled",
        )
        self.log_button.pack(side="right")

    def _choose_game_dir(self) -> None:
        selected = filedialog.askdirectory(
            parent=self,
            title="选择 16.0 游戏目录",
            initialdir=str(GAME_ROOT),
        )
        if selected:
            self.game_dir_var.set(selected)

    def _load_values(self, config) -> None:
        for key, control in self.controls.items():
            control.set_value(getattr(config, key))

    def _collect_values(self):
        return defaults().changed(**{
            key: control.value() for key, control in self.controls.items()
        })

    def _on_change(self) -> None:
        if not self._ready:
            return
        if self._change_job is not None:
            self.after_cancel(self._change_job)
        self._change_job = self.after(220, self._persist_values)

    def _persist_values(self) -> None:
        self._change_job = None
        config = self._collect_values()
        try:
            write_config(PROFILE_PATH, config)
            if self._manager is not None and self._manager.poll() is None:
                write_config(self._manager.config_path, config)
        except OSError:
            self.status_var.set("配置写入失败")

    def _reset(self) -> None:
        self._load_values(defaults())
        self._persist_values()

    def _launch(self) -> None:
        if self._manager is not None and self._manager.poll() is None:
            return
        config = self._collect_values()
        errors = list(validate_config(config))
        if errors:
            messagebox.showerror("修改设置", "\n".join(errors), parent=self)
            return
        write_config(PROFILE_PATH, config)
        try:
            manager = start_game(
                self.game_dir_var.get().strip(),
                config,
                inherit_saves=self.inherit_var.get(),
                preserve_session=self.preserve_var.get(),
            )
        except Exception as error:
            messagebox.showerror("启动失败", str(error), parent=self)
            self.status_var.set("启动失败")
            return
        self._manager = manager
        self.launch_button.state(["disabled"])
        self.log_button.state(["!disabled"])
        self.status_var.set("游戏运行中 · 修改项可实时调整")
        self.after(500, self._poll_game)

    def _poll_game(self) -> None:
        manager = self._manager
        if manager is None:
            return
        code = manager.poll()
        if code is None:
            self.after(500, self._poll_game)
            return
        tail = manager.tail_log()
        manager.finish()
        self._last_log_path = manager.log_path
        self._manager = None
        self.launch_button.state(["!disabled"])
        if code == 0:
            if manager.preserve_session:
                self.status_var.set(
                    f"游戏已结束 · 临时会话保留在 {manager.session_dir}")
            else:
                self.status_var.set("游戏已结束 · 临时会话已清理")
            self.log_button.state(["!disabled"])
        else:
            self.status_var.set(f"游戏异常退出 · 代码 {code}")
            self.log_button.state(["!disabled"])
            detail = tail.strip() or "没有可用日志。"
            messagebox.showerror(
                "游戏启动失败",
                detail[-1800:],
                parent=self,
            )

    def _open_log(self) -> None:
        manager = self._manager
        log_path = (manager.log_path if manager is not None
                    else self._last_log_path)
        if log_path is None or not log_path.is_file():
            self.status_var.set("本次会话没有可查看的日志")
            return
        try:
            os.startfile(log_path)
        except OSError as error:
            messagebox.showerror("查看日志", str(error), parent=self)

    def _on_close(self) -> None:
        manager = self._manager
        if manager is not None and manager.poll() is None:
            leave = messagebox.askyesno(
                "游戏仍在运行",
                "关闭修改器窗口不会结束游戏。是否继续关闭？",
                parent=self,
            )
            if not leave:
                return
            manager.close()
        self.destroy()


def main() -> None:
    app = ConfigModifierApp()
    app.mainloop()
