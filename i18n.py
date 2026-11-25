"""UI language selection and per-user preferences."""

import ctypes
import json
import locale
import os
from pathlib import Path
from tempfile import NamedTemporaryFile


LANGUAGES = {"zh": "简体中文", "en": "English"}
_language = "zh"


def system_language():
    try:
        lang_id = ctypes.windll.kernel32.GetUserDefaultUILanguage()
        if lang_id:
            # Primary language 0x04 covers all Chinese regions and scripts.
            return "zh" if lang_id & 0x3FF == 0x04 else "en"
    except (AttributeError, OSError):
        pass
    name = locale.getlocale()[0] or ""
    return "zh" if name.lower().replace("-", "_").split("_")[0] == "zh" else "en"


def preference_file():
    return Path(os.environ["LOCALAPPDATA"]) / "ChakramXControl" / "language.json"


def load_language(path=None):
    try:
        value = json.loads((path or preference_file()).read_text(encoding="utf-8"))
        if isinstance(value, str) and value in LANGUAGES:
            return value
    except (OSError, UnicodeError, ValueError):
        pass
    return system_language()


def save_language(language, path=None):
    if language not in LANGUAGES:
        raise ValueError(language)
    path = path or preference_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = None
    try:
        with NamedTemporaryFile(mode="w", dir=path.parent, delete=False, encoding="utf-8") as out:
            temp = Path(out.name)
            json.dump(language, out)
        os.replace(temp, path)
    finally:
        if temp:
            temp.unlink(missing_ok=True)


def get_language():
    return _language


def set_language(language):
    global _language
    if language not in LANGUAGES:
        raise ValueError(language)
    _language = language


def tr(zh, en, **values):
    text = zh if _language == "zh" else en
    return text.format(**values) if values else text


def bind_text(widget, zh, en):
    widget._ui_text = (zh, en)
    widget.configure(text=tr(zh, en))
    return widget


def refresh_text(widget):
    if hasattr(widget, "_ui_text"):
        widget.configure(text=tr(*widget._ui_text))
    for child in widget.winfo_children():
        refresh_text(child)
