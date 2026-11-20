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


def write_pairing(ids: list[int], path: Path) -> None:
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    values = {
        "ADMIN_IDS": ",".join(map(str, ids)),
        "OWNER_ID": str(ids[0]),
    }
    seen: set[str] = set()
    out: list[str] = []
    for line in lines:
        key = line.split("=", 1)[0] if "=" in line else ""
        if key in values:
            out.append(f"{key}={values[key]}")
            seen.add(key)
        else:
            out.append(line)
    for key, value in values.items():
        if key not in seen:
            out.append(f"{key}={value}")
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
    print("IMPORTANT: pair C FIRST, T SECOND.")
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
            role = "C" if len(found) == 1 else "T"
            api(token, "sendMessage", chat_id=msg["chat"]["id"], text=f"Paired {role} ({len(found)}/2).")
            print(f"paired {role}: {uid}")

    write_pairing(found, Path(".env"))
    print("\nPairing complete. Local role IDs written to .env; pairing code is now dead.")
    print("Start with: arsiderctl start")


if __name__ == "__main__":
    main()
