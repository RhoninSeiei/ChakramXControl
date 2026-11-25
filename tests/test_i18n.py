import os
from pathlib import Path
from tempfile import TemporaryDirectory
import tkinter as tk
import unittest
from unittest.mock import patch

from app import Editor
from buttons import SIDE_BUTTON_SLOTS, action_label
from i18n import get_language, load_language, save_language, set_language, system_language


class LanguageTests(unittest.TestCase):
    def test_windows_display_language(self):
        for language_id, expected in [(0x0804, "zh"), (0x0404, "zh"), (0x0c04, "zh"),
                                      (0x0409, "en"), (0x0411, "en")]:
            with self.subTest(id=language_id), patch("i18n.ctypes.windll.kernel32.GetUserDefaultUILanguage",
                                                     return_value=language_id):
                self.assertEqual(system_language(), expected)

    def test_missing_invalid_and_saved_preference(self):
        with TemporaryDirectory() as directory, patch("i18n.system_language", return_value="en"):
            path = Path(directory, "profile", "language.json")
            self.assertEqual(load_language(path), "en")
            save_language("zh", path)
            self.assertEqual(load_language(path), "zh")
            for invalid in ['"fr"', '{', '[]']:
                path.write_text(invalid, encoding="utf-8")
                self.assertEqual(load_language(path), "en")

    def test_switch_without_mouse_preserves_actions_dpi_and_tab(self):
        with TemporaryDirectory() as profile, patch.dict(os.environ, LOCALAPPDATA=profile):
            old = get_language()
            self.addCleanup(set_language, old)
            set_language("zh")
            root = tk.Tk()
            self.addCleanup(root.destroy)
            root.withdraw()
            editor = Editor(root)
            editor.enable(True)
            editor.tabs.select(editor.key_tab)
            editor.entries[1].set("1250")
            key = SIDE_BUTTON_SLOTS[0].slot
            editor.key_vars[key].set(action_label(0x01E4))
            editor.stick.keys["up"].set(action_label(0x01E5))
            for language, display, tab in [("en", "English", "Side buttons"), ("zh", "简体中文", "四个侧键")]:
                editor.language.set(display)
                with patch("app.configuration_session", side_effect=AssertionError("unexpected HID access")):
                    editor.change_language()
                self.assertEqual(load_language(), language)
                self.assertEqual(editor.tabs.tab(editor.tabs.select(), "text"), tab)
                self.assertEqual(editor.entries[1].get(), "1250")
                self.assertEqual(editor.key_vars[key].get(), action_label(0x01E4))
                self.assertEqual(editor.stick.keys["up"].get(), action_label(0x01E5))
