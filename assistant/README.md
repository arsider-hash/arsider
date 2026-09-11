# ARSIDER ASSISTANT V0

Minimal Telegram-first control plane for the Vivo Y29s microdatacenter.

## Goals
- zero paid services
- two authorized admins only
- ON / OFF / TEST / LIVE control
- natural-language task intake
- SQLite task queue
- stdlib-only Python core
- Android/Termux first
- Lenovo is an optional worker, never the always-on brain

## V0 commands
- `/status` system state + queue
- `/on` accept new tasks
- `/off` pause automation, keep remote control alive
- `/test` replies only to admins/private test flow
- `/live` enable live destination mode later
- `/stop` pause and mark queued work stopped
- `/help` tiny guide

Any non-command text from an authorized admin becomes a queued task. A lightweight router classifies it as `vivo`, `lenovo`, or `unknown` without using an LLM.

## Local simulation first
No Telegram token is needed to test the core:

```bash
cd assistant
python simulate.py
python -m unittest discover -s tests -v
```

## Termux install
Later, on the Vivo:

```bash
bash install-termux.sh
```

Copy `.env.example` to `.env`, set `TELEGRAM_BOT_TOKEN` and exactly two Telegram numeric user IDs, then:

```bash
python run.py
```

## Read-only dashboard
The dashboard is deliberately local and dependency-free:

```bash
python dashboard.py
```

Default address: `http://127.0.0.1:8787`. It shows system mode, queue depth and recent tasks. Network exposure can be enabled later deliberately; V0 does not expose it by default.

## Lenovo worker
`worker_lenovo.py` is intentionally dormant in V0. It can see tasks routed to the Lenovo, but it does not execute arbitrary shell commands. Future modules will explicitly claim safe task types. This keeps the laptop idle and prevents the control plane from becoming a remote-shell accident.

## Safety / design rules
- Modules fail independently.
- The Telegram control plane remains reachable when optional modules fail.
- No secrets belong in Git.
- Unknown users are ignored.
- The core never executes arbitrary text as shell commands.
- Expensive work must be delegated explicitly, never inferred silently.

## Scope after V0
Planned modules can be added independently: web/download, files, local personality engine, Arsider archive/repost, audio tools, Radio Blackout recorder/escopost recovery, and later the universal inbox bridge.
