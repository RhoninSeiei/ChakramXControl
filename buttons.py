"""ROG Chakram X button bindings over the ASUS USB control interface.

The transport exchanges payloads with the Windows report-ID byte removed.
Protocol references (observed 2026-11-26):
https://github.com/seerge/g-helper/blob/a3c3ccae51f005d92d8d4ee161e6661ab511274d/app/Peripherals/Mouse/Models/ChakramX.cs
https://github.com/seerge/g-helper/blob/a3c3ccae51f005d92d8d4ee161e6661ab511274d/app/Peripherals/Mouse/AsusMouse.cs
https://github.com/libratbag/libratbag/blob/1aec93b2f81036014063fb8a9ac194a1c71bdec8/src/asus.c

The four joystick directions have no documented readable positions. Their
write API returns acknowledged targets and never claims a hardware readback.
Bindings are always read from the active profile.

Joystick axis encoding additionally follows the installed AacMouseHal_x86.dll
SHA-256 3b001665baf656c9cfc48d566c356be07952652927a694dd21a7f083f4ebb90b,
P708 setter
0x10170760 and its conversion table at 0x1031E088. Axis arrangements and physical
directions follow ArmouryDevice/View/6680/resources/src/_ref/caps.json,
default.json and the View/6680/index.js setJoystickMode action. The global
game-controller interface toggle is separate from these per-profile mappings.
"""

from dataclasses import dataclass
import struct
from typing import Protocol

from i18n import get_language, tr
from performance import Performance


class Transport(Protocol):
    def exchange(self, request: bytes) -> bytes: ...


class ButtonProtocolError(RuntimeError):
    """The device rejected an operation or returned unexpected button data."""


class JoystickWriteError(ButtonProtocolError):
    """A multi-direction write failed after zero or more accepted commands."""

    def __init__(self, message: str, accepted_bindings: dict[str, int]):
        super().__init__(message)
        self.accepted_bindings = accepted_bindings.copy()


@dataclass(frozen=True)
class ButtonSlot:
    slot: int
    name: str
    source: int
    group: int
    position: int


BUTTON_SLOTS = (
    ButtonSlot(0, "左键", 0x01F0, 0, 0),
    ButtonSlot(1, "右键", 0x01F1, 0, 1),
    ButtonSlot(2, "滚轮按下", 0x01F2, 0, 2),
    ButtonSlot(3, "DPI 按钮", 0x01E6, 0, 5),
    ButtonSlot(4, "滚轮向上", 0x01E8, 0, 6),
    ButtonSlot(5, "滚轮向下", 0x01E9, 0, 7),
    ButtonSlot(10, "侧键 A", 0x01EA, 1, 2),
    ButtonSlot(11, "侧键 B", 0x01EB, 1, 3),
    ButtonSlot(12, "侧键 C", 0x01EC, 1, 4),
    ButtonSlot(13, "侧键 D", 0x01ED, 1, 5),
)
SLOTS_BY_ID = {button.slot: button for button in BUTTON_SLOTS}
SIDE_BUTTON_SLOTS = BUTTON_SLOTS[6:]

BUTTON_NAMES_EN = {
    "左键": "Left button",
    "右键": "Right button",
    "滚轮按下": "Wheel click",
    "DPI 按钮": "DPI button",
    "滚轮向上": "Scroll up",
    "滚轮向下": "Scroll down",
    "侧键 A": "Side button A",
    "侧键 B": "Side button B",
    "侧键 C": "Side button C",
    "侧键 D": "Side button D",
}


def button_label(button: ButtonSlot | str, language: str | None = None) -> str:
    name = button.name if isinstance(button, ButtonSlot) else button
    language = language or get_language()
    return BUTTON_NAMES_EN.get(name, name) if language == "en" else name


@dataclass(frozen=True)
class JoystickDirection:
    key: str
    name: str
    source: int


JOYSTICK_DIRECTIONS = (
    JoystickDirection("up", "上", 0x01D2),
    JoystickDirection("down", "下", 0x01D3),
    JoystickDirection("left", "左", 0x01D1),
    JoystickDirection("right", "右", 0x01D0),
)
JOYSTICK_MODES = {
    "digital": "数字四键",
    "analog_vertical": "模拟摇杆 · 纵向",
    "analog_horizontal": "模拟摇杆 · 横向",
}
JOYSTICK_MODES_EN = {
    "digital": "Digital four-button",
    "analog_vertical": "Analog stick · vertical",
    "analog_horizontal": "Analog stick · horizontal",
}
JOYSTICK_DIRECTIONS_EN = {"up": "Up", "down": "Down", "left": "Left", "right": "Right"}
JOYSTICK_DIRECTIONS_ZH = {"up": "上", "down": "下", "left": "左", "right": "右"}


