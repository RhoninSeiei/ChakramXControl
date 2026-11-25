"""Native Windows configuration editor for the ROG Chakram X."""

import ctypes
from dataclasses import dataclass
from pathlib import Path
import sys
import tkinter as tk
from tkinter import messagebox, ttk

from buttons import ACTIONS, SIDE_BUTTON_SLOTS, ButtonController, action_label
from device import configuration_session, devices
from performance import Performance
from light_ui import LightingPanel


@dataclass
class Snapshot:
    state: object
    dpi: tuple
    buttons: dict


def read_snapshot(transport):
    perf = Performance(transport)
    state = perf.read_state()
    result = Snapshot(state, perf.read_dpi(), ButtonController(transport).read_bindings())
    if perf.read_state() != state:
        raise RuntimeError("读取期间切换了预设或 DPI 档位，请刷新。")
    return result


class Editor:
    def __init__(self, root):
        self.root = root
        self.current = None
        self.device = None
        self.options = []
        self.recover_tab = None
        self.status = tk.StringVar(value="正在查找鼠标…")
        self.profile = tk.StringVar()
        self.labels_to_actions = {label: code for code, label in ACTIONS.items()}
        root.title("Chakram X 鼠标配置")
        root.iconbitmap(default=str(Path(__file__).resolve().parent / "assets" / "chakram-x.ico"))
        root.minsize(640, 490)
        root.option_add("*Font", ("Microsoft YaHei UI", 10))
        ttk.Style(root).configure("TNotebook.Tab", padding=(12, 5))
        base = ttk.Frame(root, padding=(22, 15))
        base.pack(fill="both", expand=True)
        bar = ttk.Frame(base)
        bar.pack(fill="x")
        ttk.Label(bar, text="ROG Chakram X", font=("Segoe UI Semibold", 20)).pack(side="left")
        ttk.Button(bar, text="刷新设备", command=self.refresh).pack(side="right")
        self.picker = ttk.Combobox(bar, width=18, state="readonly")
        self.picker.pack(side="right", padx=8)
        self.picker.bind("<<ComboboxSelected>>", lambda event: self.refresh(self.picker.current()))
        profiles = ttk.Frame(base, padding=(0, 12))
        profiles.pack(fill="x")
        ttk.Label(profiles, text="板载预设").pack(side="left")
        self.profile_picker = ttk.Combobox(profiles, width=4, values=(1, 2, 3, 4, 5),
                                            state="readonly", textvariable=self.profile)
        self.profile_picker.pack(side="left", padx=8)
        self.switch = ttk.Button(profiles, text="切换预设", command=self.change_profile)
        self.switch.pack(side="left")
        self.profile.trace_add("write", self.update_profile_switch)
        self.summary = ttk.Label(profiles)
        self.summary.pack(side="right")
        self.tabs = ttk.Notebook(base)
        self.tabs.pack(fill="both", expand=True)
        self.dpi_tab = ttk.Frame(self.tabs, padding=15)
        self.key_tab = ttk.Frame(self.tabs, padding=15)
        self.stick_tab = ttk.Frame(self.tabs, padding=15)
        self.light_tab = ttk.Frame(self.tabs, padding=15)
        for frame, title in [(self.dpi_tab, "灵敏度"), (self.key_tab, "四个侧键"),
                             (self.stick_tab, "侧面摇杆"), (self.light_tab, "灯效")]:
            self.tabs.add(frame, text=title)
        self.entries = []
        self.actual = []
        self.slot_labels = []
        self.row_bands = []
        self.activate_buttons = []
        self.key_vars = {}
        self.key_actual = {}
        self._dpi_layout()
        self._side_layout()
        self._stick_layout()
        self.lighting = LightingPanel(self, self.light_tab)
        self.tabs.bind("<<NotebookTabChanged>>", self.read_lights_if_visible)
        ttk.Label(base, textvariable=self.status, wraplength=630).pack(fill="x", pady=(12, 0))
        self.enable(False)
        root.after(50, self.refresh)
        self.poll_job = root.after(1500, self.poll)
        root.bind("<Destroy>", self.stop_poll, add="+")

    def _dpi_layout(self):
        f = self.dpi_tab
        for col, title in enumerate(("档位", "鼠标回读 X / Y", "新 DPI", "", "")):
            ttk.Label(f, text=title).grid(row=0, column=col, padx=6, sticky="w")
        for i in range(4):
            n = i + 1
            band = ttk.Frame(f, style="DpiRow.TFrame")
            band.grid(row=n, column=0, columnspan=5, sticky="nsew")
            self.row_bands.append(band)
            slot_label = ttk.Label(f, text=str(n), width=6)
            slot_label.grid(row=n, column=0, sticky="w", padx=6)
            self.slot_labels.append(slot_label)
            val = ttk.Label(f, width=16)
            val.grid(row=n, column=1, sticky="w", padx=6)
            self.actual.append(val)
            entry = tk.StringVar()
            self.entries.append(entry)
            ttk.Entry(f, width=9, textvariable=entry).grid(row=n, column=2, padx=6, pady=6)
            ttk.Button(f, text="保存数值", command=lambda idx=i: self.set_dpi(idx)).grid(row=n, column=3, padx=4)
            activate = ttk.Button(f, text="启用此档", command=lambda slot=n: self.select_dpi(slot))
            activate.grid(row=n, column=4, padx=4)
            self.activate_buttons.append(activate)
        style = ttk.Style(f)
        style.configure("ActiveDpi.TFrame", background="#D8EBF9")
        style.configure("ActiveDpi.TLabel", background="#D8EBF9", foreground="#114F7D",
                        font=("Microsoft YaHei UI", 10, "bold"))
        ttk.Label(f, text="输入 100 至 36000，步进为 50。保存后，X 轴和 Y 轴使用相同 DPI。").grid(
            row=5, column=0, columnspan=5, sticky="w", pady=(14, 0))

    def action_box(self, frame, row, name, column=1):
        ttk.Label(frame, text=name, width=12).grid(row=row, column=0, sticky="w", pady=5)
        var = tk.StringVar()
        box = ttk.Combobox(frame, values=list(self.labels_to_actions), textvariable=var,
                           width=25, state="readonly", height=16)
        box.grid(row=row, column=column, padx=10, pady=5)
        return var

    def _side_layout(self):
        for column, text in enumerate(("侧键", "当前生效", "设置为")):
            ttk.Label(self.key_tab, text=text).grid(row=0, column=column, sticky="w", padx=(0, 6))
        for i, button in enumerate(SIDE_BUTTON_SLOTS, 1):
            self.key_vars[button.slot] = self.action_box(self.key_tab, i, button.name, column=2)
            active = ttk.Label(self.key_tab, width=19, anchor="w")
            active.grid(row=i, column=1, sticky="w")
            self.key_actual[button.slot] = active
            ttk.Button(self.key_tab, text="保存按键", command=lambda slot=button.slot: self.set_button(slot)).grid(
                row=i, column=3, padx=6)

    def _stick_layout(self):
        from stick_ui import StickPanel
        self.stick = StickPanel(self, self.stick_tab)

    def enable(self, connected):
        for tab in (self.dpi_tab, self.key_tab, self.stick_tab, self.light_tab):
            self.tabs.tab(tab, state="normal" if connected else "disabled")
        if connected and not self.tabs.select():
            self.tabs.select(self.dpi_tab)
        self.profile_picker.configure(state="readonly" if connected else "disabled")
        self.update_profile_switch()

    def update_profile_switch(self, *_):
        same = self.current is not None and self.profile.get() == str(self.current.state.profile)
        self.switch.configure(text="使用中" if same else "切换预设",
                              state="normal" if self.current is not None and not same else "disabled")

    def read_lights_if_visible(self, event=None, *, preserve_draft=False):
        if self.current is not None and self.tabs.select() == str(self.light_tab):
            self.lighting.load(preserve_draft=preserve_draft or event is not None)

    def render_snapshot(self, state, *, keep_edits):
        previous = self.current
        self.current = state
        if not keep_edits:
            self.profile.set(str(state.state.profile))
        slot = state.state.dpi_slot
        active = state.dpi[slot - 1]
        dpi_text = str(active.x) if active.x == active.y else f"{active.x} / {active.y}"
        self.summary.configure(text=f"当前预设 {state.state.profile}    ·    档位 {slot}    ·    {dpi_text} DPI")
        for i, item in enumerate(state.dpi):
            selected = slot == i + 1
            self.row_bands[i].configure(style="ActiveDpi.TFrame" if selected else "TFrame")
            style = "ActiveDpi.TLabel" if selected else "TLabel"
            self.slot_labels[i].configure(style=style)
            self.actual[i].configure(text=f"{item.x} / {item.y}", style=style)
            self.activate_buttons[i].configure(text="使用中" if selected else "启用此档",
                                               state="disabled" if selected else "normal")
            old_item = previous.dpi[i] if keep_edits else None
            old_text = str(old_item.x) if old_item and old_item.x == old_item.y else ""
            if not keep_edits or (old_item != item and self.entries[i].get() == old_text):
                self.entries[i].set(str(item.x) if item.x == item.y else "")
        for key, var in self.key_vars.items():
            label = action_label(state.buttons[key])
            self.key_actual[key].configure(text=label)
            if not keep_edits or (previous.buttons[key] != state.buttons[key]
                                  and var.get() == action_label(previous.buttons[key])):
                var.set(label)

    def stop_poll(self, event):
        if event.widget is self.root and self.poll_job:
            self.root.after_cancel(self.poll_job)
            self.poll_job = None

    def poll(self):
        try:
            if self.root.winfo_viewable() and self.device is not None:
                self.sync_visible_state()
        finally:
            self.poll_job = self.root.after(1500 if self.current else 5000, self.poll)

    def sync_visible_state(self):
        try:
            with configuration_session(self.device) as tr:
                state = read_snapshot(tr)
            reconnect = self.current is None
            same_profile = not reconnect and self.current.state.profile == state.state.profile
            if reconnect:
                self.enable(True)
                if self.recover_tab:
                    self.tabs.select(self.recover_tab)
                    self.recover_tab = None
            if state != self.current:
                self.render_snapshot(state, keep_edits=same_profile)
            if not same_profile:
                self.stick.load(state)
                self.status.set("鼠标已重新连接。" if reconnect else f"鼠标已切换到预设 {state.state.profile}。")
            elif self.tabs.select() == str(self.stick_tab):
                self.stick.refresh_compatibility()
            self.read_lights_if_visible(preserve_draft=same_profile)
        except (OSError, RuntimeError, ValueError) as exc:
            self.mark_unavailable(exc)

    def mark_unavailable(self, error):
        if self.tabs.select():
            self.recover_tab = self.tabs.select()
        self.enable(False)
        self.current = None
        self.profile.set("")
        self.summary.configure(text="当前状态未知")
        self.status.set(f"{error} 请刷新设备后重试。")

    def refresh(self, selected=None, notice=""):
        try:
            old = self.device
            self.options = devices()
            self.picker.configure(values=[f"{i + 1} · {d.label}" for i, d in enumerate(self.options)])
            if not self.options:
                raise RuntimeError("未发现 Chakram X。请连接 USB 线或 2.4 GHz 接收器，然后刷新。")
            if selected is None or not 0 <= selected < len(self.options):
                selected = self.options.index(old) if old in self.options else 0
            self.device = self.options[selected]
            self.picker.current(selected)
            with configuration_session(self.device) as tr:
                state = read_snapshot(tr)
            previous = self.current if old == self.device and notice else None
            keep_edits = previous is not None and previous.state.profile == state.state.profile
            self.enable(True)
            self.render_snapshot(state, keep_edits=keep_edits)
            if self.recover_tab:
                self.tabs.select(self.recover_tab)
                self.recover_tab = None
            self.stick.load(state)
            self.status.set(notice or "当前数据来自鼠标。")
            self.read_lights_if_visible(preserve_draft=keep_edits)
        except (OSError, RuntimeError, ValueError) as exc:
            self.mark_unavailable(exc)
            if not self.options:
                self.picker.set("")

    def run(self, operation, notice):
        if self.current is None:
            return
        try:
            with configuration_session(self.device) as tr:
                if Performance(tr).read_state().profile != self.current.state.profile:
                    raise RuntimeError("鼠标的活动预设发生了变化，请核对刷新后的设置。")
                operation(tr)
        except (OSError, RuntimeError, ValueError) as exc:
            self.refresh()
            messagebox.showerror("配置未确认", str(exc), parent=self.root)
            return
        self.refresh(notice=notice)

    def change_profile(self):
        target = int(self.profile.get())
        if target != self.current.state.profile:
            self.run(lambda tr: ButtonController(tr).select_profile(target, expected_profile=self.current.state.profile),
                     f"已切换到板载预设 {target}。")

    def set_dpi(self, index):
        try:
            dpi = int(self.entries[index].get())
        except ValueError:
            messagebox.showerror("DPI 输入有误", "请输入整数 DPI。", parent=self.root)
            return
        def apply(tr):
            perf = Performance(tr)
            if perf.read_dpi()[index] != self.current.dpi[index]:
                raise RuntimeError("这个档位自读取后发生了变化，请核对最新数值。")
            if (self.current.dpi[index].x, self.current.dpi[index].y) != (dpi, dpi):
                perf.set_dpi(index + 1, dpi, expected_profile=self.current.state.profile)
        self.run(apply, f"档位 {index + 1} 的设备回读为 {dpi} DPI。")

    def select_dpi(self, slot):
        self.run(lambda tr: Performance(tr).select_dpi(slot, expected_profile=self.current.state.profile),
                 f"当前使用 DPI 档位 {slot}。")

    def set_button(self, slot):
        label = self.key_vars[slot].get()
        if label == action_label(self.current.buttons[slot]):
            return
        def apply(tr):
            controller = ButtonController(tr)
            if controller.read_binding(slot) != self.current.buttons[slot]:
                raise RuntimeError("这个侧键自读取后发生了变化，请核对最新映射。")
            controller.set_button(slot, self.labels_to_actions[label], expected_profile=self.current.state.profile)
        self.run(apply, f"侧键映射已保存并回读为 {label}。")


def main():
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
    root = tk.Tk()
    smoke_test = sys.argv[1:] == ["--smoke-test"]
    if smoke_test:
        root.withdraw()
    Editor(root)
    if smoke_test:
        devices()
        root.update_idletasks()
        root.destroy()
        return
    root.mainloop()


if __name__ == "__main__":
    main()
