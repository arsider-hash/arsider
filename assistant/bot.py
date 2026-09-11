from __future__ import annotations

from core import Store, is_admin
from router import route_task, route_reason


MAIN_KB = [
    [{"text": "STATO", "callback_data": "status"}, {"text": "ACCENDI", "callback_data": "on"}],
    [{"text": "SPEGNI", "callback_data": "off"}, {"text": "TEST", "callback_data": "test"}],
    [{"text": "LIVE", "callback_data": "live"}, {"text": "STOP", "callback_data": "stop"}],
    [{"text": "AIUTO", "callback_data": "help"}],
]

HELP = (
    "ARSIDER ASSISTANT\n\n"
    "ACCENDI: accetta nuovi task.\n"
    "SPEGNI: pausa l'automazione ma il telecomando resta vivo.\n"
    "TEST: nessuna pubblicazione esterna.\n"
    "LIVE: abilita destinazioni reali quando verranno configurate.\n"
    "STATO: salute + coda.\n"
    "STOP: ferma i task in coda.\n\n"
    "Per creare un task basta scrivere normalmente."
)


class Controller:
    def __init__(self, store: Store, admins: set[int]):
        self.store = store
        self.admins = admins

    def status(self) -> str:
        recent = self.store.recent_tasks(3)
        lines = [
            "ARSIDER // CONTROL",
            "",
            f"SYSTEM  {'🟢 ON' if self.store.get('system') == 'ON' else '⚫ OFF'}",
            f"MODE    {self.store.get('mode', 'TEST')}",
            f"QUEUE   {self.store.queued_count()}",
            f"ADMINS  {len(self.admins)} / 2 configured",
        ]
        if recent:
            lines += ["", "RECENT"]
            for t in recent:
                preview = t.text.replace("\n", " ")[:45]
                lines.append(f"#{t.id} {t.route.upper()} {t.status} · {preview}")
        return "\n".join(lines)

    def action(self, user_id: int, action: str) -> str:
        if not is_admin(user_id, self.admins):
            return ""
        if action == "status":
            return self.status()
        if action == "on":
            self.store.set("system", "ON")
            return "🟢 Sistema attivo. Accetto nuovi task."
        if action == "off":
            self.store.set("system", "OFF")
            return "⚫ Automazione spenta. Telecomando ancora raggiungibile."
        if action == "test":
            self.store.set("mode", "TEST")
            return "🧪 Modalità TEST."
        if action == "live":
            self.store.set("mode", "LIVE")
            return "🔴 Modalità LIVE selezionata. Le destinazioni reali saranno abilitate solo quando configurate."
        if action == "stop":
            self.store.set("system", "OFF")
            n = self.store.stop_queued()
            return f"STOP eseguito. {n} task in coda fermati. Telecomando attivo."
        if action == "help":
            return HELP
        return "Comando sconosciuto."

    def text(self, user_id: int, text: str) -> str:
        if not is_admin(user_id, self.admins):
            return ""
        cmd = text.strip().casefold()
        mapping = {
            "/status": "status", "/on": "on", "/off": "off", "/test": "test",
            "/live": "live", "/stop": "stop", "/help": "help", "/start": "status",
        }
        if cmd in mapping:
            return self.action(user_id, mapping[cmd])
        if self.store.get("system") != "ON":
            return "Sistema OFF. Premi ACCENDI prima di affidarmi un nuovo task."
        route = route_task(text)
        task_id = self.store.add_task(user_id, text, route)
        return f"TASK #{task_id} acquisito\nROUTE: {route.upper()}\n{route_reason(route)}"
