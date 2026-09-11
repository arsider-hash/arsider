from __future__ import annotations

import os
import shutil
import sqlite3
import sys
from pathlib import Path

from core import Store, parse_admins
from run import load_env


def check() -> tuple[bool, list[str]]:
    load_env()
    lines: list[str] = []
    ok = True

    lines.append(f"python={sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")
    if sys.version_info < (3, 11):
        ok = False
        lines.append("FAIL python>=3.11 required")

    for tool in ("git", "ffmpeg", "ssh"):
        present = bool(shutil.which(tool))
        lines.append(f"{tool}={'OK' if present else 'MISSING'}")
        ok &= present

    token = bool(os.getenv("TELEGRAM_BOT_TOKEN", "").strip())
    admins = parse_admins(os.getenv("ADMIN_IDS"))
    lines.append(f"telegram_token={'SET' if token else 'MISSING'}")
    lines.append(f"admins={len(admins)}/2")
    ok &= token and len(admins) == 2

    db_path = os.getenv("DB_PATH", "data/assistant.db")
    try:
        store = Store(db_path)
        result = store.db.execute("PRAGMA integrity_check").fetchone()[0]
        lines.append(f"sqlite={result}")
        ok &= result == "ok"
    except sqlite3.Error as exc:
        lines.append(f"FAIL sqlite={exc}")
        ok = False

    usage = shutil.disk_usage(Path(db_path).parent)
    free_mb = usage.free // (1024 * 1024)
    lines.append(f"disk_free_mb={free_mb}")
    if free_mb < 512:
        lines.append("WARN disk below 512 MB")

    return ok, lines


def main() -> None:
    ok, lines = check()
    print("ARSIDER // HEALTH")
    print("\n".join(lines))
    print("RESULT=" + ("OK" if ok else "NOT_READY"))
    raise SystemExit(0 if ok else 2)


if __name__ == "__main__":
    main()
