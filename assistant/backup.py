from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path

from run import load_env


def main() -> None:
    load_env()
    src = Path(os.getenv("DB_PATH", "data/assistant.db"))
    dst_dir = Path(os.getenv("BACKUP_DIR", "backups"))
    dst_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    dst = dst_dir / f"assistant-{stamp}.db"

    if not src.exists():
        raise SystemExit(f"database not found: {src}")

    source = sqlite3.connect(src)
    target = sqlite3.connect(dst)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()

    keep = int(os.getenv("BACKUP_KEEP", "7"))
    backups = sorted(dst_dir.glob("assistant-*.db"), reverse=True)
    for old in backups[keep:]:
        old.unlink(missing_ok=True)

    print(dst)


if __name__ == "__main__":
    main()
