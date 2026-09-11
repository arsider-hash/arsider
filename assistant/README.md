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

Any non-command text from an authorized admin becomes a queued task. A lightweight router classifies it as `vivo`, `pc`, or `unknown` without using an LLM.

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

Copy `.env.example` to `.env`, set `TELEGRAM_BOT_TOKEN` and the two Telegram numeric user IDs, then:

```bash
python run.py
```

## Design rule
Modules must fail independently. The bot/control plane must stay reachable even if web, AI, audio, archive, or PC workers are unavailable.
