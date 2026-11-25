from dataclasses import dataclass
import re
import tkinter as tk
from tkinter import colorchooser, messagebox, ttk

from device import configuration_session
from lighting import EFFECTS, SPEEDS, ZONE_EFFECTS, Lighting
from performance import Performance


ZONES = {"all": "全部灯区", "logo": "徽标", "wheel": "滚轮", "front": "前端灯带"}
ALL = EFFECTS
COMMON = {code: ALL[code] for code in ZONE_EFFECTS}
USES_COLOR = {0, 1, 4, 5}


@dataclass
class LightingDraft:
    values: tuple
    baseline: dict
    clean_values: tuple


class LightingPanel:
    def __init__(self, editor, frame):
        self.editor = editor
        self.frame = frame
        self.zones = None
        self.context = None
        self.drafts = {}
        self._loading_form = False
        self._editing_baseline = {}
        self._clean_values = ()
        self._shown_zone = None
        self.zone = tk.StringVar(value="logo")
        self.effect = tk.StringVar()
        self.brightness = tk.StringVar()
        self.color = tk.StringVar()
        self.direction = tk.StringVar()
        self.speed = tk.StringVar()
        self.random_color = tk.BooleanVar()
        self.summary = tk.StringVar(value="等待鼠标回读。")
        self.draft_status = tk.StringVar(value="编辑灯效后可保存到当前预设。")

        live = ttk.LabelFrame(frame, text="当前生效灯效", padding=10)
        live.pack(fill="x", pady=(0, 12))
        for column, caption in enumerate(("灯区", "效果", "亮度", "颜色", "动画设置")):
            ttk.Label(live, text=caption).grid(row=0, column=column, sticky="w", padx=(0, 16), pady=(0, 5))
        self.actual = {}
        self.swatches = {}
        for row, key in enumerate(("logo", "wheel", "front"), 1):
            ttk.Label(live, text=ZONES[key], width=9).grid(row=row, column=0, sticky="w", pady=4)
            fields = {name: tk.StringVar(value="—") for name in ("effect", "brightness", "color", "animation")}
            self.actual[key] = fields
            ttk.Label(live, textvariable=fields["effect"], width=12).grid(row=row, column=1, sticky="w", padx=(0, 16))
            ttk.Label(live, textvariable=fields["brightness"], width=7).grid(row=row, column=2, sticky="w", padx=(0, 16))
            color_cell = ttk.Frame(live)
            color_cell.grid(row=row, column=3, sticky="w", padx=(0, 16))
            swatch = tk.Canvas(color_cell, width=16, height=16, highlightthickness=0)
            swatch.pack(side="left", padx=(0, 5))
            swatch.create_rectangle(1, 1, 15, 15, outline="#999999", fill="#E5E7EB", tags="sample")
            self.swatches[key] = swatch
            ttk.Label(color_cell, textvariable=fields["color"], width=18).pack(side="left")
            ttk.Label(live, textvariable=fields["animation"]).grid(row=row, column=4, sticky="w")
        ttk.Label(live, textvariable=self.summary).grid(row=4, column=0, columnspan=5, sticky="w", pady=(6, 0))

        edit = ttk.LabelFrame(frame, text="编辑灯效", padding=10)
        edit.pack(fill="x")
        bar = ttk.Frame(edit)
        bar.pack(anchor="w")
        for key, name in ZONES.items():
            ttk.Radiobutton(bar, variable=self.zone, value=key, text=name, command=self.select_zone).pack(
                side="left", padx=(0, 14))
        ttk.Separator(edit).pack(fill="x", pady=10)
        form = ttk.Frame(edit)
        form.pack(anchor="w")
        for i, caption in enumerate(("效果", "亮度", "颜色")):
            ttk.Label(form, text=caption, width=8).grid(row=i, column=0, sticky="w", pady=4)
        self.effects = ttk.Combobox(form, textvariable=self.effect, state="readonly", width=17)
        self.effects.grid(row=0, column=1, sticky="w")
        self.effects.bind("<<ComboboxSelected>>", self.choose_effect)
        self.level = ttk.Combobox(form, textvariable=self.brightness, state="readonly", width=17,
                                  values=("0%", "25%", "50%", "75%", "100%"))
        self.level.grid(row=1, column=1, sticky="w")
        self.hex_entry = ttk.Entry(form, textvariable=self.color, width=19)
        self.hex_entry.grid(row=2, column=1, sticky="w")
        self.pick = ttk.Button(form, text="选择颜色…", command=self.choose_color)
        self.pick.grid(row=2, column=2, padx=6)
        self.animation = ttk.Frame(form)
        self.animation.grid(row=3, column=0, columnspan=3, sticky="w", pady=3)
        ttk.Label(self.animation, text="方向").pack(side="left")
        ttk.Combobox(self.animation, textvariable=self.direction, state="readonly", width=7,
                     values=("顺时针", "逆时针")).pack(side="left", padx=5)
        self.speed_box = ttk.Combobox(self.animation, textvariable=self.speed, values=list(SPEEDS.values()),
                                      state="readonly", width=5)
        self.speed_label = ttk.Label(self.animation, text="速度")
        self.random_box = ttk.Checkbutton(self.animation, text="随机颜色", variable=self.random_color)
        actions = ttk.Frame(edit)
        actions.pack(anchor="w", pady=(10, 3))
        self.save = ttk.Button(actions, text="保存到当前预设", command=self.apply)
        self.save.pack(side="left")
        self.reload_zone = ttk.Button(actions, text="重新载入当前灯区", command=self.reset_draft)
        self.reload_zone.pack(side="left", padx=8)
        ttk.Label(edit, textvariable=self.draft_status, wraplength=720, justify="left").pack(anchor="w", pady=(3, 0))
        self.last_effect = ""
        for variable in self._form_variables():
            variable.trace_add("write", self._form_changed)
        self.select_zone()

    def _form_variables(self):
        return (self.effect, self.brightness, self.color, self.direction, self.speed, self.random_color)

    def _form_values(self):
        return tuple(variable.get() for variable in self._form_variables())

    def _current_context(self):
        if self.editor.current is None or self.editor.device is None:
            return None
        return self.editor.device, self.editor.current.state.profile

    def load(self, preserve_draft=False):
        context = self._current_context()
        same_context = context == self.context
        before = self.zones
        if not preserve_draft or not same_context:
            self.drafts.clear()
        self.context = context
        try:
            if context is None:
                raise RuntimeError("鼠标尚未连接。")
            with configuration_session(self.editor.device) as tr:
                current = Performance(tr).read_state().profile
                if current != context[1]:
                    raise RuntimeError("活动预设发生变化，请刷新设备。")
                zones = Lighting(tr).read_lighting()
                if Performance(tr).read_state().profile != current:
                    raise RuntimeError("读取灯效期间预设发生变化，请刷新设备。")
            self.zones = zones
            self.summary.set(f"当前预设 {current}，数据来自鼠标回读。")
        except (OSError, ValueError, RuntimeError) as exc:
            self.zones = None
            self.summary.set(f"灯效读取失败。{exc}")
        self._show_actual()
        zone = self.zone.get()
        unchanged = before is not None and self.zones is not None and all(
            before[key] == self.zones[key] for key in self._relevant_zones(zone)
        )
        keep_form = (
            preserve_draft and same_context and self._shown_zone == zone
            and self.zones is not None and (zone in self.drafts or unchanged)
        )
        if keep_form:
            self._update_draft_status()
        else:
            self.select_zone()

    @staticmethod
    def format_color(color):
        return "#{:02X}{:02X}{:02X}".format(*color)

    @classmethod
    def current_color(cls, item):
        if item.mode == 240 or item.brightness == 0:
            return "未点亮", None
        if item.mode in (2, 3):
            return "动态颜色", None
        if item.mode == 6:
            return "随电量变化", None
        if item.mode == 5 and item.random == 1:
            return "随机颜色", None
        if item.mode in USES_COLOR:
            color = cls.format_color(item.color)
            return (color if item.mode == 0 else f"基色 {color}"), color
        return "由当前效果控制", None

    @staticmethod
    def current_animation(item):
        direction = {0: "顺时针", 1: "逆时针"}.get(item.direction, f"方向 {item.direction}")
        if item.mode == 3:
            speed = SPEEDS.get(item.speed, "默认" if item.speed == 0 else str(item.speed))
            return f"{direction}，速度{speed}"
        if item.mode == 5:
            color = "随机颜色" if item.random == 1 else "固定基色"
            return f"{direction}，{color}"
        return {1: "亮度随呼吸变化", 2: "颜色自动变化", 4: "按键触发", 6: "随电量变化"}.get(item.mode, "—")

    def _show_actual(self):
        for key, fields in self.actual.items():
            item = self.zones[key] if self.zones else None
            fields["effect"].set(ALL.get(item.mode, f"效果 0x{item.mode:02X}") if item else "—")
            fields["brightness"].set(("—" if item.mode == 240 else f"{item.brightness}%") if item else "—")
            label, color = self.current_color(item) if item else ("—", None)
            fields["color"].set(label)
            fields["animation"].set(self.current_animation(item) if item else "—")
            self.swatches[key].itemconfigure(
                "sample", fill=color or "#E5E7EB", state="normal" if color else "hidden",
            )

    def _relevant_zones(self, zone):
        return ("logo", "wheel", "front") if zone == "all" else (zone,)

    def select_zone(self):
        zone = self.zone.get()
        self._shown_zone = zone
        modes = ALL if zone == "all" else COMMON
        self.effects.configure(values=tuple(modes.values()))
        draft = self.drafts.get(zone)
        item = None
        if self.zones:
            if zone != "all":
                item = self.zones[zone]
            elif len(set(self.zones.values())) == 1:
                item = self.zones["logo"]
        values = (
            ALL.get(item.mode, "") if item else "",
            f"{item.brightness}%" if item else "100%",
            self.format_color(item.color) if item else "#FF2020",
            "逆时针" if item and item.direction == 1 else "顺时针",
            SPEEDS.get(item.speed, "中") if item else "中",
            bool(item and item.random == 1),
        )
        self._clean_values = draft.clean_values if draft else values
        if draft:
            self._editing_baseline = draft.baseline.copy()
        else:
            self._editing_baseline = {key: self.zones[key] for key in self._relevant_zones(zone)} if self.zones else {}
        self._loading_form = True
        try:
            for variable, value in zip(self._form_variables(), draft.values if draft else values):
                variable.set(value)
        finally:
            self._loading_form = False
        self.last_effect = self.effect.get()
        self.edit_effect()

    def _form_changed(self, *_):
        if self._loading_form:
            return
        zone = self.zone.get()
        values = self._form_values()
        if values == self._clean_values:
            self.drafts.pop(zone, None)
        else:
            self.drafts[zone] = LightingDraft(values, self._editing_baseline.copy(), self._clean_values)
        self.edit_effect()

    def _has_conflict(self):
        draft = self.drafts.get(self.zone.get())
        return bool(draft and self.zones and any(self.zones[key] != item for key, item in draft.baseline.items()))

    def reset_draft(self):
        self.drafts.pop(self.zone.get(), None)
        self.select_zone()

    def choose_effect(self, event=None):
        if self.last_effect == ALL[240] and self.effect.get() != self.last_effect:
            if self.brightness.get() == "0%":
                self.brightness.set("100%")
            if self.color.get() == "#000000":
                self.color.set("#FF2020")
        self.last_effect = self.effect.get()
        self.edit_effect()

    def edit_effect(self):
        modes = ALL if self.zone.get() == "all" else COMMON
        code = next((k for k, name in modes.items() if name == self.effect.get()), None)
        ready = self.zones is not None
        self.effects.configure(state="readonly" if ready else "disabled")
        self.level.configure(state="readonly" if ready and code != 240 else "disabled")
        color_state = "normal" if ready and code in USES_COLOR and not (code == 5 and self.random_color.get()) else "disabled"
        self.animation.grid_remove()
        for widget in (self.speed_label, self.speed_box, self.random_box):
            widget.pack_forget()
        if code in (3, 5):
            self.animation.grid()
            if code == 3:
                self.speed_label.pack(side="left")
                self.speed_box.pack(side="left", padx=5)
            else:
                self.random_box.pack(side="left")
        self.hex_entry.configure(state=color_state)
        self.pick.configure(state=color_state)
        self._update_draft_status()

    def _update_draft_status(self):
        modes = ALL if self.zone.get() == "all" else COMMON
        code = next((k for k, name in modes.items() if name == self.effect.get()), None)
        ready = self.zones is not None
        dirty = self.zone.get() in self.drafts
        conflict = self._has_conflict()
        self.save.configure(state="normal" if ready and code is not None and dirty and not conflict else "disabled")
        self.reload_zone.configure(state="normal" if ready and dirty else "disabled")
        if not ready:
            self.draft_status.set("等待有效的鼠标回读，草稿暂时保留。" if dirty else "等待有效的鼠标回读。")
        elif conflict:
            self.draft_status.set("当前灯区的生效设置发生变化。草稿保留，请重新载入当前灯区后编辑。")
        elif dirty:
            self.draft_status.set("草稿待保存，保存后应用到鼠标。")
        elif code is None and self.zone.get() == "all":
            self.draft_status.set("三个灯区的当前设置不同。选择效果、亮度和颜色后可统一保存。")
        elif code is None:
            self.draft_status.set("选择受支持的效果后可编辑，彩虹、彗星和电量效果通过全部灯区编辑。")
        else:
            self.draft_status.set("编辑区与当前回读一致。")

    def choose_color(self):
        initial = self.color.get()
        result = colorchooser.askcolor(color=initial if re.fullmatch(r"#[0-9A-Fa-f]{6}", initial) else "#FFFFFF",
                                       parent=self.frame, title="选择灯光颜色")[1]
        if result:
            self.color.set(result.upper())

    def apply(self):
        if not self.zones or self.zone.get() not in self.drafts:
            return
        if self._current_context() != self.context:
            self.load()
            return
        if self._has_conflict():
            messagebox.showerror("灯效已变化", "当前灯区的生效设置发生变化，请重新载入当前灯区后编辑。", parent=self.frame)
            return
        zone = self.zone.get()
        modes = ALL if zone == "all" else COMMON
        mode = next((k for k, v in modes.items() if v == self.effect.get()), None)
        if mode is None:
            return
        color = None
        if mode in USES_COLOR and not (mode == 5 and self.random_color.get()):
            value = self.color.get().strip()
            if not re.fullmatch(r"#?[0-9A-Fa-f]{6}", value):
                messagebox.showerror("颜色格式", "请输入六位十六进制颜色，如 #FF2020。", parent=self.frame)
                return
            color = tuple(bytes.fromhex(value.lstrip("#")))
        elif zone == "all":
            color = (0, 0, 0)
        try:
            level = int(self.brightness.get().rstrip("%"))
            options = {}
            if mode in (3, 5):
                options["direction"] = int(self.direction.get() == "逆时针")
            if mode == 3:
                options["speed"] = next(k for k, label in SPEEDS.items() if label == self.speed.get())
            if mode == 5:
                options["random"] = int(self.random_color.get())
        except (ValueError, StopIteration):
            messagebox.showerror("灯效参数", "请选择有效的亮度和动画速度。", parent=self.frame)
            return
        baseline = self.drafts[zone].baseline.copy()
        profile = self.context[1]

        def write(tr):
            light = Lighting(tr)
            actual = light.read_lighting()
            if any(actual[key] != item for key, item in baseline.items()):
                raise RuntimeError("灯效自编辑开始后发生变化，请核对刷新后的设置。")
            confirmed = light.set_lighting(zone, mode=mode, brightness=level, color=color,
                                           expected_profile=profile, persist=True, **options)
            self.drafts.pop(zone, None)
            self.zones = confirmed
            self._show_actual()
            self.select_zone()

        self.editor.run(write, f"{ZONES[zone]}的灯效已保存并通过鼠标回读校验。")
