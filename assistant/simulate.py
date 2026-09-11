from __future__ import annotations

import tempfile
from pathlib import Path

from bot import Controller
from core import Store


def main() -> None:
    tmp = Path(tempfile.mkdtemp()) / "assistant.db"
    ctl = Controller(Store(str(tmp)), {1, 2})
    print("SIMULATOR // admin=1 // type 'quit' to exit")
    while True:
        text = input("> ").strip()
        if text.casefold() in {"quit", "exit"}:
            break
        print(ctl.text(1, text))


if __name__ == "__main__":
    main()
