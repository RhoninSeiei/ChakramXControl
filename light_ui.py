from dataclasses import dataclass
import re
import tkinter as tk
from tkinter import colorchooser, messagebox, ttk

from device import configuration_session
from lighting import EFFECTS, SPEEDS, ZONE_EFFECTS, Lighting, effect_label, effect_names, speed_names
from i18n import bind_text, get_language, refresh_text, tr
from performance import Performance


ZONES = {"all": "全部灯区", "logo": "徽标", "wheel": "滚轮", "front": "前端灯带"}
USES_COLOR = {0, 1, 4, 5}
ZONE_LABELS = {
    "all": ("全部灯区", "All zones"), "logo": ("徽标", "Logo"),
    "wheel": ("滚轮", "Scroll wheel"), "front": ("前端灯带", "Front strip"),
}


def zone_name(zone):
    return tr(*ZONE_LABELS[zone])


def direction_names(language=None):
    return {0: "顺时针", 1: "逆时针"} if (language or get_language()) == "zh" else {
        0: "Clockwise", 1: "Counterclockwise",
    }


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
        self.summary = tk.StringVar(value=tr("等待鼠标回读。", "Waiting for mouse readback."))
        self.draft_status = tk.StringVar(value=tr("编辑灯效后可保存到当前预设。", "Edit lighting, then save it to the current profile."))

        live = bind_text(ttk.LabelFrame(frame, padding=10), '当前生效灯效', 'Current lighting')
        live.pack(fill="x", pady=(0, 12))
        for column, caption in enumerate((("灯区", "Zone"), ("效果", "Effect"), ("亮度", "Brightness"), ("颜色", "Color"), ("动画设置", "Animation"))):
            bind_text(ttk.Label(live), *caption).grid(row=0, column=column, sticky="w", padx=(0, 16), pady=(0, 5))
        self.actual = {}
        self.swatches = {}
        for row, key in enumerate(("logo", "wheel", "front"), 1):
            bind_text(ttk.Label(live, width=12), *ZONE_LABELS[key]).grid(row=row, column=0, sticky="w", pady=4)
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

        edit = bind_text(ttk.LabelFrame(frame, padding=10), '编辑灯效', 'Edit lighting')
        edit.pack(fill="x")
        bar = ttk.Frame(edit)
        bar.pack(anchor="w")
        for key in ZONES:
            bind_text(ttk.Radiobutton(bar, variable=self.zone, value=key, command=self.select_zone), *ZONE_LABELS[key]).pack(
                side="left", padx=(0, 14))
        ttk.Separator(edit).pack(fill="x", pady=10)
        form = ttk.Frame(edit)
        form.pack(anchor="w")
        for i, caption in enumerate((("效果", "Effect"), ("亮度", "Brightness"), ("颜色", "Color"))):
            bind_text(ttk.Label(form, width=12), *caption).grid(row=i, column=0, sticky="w", pady=4)
        self.effects = ttk.Combobox(form, textvariable=self.effect, state="readonly", width=17)
        self.effects.grid(row=0, column=1, sticky="w")
        self.effects.bind("<<ComboboxSelected>>", self.choose_effect)
        self.level = ttk.Combobox(form, textvariable=self.brightness, state="readonly", width=17,
                                  values=("0%", "25%", "50%", "75%", "100%"))
        self.level.grid(row=1, column=1, sticky="w")
        self.hex_entry = ttk.Entry(form, textvariable=self.color, width=19)
        self.hex_entry.grid(row=2, column=1, sticky="w")
        self.pick = bind_text(ttk.Button(form, command=self.choose_color), '选择颜色…', 'Choose color…')
        self.pick.grid(row=2, column=2, padx=6)
        self.animation = ttk.Frame(form)
        self.animation.grid(row=3, column=0, columnspan=3, sticky="w", pady=3)
        bind_text(ttk.Label(self.animation), '方向', 'Direction').pack(side="left")
        self.direction_box = ttk.Combobox(self.animation, textvariable=self.direction, state="readonly", width=18,
                                         values=tuple(direction_names().values()))
        self.direction_box.pack(side="left", padx=5)
        self.speed_box = ttk.Combobox(self.animation, textvariable=self.speed, values=list(speed_names().values()),
                                      state="readonly", width=9)
        self.speed_label = bind_text(ttk.Label(self.animation), '速度', 'Speed')
        self.random_box = bind_text(ttk.Checkbutton(self.animation, variable=self.random_color), '随机颜色', 'Random color')
        actions = ttk.Frame(edit)
        actions.pack(anchor="w", pady=(10, 3))
        self.save = bind_text(ttk.Button(actions, command=self.apply), '保存到当前预设', 'Save to current profile')
        self.save.pack(side="left")
        self.reload_zone = bind_text(ttk.Button(actions, command=self.reset_draft), '重新载入当前灯区', 'Reload selected zone')
        self.reload_zone.pack(side="left", padx=8)
        ttk.Label(edit, textvariable=self.draft_status, wraplength=720, justify="left").pack(anchor="w", pady=(3, 0))
        self.last_effect = None
        self._load_error = None
        for variable in self._form_variables():
            variable.trace_add("write", self._form_changed)
        self.select_zone()

    def _form_variables(self):
        return (self.effect, self.brightness, self.color, self.direction, self.speed, self.random_color)

    def _form_values(self, language=None):
        values = [variable.get() for variable in self._form_variables()]
        # Drafts contain wire codes, so translating labels never changes inputs.
        for index, names in ((0, effect_names(language)), (3, direction_names(language)),
                             (4, speed_names(language))):
            values[index] = next((code for code, label in names.items() if label == values[index]), values[index])
        return tuple(values)

    def _set_form_values(self, values):
        display = list(values)
        for index, names in ((0, effect_names()), (3, direction_names()), (4, speed_names())):
            display[index] = names.get(display[index], display[index])
        self._loading_form = True
        try:
            for variable, value in zip(self._form_variables(), display):
                if variable.get() != value:
                    variable.set(value)
        finally:
            self._loading_form = False

    def _mode_names(self):
        names = effect_names()
        return names if self.zone.get() == "all" else {code: names[code] for code in ZONE_EFFECTS}

    def retranslate(self, old_language):
        values = self._form_values(old_language)
        refresh_text(self.frame)
        self.effects.configure(values=tuple(self._mode_names().values()))
        self.direction_box.configure(values=tuple(direction_names().values()))
        self.speed_box.configure(values=tuple(speed_names().values()))
        self._set_form_values(values)
        self.last_effect = values[0]
        self._show_actual()
        self._update_summary()
        self.edit_effect()

    def _update_summary(self):
        if self.zones is not None:
            self.summary.set(tr("当前预设 {profile}，数据来自鼠标回读。",
                                "Profile {profile}, read back from the mouse.", profile=self.context[1]))
        elif self._load_error is not None:
            self.summary.set(tr("灯效读取失败。{error}", "Lighting read failed. {error}", error=self._load_error))
        else:
            self.summary.set(tr("等待鼠标回读。", "Waiting for mouse readback."))

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
                raise RuntimeError(tr("鼠标尚未连接。", "The mouse is not connected."))
            with configuration_session(self.editor.device) as transport:
                current = Performance(transport).read_state().profile
                if current != context[1]:
                    raise RuntimeError(tr("活动预设发生变化，请刷新设备。", "The active profile changed. Refresh the device."))
                zones = Lighting(transport).read_lighting()
                if Performance(transport).read_state().profile != current:
                    raise RuntimeError(tr("读取灯效期间预设发生变化，请刷新设备。", "The profile changed while reading lighting. Refresh the device."))
            self.zones = zones
            self._load_error = None
        except (OSError, ValueError, RuntimeError) as exc:
            self.zones = None
            self._load_error = exc
        self._show_actual()
        self._update_summary()
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
            return tr("未点亮", "Not lit"), None
        if item.mode in (2, 3):
            return tr("动态颜色", "Dynamic colors"), None
        if item.mode == 6:
            return tr("随电量变化", "Battery-dependent"), None
        if item.mode == 5 and item.random == 1:
            return tr("随机颜色", "Random colors"), None
        if item.mode in USES_COLOR:
            color = cls.format_color(item.color)
            return (color if item.mode == 0 else tr("基色 {color}", "Base {color}", color=color)), color
        return tr("由当前效果控制", "Effect-controlled"), None

    @staticmethod
    def current_animation(item):
        direction = direction_names().get(item.direction, tr("方向 {value}", "Direction {value}", value=item.direction))
        if item.mode == 3:
            speed = speed_names().get(item.speed, tr("默认", "Default") if item.speed == 0 else str(item.speed))
            return tr("{direction}，速度{speed}", "{direction}, {speed} speed", direction=direction, speed=speed)
        if item.mode == 5:
            color = tr("随机颜色", "Random colors") if item.random == 1 else tr("固定基色", "Fixed base color")
            return tr("{direction}，{color}", "{direction}, {color}", direction=direction, color=color)
        return {
            1: tr("亮度随呼吸变化", "Pulsing brightness"),
            2: tr("颜色自动变化", "Automatic color cycle"),
            4: tr("按键触发", "Button-triggered"),
            6: tr("随电量变化", "Battery-dependent"),
        }.get(item.mode, "—")

    def _show_actual(self):
        for key, fields in self.actual.items():
            item = self.zones[key] if self.zones else None
            fields["effect"].set(effect_label(item.mode) if item else "—")
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
        modes = self._mode_names()
        self.effects.configure(values=tuple(modes.values()))
        draft = self.drafts.get(zone)
        item = None
        if self.zones:
            if zone != "all":
                item = self.zones[zone]
            elif len(set(self.zones.values())) == 1:
                item = self.zones["logo"]
        values = (
            item.mode if item and item.mode in EFFECTS else "",
            f"{item.brightness}%" if item else "100%",
            self.format_color(item.color) if item else "#FF2020",
            1 if item and item.direction == 1 else 0,
            item.speed if item and item.speed in SPEEDS else 7,
            bool(item and item.random == 1),
        )
        self._clean_values = draft.clean_values if draft else values
        if draft:
            self._editing_baseline = draft.baseline.copy()
        else:
            self._editing_baseline = {key: self.zones[key] for key in self._relevant_zones(zone)} if self.zones else {}
        self._set_form_values(draft.values if draft else values)
        self.last_effect = self._form_values()[0]
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
        if self.last_effect == 240 and self._form_values()[0] != self.last_effect:
            if self.brightness.get() == "0%":
                self.brightness.set("100%")
            if self.color.get() == "#000000":
                self.color.set("#FF2020")
        self.last_effect = self._form_values()[0]
        self.edit_effect()

    def edit_effect(self):
        modes = self._mode_names()
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
        modes = self._mode_names()
        code = next((k for k, name in modes.items() if name == self.effect.get()), None)
        ready = self.zones is not None
        dirty = self.zone.get() in self.drafts
        conflict = self._has_conflict()
        self.save.configure(state="normal" if ready and code is not None and dirty and not conflict else "disabled")
        self.reload_zone.configure(state="normal" if ready and dirty else "disabled")
        if not ready:
            self.draft_status.set(tr('等待有效的鼠标回读，草稿暂时保留。', 'Waiting for valid mouse readback. The draft is retained.') if dirty else tr('等待有效的鼠标回读。', 'Waiting for valid mouse readback.'))
        elif conflict:
            self.draft_status.set(tr('当前灯区的生效设置发生变化。草稿保留，请重新载入当前灯区后编辑。', 'This zone changed on the mouse. The draft is retained. Reload the selected zone before editing.'))
        elif dirty:
            self.draft_status.set(tr('草稿待保存，保存后应用到鼠标。', 'Unsaved draft. Save to apply it to the mouse.'))
        elif code is None and self.zone.get() == "all":
            self.draft_status.set(tr('三个灯区的当前设置不同。选择效果、亮度和颜色后可统一保存。', 'The three zones have different settings. Select an effect, brightness, and color to apply to all zones.'))
        elif code is None:
            self.draft_status.set(tr('选择受支持的效果后可编辑，彩虹、彗星和电量效果通过全部灯区编辑。', 'Select a supported effect to edit. Use All zones for Rainbow, Comet, and Battery effects.'))
        else:
            self.draft_status.set(tr('编辑区与当前回读一致。', 'The editor matches the current mouse readback.'))

    def choose_color(self):
        initial = self.color.get()
        result = colorchooser.askcolor(color=initial if re.fullmatch(r"#[0-9A-Fa-f]{6}", initial) else "#FFFFFF",
                                       parent=self.frame, title=tr('选择灯光颜色', 'Choose lighting color'))[1]
        if result:
            self.color.set(result.upper())

    def apply(self):
        if not self.zones or self.zone.get() not in self.drafts:
            return
        if self._current_context() != self.context:
            self.load()
            return
        if self._has_conflict():
            messagebox.showerror(tr('灯效已变化', 'Lighting changed'), tr('当前灯区的生效设置发生变化，请重新载入当前灯区后编辑。', 'This zone changed on the mouse. Reload the selected zone before editing.'), parent=self.frame)
            return
        zone = self.zone.get()
        modes = self._mode_names()
        mode = next((k for k, v in modes.items() if v == self.effect.get()), None)
        if mode is None:
            return
        color = None
        if mode in USES_COLOR and not (mode == 5 and self.random_color.get()):
            value = self.color.get().strip()
            if not re.fullmatch(r"#?[0-9A-Fa-f]{6}", value):
                messagebox.showerror(tr('颜色格式', 'Color format'), tr('请输入六位十六进制颜色，如 #FF2020。', 'Enter a six-digit hexadecimal color, such as #FF2020.'), parent=self.frame)
                return
            color = tuple(bytes.fromhex(value.lstrip("#")))
        elif zone == "all":
            color = (0, 0, 0)
        try:
            level = int(self.brightness.get().rstrip("%"))
            options = {}
            if mode in (3, 5):
                options["direction"] = self._form_values()[3]
            if mode == 3:
                options["speed"] = next(k for k, label in speed_names().items() if label == self.speed.get())
            if mode == 5:
                options["random"] = int(self.random_color.get())
        except (ValueError, StopIteration):
            messagebox.showerror(tr('灯效参数', 'Lighting settings'), tr('请选择有效的亮度和动画速度。', 'Select a valid brightness and animation speed.'), parent=self.frame)
            return
        baseline = self.drafts[zone].baseline.copy()
        profile = self.context[1]

        def write(transport):
            light = Lighting(transport)
            actual = light.read_lighting()
            if any(actual[key] != item for key, item in baseline.items()):
                raise RuntimeError(tr("灯效自编辑开始后发生变化，请核对刷新后的设置。", "Lighting changed after editing began. Check the refreshed settings."))
            confirmed = light.set_lighting(zone, mode=mode, brightness=level, color=color,
                                           expected_profile=profile, persist=True, **options)
            self.drafts.pop(zone, None)
            self.zones = confirmed
            self._show_actual()
            self.select_zone()

        self.editor.run(write, tr("{zone}的灯效已保存并通过鼠标回读校验。",
                                  "{zone} lighting was saved and verified by mouse readback.", zone=zone_name(zone)))
