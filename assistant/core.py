from __future__ import annotations

import os
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class Task:
    id: int
    created_at: int
    user_id: int
    text: str
    route: str
    status: str


class Store:
    def __init__(self, path: str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path)
        self.db.row_factory = sqlite3.Row
        self._init()

    def _init(self) -> None:
        self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS kv (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                text TEXT NOT NULL,
                route TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'queued'
            );
            """
        )
        self.db.commit()
        self.set_default("system", "OFF")
        self.set_default("mode", os.getenv("DEFAULT_MODE", "TEST").upper())

    def set_default(self, key: str, value: str) -> None:
        self.db.execute("INSERT OR IGNORE INTO kv(key,value) VALUES (?,?)", (key, value))
        self.db.commit()

    def get(self, key: str, default: str = "") -> str:
        row = self.db.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        return row[0] if row else default

    def set(self, key: str, value: str) -> None:
        self.db.execute(
            "INSERT INTO kv(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        self.db.commit()

    def add_task(self, user_id: int, text: str, route: str) -> int:
        cur = self.db.execute(
            "INSERT INTO tasks(created_at,user_id,text,route,status) VALUES (?,?,?,?, 'queued')",
            (int(time.time()), user_id, text.strip(), route),
        )
        self.db.commit()
        return int(cur.lastrowid)

    def recent_tasks(self, limit: int = 5) -> list[Task]:
        rows = self.db.execute(
            "SELECT id,created_at,user_id,text,route,status FROM tasks ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [Task(**dict(r)) for r in rows]

    def queued_count(self) -> int:
        return int(self.db.execute("SELECT COUNT(*) FROM tasks WHERE status='queued'").fetchone()[0])

    def stop_queued(self) -> int:
        cur = self.db.execute("UPDATE tasks SET status='stopped' WHERE status='queued'")
        self.db.commit()
        return int(cur.rowcount)


def parse_admins(raw: str | None) -> set[int]:
    if not raw:
        return set()
    out: set[int] = set()
    for item in raw.split(","):
        item = item.strip()
        if item:
            out.add(int(item))
    return out


def is_admin(user_id: int, admins: Iterable[int]) -> bool:
    return user_id in set(admins)