def joystick_mode_label(mode: str, language: str | None = None) -> str:
    language = language or get_language()
    labels = JOYSTICK_MODES_EN if language == "en" else JOYSTICK_MODES
    return labels.get(mode, mode)


def direction_label(direction: str, language: str | None = None) -> str:
    language = language or get_language()
    labels = JOYSTICK_DIRECTIONS_EN if language == "en" else JOYSTICK_DIRECTIONS_ZH
    return labels.get(direction, direction)
DEFAULT_DIGITAL_BINDINGS = {"up": 0x0052, "down": 0x0051, "left": 0x0050, "right": 0x004F}
ANALOG_BINDINGS = {
    "analog_vertical": {"up": 0x01DB, "down": 0x01DB, "left": 0x01D8, "right": 0x01D8},
    "analog_horizontal": {"up": 0x01D8, "down": 0x01D8, "left": 0x01DA, "right": 0x01DA},
}

# ASUS action values contain an action byte and a type byte. Keyboard actions
# use type 0, mouse functions use type 1. These are device codes, not Win32 VKs.
ACTIONS = {
    0x0000: "空键",
    0x01FF: "禁用",
    0x01F0: "鼠标左键",
    0x01F1: "鼠标右键",
    0x01F2: "鼠标中键",
    0x01E3: "双击",
    0x01E4: "后退",
    0x01E5: "前进",
    0x01E6: "切换 DPI 档位",
    0x01E7: "瞄准辅助 DPI",
    0x01E8: "滚轮向上",
    0x01E9: "滚轮向下",
    0x01EA: "侧键 A 默认动作",
    0x01EB: "侧键 B 默认动作",
    0x01EC: "侧键 C 默认动作",
    0x01ED: "侧键 D 默认动作",
    0x00F0: "播放或暂停",
    0x00F1: "停止播放",
    0x00F2: "下一曲",
    0x00F3: "上一曲",
    0x00F4: "静音",
    0x00F5: "降低音量",
    0x00F6: "提高音量",
    0x0028: "Enter",
    0x0029: "Escape",
    0x002A: "Backspace",
    0x002B: "Tab",
    0x002C: "Space",
    0x002D: "-",
    0x002E: "=",
    0x002F: "[",
    0x0030: "]",
    0x0033: ";",
    0x0034: "'",
    0x0036: ",",
    0x0037: ".",
    0x0038: "/",
    0x0046: "Print Screen",
    0x0049: "Insert",
    0x004A: "Home",
    0x004B: "Page Up",
    0x004C: "Delete",
    0x004D: "End",
    0x004E: "Page Down",
    0x004F: "Right",
    0x0050: "Left",
    0x0051: "Down",
    0x0052: "Up",
    0x00E0: "Left Ctrl",
    0x00E1: "Left Shift",
    0x00E2: "Left Alt",
    0x00E3: "Left Win",
    0x00E4: "Right Ctrl",
    0x00E5: "Right Shift",
    0x00E6: "Right Alt",
    0x00E7: "Right Win",
}
ACTIONS.update({4 + index: chr(ord("A") + index) for index in range(26)})
ACTIONS.update({0x001E + index: key for index, key in enumerate("1234567890")})
ACTIONS.update({0x003A + index: f"F{index + 1}" for index in range(12)})
ACTIONS.update({0x0068 + index: f"F{index + 13}" for index in range(12)})

_ACTION_NAMES_EN = {
    0x0000: "No action",
    0x01FF: "Disabled",
    0x01F0: "Left mouse button",
    0x01F1: "Right mouse button",
    0x01F2: "Middle mouse button",
    0x01E3: "Double click",
    0x01E4: "Back",
    0x01E5: "Forward",
    0x01E6: "Switch DPI stage",
    0x01E7: "Sniper DPI",
    0x01E8: "Scroll up",
    0x01E9: "Scroll down",
    0x01EA: "Side button A default",
    0x01EB: "Side button B default",
    0x01EC: "Side button C default",
    0x01ED: "Side button D default",
    0x00F0: "Play/Pause",
    0x00F1: "Stop",
    0x00F2: "Next track",
    0x00F3: "Previous track",
    0x00F4: "Mute",
    0x00F5: "Volume down",
    0x00F6: "Volume up",
}
_ACTIONS_EN = {code: _ACTION_NAMES_EN.get(code, label) for code, label in ACTIONS.items()}


