import tkinter as tk
import unittest
from contextlib import nullcontext
from unittest.mock import patch

from app import Editor, Snapshot
from buttons import SIDE_BUTTON_SLOTS
from performance import DpiPreset, ProfileState


class LiveViewTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        self.editor = Editor(self.root)
        self.editor.device = "wired"
        self.dpi = tuple(DpiPreset(v, v, (0, 0, 0)) for v in (400, 800, 3500, 3500))
        self.keys = {s.slot: 4 for s in SIDE_BUTTON_SLOTS}

    def snapshot(self, slot, profile=2):
        return Snapshot(ProfileState(profile, slot), self.dpi, self.keys)

    def test_active_marker_follows_slot_even_when_two_slots_share_dpi(self):
        e = self.editor
        e.render_snapshot(self.snapshot(3), keep_edits=False)
        self.assertTrue(e.activate_buttons[2].instate(["disabled"]))
        self.assertEqual(e.activate_buttons[2].cget("text"), "使用中")
        e.entries[0].set("750")
        e.profile.set("5")
        with patch("app.configuration_session", return_value=nullcontext(object())), \
             patch("app.read_snapshot", return_value=self.snapshot(4)):
            e.sync_visible_state()
        self.assertTrue(e.activate_buttons[2].instate(["!disabled"]))
        self.assertEqual(e.activate_buttons[3].cget("text"), "使用中")
        self.assertEqual(e.entries[0].get(), "750")
        self.assertEqual(e.profile.get(), "5")

    def test_actual_side_binding_is_independent_of_unsaved_selection(self):
        e = self.editor
        e.render_snapshot(self.snapshot(1), keep_edits=False)
        slot = SIDE_BUTTON_SLOTS[0].slot
        e.key_vars[slot].set("B")
        e.render_snapshot(self.snapshot(2), keep_edits=True)
        self.assertEqual(e.key_actual[slot].cget("text"), "A")
        self.assertEqual(e.key_vars[slot].get(), "B")
        e.render_snapshot(self.snapshot(1, profile=3), keep_edits=False)
        self.assertEqual(e.key_vars[slot].get(), "A")

    def test_disconnect_clears_active_indicator_and_poll_recovers_same_device(self):
        e = self.editor
        e.enable(True)
        e.render_snapshot(self.snapshot(2), keep_edits=False)
        e.tabs.select(e.key_tab)
        with patch("app.configuration_session", return_value=nullcontext(object())), \
             patch("app.read_snapshot", side_effect=[OSError("断开"), self.snapshot(1, profile=4)]), \
             patch.object(e.stick, "load"):
            e.sync_visible_state()
            self.assertIsNone(e.current)
            self.assertEqual(e.summary.cget("text"), "当前状态未知")
            e.sync_visible_state()
        self.assertEqual(e.tabs.select(), str(e.key_tab))
        self.assertEqual(e.profile.get(), "4")
        self.assertEqual(e.activate_buttons[0].cget("text"), "使用中")
