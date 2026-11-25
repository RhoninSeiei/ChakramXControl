import struct
import unittest

from buttons import BUTTON_SLOTS, ButtonController, ButtonProtocolError, JoystickWriteError, action_label


def group_packet(group, actions):
    packet = bytearray(64)
    packet[:3] = bytes((0x12, 0x05, group))
    # Unmapped holes must not be mistaken for the four side buttons.
    packet[4:20] = b"\xff" * 16
    for button in BUTTON_SLOTS:
        if button.group == group:
            struct.pack_into("<H", packet, 4 + button.position * 2, actions[button.slot])
    return bytes(packet)


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


class ButtonTests(unittest.TestCase):
    def setUp(self):
        self.actions = {button.slot: button.source for button in BUTTON_SLOTS}

    def test_read_primary_and_secondary_groups_skips_unmapped_holes(self):
        self.actions[10] = 0x0004
        self.actions[11] = 0x00F6
        self.actions[12] = 0x0380  # Existing custom action must survive reading.
        self.actions[13] = 0
        transport = ScriptedTransport([
            (b"\x12\x05\x00\x00\x00", group_packet(0, self.actions)),
            (b"\x12\x05\x01\x00\x00", group_packet(1, self.actions)),
        ])
        self.assertEqual(ButtonController(transport).read_bindings(), self.actions)

    def test_parse_side_buttons_from_actual_machine_capture(self):
        capture = bytes.fromhex("12 05 01 00 ff ff ff ff 2e 00 e5 01 e4 01 13 00")
        transport = ScriptedTransport([
            (b"\x12\x05\x00\x00\x00", group_packet(0, self.actions)),
            (b"\x12\x05\x01\x00\x00", capture),
        ])
        result = ButtonController(transport).read_bindings()
        self.assertEqual([result[i] for i in (10, 11, 12, 13)], [0x002E, 0x01E5, 0x01E4, 0x0013])

    def test_change_secondary_side_button_checks_before_and_after_save(self):
        self.actions[12] = 0x0004
        read = b"\x12\x05\x01\x00\x00"
        transport = ScriptedTransport([
            (bytes.fromhex("51 21 00 00 ec 01 04 00"), b"\x51\x21"),
            (read, group_packet(1, self.actions)),
            (b"\x50\x03", b"\x50\x03"),
            (read, group_packet(1, self.actions)),
        ])
        self.assertEqual(ButtonController(transport).set_binding(12, 0x0004), 0x0004)
        self.assertEqual(transport.steps, [])

    def test_failed_readback_does_not_save_wrong_binding(self):
        transport = ScriptedTransport([
            (bytes.fromhex("51 21 00 00 ea 01 04 00"), b"\x51\x21"),
            (b"\x12\x05\x01\x00\x00", group_packet(1, self.actions)),
        ])
        with self.assertRaises(ButtonProtocolError):
            ButtonController(transport).set_binding(10, 0x0004)
        self.assertNotIn(b"\x50\x03", transport.requests)

    def test_nonpersistent_change_verifies_without_save(self):
        self.actions[11] = 0x00F0
        transport = ScriptedTransport([
            (bytes.fromhex("51 21 00 00 eb 01 f0 00"), b"\x51\x21"),
            (b"\x12\x05\x01\x00\x00", group_packet(1, self.actions)),
        ])
        self.assertEqual(ButtonController(transport).set_binding(11, 0x00F0, persist=False), 0x00F0)
        self.assertEqual(transport.steps, [])

    def test_save_ack_does_not_hide_a_post_save_binding_change(self):
        changed = self.actions.copy()
        changed[10] = 0x0004
        read = b"\x12\x05\x01\x00\x00"
        transport = ScriptedTransport([
            (bytes.fromhex("51 21 00 00 ea 01 04 00"), b"\x51\x21"),
            (read, group_packet(1, changed)),
            (b"\x50\x03", b"\x50\x03"),
            (read, group_packet(1, self.actions)),
        ])
        with self.assertRaises(ButtonProtocolError):
            ButtonController(transport).set_binding(10, 0x0004)

    def test_invalid_input_does_not_send(self):
        transport = ScriptedTransport([])
        controller = ButtonController(transport)
        for slot, action in [(6, 4), (True, 4), (10, -1), (10, 65535), (10, True)]:
            with self.assertRaises(ValueError):
                controller.set_binding(slot, action)
        self.assertEqual(transport.requests, [])

    def test_rejects_wrong_group_truncated_and_error_responses(self):
        for response in [b"\x12\x05", group_packet(0, self.actions), b"\xff\xaa"]:
            transport = ScriptedTransport([(b"\x12\x05\x01\x00\x00", response)])
            with self.assertRaises(ButtonProtocolError):
                ButtonController(transport).read_binding(10)

    def test_command_rejection_stops_before_readback(self):
        transport = ScriptedTransport([(bytes.fromhex("51 21 00 00 ea 01 04 00"), b"\xff\xaa")])
        with self.assertRaises(ButtonProtocolError):
            ButtonController(transport).set_binding(10, 4)
        self.assertEqual(len(transport.requests), 1)

    def test_labels_preserve_unknown_action_identity(self):
        self.assertIn("0380", action_label(0x0380))
        self.assertEqual(action_label(4), "A")

    def test_profile_selection_uses_zero_based_wire_index_and_readback(self):
        before = bytes.fromhex("12 00 00 00 17 02 22 00 05 07 01 03 ff ff")
        after = bytearray(before)
        after[10] = 4
        transport = ScriptedTransport([
            (b"\x12\x00", before),
            (b"\x50\x02\x04", b"\x50\x02"),
            (b"\x50\x03", b"\x50\x03"),
            (b"\x12\x00", after),
        ])
        self.assertEqual(ButtonController(transport).select_profile(5, expected_profile=2), 5)

    def test_profile_changed_prevents_button_write(self):
        capture = bytes.fromhex("12 00 00 00 17 02 22 00 05 07 01 03 ff ff")
        transport = ScriptedTransport([(b"\x12\x00", capture)])
        with self.assertRaises(ButtonProtocolError):
            ButtonController(transport).set_button(10, 4, expected_profile=1)
        self.assertEqual(transport.requests, [b"\x12\x00"])

    def test_invalid_profile_selection_does_not_send(self):
        transport = ScriptedTransport([])
        for profile in (0, 6, True, 1.0):
            with self.assertRaises(ValueError):
                ButtonController(transport).select_profile(profile)
        self.assertEqual(transport.requests, [])

    def joystick_steps(self, writes):
        state = bytes.fromhex("12 00 00 00 17 02 22 00 05 07 01 03 ff ff")
        steps = [
            (b"\x12\x00", state),
            (b"\x12\x05\x00\x00\x00", group_packet(0, self.actions)),
            (b"\x12\x05\x01\x00\x00", group_packet(1, self.actions)),
        ]
        for request in writes:
            steps.extend([(b"\x12\x00", state), (bytes.fromhex(request), b"\x51\x21")])
        steps.extend([
            (b"\x12\x00", state),
            (b"\x12\x05\x00\x00\x00", group_packet(0, self.actions)),
            (b"\x12\x05\x01\x00\x00", group_packet(1, self.actions)),
        ])
        return steps

    def test_digital_joystick_maps_all_four_physical_directions(self):
        transport = ScriptedTransport(self.joystick_steps([
            "51 21 00 00 d2 01 1a 00",  # physical up -> W
            "51 21 00 00 d3 01 16 00",  # down -> S
            "51 21 00 00 d1 01 04 00",  # left -> A
            "51 21 00 00 d0 01 07 00",  # right -> D
        ]))
        wanted = {"up": 0x1A, "down": 0x16, "left": 4, "right": 7}
        self.assertEqual(ButtonController(transport).set_joystick_mode("digital", wanted), wanted)
        self.assertEqual(transport.steps, [])
        self.assertNotIn(b"\x50\x03", transport.requests)

    def test_analog_vertical_uses_native_axis_codes(self):
        transport = ScriptedTransport(self.joystick_steps([
            "51 21 00 00 d2 01 db 01",
            "51 21 00 00 d3 01 db 01",
            "51 21 00 00 d1 01 d8 01",
            "51 21 00 00 d0 01 d8 01",
        ]))
        result = ButtonController(transport).set_joystick_mode("analog_vertical")
        self.assertEqual(result, {"up": 0x1DB, "down": 0x1DB, "left": 0x1D8, "right": 0x1D8})
        self.assertEqual(transport.steps, [])

    def test_analog_horizontal_uses_native_axis_codes(self):
        transport = ScriptedTransport(self.joystick_steps([
            "51 21 00 00 d2 01 d8 01",
            "51 21 00 00 d3 01 d8 01",
            "51 21 00 00 d1 01 da 01",
            "51 21 00 00 d0 01 da 01",
        ]))
        result = ButtonController(transport).set_joystick_mode("analog_horizontal")
        self.assertEqual(result, {"up": 0x1D8, "down": 0x1D8, "left": 0x1DA, "right": 0x1DA})
        self.assertEqual(transport.steps, [])

    def test_joystick_rejects_all_invalid_directions_before_io(self):
        transport = ScriptedTransport([])
        controller = ButtonController(transport)
        for mode, bindings in [
            ("other", None), ("digital", {}),
            ("digital", {"up": 4, "down": 5, "left": -1, "right": 7}),
            ("analog_vertical", {"up": 4}),
        ]:
            with self.assertRaises(ValueError):
                controller.set_joystick_mode(mode, bindings)
        self.assertEqual(transport.requests, [])

    def test_joystick_failure_records_only_acknowledged_directions(self):
        steps = self.joystick_steps([
            "51 21 00 00 d2 01 52 00",
            "51 21 00 00 d3 01 51 00",
        ])[:7]
        steps[-1] = (steps[-1][0], b"\xff\xaa")
        transport = ScriptedTransport(steps)
        with self.assertRaises(JoystickWriteError) as result:
            ButtonController(transport).set_joystick_mode("digital")
        self.assertEqual(result.exception.accepted_bindings, {"up": 0x52})
        self.assertNotIn(b"\x50\x03", transport.requests)

    def test_joystick_detects_unrelated_side_binding_change(self):
        steps = self.joystick_steps([
            "51 21 00 00 d2 01 52 00", "51 21 00 00 d3 01 51 00",
            "51 21 00 00 d1 01 50 00", "51 21 00 00 d0 01 4f 00",
        ])
        modified = self.actions.copy()
        modified[10] = 4
        steps[-1] = (steps[-1][0], group_packet(1, modified))
        transport = ScriptedTransport(steps)
        with self.assertRaises(JoystickWriteError) as result:
            ButtonController(transport).set_joystick_mode("digital")
        self.assertEqual(len(result.exception.accepted_bindings), 4)
        self.assertNotIn(b"\x50\x03", transport.requests)


if __name__ == "__main__":
    unittest.main()
