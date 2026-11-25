import os
from pathlib import Path
import sqlite3
import subprocess
import tkinter as tk
from tkinter import messagebox, ttk

from buttons import ButtonController, action_label, direction_label, joystick_mode_label
from device import configuration_session, container_id, gamepad_flag, gamepad_present, wait_gamepad
from i18n import bind_text, get_language, refresh_text, tr
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
        self._target_mode = "digital"
        self.target = tk.StringVar(value=joystick_mode_label(self._target_mode))
        self.compatibility = tk.BooleanVar()
        self.info = tk.StringVar()
        self.last = tk.StringVar()
        self.available = False
        self._info_kind = "unknown"
        self._info_error = ""
        self._history = None
        self._test_windows = []

        controller = ttk.Frame(frame)
        controller.pack(fill="x")
        self.toggle = ttk.Checkbutton(controller, variable=self.compatibility,
                                      command=self.toggle_compatibility)
        bind_text(self.toggle, "摇杆兼容模式", "Joystick compatibility mode")
        self.toggle.pack(side="left")
        ttk.Label(controller, textvariable=self.info).pack(side="left", padx=10)
        self.controller_test_button = ttk.Button(controller, command=self.open_game_controllers)
        bind_text(self.controller_test_button, "测试控制器…", "Test controller…")
        self.controller_test_button.pack(side="right")

        self.explanation = ttk.Label(frame, anchor="w", wraplength=620)
        bind_text(self.explanation,
                  "勾选后，Windows 会隐藏这只鼠标的手柄接口。应用模拟摇杆设置会关闭兼容模式。",
                  "When enabled, Windows hides this mouse's game controller interface. Applying an analog stick layout turns compatibility mode off.")
        self.explanation.pack(anchor="w")
        ttk.Separator(frame).pack(fill="x", pady=8)
        self.history_label = ttk.Label(frame, textvariable=self.last, wraplength=620)
        self.history_label.pack(anchor="w", pady=(0, 8))

        self.layout = ttk.Frame(frame)
        self.layout.pack(fill="x")
        self.mode_label = ttk.Label(self.layout, width=12)
        bind_text(self.mode_label, "目标模式", "Target mode")
        self.mode_label.grid(row=0, column=0, sticky="w")
        self.mode = ttk.Combobox(self.layout, values=self._mode_values(), textvariable=self.target,
                                 state="readonly", width=25)
        self.mode.grid(row=0, column=1, padx=10, sticky="w")
        self.mode.bind("<<ComboboxSelected>>", self._mode_selected)
        self.apply_button = ttk.Button(self.layout, command=self.apply)
        bind_text(self.apply_button, "应用摇杆设置", "Apply joystick settings")
        self.apply_button.grid(row=0, column=2, padx=4)

        self.keys = {}
        self.direction_labels = {}
        for row, (name, title) in enumerate(DIRECTIONS.items(), 1):
            self.keys[name] = editor.action_box(self.layout, row, "")
            label = self.layout.grid_slaves(row=row, column=0)[0]
            bind_text(label, f"摇杆向{title}", f"Joystick {direction_label(name, 'en').lower()}")
            self.direction_labels[name] = label

        self.key_test_button = ttk.Button(frame, command=self.test_keys)
        bind_text(self.key_test_button, "测试按键输入…", "Test key input…")
        self.key_test_button.pack(anchor="w", pady=(5, 0))

    @staticmethod
    def _mode_values(language=None):
        return [joystick_mode_label(mode, language) for mode in MODES]

    def _mode_selected(self, _event=None):
        for key in MODES:
            if self.target.get() == joystick_mode_label(key):
                self._target_mode = key
                break
        self.update_controls()

    def _render_info(self):
        if self._info_kind == "error":
            self.info.set(tr("无法读取兼容模式：{error}", "Could not read compatibility mode: {error}",
                             error=self._info_error))
        elif self._info_kind == "present":
            self.info.set(tr("Windows 已识别鼠标手柄", "Windows detects the mouse game controller"))
        elif self._info_kind == "missing":
            self.info.set(tr("Windows 未检测到鼠标手柄", "Windows does not detect the mouse game controller"))
        elif self._info_kind == "unavailable":
            self.info.set(tr("Windows 手柄状态暂不可用", "Windows game controller status is unavailable"))
        else:
            self.info.set("")

    def _render_history(self):
        if self._history is None:
            self.last.set("")
            return
        profile, available, mode, codes, has_bindings = self._history
        if not available:
            self.last.set(tr("预设 5 为快速射击预设。请切换到预设 1 至 4 编辑摇杆。",
                             "Profile 5 is reserved for rapid fire. Switch to profile 1 through 4 to edit the joystick."))
            return
        if mode in MODES:
            source = tr("本机上次写入　{mode}", "Last saved on this PC　{mode}",
                        mode=joystick_mode_label(mode))
        else:
            source = tr("此预设尚无本机写入记录", "No joystick layout has been saved on this PC for this profile")
        if mode == "digital" and has_bindings:
            names = [direction_label(name) for name in DIRECTIONS]
            source += "　" + "  ".join(
                f"{direction} {action_label(code)}" for direction, code in zip(names, codes)
            )
        source += "\n" + tr("固件无法回读四方向绑定。下面的设置仅在点击应用时写入。",
                            "The firmware cannot read back the four direction bindings. Settings below are written only when Apply is clicked.")
        self.last.set(source)

    def update_controls(self):
        digital = self._target_mode == "digital"
        self.mode.configure(state="readonly" if self.available else "disabled")
        self.apply_button.configure(state="normal" if self.available else "disabled")
        for box in self.layout.winfo_children():
            if isinstance(box, ttk.Combobox) and box is not self.mode:
                box.configure(state="readonly" if self.available and digital else "disabled")

    def retranslate(self, old_language):
        """Refresh visible text without querying hardware or changing draft values."""
        current = self.target.get()
        for key in MODES:
            if current == joystick_mode_label(key, old_language):
                self._target_mode = key
                break
        self.target.set(joystick_mode_label(self._target_mode))
        self.mode.configure(values=self._mode_values())
        # The checkbox and action variables are deliberately left untouched.
        refresh_text(self.frame)
        for window, output in tuple(self._test_windows):
            try:
                if window.winfo_exists():
                    refresh_text(window)
                    window.title(tr("测试按键输入", "Test key input"))
                    waiting_old = "等候按键" if old_language == "zh" else "Waiting for a key"
                    if output.get() == waiting_old:
                        output.set(tr("等候按键", "Waiting for a key"))
            except tk.TclError:
                continue
        self._render_info()
        self._render_history()
        self.update_controls()

    def load(self, snapshot):
        self.available = snapshot.state.profile in (1, 2, 3, 4)
        self.refresh_compatibility()
        self.identity = container_id(self.editor.device.path)
        try:
            saved = self.record.read(self.identity, snapshot.state.profile)
        except (OSError, sqlite3.Error):
            saved = None
        last_mode = saved[0] if saved else None
        self._target_mode = last_mode if last_mode in MODES else "digital"
        self.target.set(joystick_mode_label(self._target_mode))
        has_bindings = bool(saved and all(value is not None for value in saved[1:]))
        codes = tuple(saved[1:]) if has_bindings else ARROWS
        for var, code in zip(self.keys.values(), codes):
            var.set(action_label(code))
        self._history = (snapshot.state.profile, self.available, last_mode, codes, has_bindings)
        self._render_history()
        self.update_controls()

    def refresh_compatibility(self):
        try:
            with configuration_session(self.editor.device) as transport:
                self.compatibility.set(not gamepad_flag(transport))
            self.toggle.state(["!disabled", "!alternate"])
        except (OSError, RuntimeError, ValueError) as exc:
            self.toggle.state(["disabled", "alternate"])
            self._info_kind = "error"
            self._info_error = str(exc)
            self._render_info()
            return
        try:
            present = gamepad_present(self.editor.device)
            self._info_kind = "present" if present else "missing"
        except OSError:
            self._info_kind = "unavailable"
        self._render_info()

    def toggle_compatibility(self):
        enabled = self.compatibility.get()
        self.toggle.state(["disabled"])
        self.editor.status.set(tr("正在切换摇杆兼容模式，等待 Windows 重新识别鼠标…",
                                  "Switching joystick compatibility mode; waiting for Windows to re-detect the mouse…"))
        self.frame.update_idletasks()
        try:
            ensure_gamepad(self.editor.device, not enabled)
        except (OSError, RuntimeError, ValueError) as exc:
            self.refresh_compatibility()
            self.editor.status.set(tr("兼容模式切换未确认，请刷新设备。",
                                      "The compatibility mode change was not confirmed. Refresh the device."))
            messagebox.showerror(tr("摇杆兼容模式", "Joystick compatibility mode"), str(exc), parent=self.editor.root)
            return
        self.refresh_compatibility()
        self.editor.status.set(
            tr("兼容模式已开启，鼠标手柄已隐藏。", "Compatibility mode is on; the mouse game controller is hidden.")
            if enabled else
            tr("兼容模式已关闭，Windows 已识别鼠标手柄。", "Compatibility mode is off; Windows detects the mouse game controller.")
        )

    def apply(self):
        if not self.available or not self.editor.current:
            return
        mode = self._target_mode
        digital = mode == "digital"
        bindings = {direction: self.editor.labels_to_actions[var.get()]
                    for direction, var in self.keys.items()} if digital else None
        device = self.editor.device
        profile = self.editor.current.state.profile
        wrote = False
        try:
            if not digital:
                ensure_gamepad(device, True)
            with configuration_session(device) as transport:
                if Performance(transport).read_state().profile != profile:
                    raise RuntimeError(tr("活动预设发生变化，请刷新后重试。",
                                          "The active profile changed. Refresh and try again."))
                ButtonController(transport).set_joystick_mode(mode, bindings,
                                                               expected_profile=profile, persist=True)
                wrote = True
            self.record.save(self.identity, profile, mode, tuple(bindings.values()) if digital else None)
        except (OSError, RuntimeError, ValueError, sqlite3.Error) as exc:
            self.editor.refresh()
            prefix = tr("鼠标已接受设置，本机记录保存失败。", "The mouse accepted the settings, but saving the local record failed.") if wrote else ""
            messagebox.showerror(tr("摇杆设置", "Joystick settings"), prefix + str(exc), parent=self.editor.root)
            return
        self.editor.refresh(notice=tr("预设 {profile} 已接收四方向映射和板载保存命令。",
                                      "Profile {profile} accepted the four direction mappings and onboard save command.",
                                      profile=profile))

    def test_keys(self):
        window = tk.Toplevel(self.editor.root)
        window.title(tr("测试按键输入", "Test key input"))
        window.transient(self.editor.root)
        panel = ttk.Frame(window, padding=20)
        panel.pack(fill="both", expand=True)
        description = ttk.Label(panel, wraplength=560)
        bind_text(description,
                  "保持窗口焦点，拨动摇杆或按下侧键，即可查看键盘映射产生的输入。",
                  "Keep this window focused, then move the stick or press a side button to see the resulting keyboard input.")
        description.pack()
        waiting = ("等候按键", "Waiting for a key")
        output = tk.StringVar(value=tr(*waiting))
        output_label = ttk.Label(panel, textvariable=output, font=("Segoe UI", 18))
        output_label.pack(pady=16)

        def pressed(event):
            output.set(event.keysym)
            return "break"

        window.bind("<KeyPress>", pressed)
        window.focus_set()
        self._test_windows.append((window, output))

        def closed(_event=None):
            self._test_windows[:] = [(candidate, var) for candidate, var in self._test_windows
                                     if candidate is not window]

        window.bind("<Destroy>", closed, add="+")

    @staticmethod
    def open_game_controllers():
        control = Path(os.environ["SystemRoot"], "System32", "control.exe")
        subprocess.Popen([str(control), "joy.cpl"])
