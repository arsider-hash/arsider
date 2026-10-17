# Security boundaries

V0 is a control plane, not a remote shell.

- Only exactly two Telegram user IDs are accepted after one-shot pairing.
- Unknown users receive no operational response.
- Task text is stored as data and is never passed to a shell.
- LIVE is only a state flag; modules must separately implement and authorize external actions.
- Dashboard binds to localhost by default and is read-only.
- Telegram uses outbound long polling; no public inbound port is required.
- `.env`, local databases, backups and logs stay out of Git.
- Lenovo capabilities must be explicit named tools with bounded arguments, timeouts and failure isolation.
- Financial accounts, password stores and other high-impact personal administration are outside the intended capability set.

## Recovery order
1. `arsiderctl status`
2. `arsiderctl health`
3. `arsiderctl logs`
4. `arsiderctl restart`
5. if code changed: `arsiderctl update`
6. if the database is damaged, stop the service and restore the newest known-good file from `backups/`

Never solve a failure by deleting `.env` or the database before making a copy.
