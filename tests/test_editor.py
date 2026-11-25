import tkinter as tk
import unittest
from contextlib import nullcontext
from unittest.mock import patch

from app import Editor


class EditorTabsTests(unittest.TestCase):
    def test_compatibility_checkbox_uses_firmware_and_hides_gamepad_when_checked(self):
        root = tk.Tk()
        root.withdraw()
        self.addCleanup(root.destroy)
        editor = Editor(root)
        panel = editor.stick
        flag = [False]
        # Simulate a delay before Windows removes the gamepad collection.
        with patch("stick_ui.configuration_session", return_value=nullcontext(object())), \
             patch("stick_ui.gamepad_flag", side_effect=lambda _: flag[0]), \
             patch("stick_ui.gamepad_present", return_value=True), \
             patch("stick_ui.ensure_gamepad", side_effect=lambda _, enable: flag.__setitem__(0, enable)):
            panel.refresh_compatibility()
            self.assertTrue(panel.compatibility.get())
            self.assertIn("已识别", panel.info.get())
            panel.toggle.invoke()
            self.assertTrue(flag[0])
            self.assertFalse(panel.compatibility.get())
            panel.toggle.invoke()
            self.assertFalse(flag[0])
            self.assertTrue(panel.compatibility.get())

    def test_device_connection_displays_editor_and_reconnect_restores_a_tab(self):
        root = tk.Tk()
        root.withdraw()
        try:
            editor = Editor(root)
            editor.enable(True)
            self.assertEqual(editor.tabs.select(), str(editor.dpi_tab))
            editor.tabs.select(editor.stick_tab)
            editor.enable(True)
            self.assertEqual(editor.tabs.select(), str(editor.stick_tab))
            editor.enable(False)
            editor.enable(True)
            self.assertEqual(editor.tabs.select(), str(editor.dpi_tab))
        finally:
            root.destroy()

    def test_unreadable_compatibility_flag_is_unknown_until_refresh(self):
        root = tk.Tk()
        root.withdraw()
        self.addCleanup(root.destroy)
        panel = Editor(root).stick
        with patch("stick_ui.configuration_session", return_value=nullcontext(object())), \
             patch("stick_ui.gamepad_flag", side_effect=[TimeoutError("超时"), True]), \
             patch("stick_ui.gamepad_present", return_value=True):
            panel.refresh_compatibility()
            self.assertTrue(panel.toggle.instate(["disabled", "alternate"]))
            panel.refresh_compatibility()
            self.assertTrue(panel.toggle.instate(["!disabled", "!alternate"]))
            self.assertFalse(panel.compatibility.get())
