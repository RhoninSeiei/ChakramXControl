import struct
import unittest

from performance import DpiPreset, Performance, PerformanceError, ProfileState


def profile_reply(profile=1, slot=2):
    reply = bytearray(64)
    reply[:2] = b"\x12\x00"
    reply[10] = profile - 1
    reply[11] = slot
    return bytes(reply)


def dpi_reply(presets):
    reply = bytearray(64)
    reply[:3] = b"\x12\x04\x02"
    for index, (x, y) in enumerate(presets):
        struct.pack_into("<HH", reply, 4 + index * 4, x // 50 - 1, y // 50 - 1)
    return bytes(reply)


def color_reply():
    reply = bytearray(64)
    reply[:3] = b"\x12\x04\x03"
    reply[4:16] = bytes((255, 0, 0, 12, 34, 56, 0, 0, 255, 0, 255, 0))
    return bytes(reply)


class ScriptedTransport:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.requests = []

    def exchange(self, request):
        self.requests.append(request)
        return next(self.replies)


class PerformanceTests(unittest.TestCase):
    presets = ((800, 850), (1000, 1000), (1600, 1600), (3200, 3200))

    def test_reads_real_xy_layout_without_losing_axis_difference(self):
        transport = ScriptedTransport([dpi_reply(self.presets), color_reply()])
        result = Performance(transport).read_dpi()
        self.assertEqual(result[0], DpiPreset(800, 850, (255, 0, 0)))
        self.assertEqual(result[1], DpiPreset(1000, 1000, (12, 34, 56)))
        self.assertEqual(transport.requests, [b"\x12\x04\x02", b"\x12\x04\x03"])

    def test_reads_one_based_public_profile_and_dpi_slot(self):
        transport = ScriptedTransport([profile_reply(5, 4)])
        self.assertEqual(Performance(transport).read_state(), ProfileState(5, 4))

    def test_decodes_local_chakram_x_capture(self):
        transport = ScriptedTransport([
            bytes.fromhex("12 00 00 00 17 02 22 00 05 07 01 03 ff ff"),
            bytes.fromhex("12 04 02 00 07 00 07 00 0f 00 0f 00 45 00 45 00 45 00 45 00"),
            bytes.fromhex("12 04 03 00 ff 00 00 c1 00 ff 00 3d ff 31 ff 00"),
        ])
        performance = Performance(transport)
        self.assertEqual(performance.read_state(), ProfileState(2, 3))
        self.assertEqual(performance.read_dpi(), (
            DpiPreset(400, 400, (255, 0, 0)),
            DpiPreset(800, 800, (193, 0, 255)),
            DpiPreset(3500, 3500, (0, 61, 255)),
            DpiPreset(3500, 3500, (49, 255, 0)),
        ))

    def test_set_dpi_preserves_color_and_verifies_both_axes(self):
        updated = list(self.presets)
        updated[1] = (1250, 1250)
        transport = ScriptedTransport([
            dpi_reply(self.presets), color_reply(), profile_reply(),
            b"\x51\x31", b"\x50\x03", profile_reply(),
            dpi_reply(updated), color_reply(),
        ])
        Performance(transport).set_dpi(2, 1250, expected_profile=1)
        self.assertIn(b"\x51\x31\x01\x00\x18\x00\x0c\x22\x38", transport.requests)
        self.assertEqual(transport.requests[4], b"\x50\x03")

    def test_deferred_save_only_sends_setting(self):
        transport = ScriptedTransport([dpi_reply(self.presets), color_reply(), b"\x51\x31"])
        Performance(transport).set_dpi(1, 800, persist=False)
        self.assertEqual(len(transport.requests), 3)
        self.assertNotIn(b"\x50\x03", transport.requests)

    def test_invalid_dpi_and_slot_do_not_touch_transport(self):
        transport = ScriptedTransport([])
        performance = Performance(transport)
        for slot, dpi in [(0, 800), (5, 800), (1, 99), (1, 36050), (1, 1234), (True, 800), (1, 800.0)]:
            with self.subTest(slot=slot, dpi=dpi), self.assertRaises(ValueError):
                performance.set_dpi(slot, dpi)
        self.assertEqual(transport.requests, [])

    def test_low_and_high_supported_dpi_are_encoded_without_truncation(self):
        for dpi, encoded in [(100, b"\x01\x00"), (36000, b"\xcf\x02")]:
            transport = ScriptedTransport([dpi_reply(self.presets), color_reply(), b"\x51\x31"])
            Performance(transport).set_dpi(4, dpi, persist=False)
            self.assertEqual(transport.requests[-1][4:6], encoded)

    def test_changed_profile_blocks_write(self):
        transport = ScriptedTransport([dpi_reply(self.presets), color_reply(), profile_reply(2)])
        with self.assertRaisesRegex(PerformanceError, "配置.*2"):
            Performance(transport).set_dpi(2, 1000, expected_profile=1)
        self.assertFalse(any(request.startswith(b"\x51") for request in transport.requests))

    def test_one_axis_readback_mismatch_is_reported(self):
        updated = list(self.presets)
        updated[1] = (1250, 1000)
        transport = ScriptedTransport([
            dpi_reply(self.presets), color_reply(), b"\x51\x31", b"\x50\x03",
            dpi_reply(updated), color_reply(),
        ])
        with self.assertRaisesRegex(PerformanceError, "X=1250.*Y=1000"):
            Performance(transport).set_dpi(2, 1250)

    def test_select_dpi_uses_one_based_slot_and_reads_back(self):
        transport = ScriptedTransport([profile_reply(3, 1), b"\x51\x31", b"\x50\x03", profile_reply(3, 4)])
        Performance(transport).select_dpi(4, expected_profile=3)
        self.assertEqual(transport.requests[1], b"\x51\x31\x09\x00\x04")

    def test_select_dpi_rejects_unsuccessful_readback(self):
        transport = ScriptedTransport([b"\x51\x31", b"\x50\x03", profile_reply(1, 1)])
        with self.assertRaisesRegex(PerformanceError, "档位.*1"):
            Performance(transport).select_dpi(4)

    def test_invalid_profile_or_slot_response_is_not_used(self):
        for reply in [profile_reply(6), profile_reply(1, 5), b"\x12\x00"]:
            with self.subTest(reply=reply), self.assertRaises(PerformanceError):
                Performance(ScriptedTransport([reply])).read_state()

    def test_malformed_dpi_response_is_not_used(self):
        for reply in [b"\x12\x04\x02", bytes(64), b"\xff\xaa"]:
            with self.subTest(reply=reply), self.assertRaises(PerformanceError):
                Performance(ScriptedTransport([reply])).read_dpi()


if __name__ == "__main__":
    unittest.main()
