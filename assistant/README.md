# ARSIDER ASSISTANT V0

Telegram-first control plane for the Vivo Y29s microdatacenter.

## Core goals
- zero paid services
- exactly two authorized admins
- ON / OFF / TEST / LIVE control
- natural-language task intake
- persistent SQLite queue
- Android/Termux first
- Lenovo is optional and idle unless explicitly needed
- no arbitrary text-to-shell execution
- no public inbound port

The Telegram runtime uses `python-telegram-bot`; the queue/state layer remains small and local. See `SCAVENGING.md` for the permanent reuse-before-rebuild policy.

## Telegram controls
- `/status` system state + queue
- `/on` accept new tasks
- `/off` pause automation while the remote stays alive
- `/test` private/safe mode
- `/live` select live mode for future output modules
- `/stop` stop queued work and pause intake
- `/help` tiny guide

The same controls are exposed as inline buttons. Any other text from an authorized admin becomes a queued task. The V0 router labels it `vivo`, `pc`, or `unknown`; it does not execute the task yet.

## Test without Telegram

```bash
cd assistant
python -m pip install -r requirements.txt
arsiderctl test
```

or:

```bash
python -m unittest discover -s tests -v
printf '/status\n/on\ntrovami un pdf\n/stop\nquit\n' | python simulate.py
```

## Vivo / Termux bootstrap
From this directory on the Vivo:

```bash
bash install-termux.sh
```

The installer is intended to be safe to re-run. It installs Python, Git, FFmpeg, OpenSSH, `termux-services`, the pinned Telegram library, creates local directories, installs a supervised service in the disabled state, and runs tests.

Then the only secret you enter manually is the BotFather token in `.env`:

```text
TELEGRAM_BOT_TOKEN=...
```

Do not manually hunt for Telegram numeric user IDs. Run:

```bash
arsiderctl pair
```

It prints a one-time code. Send `/pair CODE` to the bot from the two authorized Telegram accounts. Their IDs are written locally to `.env`, which is kept out of Git and restricted to the local user.

Finish with:

```bash
arsiderctl health
arsiderctl start
```

Useful local maintenance commands:

```bash
arsiderctl status
arsiderctl logs
arsiderctl backup
arsiderctl restart
arsiderctl stop
arsiderctl dashboard
```

## Persistence on Android
`termux-services`/runit supervises the process and restarts it after a crash while Termux is alive. The installer also prepares a Termux:Boot script. Android itself can still kill background apps, so the official Termux:Boot add-on must be installed/opened once and battery optimization for Termux should be disabled during real deployment. Boot persistence is treated as recoverable infrastructure, not magic.

## Read-only dashboard

```bash
arsiderctl dashboard
```

Default: `http://127.0.0.1:8787`. It is localhost-only by default and exposes no controls.

## Lenovo worker
`worker_lenovo.py` is deliberately dormant. It can observe jobs routed to the PC but cannot execute arbitrary commands. Future PC capabilities must be explicit tools with bounded inputs, permissions and timeouts.

## Health and backup
`health.py` verifies runtime tools, configuration, admin count, SQLite integrity and disk headroom. `backup.py` uses SQLite's own backup API and retains a small rolling history.

## Safety rules
- unknown Telegram users are ignored;
- exactly two admins are accepted;
- secrets never belong in Git;
- optional modules may fail without taking the control plane down;
- no arbitrary task text becomes a shell command;
- expensive work is delegated explicitly;
- dashboard binds to localhost unless deliberately changed;
- LIVE mode by itself does not magically grant publication powers: output modules must be installed separately.

## Not in V0
Web research/download execution, local LLM/personality, archive/repost, audio factory, Radio Blackout recorder, computer-use and universal inbox are independent later modules. Before each one, apply `SCAVENGING.md`.