def action_label(code: int, language: str | None = None) -> str:
    language = language or get_language()
    labels = _ACTIONS_EN if language == "en" else ACTIONS
    if code in labels:
        return labels[code]
    return (f"Custom action 0x{code:04X}" if language == "en"
            else f"自定义动作 0x{code:04X}")


class ButtonController:
    def __init__(self, transport: Transport):
        self.transport = transport

    def _exchange(self, request: bytes, minimum_length: int = 2) -> bytes:
        response = bytes(self.transport.exchange(request))
        if response[:2] == b"\xff\xaa":
            raise ButtonProtocolError(tr("鼠标拒绝了按键配置命令。", "The mouse rejected the button configuration command."))
        if len(response) < minimum_length or response[:2] != request[:2]:
            raise ButtonProtocolError(tr("鼠标返回的按键配置数据不完整或命令不匹配。", "The mouse returned incomplete button data or a mismatched command."))
        return response

    def _read_group(self, group: int) -> bytes:
        # Group 0 contains eight raw positions, group 1 contains six.
        required_length = 20 if group == 0 else 16
        response = self._exchange(bytes((0x12, 0x05, group, 0, 0)), required_length)
        if response[2] != group:
            raise ButtonProtocolError(tr("鼠标返回的按键分组不匹配。", "The mouse returned a mismatched button group."))
        return response

    def read_bindings(self) -> dict[int, int]:
        """Return all ten readable bindings, preserving unknown action values."""
        groups = (self._read_group(0), self._read_group(1))
        return {
            button.slot: struct.unpack_from("<H", groups[button.group], 4 + button.position * 2)[0]
            for button in BUTTON_SLOTS
        }

    def read_binding(self, slot: int) -> int:
        button = self._get_slot(slot)
        response = self._read_group(button.group)
        return struct.unpack_from("<H", response, 4 + button.position * 2)[0]

    @staticmethod
    def _get_slot(slot: int) -> ButtonSlot:
        if type(slot) is not int or slot not in SLOTS_BY_ID:
            raise ValueError(tr("该按键没有可回读的 Chakram X 配置。", "This Chakram X button has no readable configuration."))
        return SLOTS_BY_ID[slot]

    def _check_profile(self, expected_profile: int | None) -> None:
        if expected_profile is None:
            return
        if type(expected_profile) is not int or not 1 <= expected_profile <= 5:
            raise ValueError(tr("配置编号必须为 1 至 5 的整数。", "The profile must be an integer from 1 to 5."))
        actual = Performance(self.transport).read_state().profile
        if actual != expected_profile:
            raise ButtonProtocolError(tr("当前鼠标配置为 {actual}，请重新读取配置后再应用。",
                                         "The active mouse profile is {actual}; refresh before applying.", actual=actual))

    def select_profile(self, profile: int, *, expected_profile: int | None = None) -> int:
        """Switch to one of the five onboard profiles and confirm the result."""
        if type(profile) is not int or not 1 <= profile <= 5:
            raise ValueError(tr("配置编号必须为 1 至 5 的整数。", "The profile must be an integer from 1 to 5."))
        self._check_profile(expected_profile)
        self._exchange(bytes((0x50, 0x02, profile - 1)))
        self.save()
        actual = Performance(self.transport).read_state().profile
        if actual != profile:
            raise ButtonProtocolError(tr("配置切换回读为 {actual}，目标为 {profile}。",
                                         "Profile readback is {actual}; the requested profile was {profile}.",
                                         actual=actual, profile=profile))
        return actual

    def set_binding(
        self, slot: int, action: int, *, persist: bool = True,
        expected_profile: int | None = None,
    ) -> int:
        """Set one readable binding and verify it before saving to the mouse.

        Unknown existing actions can be restored by their original 16-bit value.
        Callers exposing arbitrary inputs should offer the documented ACTIONS.
        A failure raises an exception and never reports a successful save.
        """
        button = self._get_slot(slot)
        if type(action) is not int or not 0 <= action < 0xFFFF:
            raise ValueError(tr("按键动作必须为 0 到 65534 的整数。", "Button action must be an integer from 0 to 65534."))
        self._check_profile(expected_profile)
        self._exchange(b"\x51\x21\x00\x00" + struct.pack("<HH", button.source, action))
        actual = self.read_binding(slot)
        if actual != action:
            raise ButtonProtocolError(tr("按键回读校验失败，期望 0x{action:04X}，实际 0x{actual:04X}。",
                                         "Button readback mismatch: expected 0x{action:04X}, received 0x{actual:04X}.",
                                         action=action, actual=actual))
        if persist:
            self.save()
            self._check_profile(expected_profile)
            actual = self.read_binding(slot)
            if actual != action:
                raise ButtonProtocolError(tr("保存后按键配置发生变化，请重新读取鼠标配置。",
                                             "The button mapping changed after saving; refresh the mouse configuration."))
        return actual

    def set_button(
        self, slot: int, action: int, *, persist: bool = True,
        expected_profile: int | None = None,
    ) -> int:
        return self.set_binding(slot, action, persist=persist, expected_profile=expected_profile)

    def set_joystick_mode(
        self, mode: str, digital_bindings: dict[str, int] | None = None, *,
        expected_profile: int | None = None, persist: bool = False,
    ) -> dict[str, int]:
        """Configure four joystick directions in the active onboard profile.

        The returned values are acknowledged write targets. The protocol used
        here cannot read them back. Readable mouse/side bindings are checked
        before and after this operation. The caller controls the independent
        global game-controller interface setting and stores its own write log.

        A hardware failure may leave some directions changed in volatile state.
        JoystickWriteError.accepted_bindings identifies acknowledged writes.
        """
        if mode not in JOYSTICK_MODES:
            raise ValueError(tr("摇杆模式必须为 digital、analog_vertical 或 analog_horizontal。",
                                "Joystick mode must be digital, analog_vertical, or analog_horizontal."))
        if mode == "digital":
            bindings = DEFAULT_DIGITAL_BINDINGS.copy() if digital_bindings is None else dict(digital_bindings)
        else:
            if digital_bindings is not None:
                raise ValueError(tr("模拟模式使用原厂轴映射，请清空数字模式按键参数。",
                                    "Analog mode uses the factory axis mapping; clear digital button bindings."))
            bindings = ANALOG_BINDINGS[mode].copy()
        if set(bindings) != {direction.key for direction in JOYSTICK_DIRECTIONS}:
            raise ValueError(tr("需要同时提供上、下、左、右四个方向的按键。",
                                "Provide bindings for all four directions: up, down, left, and right."))
        if any(type(action) is not int or not 0 <= action < 0xFFFF for action in bindings.values()):
            raise ValueError(tr("摇杆按键动作必须为 0 到 65534 的整数。",
                                "Joystick button actions must be integers from 0 to 65534."))
        current_profile = Performance(self.transport).read_state().profile
        if expected_profile is not None and current_profile != expected_profile:
            raise ButtonProtocolError(tr("当前鼠标配置为 {profile}，请重新读取配置后再应用。",
                                         "The active mouse profile is {profile}; refresh before applying.",
                                         profile=current_profile))
        if current_profile == 5:
            raise ButtonProtocolError(tr("请切换到预设 1 至 4 编辑摇杆。",
                                         "Switch to profile 1 through 4 to edit the joystick."))
        before = self.read_bindings()
        accepted = {}
        try:
            for direction in JOYSTICK_DIRECTIONS:
                self._check_profile(current_profile)
                target = bindings[direction.key]
                request = b"\x51\x21\x00\x00" + struct.pack("<HH", direction.source, target)
                self._exchange(request)
                accepted[direction.key] = target
            self._check_profile(current_profile)
            if self.read_bindings() != before:
                raise ButtonProtocolError(tr("摇杆配置期间鼠标按键发生变化，请重新读取配置。",
                                             "Mouse button mappings changed during joystick setup; refresh the configuration."))
            if persist:
                self.save()
                self._check_profile(current_profile)
                if self.read_bindings() != before:
                    raise ButtonProtocolError(tr("保存摇杆后鼠标按键发生变化，请重新读取配置。",
                                                 "Mouse button mappings changed after saving the joystick; refresh the configuration."))
        except Exception as error:
            raise JoystickWriteError(
                tr("摇杆配置未完成，{count} 个方向收到写入确认。{error}",
                   "Joystick setup is incomplete; {count} directions were acknowledged. {error}",
                   count=len(accepted), error=error), accepted,
            ) from error
        return accepted

    def save(self) -> None:
        """Save active-profile settings to onboard storage."""
        self._exchange(b"\x50\x03")
