from __future__ import annotations

import html
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from core import Store


def render(store: Store) -> bytes:
    tasks = store.recent_tasks(8)
    rows = "".join(
        f"<tr><td>#{t.id}</td><td>{html.escape(t.route)}</td><td>{html.escape(t.status)}</td><td>{html.escape(t.text[:80])}</td></tr>"
        for t in tasks
    ) or "<tr><td colspan='4'>no tasks</td></tr>"
    system = html.escape(store.get("system", "OFF"))
    mode = html.escape(store.get("mode", "TEST"))
    body = f"""<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>ARSIDER CONTROL</title><style>
body{{background:#0b0d0f;color:#d7ffd9;font:15px monospace;margin:0;padding:24px}}main{{max-width:900px;margin:auto}}h1{{font-size:20px;letter-spacing:.18em}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px}}.box{{border:1px solid #405047;padding:14px}}.on{{font-size:24px}}table{{width:100%;border-collapse:collapse;margin-top:18px}}td,th{{border-bottom:1px solid #28322d;padding:9px;text-align:left}}small{{opacity:.6}}</style></head><body><main>
<h1>ARSIDER // CONTROL</h1><div class='grid'><div class='box'>SYSTEM<div class='on'>{system}</div></div><div class='box'>MODE<div class='on'>{mode}</div></div><div class='box'>QUEUE<div class='on'>{store.queued_count()}</div></div></div>
<table><thead><tr><th>TASK</th><th>ROUTE</th><th>STATE</th><th>TEXT</th></tr></thead><tbody>{rows}</tbody></table><p><small>read-only local status // refresh page to update</small></p></main></body></html>"""
    return body.encode("utf-8")


def main() -> None:
    db_path = os.getenv("DB_PATH", "data/assistant.db")
    host = os.getenv("DASHBOARD_HOST", "127.0.0.1")
    port = int(os.getenv("DASHBOARD_PORT", "8787"))
    store = Store(db_path)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path not in ("/", "/status"):
                self.send_error(404)
                return
            data = render(store)
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, fmt, *args):
            return

    print(f"dashboard: http://{host}:{port}", flush=True)
    ThreadingHTTPServer((host, port), Handler).serve_forever()


if __name__ == "__main__":
    main()
