"""Native Windows configuration editor for the ROG Chakram X."""

import ctypes
from dataclasses import dataclass
from pathlib import Path
import sys
import tkinter as tk
from tkinter import messagebox, ttk

from buttons import ACTIONS, SIDE_BUTTON_SLOTS, ButtonController, action_label, button_label
from device import configuration_session, devices
from performance import Performance
from light_ui import LightingPanel
from i18n import LANGUAGES, bind_text, get_language, load_language, refresh_text, save_language, set_language, tr as T


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
        raise RuntimeError(T("读取期间切换了预设或 DPI 档位，请刷新。", "The profile or DPI stage changed during the read. Refresh devices."))
    return result


class Editor:
    def __init__(self, root):
        self.root = root
        self.current = None
        self.device = None
        self.options = []
        self.recover_tab = None
        self.status = tk.StringVar(value=T("正在查找鼠标…", "Looking for the mouse…"))
        self.profile = tk.StringVar()
        self.labels_to_actions = {action_label(code): code for code in ACTIONS}
        self.action_boxes = []
        self.language = tk.StringVar(value=LANGUAGES[get_language()])
        root.title(T("Chakram X 鼠标配置", "Chakram X Control"))
        root.iconbitmap(default=str(Path(__file__).resolve().parent / "assets" / "chakram-x.ico"))
        root.minsize(640, 490)
        root.option_add("*Font", ("Microsoft YaHei UI", 10))
        ttk.Style(root).configure("TNotebook.Tab", padding=(12, 5))
        base = ttk.Frame(root, padding=(22, 15))
        base.pack(fill="both", expand=True)
        bar = ttk.Frame(base)
        bar.pack(fill="x")
        ttk.Label(bar, text="ROG Chakram X", font=("Segoe UI Semibold", 20)).pack(side="left")
        self.language_picker = ttk.Combobox(bar, width=10, state="readonly", values=list(LANGUAGES.values()),
                                            textvariable=self.language)
        self.language_picker.pack(side="right", padx=(6, 0))
        self.language_picker.bind("<<ComboboxSelected>>", self.change_language)
        bind_text(ttk.Button(bar, command=self.refresh), "刷新设备", "Refresh devices").pack(side="right")
        self.picker = ttk.Combobox(bar, width=18, state="readonly")
        self.picker.pack(side="right", padx=8)
        self.picker.bind("<<ComboboxSelected>>", lambda event: self.refresh(self.picker.current()))
        profiles = ttk.Frame(base, padding=(0, 12))
        profiles.pack(fill="x")
        bind_text(ttk.Label(profiles), "板载预设", "Onboard profile").pack(side="left")
        self.profile_picker = ttk.Combobox(profiles, width=4, values=(1, 2, 3, 4, 5),
                                            state="readonly", textvariable=self.profile)
        self.profile_picker.pack(side="left", padx=8)
        self.switch = ttk.Button(profiles, text=T("切换预设", "Switch profile"), command=self.change_profile)
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
        self.tab_titles = [(self.dpi_tab, "灵敏度", "Sensitivity"), (self.key_tab, "四个侧键", "Side buttons"),
                           (self.stick_tab, "侧面摇杆", "Thumb joystick"), (self.light_tab, "灯效", "Lighting")]
        for frame, zh, en in self.tab_titles:
            self.tabs.add(frame, text=T(zh, en))
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
        for col, title in enumerate((("档位", "Stage"), ("鼠标回读 X / Y", "Device X / Y"), ("新 DPI", "New DPI"))):
            bind_text(ttk.Label(f), *title).grid(row=0, column=col, padx=6, sticky="w")
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
            bind_text(ttk.Button(f, command=lambda idx=i: self.set_dpi(idx)), "保存数值", "Save value").grid(row=n, column=3, padx=4)
            activate = ttk.Button(f, text=T("启用此档", "Activate stage"), command=lambda slot=n: self.select_dpi(slot))
            activate.grid(row=n, column=4, padx=4)
            self.activate_buttons.append(activate)
        style = ttk.Style(f)
        style.configure("ActiveDpi.TFrame", background="#D8EBF9")
        style.configure("ActiveDpi.TLabel", background="#D8EBF9", foreground="#114F7D",
                        font=("Microsoft YaHei UI", 10, "bold"))
        bind_text(ttk.Label(f), "输入 100 至 36000，步进为 50。保存后，X 轴和 Y 轴使用相同 DPI。",
                  "Enter 100–36,000 in steps of 50. Saving sets the same DPI on both axes.").grid(
            row=5, column=0, columnspan=5, sticky="w", pady=(14, 0))

    def action_box(self, frame, row, name, column=1):
        ttk.Label(frame, text=name, width=12).grid(row=row, column=0, sticky="w", pady=5)
        var = tk.StringVar()
        box = ttk.Combobox(frame, values=list(self.labels_to_actions), textvariable=var,
                           width=25, state="readonly", height=16)
        box.grid(row=row, column=column, padx=10, pady=5)
        self.action_boxes.append((box, var))
        return var

    def _side_layout(self):
        for column, labels in enumerate((("侧键", "Button"), ("当前生效", "Active binding"), ("设置为", "Set to"))):
            bind_text(ttk.Label(self.key_tab), *labels).grid(row=0, column=column, sticky="w", padx=(0, 6))
        for i, button in enumerate(SIDE_BUTTON_SLOTS, 1):
            self.key_vars[button.slot] = self.action_box(self.key_tab, i, button.name, column=2)
            label, = self.key_tab.grid_slaves(row=i, column=0)
            bind_text(label, button_label(button, "zh"), button_label(button, "en"))
            active = ttk.Label(self.key_tab, width=19, anchor="w")
            active.grid(row=i, column=1, sticky="w")
            self.key_actual[button.slot] = active
            bind_text(ttk.Button(self.key_tab, command=lambda slot=button.slot: self.set_button(slot)), "保存按键", "Save binding").grid(
                row=i, column=3, padx=6)

    def _stick_layout(self):
        from stick_ui import StickPanel
        self.stick = StickPanel(self, self.stick_tab)

    def change_language(self, event=None):
        old = get_language()
        new = next(code for code, name in LANGUAGES.items() if name == self.language.get())
        try:
            save_language(new)
        except OSError as exc:
            self.language.set(LANGUAGES[old])
            messagebox.showerror(T("无法保存语言", "Could not save language"), str(exc), parent=self.root)
            return
        old_actions = self.labels_to_actions.copy()
        if self.current:
            for code in self.current.buttons.values():
                old_actions[action_label(code)] = code
        set_language(new)
        self.root.title(T("Chakram X 鼠标配置", "Chakram X Control"))
        refresh_text(self.root)
        for frame, zh, en in self.tab_titles:
            self.tabs.tab(frame, text=T(zh, en))
        self.labels_to_actions = {action_label(code): code for code in ACTIONS}
        for box, var in self.action_boxes:
            code = old_actions.get(var.get())
            box.configure(values=list(self.labels_to_actions))
            if code is not None:
                var.set(action_label(code))
        self.picker.configure(values=[f"{i + 1} · {d.label}" for i, d in enumerate(self.options)])
        if self.device in self.options:
            self.picker.current(self.options.index(self.device))
        self.update_profile_switch()
        if self.current:
            self.render_snapshot(self.current, keep_edits=True)
        else:
            self.summary.configure(text=T("当前状态未知", "Device state unknown"))
        self.stick.retranslate(old)
        self.lighting.retranslate(old)
        self.status.set(T("界面语言已保存。", "Language preference saved.") if self.current else
                        T("请连接鼠标并刷新设备。", "Connect the mouse and refresh devices."))

    def enable(self, connected):
        for tab in (self.dpi_tab, self.key_tab, self.stick_tab, self.light_tab):
            self.tabs.tab(tab, state="normal" if connected else "disabled")
        if connected and not self.tabs.select():
            self.tabs.select(self.dpi_tab)
        self.profile_picker.configure(state="readonly" if connected else "disabled")
        self.update_profile_switch()

    def update_profile_switch(self, *_):
        same = self.current is not None and self.profile.get() == str(self.current.state.profile)
        self.switch.configure(text=T("使用中", "Active") if same else T("切换预设", "Switch profile"),
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
        self.summary.configure(text=T("当前预设 {profile}    ·    档位 {slot}    ·    {dpi} DPI", "Profile {profile}    ·    Stage {slot}    ·    {dpi} DPI", profile=state.state.profile, slot=slot, dpi=dpi_text))
        for i, item in enumerate(state.dpi):
            selected = slot == i + 1
            self.row_bands[i].configure(style="ActiveDpi.TFrame" if selected else "TFrame")
            style = "ActiveDpi.TLabel" if selected else "TLabel"
            self.slot_labels[i].configure(style=style)
            self.actual[i].configure(text=f"{item.x} / {item.y}", style=style)
            self.activate_buttons[i].configure(text=T("使用中", "Active") if selected else T("启用此档", "Activate stage"),
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
                self.status.set(T("鼠标已重新连接。", "Mouse reconnected.") if reconnect else T("鼠标已切换到预设 {profile}。", "Mouse switched to profile {profile}.", profile=state.state.profile))
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
        self.summary.configure(text=T("当前状态未知", "Device state unknown"))
        self.status.set(T("{error} 请刷新设备后重试。", "{error} Refresh devices and try again.", error=error))

    def refresh(self, selected=None, notice=""):
        try:
            old = self.device
            self.options = devices()
            self.picker.configure(values=[f"{i + 1} · {d.label}" for i, d in enumerate(self.options)])
            if not self.options:
                raise RuntimeError(T("未发现 Chakram X。请连接 USB 线或 2.4 GHz 接收器，然后刷新。", "No Chakram X found. Connect the USB cable or 2.4 GHz receiver, then refresh."))
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
            self.status.set(notice or T("当前数据来自鼠标。", "Showing settings read from the mouse."))
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
                    raise RuntimeError(T("鼠标的活动预设发生了变化，请核对刷新后的设置。", "The active profile changed. Review the refreshed settings."))
                operation(tr)
        except (OSError, RuntimeError, ValueError) as exc:
            self.refresh()
            messagebox.showerror(T("配置未确认", "Settings not confirmed"), str(exc), parent=self.root)
            return
        self.refresh(notice=notice)

    def change_profile(self):
        target = int(self.profile.get())
        if target != self.current.state.profile:
            self.run(lambda tr: ButtonController(tr).select_profile(target, expected_profile=self.current.state.profile),
                     T("已切换到板载预设 {target}。", "Switched to onboard profile {target}.", target=target))

    def set_dpi(self, index):
        try:
            dpi = int(self.entries[index].get())
        except ValueError:
            messagebox.showerror(T("DPI 输入有误", "Invalid DPI"), T("请输入整数 DPI。", "Enter a whole number for DPI."), parent=self.root)
            return
        def apply(tr):
            perf = Performance(tr)
            if perf.read_dpi()[index] != self.current.dpi[index]:
                raise RuntimeError(T("这个档位自读取后发生了变化，请核对最新数值。", "This stage changed. Review the latest DPI value."))
            if (self.current.dpi[index].x, self.current.dpi[index].y) != (dpi, dpi):
                perf.set_dpi(index + 1, dpi, expected_profile=self.current.state.profile)
        self.run(apply, T("档位 {stage} 的设备回读为 {dpi} DPI。", "Stage {stage} reads {dpi} DPI.", stage=index + 1, dpi=dpi))

    def select_dpi(self, slot):
        self.run(lambda tr: Performance(tr).select_dpi(slot, expected_profile=self.current.state.profile),
                 T("当前使用 DPI 档位 {slot}。", "DPI stage {slot} is active.", slot=slot))

    def set_button(self, slot):
        label = self.key_vars[slot].get()
        if label == action_label(self.current.buttons[slot]):
            return
        def apply(tr):
            controller = ButtonController(tr)
            if controller.read_binding(slot) != self.current.buttons[slot]:
                raise RuntimeError(T("这个侧键自读取后发生了变化，请核对最新映射。", "This binding changed. Review the latest assignment."))
            controller.set_button(slot, self.labels_to_actions[label], expected_profile=self.current.state.profile)
        self.run(apply, T("侧键映射已保存并回读为 {label}。", "Saved and verified the side button binding: {label}.", label=label))


def main():
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
    set_language(load_language())
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
