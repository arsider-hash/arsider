from __future__ import annotations

import json
import urllib.parse
import urllib.request


class TelegramAPI:
    def __init__(self, token: str):
        self.base = f"https://api.telegram.org/bot{token}/"

    def _call(self, method: str, payload: dict | None = None, timeout: int = 35) -> dict:
        data = urllib.parse.urlencode(payload or {}).encode()
        req = urllib.request.Request(self.base + method, data=data)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))

    def get_updates(self, offset: int | None = None, timeout: int = 30) -> list[dict]:
        payload = {"timeout": timeout}
        if offset is not None:
            payload["offset"] = offset
        res = self._call("getUpdates", payload, timeout=timeout + 5)
        return res.get("result", [])

    def send_message(self, chat_id: int, text: str, keyboard: list[list[dict]] | None = None) -> None:
        payload: dict[str, object] = {"chat_id": chat_id, "text": text}
        if keyboard:
            payload["reply_markup"] = json.dumps({"inline_keyboard": keyboard})
        self._call("sendMessage", payload)

    def answer_callback(self, callback_query_id: str, text: str = "") -> None:
        self._call("answerCallbackQuery", {"callback_query_id": callback_query_id, "text": text})
