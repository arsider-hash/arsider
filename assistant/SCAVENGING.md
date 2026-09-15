# ARSIDER SCAVENGING PROTOCOL

This is an architectural rule, not a one-off research step.

Before implementing any non-trivial feature:

1. Search for mature, actively maintained implementations and libraries.
2. Inspect failure handling, lifecycle, security boundaries and deployment model.
3. Prefer, in order:
   - reuse a mature dependency when it removes significant maintenance;
   - extract a proven pattern when the dependency is too heavy;
   - build locally only when the existing options violate project constraints.
4. Reject technology that adds more operational weight than capability.
5. Never import an entire agent stack just because one component is useful.
6. Keep optional modules independently removable and independently fail-able.
7. Every dependency must justify itself against the stdlib/local alternative.

## Acceptance filter
A candidate should normally satisfy most of:
- free/open source;
- actively maintained;
- works without a paid cloud dependency;
- low idle CPU/RAM;
- compatible with Android/Termux or the optional Lenovo worker;
- understandable recovery path;
- no inbound public ports unless strictly necessary;
- secrets can remain local;
- does not force the core to depend on it.

## Current scavenged decisions
- `python-telegram-bot`: reuse. Mature Telegram lifecycle/error handling is worth one dependency.
- SQLite queue: keep local implementation. Existing lightweight queues validate the architecture; a queue framework is unnecessary at V0 scale.
- `termux-services`/runit: reuse for service supervision.
- Termux:Boot: optional boot trigger only. Do not treat Android boot persistence as infallible.
- Desktop/computer-use agents: study patterns, do not import wholesale. Lenovo execution remains explicit-tool-only.

When a new module is proposed, document the scavenged alternatives before merging it.
