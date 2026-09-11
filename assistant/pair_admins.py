from __future__ import annotations

import json
import os
import secrets
import urllib.parse
import urllib.request
from pathlib import Path

from run import load_env


def api(token: str, method: str, **params):
    data = urllib.parse.urlencode(params).encode()
    with urllib.request.urlopen(f"https://api.telegram.org/bot{token}/{method}", data=data, timeout=40) as r:
        payload = json.load(r)
    if not payload.get("ok"):
        raise RuntimeError(payload)
    return payload["result"]


def write_admins(ids: list[int], path: Path) -> None:
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    out = []
    replaced = False
    for line in lines:
        if line.startswith("ADMIN_IDS="):
            out.append("ADMIN_IDS=" + ",".join(map(str, ids)))
            replaced = True
        else:
            out.append(line)
    if not replaced:
        out.append("ADMIN_IDS=" + ",".join(map(str, ids)))
    path.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass


def main() -> None:
    load_env()
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise SystemExit("Set TELEGRAM_BOT_TOKEN in .env first.")

    code = secrets.token_hex(4).upper()
    print("ARSIDER // ADMIN PAIRING")
    print(f"Send /pair {code} to the bot from exactly TWO Telegram accounts.")
    print("The code is valid only while this program is running.\n")

    found: list[int] = []
    offset = None
    while len(found) < 2:
        args = {"timeout": 30}
        if offset is not None:
            args["offset"] = offset
        updates = api(token, "getUpdates", **args)
        for u in updates:
            offset = u["update_id"] + 1
            msg = u.get("message") or {}
            sender = msg.get("from") or {}
            text = (msg.get("text") or "").strip()
            if text != f"/pair {code}" or "id" not in sender:
                continue
            uid = int(sender["id"])
            if uid in found:
                continue
            found.append(uid)
            api(token, "sendMessage", chat_id=msg["chat"]["id"], text=f"Paired admin {len(found)}/2.")
            print(f"paired {len(found)}/2: {uid}")

    write_admins(found, Path(".env"))
    print("\nPairing complete. ADMIN_IDS written to .env; pairing code is now dead.")
    print("Start with: arsiderctl start")


if __name__ == "__main__":
    main()
