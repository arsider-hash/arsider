from __future__ import annotations

import os
import time

from core import Store


def main() -> None:
    store = Store(os.getenv("DB_PATH", "data/assistant.db"))
    poll = int(os.getenv("WORKER_POLL_SECONDS", "15"))
    print("lenovo worker online; no heavy jobs implemented yet", flush=True)
    while True:
        rows = store.db.execute(
            "SELECT id,text FROM tasks WHERE status='queued' AND route='lenovo' ORDER BY id LIMIT 1"
        ).fetchall()
        if not rows:
            time.sleep(poll)
            continue
        row = rows[0]
        # V0 deliberately does not execute arbitrary commands.
        # Later modules will claim explicit task types here.
        print(f"task #{row['id']} waiting for an installed Lenovo module", flush=True)
        time.sleep(poll)


if __name__ == "__main__":
    main()
