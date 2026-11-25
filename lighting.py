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


class Transport(Protocol):
    def exchange(self, request: bytes) -> bytes: ...


class LightingError(RuntimeError):
    """The mouse rejected a request or failed lighting readback verification."""


ZONES = {"logo": 0, "wheel": 1, "front": 2, "all": 3}
ZONE_NAMES = {"logo": "Logo", "wheel": "滚轮", "front": "前端灯带", "all": "全部灯区"}
EFFECTS = {
    0x00: "常亮",
    0x01: "呼吸",
    0x02: "颜色循环",
    0x04: "触发",
    0x03: "彩虹",
    0x05: "彗星",
    0x06: "电量",
    0xF0: "关闭",
}
ZONE_EFFECTS = (0x00, 0x01, 0x02, 0x04, 0xF0)
SPEEDS = {5: "快", 7: "中", 9: "慢"}


@dataclass(frozen=True)
class LightSetting:
    mode: int
    brightness: int
    color: tuple[int, int, int]
    direction: int = 0
    random: int = 0
    speed: int = 0


def effect_label(mode: int) -> str:
    return EFFECTS.get(mode, f"其他灯效 0x{mode:02X}")


def _integer(value: int, minimum: int, maximum: int, label: str) -> None:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"{label}必须为 {minimum} 至 {maximum} 的整数。")


class Lighting:
    def __init__(self, transport: Transport):
        self.transport = transport

    def _exchange(self, request: bytes, minimum_length: int = 2) -> bytes:
        response = bytes(self.transport.exchange(request))
        if len(response) < minimum_length or response[:2] != request[:2]:
            raise LightingError("鼠标返回的灯光数据不完整或命令不匹配。")
        return response

    def read_zone(self, zone: str) -> LightSetting:
        if zone not in ZONES or zone == "all":
            raise ValueError("读取灯区必须为 logo、wheel 或 front。")
        response = self._exchange(bytes((0x12, 0x03, ZONES[zone])), 13)
        brightness = response[5]
        if brightness > 100:
            raise LightingError(f"鼠标返回无效的灯光亮度 {brightness}。")
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
            raise LightingError(f"鼠标当前配置为 {actual}，请重新读取配置后再应用灯光。")

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
            raise ValueError("灯区必须为 logo、wheel、front 或 all。")
        if mode is not None:
            if type(mode) is not int or mode not in EFFECTS:
                raise ValueError("灯效不在当前支持范围内。")
            if zone != "all" and mode not in ZONE_EFFECTS:
                raise ValueError("彩虹、彗星和电量效果需要应用到全部灯区。")
        if brightness is not None:
            _integer(brightness, 0, 100, "灯光亮度")
        if color is not None:
            if not isinstance(color, (tuple, list)) or len(color) != 3:
                raise ValueError("灯光颜色需要三个 RGB 分量。")
            for component in color:
                _integer(component, 0, 255, "RGB 分量")
            color = tuple(color)
        if direction is not None:
            _integer(direction, 0, 1, "动画方向")
        if random is not None:
            _integer(random, 0, 1, "随机颜色开关")
        if speed is not None and (type(speed) is not int or speed not in (0, 5, 7, 9)):
            raise ValueError("动画速度必须为 0、5、7 或 9。")
        if expected_profile is not None:
            _integer(expected_profile, 1, 5, "配置编号")
        if zone == "all" and (mode is None or brightness is None or color is None):
            raise ValueError("应用全部灯区时需要明确指定灯效、亮度和颜色。")

        profile = Performance(self.transport).read_state().profile
        if expected_profile is not None and profile != expected_profile:
            raise LightingError(f"鼠标当前配置为 {profile}，请重新读取配置后再应用灯光。")
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
                raise ValueError("当前灯效需要通过受支持的灯效选项替换后再修改。")
            desired[zone] = setting
        if desired == before:
            return before

        self._check_profile(profile)
        self._exchange(self._packet(zone, setting))
        self._check_profile(profile)
        actual = self.read_lighting()
        if actual != desired:
            raise LightingError("灯光写入后的回读不一致，请重新读取鼠标配置。")
        if persist:
            self.save()
            self._check_profile(profile)
            actual = self.read_lighting()
            if actual != desired:
                raise LightingError("保存后灯光回读不一致，请重新读取鼠标配置。")
        return actual

    def save(self) -> None:
        self._exchange(b"\x50\x03")
