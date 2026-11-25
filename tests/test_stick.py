from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from buttons import ButtonController, ButtonProtocolError
from device import Transport, gamepad_flag
from stick_record import StickRecord


class Port:
    def __init__(self):
        self.input = []
        self.output = []

    def write(self, packet):
        self.output.append(packet)
        return len(packet)

    def read(self, size, timeout):
        return self.input.pop(0) if timeout > 1 and self.input else []


class StickTests(unittest.TestCase):
    def test_controller_switch_uses_single_no_ack_report(self):
        port = Port()
        transport = Transport(port)
        for state in (True, False):
            transport.set_gamepad_flag(state)
        self.assertEqual(port.output, [
            bytes.fromhex("00 51 40 00 00 01").ljust(65, b"\x00"),
            bytes.fromhex("00 51 40 00 00 00").ljust(65, b"\x00"),
        ])

    def test_query_skips_unrelated_reports_and_returns_device_flag(self):
        port = Port()
        port.input = [bytes.fromhex(v).ljust(64, b"\x00")
                      for v in ("12 00 00 00 00", "12 00 06 00 01")]
        self.assertTrue(gamepad_flag(Transport(port)))
        self.assertEqual(len(port.output), 1)

    def test_wheel_lighting_reply_uses_selector_zero(self):
        port = Port()
        reply = bytes.fromhex("12 03 00 00 01 19 B3 19 50").ljust(64, b"\x00")
        port.input = [reply]
        self.assertEqual(Transport(port).exchange(b"\x12\x03\x01"), reply)
        self.assertEqual(port.output, [bytes.fromhex("00 12 03 01").ljust(65, b"\x00")])

    def test_profile_five_blocks_direction_writes(self):
        port = Port()
        port.input = [bytes.fromhex("12 00 00 00 17 02 22 00 05 07 04 01").ljust(64, b"\x00")]
        with self.assertRaises(ButtonProtocolError):
            ButtonController(Transport(port)).set_joystick_mode("analog_vertical", expected_profile=5)
        self.assertEqual(len(port.output), 1)

    def test_analog_mode_preserves_last_digital_keys_for_one_profile(self):
        with TemporaryDirectory() as tmp:
            record = StickRecord(Path(tmp) / "settings.db")
            self.assertIsNone(record.read("mouse1", 2))
            keys = (26, 22, 4, 7)
            record.save("mouse1", 2, "digital", keys)
            record.save("mouse1", 2, "analog_vertical")
            self.assertEqual(record.read("mouse1", 2), ("analog_vertical", *keys))
            self.assertIsNone(record.read("mouse1", 1))
            self.assertIsNone(record.read("mouse2", 2))
