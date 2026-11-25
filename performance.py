"""ROG Chakram X DPI commands over an injected HID transport.

Wire layout follows G-Helper's AsusMouse and ChakramX implementations.
https://github.com/seerge/g-helper/blob/main/app/Peripherals/Mouse/AsusMouse.cs
https://github.com/seerge/g-helper/blob/main/app/Peripherals/Mouse/Models/ChakramX.cs

Requests and responses exclude the Windows HID report-ID byte. Reads retain
independent X/Y values. The documented setting command sets a symmetric DPI and
includes the existing indicator color. A successful persisted write is checked
against both axes. All public profile and DPI-slot numbers are one-based.
"""

from dataclasses import dataclass
import struct
from typing import Protocol

from i18n import tr


class Transport(Protocol):
    def exchange(self, request: bytes) -> bytes:
        ...


class PerformanceError(RuntimeError):
    """The mouse returned invalid data or did not confirm the requested state."""


@dataclass(frozen=True)
class ProfileState:
    profile: int
    dpi_slot: int


@dataclass(frozen=True)
class DpiPreset:
    x: int
    y: int
    color: tuple[int, int, int]


def _validate_slot(slot: int) -> None:
    if type(slot) is not int or not 1 <= slot <= 4:
        raise ValueError(tr("DPI 档位必须为 1 至 4 的整数。", "The DPI slot must be an integer from 1 to 4."))


class Performance:
    def __init__(self, transport: Transport):
        self.transport = transport

    def _read(self, request: bytes, minimum_length: int) -> bytes:
        reply = self.transport.exchange(request)
        if len(reply) < minimum_length or reply[:len(request)] != request:
            raise PerformanceError(tr("鼠标返回的配置数据不完整或命令不匹配，请重新读取。",
                                      "The mouse returned incomplete configuration data or a mismatched command. Refresh and try again."))
        return reply

    def read_state(self) -> ProfileState:
        reply = self._read(b"\x12\x00", 12)
        profile = reply[10] + 1
        slot = reply[11]
        if not 1 <= profile <= 5 or not 1 <= slot <= 4:
            raise PerformanceError(tr("鼠标返回无效的配置 {profile} 或 DPI 档位 {slot}。",
                                      "The mouse returned an invalid profile ({profile}) or DPI slot ({slot}).",
                                      profile=profile, slot=slot))
        return ProfileState(profile, slot)

    def read_dpi(self) -> tuple[DpiPreset, ...]:
        reply = self._read(b"\x12\x04\x02", 20)
        colors = self._read(b"\x12\x04\x03", 16)
        presets = []
        for index in range(4):
            encoded_x, encoded_y = struct.unpack_from("<HH", reply, 4 + index * 4)
            x, y = encoded_x * 50 + 50, encoded_y * 50 + 50
            if not 100 <= x <= 36000 or not 100 <= y <= 36000:
                raise PerformanceError(tr("鼠标返回无效 DPI，档位 {slot} 为 X={x}，Y={y}。",
                                          "The mouse returned invalid DPI for slot {slot}: X={x}, Y={y}.",
                                          slot=index + 1, x=x, y=y))
            color = tuple(colors[4 + index * 3:7 + index * 3])
            presets.append(DpiPreset(x, y, color))
        return tuple(presets)

    def _check_profile(self, expected_profile: int | None) -> None:
        if expected_profile is None:
            return
        if type(expected_profile) is not int or not 1 <= expected_profile <= 5:
            raise ValueError(tr("配置编号必须为 1 至 5 的整数。", "The profile must be an integer from 1 to 5."))
        current = self.read_state().profile
        if current != expected_profile:
            raise PerformanceError(tr("鼠标当前配置为 {profile}，请重新读取配置后再应用。",
                                      "The active mouse profile is {profile}; refresh before applying.",
                                      profile=current))

    def set_dpi(self, slot: int, dpi: int, *, expected_profile: int | None = None, persist: bool = True) -> None:
        """Set both axes of one slot while retaining its indicator color.

        With persist=False the caller must save and verify the resulting state.
        A later operation can fail after the mouse has accepted this change.
        """
        _validate_slot(slot)
        if type(dpi) is not int or not 100 <= dpi <= 36000 or dpi % 50:
            raise ValueError(tr("DPI 必须为 100 至 36000 的整数，步进为 50。",
                                "DPI must be an integer from 100 to 36000 in increments of 50."))
        preset = self.read_dpi()[slot - 1]
        self._check_profile(expected_profile)
        encoded = dpi // 50 - 1
        request = b"\x51\x31" + bytes((slot - 1, 0)) + struct.pack("<H", encoded) + bytes(preset.color)
        self.transport.exchange(request)
        if persist:
            self.transport.exchange(b"\x50\x03")
            self._check_profile(expected_profile)
            actual = self.read_dpi()[slot - 1]
            if actual.x != dpi or actual.y != dpi or actual.color != preset.color:
                raise PerformanceError(
                    tr("DPI 写入后的回读不一致，档位 {slot} 目标为 {dpi}，实际为 X={x}，Y={y}，指示颜色为 {color}。",
                       "DPI readback mismatch for slot {slot}: requested {dpi}, received X={x}, Y={y}, indicator color {color}.",
                       slot=slot, dpi=dpi, x=actual.x, y=actual.y, color=actual.color)
                )

    def select_dpi(self, slot: int, *, expected_profile: int | None = None, persist: bool = True) -> None:
        """Select an existing DPI slot in the currently active profile."""
        _validate_slot(slot)
        self._check_profile(expected_profile)
        self.transport.exchange(b"\x51\x31\x09\x00" + bytes((slot,)))
        if persist:
            self.transport.exchange(b"\x50\x03")
            actual = self.read_state()
            if expected_profile is not None and actual.profile != expected_profile:
                raise PerformanceError(tr("鼠标当前配置为 {profile}，请重新读取配置。",
                                          "The active mouse profile is {profile}; refresh the configuration.",
                                          profile=actual.profile))
            if actual.dpi_slot != slot:
                raise PerformanceError(tr("DPI 档位回读为 {actual}，目标为 {target}，请重新读取。",
                                          "DPI slot readback is {actual}; the requested slot was {target}. Refresh and try again.",
                                          actual=actual.dpi_slot, target=slot))
