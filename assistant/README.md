# ARSIDER ASSISTANT V0

Telegram-first control plane for the Vivo Y29s microdatacenter.

## Core goals
- zero paid services
- exactly two authorized users
- differentiated capabilities, not two identical roots
- ON / OFF / TEST / LIVE control
- natural-language task intake
- persistent SQLite queue
- Android/Termux first
- Lenovo is optional and owner-only
- no arbitrary text-to-shell execution
- no public inbound port

The Telegram runtime uses `python-telegram-bot`; the queue/state layer remains small and local. See `SCAVENGING.md` for the permanent reuse-before-rebuild policy.

## User roles
The first account paired is `OWNER` (Emi). The second is `COLLABORATOR` (Tom).

Both can:
- ask general tasks in private;
- use Arsider group tools;
- inspect ordinary bot status/actions allowed to both users.

Only OWNER can:
- bind the Arsider group;
- create tasks routed to the Lenovo/PC worker.

The Arsider group never gets PC access. PC-bound requests must be sent in private by OWNER.

## Arsider group mode
Add the bot to the Telegram Arsider group, then OWNER sends:

```text
/bind_arsider
```

The bot stores that group ID locally. In the group it stays quiet unless:
- one of the two authorized users mentions `@botusername`, or
- one of the two authorized users replies directly to a bot message.

Group tasks are treated as shared Arsider work. Administrative controls and PC work stay in private chat.

## Telegram controls
- `/status` system state + queue
- `/on` accept new tasks
- `/off` pause automation while the remote stays alive
- `/test` private/safe mode
- `/live` select live mode for future output modules
- `/stop` stop queued work and pause intake
- `/help` tiny guide

The same controls are exposed as inline buttons in private chat. Any other text from an authorized user becomes a queued task. The V0 router labels it `vivo`, `pc`, or `unknown`; it does not execute the task yet.

## Test without Telegram

```bash
cd assistant
python -m pip install -r requirements.txt
./arsiderctl test
```

## Vivo / Termux bootstrap
From this directory on the Vivo:

```bash
bash install-termux.sh
```

The installer is safe to re-run. It installs Python, Git, FFmpeg, OpenSSH, `termux-services`, the pinned Telegram library, creates local directories, installs a supervised service in the disabled state, and runs tests.

Then put only the BotFather token in `.env`:

```text
TELEGRAM_BOT_TOKEN=...
```

Run:

```bash
arsiderctl pair
```

Pair OWNER/Emi first and COLLABORATOR/Tom second. The script writes `OWNER_ID` and `ADMIN_IDS` locally to `.env`.

Finish with:

```bash
arsiderctl health
arsiderctl start
```

Useful maintenance commands:

```bash
arsiderctl status
arsiderctl logs
arsiderctl backup
arsiderctl restart
arsiderctl stop
arsiderctl dashboard
arsiderctl update
```

## Important current state
Nothing has been installed on the Vivo yet. The phone currently has neither the bot runtime nor a local AI model from this project. The repository is only the prepared software. The local model is a later independent module and is not required for V0 Telegram control.

## Persistence on Android
`termux-services`/runit supervises the process and restarts it after a crash while Termux is alive. The installer also prepares a Termux:Boot script. Android itself can still kill background apps, so Termux:Boot must be installed/opened once and battery optimization for Termux disabled during real deployment.

## Read-only dashboard

```bash
arsiderctl dashboard
```

Default: `http://127.0.0.1:8787`. It is localhost-only by default and exposes no controls.

## Lenovo worker
`worker_lenovo.py` is deliberately dormant. It can observe jobs routed to the PC but cannot execute arbitrary commands. Future PC capabilities must be explicit tools with bounded inputs, permissions and timeouts. Only OWNER can create PC-routed jobs.

## Health and backup
`health.py` verifies runtime tools, configuration, admin count, SQLite integrity and disk headroom. `backup.py` uses SQLite's own backup API and retains a small rolling history.

## Safety rules
- unknown Telegram users are ignored;
- exactly two authorized users are accepted;
- only OWNER has PC capability;
- group chat has no PC capability;
- secrets never belong in Git;
- optional modules may fail without taking the control plane down;
- no arbitrary task text becomes a shell command;
- dashboard binds to localhost unless deliberately changed;
- LIVE mode alone grants no publication powers: output modules must be installed separately.

## Not in V0
Web research/download execution, local LLM/personality, archive/repost, audio factory, Radio Blackout recorder, computer-use and universal inbox are independent later modules. Before each one, apply `SCAVENGING.md`.
