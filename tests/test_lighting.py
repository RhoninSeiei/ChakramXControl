import unittest

from lighting import LightSetting, Lighting, LightingError, EFFECTS, SPEEDS, effect_names, speed_names, effect_label
from i18n import get_language, set_language


STATE = bytes.fromhex("12 00 00 00 17 02 22 00 05 07 01 03 ff ff")


def packet(setting):
    # Response selectors are always zero, including for wheel and front.
    return bytes((
        0x12, 0x03, 0, 0, setting.mode, setting.brightness, *setting.color,
        0, setting.direction, setting.random, setting.speed,
    )) + bytes(51)


def read_steps(snapshot):
    return [
        (bytes((0x12, 0x03, index)), packet(snapshot[zone]))
        for index, zone in enumerate(("logo", "wheel", "front"))
    ]


class ScriptedTransport:
    def __init__(self, steps):
        self.steps = list(steps)
        self.requests = []

    def exchange(self, request):
        self.requests.append(request)
        expected, response = self.steps.pop(0)
        if request != expected:
            raise AssertionError(f"Expected {expected.hex()}, received {request.hex()}")
        return response


class LightingTests(unittest.TestCase):
    def setUp(self):
        previous_language = get_language()
        set_language("zh")
        self.addCleanup(set_language, previous_language)
        self.before = {
            "logo": LightSetting(0, 25, (42, 12, 27)),
            "wheel": LightSetting(1, 50, (43, 12, 27)),
            "front": LightSetting(240, 0, (44, 12, 27)),
        }

    def write_steps(self, request, after):
        return (
            [(b"\x12\x00", STATE)] + read_steps(self.before)
            + [(b"\x12\x00", STATE), (bytes.fromhex(request), b"\x51\x28"), (b"\x12\x00", STATE)]
            + read_steps(after)
        )

    def test_reads_three_actual_zone_captures_with_fixed_response_selector(self):
        captures = [
            bytes.fromhex("12 03 00 00 00 19 2a 0c 1b") + bytes(55),
            bytes.fromhex("12 03 00 00 00 19 2b 0c 1b") + bytes(55),
            bytes.fromhex("12 03 00 00 00 19 2c 0c 1b") + bytes(55),
        ]
        transport = ScriptedTransport([(bytes((0x12, 3, i)), reply) for i, reply in enumerate(captures)])
        result = Lighting(transport).read_lighting()
        self.assertEqual(result["logo"], LightSetting(0, 25, (42, 12, 27)))
        self.assertEqual(result["wheel"], LightSetting(0, 25, (43, 12, 27)))
        self.assertEqual(result["front"], LightSetting(0, 25, (44, 12, 27)))

    def test_preserves_unmodified_fields_and_other_zones(self):
        after = self.before.copy()
        after["wheel"] = LightSetting(1, 50, (1, 2, 3))
        transport = ScriptedTransport(self.write_steps("51 28 01 00 01 32 01 02 03 00 00 00", after))
        self.assertEqual(Lighting(transport).set_lighting("wheel", color=(1, 2, 3)), after)
        self.assertEqual(transport.steps, [])
        self.assertNotIn(b"\x50\x03", transport.requests)

    def test_preserves_native_direction_random_and_speed_fields(self):
        self.before["logo"] = LightSetting(5, 25, (42, 12, 27), 1, 1, 0)
        after = self.before.copy()
        after["logo"] = LightSetting(5, 75, (42, 12, 27), 1, 1, 0)
        transport = ScriptedTransport(self.write_steps("51 28 00 00 05 4b 2a 0c 1b 01 01 00", after))
        self.assertEqual(Lighting(transport).set_lighting("logo", brightness=75), after)

    def test_all_zone_rainbow_broadcast_has_explicit_defaults(self):
        after = {zone: LightSetting(3, 25, (42, 12, 27), 0, 0, 7) for zone in self.before}
        transport = ScriptedTransport(self.write_steps("51 28 03 00 03 19 2a 0c 1b 00 00 07", after))
        actual = Lighting(transport).set_lighting("all", mode=3, brightness=25, color=(42, 12, 27))
        self.assertEqual(actual, after)
        self.assertEqual(transport.steps, [])

    def test_all_zone_comet_preserves_explicit_advanced_parameters(self):
        after = {zone: LightSetting(5, 50, (0, 12, 255), 1, 1, 0) for zone in self.before}
        transport = ScriptedTransport(self.write_steps("51 28 03 00 05 32 00 0c ff 01 01 00", after))
        actual = Lighting(transport).set_lighting(
            "all", mode=5, brightness=50, color=(0, 12, 255), direction=1, random=1, speed=0,
        )
        self.assertEqual(actual, after)

    def test_single_zone_and_save_are_verified(self):
        after = self.before.copy()
        after["front"] = LightSetting(0, 100, (255, 0, 0))
        steps = self.write_steps("51 28 02 00 00 64 ff 00 00 00 00 00", after)
        steps += [(b"\x50\x03", b"\x50\x03"), (b"\x12\x00", STATE)] + read_steps(after)
        transport = ScriptedTransport(steps)
        self.assertEqual(
            Lighting(transport).set_lighting("front", mode=0, brightness=100, color=(255, 0, 0), persist=True),
            after,
        )
        self.assertEqual(transport.steps, [])

    def test_all_zone_edits_require_explicit_mode_brightness_and_color(self):
        transport = ScriptedTransport([])
        for arguments in ({}, {"mode": 0}, {"mode": 0, "brightness": 25}, {"brightness": 25, "color": (1, 2, 3)}):
            with self.assertRaises(ValueError):
                Lighting(transport).set_lighting("all", **arguments)
        self.assertEqual(transport.requests, [])

    def test_invalid_inputs_do_not_touch_device(self):
        transport = ScriptedTransport([])
        for zone, arguments in [
            ("other", {}), ("logo", {"mode": 3}), ("logo", {"mode": 7}),
            ("logo", {"brightness": -1}), ("logo", {"brightness": True}),
            ("logo", {"color": (1, 2)}), ("logo", {"color": (256, 2, 3)}),
            ("logo", {"direction": 2}), ("logo", {"random": 2}),
            ("logo", {"speed": 8}), ("logo", {"expected_profile": 0}),
        ]:
            with self.assertRaises(ValueError):
                Lighting(transport).set_lighting(zone, **arguments)
        self.assertEqual(transport.requests, [])

    def test_profile_change_prevents_the_lighting_write(self):
        state3 = bytearray(STATE)
        state3[10] = 2
        steps = [(b"\x12\x00", STATE)] + read_steps(self.before) + [(b"\x12\x00", state3)]
        transport = ScriptedTransport(steps)
        with self.assertRaises(LightingError):
            Lighting(transport).set_lighting("logo", brightness=50)
        self.assertFalse(any(request.startswith(b"\x51") for request in transport.requests))

    def test_unrelated_zone_change_fails_verification_before_save(self):
        after = self.before.copy()
        after["logo"] = LightSetting(0, 50, (42, 12, 27))
        after["front"] = LightSetting(0, 0, (44, 12, 27))
        transport = ScriptedTransport(self.write_steps("51 28 00 00 00 32 2a 0c 1b 00 00 00", after))
        with self.assertRaises(LightingError):
            Lighting(transport).set_lighting("logo", brightness=50, persist=True)
        self.assertNotIn(b"\x50\x03", transport.requests)

    def test_unknown_existing_mode_is_preserved_on_read(self):
        unknown = LightSetting(0xFE, 75, (1, 2, 3), 0xAA, 0xBB, 0xCC)
        transport = ScriptedTransport([(b"\x12\x03\x00", packet(unknown))])
        self.assertEqual(Lighting(transport).read_zone("logo"), unknown)

    def test_rejects_bad_headers_truncated_data_and_invalid_brightness(self):
        for response in [b"\x12\x03", b"\xff\xaa", packet(LightSetting(0, 101, (0, 0, 0)))]:
            transport = ScriptedTransport([(b"\x12\x03\x00", response)])
            with self.assertRaises(LightingError):
                Lighting(transport).read_zone("logo")

    def test_localized_names_keep_the_same_wire_codes(self):
        self.assertEqual(effect_names("zh")[3], "彩虹")
        self.assertEqual(effect_names("en")[3], "Rainbow")
        self.assertEqual(speed_names("en"), {5: "Fast", 7: "Medium", 9: "Slow"})
        set_language("en")
        self.assertEqual(effect_label(5), "Comet")
        self.assertEqual(effect_label(0xFE), "Other effect 0xFE")
        self.assertEqual(EFFECTS[5], "彗星")
        self.assertEqual(SPEEDS[7], "中")

    def test_english_validation_and_read_errors(self):
        set_language("en")
        transport = ScriptedTransport([])
        with self.assertRaisesRegex(ValueError, "Brightness must be an integer"):
            Lighting(transport).set_lighting("logo", brightness=-1)
        with self.assertRaisesRegex(ValueError, "all zones"):
            Lighting(transport).set_lighting("logo", mode=3)
        with self.assertRaisesRegex(ValueError, "explicit effect, brightness, and color"):
            Lighting(transport).set_lighting("all")
        with self.assertRaisesRegex(ValueError, "must be logo, wheel, or front"):
            Lighting(transport).read_zone("all")
        self.assertEqual(transport.requests, [])
        failed = ScriptedTransport([(b"\x12\x03\x00", b"\xff\xaa")])
        with self.assertRaisesRegex(LightingError, "incomplete lighting data"):
            Lighting(failed).read_zone("logo")


if __name__ == "__main__":
    unittest.main()
