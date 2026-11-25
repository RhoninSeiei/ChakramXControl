"""Direct RGB configuration for the tested ROG Chakram X firmware.

Wire definitions follow G-Helper AsusMouse.cs and the installed ASUS P708 HAL
setter at 0x10171e50. The local mouse was verified to return one light zone per
12 03 <zone> request, with a response selector fixed at zero. The older HAL's
single-response three-zone reader does not describe this firmware's responses.
https://github.com/seerge/g-helper/blob/a3c3ccae51f005d92d8d4ee161e6661ab511274d/app/Peripherals/Mouse/AsusMouse.cs

Requests and responses exclude the Windows report-ID byte. Brightness is an
integer percentage. All public profile numbers are one-based.
"""

from dataclasses import dataclass, replace
from typing import Protocol

from performance import Performance
from i18n import get_language, tr


class Transport(Protocol):
    def exchange(self, request: bytes) -> bytes: ...


class LightingError(RuntimeError):
    """The mouse rejected a request or failed lighting readback verification."""


ZONES = {"logo": 0, "wheel": 1, "front": 2, "all": 3}
ZONE_NAMES = {"logo": "Logo", "wheel": "滚轮", "front": "前端灯带", "all": "全部灯区"}
EFFECT_LABELS = {
    0x00: ("常亮", "Static"),
    0x01: ("呼吸", "Breathing"),
    0x02: ("颜色循环", "Color cycle"),
    0x04: ("触发", "Reactive"),
    0x03: ("彩虹", "Rainbow"),
    0x05: ("彗星", "Comet"),
    0x06: ("电量", "Battery"),
    0xF0: ("关闭", "Off"),
}
# Preserve the original Chinese dictionaries for existing callers. UI code
# resolves display labels from stable wire codes using the functions below.
EFFECTS = {code: labels[0] for code, labels in EFFECT_LABELS.items()}
ZONE_EFFECTS = (0x00, 0x01, 0x02, 0x04, 0xF0)
SPEED_LABELS = {5: ("快", "Fast"), 7: ("中", "Medium"), 9: ("慢", "Slow")}
SPEEDS = {code: labels[0] for code, labels in SPEED_LABELS.items()}


def effect_names(language=None):
    index = 0 if (language or get_language()) == "zh" else 1
    return {code: labels[index] for code, labels in EFFECT_LABELS.items()}


def speed_names(language=None):
    index = 0 if (language or get_language()) == "zh" else 1
    return {code: labels[index] for code, labels in SPEED_LABELS.items()}


@dataclass(frozen=True)
class LightSetting:
    mode: int
    brightness: int
    color: tuple[int, int, int]
    direction: int = 0
    random: int = 0
    speed: int = 0


def effect_label(mode: int) -> str:
    return effect_names().get(mode, tr("其他灯效 0x{mode:02X}", "Other effect 0x{mode:02X}", mode=mode))


def _integer(value: int, minimum: int, maximum: int, label: str) -> None:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(tr("{label}必须为 {minimum} 至 {maximum} 的整数。",
                            "{label} must be an integer from {minimum} to {maximum}.",
                            label=label, minimum=minimum, maximum=maximum))


