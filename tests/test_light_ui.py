from contextlib import nullcontext
from dataclasses import replace
from types import SimpleNamespace
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import Mock, patch

from light_ui import LightingPanel
from lighting import LightSetting


class LightingPanelTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        self.frame = ttk.Frame(self.root)
        self.frame.pack(fill="both", expand=True)
        self.editor = SimpleNamespace(
            device=(b"mouse-one", 0x1A18),
            current=SimpleNamespace(state=SimpleNamespace(profile=2)),
            run=Mock(),
        )
        self.snapshot = {
            "logo": LightSetting(0, 25, (42, 12, 27)),
            "wheel": LightSetting(2, 50, (43, 12, 27)),
            "front": LightSetting(240, 75, (44, 12, 27)),
        }
        self.light = Mock()
        self.light.read_lighting.side_effect = lambda: self.snapshot.copy()
        self.perf = Mock()
        self.perf.read_state.side_effect = lambda: self.editor.current.state
        self.addCleanup(patch.stopall)
        patch("light_ui.configuration_session", side_effect=lambda _: nullcontext(object())).start()
        patch("light_ui.Lighting", return_value=self.light).start()
        patch("light_ui.Performance", return_value=self.perf).start()
        self.errors = patch("light_ui.messagebox.showerror").start()
        self.panel = LightingPanel(self.editor, self.frame)
        self.panel.load()
        self.root.update_idletasks()

    def select(self, zone):
        self.panel.zone.set(zone)
        self.panel.select_zone()

    def test_actual_table_uses_readback_and_hides_dynamic_and_off_rgb(self):
        self.assertEqual(self.panel.actual["logo"]["effect"].get(), "常亮")
        self.assertEqual(self.panel.actual["logo"]["brightness"].get(), "25%")
        self.assertEqual(self.panel.actual["logo"]["color"].get(), "#2A0C1B")
        self.assertEqual(self.panel.swatches["logo"].itemcget("sample", "fill"), "#2A0C1B")
        self.assertEqual(self.panel.actual["wheel"]["color"].get(), "动态颜色")
        self.assertEqual(self.panel.actual["front"]["color"].get(), "未点亮")
        self.assertEqual(self.panel.actual["front"]["brightness"].get(), "—")
        self.assertNotIn("#", self.panel.actual["wheel"]["color"].get())
        self.assertEqual(self.panel.swatches["wheel"].itemcget("sample", "state"), "hidden")
        self.assertEqual(self.panel.swatches["front"].itemcget("sample", "state"), "hidden")

    def test_advanced_readback_displays_animation_and_random_color(self):
        self.snapshot["logo"] = LightSetting(3, 50, (200, 12, 27), 1, 0, 9)
        self.snapshot["wheel"] = LightSetting(5, 75, (43, 12, 27), 0, 1, 0)
        self.snapshot["front"] = LightSetting(6, 25, (44, 12, 27))
        self.panel.load(preserve_draft=True)
        self.assertEqual(self.panel.actual["logo"]["animation"].get(), "逆时针，速度慢")
        self.assertEqual(self.panel.actual["logo"]["color"].get(), "动态颜色")
        self.assertEqual(self.panel.actual["wheel"]["animation"].get(), "顺时针，随机颜色")
        self.assertEqual(self.panel.actual["wheel"]["color"].get(), "随机颜色")
        self.assertEqual(self.panel.actual["front"]["color"].get(), "随电量变化")

    def test_same_readback_preserves_entry_caret_selection_and_form_layout(self):
        self.panel.hex_entry.icursor(3)
        self.panel.hex_entry.selection_range(1, 4)
        original = self.panel._form_values()
        with patch.object(self.panel, "select_zone", wraps=self.panel.select_zone) as select, \
             patch.object(self.panel, "edit_effect", wraps=self.panel.edit_effect) as layout:
            self.panel.load(preserve_draft=True)
        self.assertEqual(self.panel._form_values(), original)
        self.assertEqual(self.panel.hex_entry.index(tk.INSERT), 3)
        self.assertEqual((self.panel.hex_entry.index(tk.SEL_FIRST), self.panel.hex_entry.index(tk.SEL_LAST)), (1, 4))
        select.assert_not_called()
        layout.assert_not_called()

    def test_poll_preserves_draft_and_updates_actual_values_independently(self):
        self.panel.color.set("#123456")
        self.panel.hex_entry.icursor(4)
        self.assertIn("待保存", self.panel.draft_status.get())
        self.snapshot["wheel"] = replace(self.snapshot["wheel"], brightness=75)
        self.panel.load(preserve_draft=True)
        self.assertEqual(self.panel.color.get(), "#123456")
        self.assertEqual(self.panel.hex_entry.index(tk.INSERT), 4)
        self.assertEqual(self.panel.actual["logo"]["color"].get(), "#2A0C1B")
        self.assertEqual(self.panel.actual["wheel"]["brightness"].get(), "75%")
        self.assertTrue(self.panel.save.instate(["!disabled"]))

    def test_changed_selected_zone_blocks_stale_draft_until_reload(self):
        self.panel.color.set("#123456")
        self.snapshot["logo"] = replace(self.snapshot["logo"], brightness=50)
        self.panel.load(preserve_draft=True)
        self.assertEqual(self.panel.color.get(), "#123456")
        self.assertTrue(self.panel.save.instate(["disabled"]))
        self.assertIn("发生变化", self.panel.draft_status.get())
        self.panel.apply()
        self.editor.run.assert_not_called()
        self.errors.assert_called_once()
        self.panel.reload_zone.invoke()
        self.assertEqual(self.panel.brightness.get(), "50%")
        self.assertEqual(self.panel.color.get(), "#2A0C1B")
        self.assertNotIn("logo", self.panel.drafts)

    def test_all_zone_draft_conflicts_when_any_zone_changes(self):
        self.select("all")
        self.panel.effect.set("彩虹")
        self.snapshot["front"] = replace(self.snapshot["front"], mode=0)
        self.panel.load(preserve_draft=True)
        self.assertEqual(self.panel.effect.get(), "彩虹")
        self.assertTrue(self.panel.save.instate(["disabled"]))

    def test_switching_zones_preserves_each_zone_draft(self):
        self.panel.color.set("#123456")
        self.select("front")
        self.panel.effect.set("常亮")
        self.panel.brightness.set("100%")
        self.select("logo")
        self.assertEqual(self.panel.color.get(), "#123456")
        self.select("front")
        self.assertEqual(self.panel.effect.get(), "常亮")
        self.assertEqual(self.panel.brightness.get(), "100%")
        self.assertEqual(set(self.panel.drafts), {"logo", "front"})

    def test_profile_or_device_change_discards_prior_context_drafts(self):
        for change in (
            lambda: setattr(self.editor.current.state, "profile", 3),
            lambda: setattr(self.editor, "device", (b"mouse-two", 0x1A18)),
        ):
            self.panel.color.set("#123456")
            change()
            self.panel.load(preserve_draft=True)
            self.assertEqual(self.panel.color.get(), "#2A0C1B")
            self.assertEqual(self.panel.drafts, {})

    def test_explicit_reload_discards_drafts(self):
        self.panel.color.set("#123456")
        self.panel.load()
        self.assertEqual(self.panel.color.get(), "#2A0C1B")
        self.assertFalse(self.panel.drafts)

    def test_write_checks_original_draft_baseline_even_before_next_poll(self):
        self.panel.color.set("#123456")
        self.snapshot["logo"] = replace(self.snapshot["logo"], brightness=50)
        self.editor.run.side_effect = lambda operation, _: operation(object())
        with self.assertRaisesRegex(RuntimeError, "编辑开始后发生变化"):
            self.panel.apply()
        self.light.set_lighting.assert_not_called()
        self.assertIn("logo", self.panel.drafts)

    def test_success_clears_only_saved_zone_and_retains_other_drafts_on_poll(self):
        self.panel.color.set("#123456")
        self.select("front")
        self.panel.effect.set("常亮")
        self.panel.brightness.set("100%")
        self.select("logo")
        confirmed = self.snapshot.copy()
        confirmed["logo"] = replace(confirmed["logo"], color=(0x12, 0x34, 0x56))
        self.light.set_lighting.return_value = confirmed
        self.editor.run.side_effect = lambda operation, _: operation(object())
        self.panel.apply()
        self.assertNotIn("logo", self.panel.drafts)
        self.assertIn("front", self.panel.drafts)
        self.assertEqual(self.panel.actual["logo"]["color"].get(), "#123456")
        self.snapshot = confirmed
        self.panel.load(preserve_draft=True)
        self.select("front")
        self.assertEqual(self.panel.effect.get(), "常亮")
        self.assertEqual(self.panel.brightness.get(), "100%")
        self.assertFalse(self.panel._has_conflict())

    def test_failed_read_clears_current_display_and_retains_draft_for_recovery(self):
        self.panel.color.set("#123456")
        self.light.read_lighting.side_effect = TimeoutError("超时")
        self.panel.load(preserve_draft=True)
        self.assertEqual(self.panel.actual["logo"]["color"].get(), "—")
        self.assertTrue(self.panel.save.instate(["disabled"]))
        self.assertIn("logo", self.panel.drafts)
        self.light.read_lighting.side_effect = lambda: self.snapshot.copy()
        self.panel.load(preserve_draft=True)
        self.assertEqual(self.panel.color.get(), "#123456")
        self.assertTrue(self.panel.save.instate(["!disabled"]))


if __name__ == "__main__":
    unittest.main()
