import os
from pathlib import Path
import sqlite3
import subprocess
import tkinter as tk
from tkinter import messagebox, ttk

from buttons import ButtonController, action_label
from device import configuration_session, container_id, gamepad_flag, gamepad_present, wait_gamepad
from performance import Performance
from stick_record import StickRecord


MODES = {"digital": "数字四键", "analog_vertical": "模拟摇杆 · 纵向",
         "analog_horizontal": "模拟摇杆 · 横向"}
DIRECTIONS = {"up": "上", "down": "下", "left": "左", "right": "右"}
ARROWS = (0x52, 0x51, 0x50, 0x4F)


def ensure_gamepad(device, enabled):
    with configuration_session(device) as tr:
        if gamepad_flag(tr) != enabled:
            tr.set_gamepad_flag(enabled)
    wait_gamepad(device, enabled)


class StickPanel:
    def __init__(self, editor, frame):
        self.editor = editor
        self.frame = frame
        self.record = StickRecord()
        self.target = tk.StringVar(value=MODES["digital"])
        self.compatibility = tk.BooleanVar()
        self.info = tk.StringVar()
        self.last = tk.StringVar()
        controller = ttk.Frame(frame)
        controller.pack(fill="x")
        self.toggle = ttk.Checkbutton(controller, text="摇杆兼容模式", variable=self.compatibility,
                                      command=self.toggle_compatibility)
        self.toggle.pack(side="left")
        ttk.Label(controller, textvariable=self.info).pack(side="left", padx=10)
        ttk.Button(controller, text="测试控制器…", command=self.open_game_controllers).pack(side="right")
        ttk.Label(frame, text="勾选后，Windows 会隐藏这只鼠标的手柄接口。应用模拟摇杆设置会关闭兼容模式。").pack(anchor="w")
        ttk.Separator(frame).pack(fill="x", pady=8)
        ttk.Label(frame, textvariable=self.last, wraplength=590).pack(anchor="w", pady=(0, 8))
        self.layout = ttk.Frame(frame)
        self.layout.pack(fill="x")
        ttk.Label(self.layout, text="目标模式", width=12).grid(row=0, column=0, sticky="w")
        self.mode = ttk.Combobox(self.layout, values=list(MODES.values()), textvariable=self.target,
                                 state="readonly", width=25)
        self.mode.grid(row=0, column=1, padx=10, sticky="w")
        self.mode.bind("<<ComboboxSelected>>", lambda _: self.update_controls())
        self.apply_button = ttk.Button(self.layout, text="应用摇杆设置", command=self.apply)
        self.apply_button.grid(row=0, column=2, padx=4)
        self.keys = {name: editor.action_box(self.layout, i, f"摇杆向{title}")
                     for i, (name, title) in enumerate(DIRECTIONS.items(), 1)}
        ttk.Button(frame, text="测试按键输入…", command=self.test_keys).pack(anchor="w", pady=(5, 0))
        self.available = False

    def update_controls(self):
        digital = self.target.get() == MODES["digital"]
        self.mode.configure(state="readonly" if self.available else "disabled")
        self.apply_button.configure(state="normal" if self.available else "disabled")
        for box in self.layout.winfo_children():
            if isinstance(box, ttk.Combobox) and box is not self.mode:
                box.configure(state="readonly" if self.available and digital else "disabled")

    def load(self, snapshot):
        self.available = snapshot.state.profile in (1, 2, 3, 4)
        self.refresh_compatibility()
        self.identity = container_id(self.editor.device.path)
        try:
            saved = self.record.read(self.identity, snapshot.state.profile)
        except (OSError, sqlite3.Error):
            saved = None
        last_mode = saved[0] if saved else None
        self.target.set(MODES.get(last_mode, MODES["digital"]))
        codes = saved[1:] if saved and all(v is not None for v in saved[1:]) else ARROWS
        for var, code in zip(self.keys.values(), codes):
            var.set(action_label(code))
        if self.available:
            source = f"本机上次写入　{MODES[last_mode]}" if last_mode in MODES else "此预设尚无本机写入记录"
            if last_mode == "digital" and all(value is not None for value in saved[1:]):
                source += "　" + "  ".join(f"{d} {action_label(v)}" for d, v in zip(DIRECTIONS.values(), codes))
            self.last.set(source + "\n固件无法回读四方向绑定。下面的设置仅在点击应用时写入。")
        else:
            self.last.set("预设 5 为快速射击预设。请切换到预设 1 至 4 编辑摇杆。")
        self.update_controls()

    def refresh_compatibility(self):
        try:
            with configuration_session(self.editor.device) as tr:
                self.compatibility.set(not gamepad_flag(tr))
            self.toggle.state(["!disabled", "!alternate"])
        except (OSError, RuntimeError, ValueError) as exc:
            self.toggle.state(["disabled", "alternate"])
            self.info.set(f"无法读取兼容模式：{exc}")
            return
        try:
            present = gamepad_present(self.editor.device)
            self.info.set("Windows 已识别鼠标手柄" if present else "Windows 未检测到鼠标手柄")
        except OSError:
            self.info.set("Windows 手柄状态暂不可用")

    def toggle_compatibility(self):
        enabled = self.compatibility.get()
        self.toggle.state(["disabled"])
        self.editor.status.set("正在切换摇杆兼容模式，等待 Windows 重新识别鼠标…")
        self.frame.update_idletasks()
        try:
            ensure_gamepad(self.editor.device, not enabled)
        except (OSError, RuntimeError, ValueError) as exc:
            self.refresh_compatibility()
            self.editor.status.set("兼容模式切换未确认，请刷新设备。")
            messagebox.showerror("摇杆兼容模式", str(exc), parent=self.editor.root)
            return
        self.refresh_compatibility()
        self.editor.status.set("兼容模式已开启，鼠标手柄已隐藏。" if enabled else "兼容模式已关闭，Windows 已识别鼠标手柄。")

    def apply(self):
        if not self.available or not self.editor.current:
            return
        mode = next(k for k, label in MODES.items() if label == self.target.get())
        digital = mode == "digital"
        bindings = {d: self.editor.labels_to_actions[v.get()] for d, v in self.keys.items()} if digital else None
        dev = self.editor.device
        profile = self.editor.current.state.profile
        wrote = False
        try:
            if not digital:
                ensure_gamepad(dev, True)
            with configuration_session(dev) as tr:
                if Performance(tr).read_state().profile != profile:
                    raise RuntimeError("活动预设发生变化，请刷新后重试。")
                ButtonController(tr).set_joystick_mode(mode, bindings, expected_profile=profile, persist=True)
                wrote = True
            self.record.save(self.identity, profile, mode, tuple(bindings.values()) if digital else None)
        except (OSError, RuntimeError, ValueError, sqlite3.Error) as exc:
            self.editor.refresh()
            prefix = "鼠标已接受设置，本机记录保存失败。" if wrote else ""
            messagebox.showerror("摇杆设置", prefix + str(exc), parent=self.editor.root)
            return
        self.editor.refresh(notice=f"预设 {profile} 已接收四方向映射和板载保存命令。")

    def test_keys(self):
        window = tk.Toplevel(self.editor.root)
        window.title("测试按键输入")
        window.transient(self.editor.root)
        panel = ttk.Frame(window, padding=20)
        panel.pack(fill="both", expand=True)
        ttk.Label(panel, text="保持窗口焦点，拨动摇杆或按下侧键，即可查看键盘映射产生的输入。").pack()
        output = tk.StringVar(value="等候按键")
        ttk.Label(panel, textvariable=output, font=("Segoe UI", 18)).pack(pady=16)
        def pressed(event):
            output.set(event.keysym)
            return "break"
        window.bind("<KeyPress>", pressed)
        window.focus_set()

    @staticmethod
    def open_game_controllers():
        control = Path(os.environ["SystemRoot"], "System32", "control.exe")
        subprocess.Popen([str(control), "joy.cpl"])