class Lighting:
    def __init__(self, transport: Transport):
        self.transport = transport

    def _exchange(self, request: bytes, minimum_length: int = 2) -> bytes:
        response = bytes(self.transport.exchange(request))
        if len(response) < minimum_length or response[:2] != request[:2]:
            raise LightingError(tr("鼠标返回的灯光数据不完整或命令不匹配。", "The mouse returned incomplete lighting data or an unexpected command."))
        return response

    def read_zone(self, zone: str) -> LightSetting:
        if zone not in ZONES or zone == "all":
            raise ValueError(tr("读取灯区必须为 logo、wheel 或 front。", "The light zone to read must be logo, wheel, or front."))
        response = self._exchange(bytes((0x12, 0x03, ZONES[zone])), 13)
        brightness = response[5]
        if brightness > 100:
            raise LightingError(tr("鼠标返回无效的灯光亮度 {brightness}。",
                                   "The mouse returned invalid lighting brightness {brightness}.", brightness=brightness))
        # This firmware replies with selector 00 for every zone. Byte 9 is
        # reserved. Direction, random-color and speed follow at 10, 11 and 12.
        return LightSetting(
            response[4], brightness, tuple(response[6:9]),
            response[10], response[11], response[12],
        )

    def read_lighting(self) -> dict[str, LightSetting]:
        return {zone: self.read_zone(zone) for zone in ("logo", "wheel", "front")}

    def _check_profile(self, expected_profile: int) -> None:
        actual = Performance(self.transport).read_state().profile
        if actual != expected_profile:
            raise LightingError(tr("鼠标当前配置为 {profile}，请重新读取配置后再应用灯光。",
                                   "The active mouse profile is {profile}. Refresh before applying lighting.", profile=actual))

    @staticmethod
    def _packet(zone: str, setting: LightSetting) -> bytes:
        return bytes((
            0x51, 0x28, ZONES[zone], 0,
            setting.mode, setting.brightness, *setting.color,
            setting.direction, setting.random, setting.speed,
        ))

    def set_lighting(
        self, zone: str, *, mode: int | None = None,
        brightness: int | None = None, color: tuple[int, int, int] | None = None,
        direction: int | None = None, random: int | None = None,
        speed: int | None = None, expected_profile: int | None = None,
        persist: bool = False,
    ) -> dict[str, LightSetting]:
        """Modify one zone, or explicitly configure all zones by broadcast.

        Single-zone changes preserve unspecified fields and verify every zone.
        All-zone writes require mode, brightness and color. Advanced parameters
        use explicit defaults when omitted, avoiding inference from one zone.
        With persist=False the caller saves the verified volatile setting later.
        A failed write may have changed the active volatile configuration.
        """
        if zone not in ZONES:
            raise ValueError(tr("灯区必须为 logo、wheel、front 或 all。", "The light zone must be logo, wheel, front, or all."))
        if mode is not None:
            if type(mode) is not int or mode not in EFFECTS:
                raise ValueError(tr("灯效不在当前支持范围内。", "This lighting effect is unsupported."))
            if zone != "all" and mode not in ZONE_EFFECTS:
                raise ValueError(tr("彩虹、彗星和电量效果需要应用到全部灯区。", "Rainbow, Comet, and Battery effects must be applied to all zones."))
        if brightness is not None:
            _integer(brightness, 0, 100, tr("灯光亮度", "Brightness"))
        if color is not None:
            if not isinstance(color, (tuple, list)) or len(color) != 3:
                raise ValueError(tr("灯光颜色需要三个 RGB 分量。", "The lighting color requires three RGB components."))
            for component in color:
                _integer(component, 0, 255, tr("RGB 分量", "RGB component"))
            color = tuple(color)
        if direction is not None:
            _integer(direction, 0, 1, tr("动画方向", "Animation direction"))
        if random is not None:
            _integer(random, 0, 1, tr("随机颜色开关", "Random-color setting"))
        if speed is not None and (type(speed) is not int or speed not in (0, 5, 7, 9)):
            raise ValueError(tr("动画速度必须为 0、5、7 或 9。", "Animation speed must be 0, 5, 7, or 9."))
        if expected_profile is not None:
            _integer(expected_profile, 1, 5, tr("配置编号", "Profile number"))
        if zone == "all" and (mode is None or brightness is None or color is None):
            raise ValueError(tr("应用全部灯区时需要明确指定灯效、亮度和颜色。", "Applying all zones requires an explicit effect, brightness, and color."))

        profile = Performance(self.transport).read_state().profile
        if expected_profile is not None and profile != expected_profile:
            raise LightingError(tr("鼠标当前配置为 {profile}，请重新读取配置后再应用灯光。",
                                   "The active mouse profile is {profile}. Refresh before applying lighting.", profile=profile))
        before = self.read_lighting()
        desired = before.copy()
        if zone == "all":
            setting = LightSetting(
                mode, brightness, color,
                0 if direction is None else direction,
                0 if random is None else random,
                (7 if mode == 3 else 0) if speed is None else speed,
            )
            desired = {key: setting for key in before}
        else:
            changes = {
                name: value for name, value in (
                    ("mode", mode), ("brightness", brightness), ("color", color),
                    ("direction", direction), ("random", random), ("speed", speed),
                ) if value is not None
            }
            setting = replace(before[zone], **changes)
            if setting.mode not in EFFECTS:
                raise ValueError(tr("当前灯效需要通过受支持的灯效选项替换后再修改。", "Select a supported effect before modifying this lighting configuration."))
            desired[zone] = setting
        if desired == before:
            return before

        self._check_profile(profile)
        self._exchange(self._packet(zone, setting))
        self._check_profile(profile)
        actual = self.read_lighting()
        if actual != desired:
            raise LightingError(tr("灯光写入后的回读不一致，请重新读取鼠标配置。", "Lighting readback differs from the requested setting. Refresh the mouse configuration."))
        if persist:
            self.save()
            self._check_profile(profile)
            actual = self.read_lighting()
            if actual != desired:
                raise LightingError(tr("保存后灯光回读不一致，请重新读取鼠标配置。", "Lighting readback differs after saving. Refresh the mouse configuration."))
        return actual

    def save(self) -> None:
        self._exchange(b"\x50\x03")
