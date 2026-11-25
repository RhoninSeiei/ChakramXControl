"""Last submitted joystick layout, kept separately for each device and profile."""

import os
import sqlite3
from contextlib import closing
from pathlib import Path
from i18n import tr


class StickRecord:
    def __init__(self, path=None):
        self.path = path or Path(os.environ["LOCALAPPDATA"]) / "ChakramXControl" / "settings.sqlite3"

    def _connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path)
        db.execute("""CREATE TABLE IF NOT EXISTS layouts(
            device TEXT, profile INTEGER, mode TEXT, k1 INTEGER, k2 INTEGER, k3 INTEGER, k4 INTEGER,
            PRIMARY KEY(device, profile))""")
        return db

    def read(self, device, profile):
        if not self.path.exists():
            return None
        with closing(self._connect()) as db:
            return db.execute("SELECT mode,k1,k2,k3,k4 FROM layouts WHERE device=? AND profile=?",
                              (device, profile)).fetchone()

    def save(self, device, profile, mode, keys=None):
        if keys is not None and len(keys) != 4:
            raise ValueError(tr("需要四个方向的映射。", "Bindings for all four directions are required."))
        with closing(self._connect()) as db, db:
            db.execute("""INSERT INTO layouts VALUES(?,?,?,?,?,?,?)
                ON CONFLICT(device,profile) DO UPDATE SET mode=excluded.mode,
                k1=coalesce(excluded.k1,k1), k2=coalesce(excluded.k2,k2),
                k3=coalesce(excluded.k3,k3), k4=coalesce(excluded.k4,k4)""",
                (device, profile, mode, *(keys or (None,) * 4)))
