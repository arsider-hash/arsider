from __future__ import annotations

import tempfile
from pathlib import Path

from bot import Controller
from core import Store


def main() -> None:
    tmp = Path(tempfile.mkdtemp()) / "assistant.db"
    ctl = Controller(Store(str(tmp)), {1, 2}, owner_id=1)
    print("SIMULATOR // owner=1 collaborator=2 // type 'quit' to exit")
    while True:
        try:
            text = input("> ").strip()
        except EOFError:
            break
        if text.casefold() in {"quit", "exit"}:
            break
        print(ctl.text(1, text))


if __name__ == "__main__":
    main()
