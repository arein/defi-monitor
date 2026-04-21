# CLAUDE.md

Project-local instructions for Claude Code when working in `~/Code/defi-monitor`.

## 🎯 What this repo is

A single Claude Code skill (`.claude/skills/defi-monitor/`) that archives the **ETHSecurity Community** Telegram channel into per-day markdown logs and produces a prose digest of DeFi security events. See [`PLAN.md`](./PLAN.md) for full design.

## 🕐 Timezone

**All day boundaries are UTC+7** (Derek's local). A log file named `logs/2026-04-19.md` contains messages whose Telegram timestamps fall within `2026-04-19 00:00 UTC+7` through `2026-04-19 23:59 UTC+7` - equivalently, `2026-04-18 17:00 UTC` through `2026-04-19 16:59 UTC`.

When reading timestamps inside messages, UTC timestamps are the canonical source; UTC+7 is only used for day-grouping.

## 📄 Log file format

Each `logs/YYYY-MM-DD.md` has exactly this shape:

```markdown
# YYYY-MM-DD (UTC+7)

<!-- digest:start -->
## Digest

_generated <timestamp> from N messages_

<prose digest or "_not yet generated_">
<!-- digest:end -->

<!-- raw:start -->
## Raw messages

_last synced <timestamp> (last_msg_id=<id>)_

- **HH:MM:SS** `sender`: message text
- **HH:MM:SS** `sender`: ...
<!-- raw:end -->
```

**Rules enforced by the sync script:**
- Both `digest:` and `raw:` marker blocks must exist on disk even when empty
- `sync` only writes between `raw:start` and `raw:end`
- `digest` only writes between `digest:start` and `digest:end`
- Raw messages are ordered oldest-first and deduped by Telegram message ID

## 🔧 Telegram CLI

This project runs anywhere the `telegram` CLI (v0.9+) is installed and authenticated. We use a portable resolution order inside `scripts/sync.py`:

1. `TELEGRAM_BIN` env var (absolute path override - set this in systemd units, crontabs, or Dockerfiles)
2. `telegram` on `PATH` (covers Homebrew on macOS - `/opt/homebrew/bin/telegram` - and standard Linux installs - `/usr/local/bin/telegram` via `npm -g`, etc.)

Each host needs its own authenticated session (the CLI keeps a local TDLib DB). That's a one-time setup per machine, out of scope for this repo.

Relevant subcommands:

- `telegram read "ETHSecurity Community" --since <N>d -n <limit> --json` - fetch messages. Messages come back newest-first.
- `telegram chats --limit 1000 --json` - list all chats (used to verify the channel name hasn't changed).

**stdout is polluted** with ANSI-colored log lines (INFO/WARN) from gramJS. The sync script filters these before JSON parsing - see `scripts/sync.py` for the extraction pattern.

`--since` takes offsets (`"7d"`, `"1h"`), not absolute dates. For first-run history depth we default to 7 days.

## 🎛️ Skill conventions

- `/defi-monitor` with no args prints status (last sync, date range archived, dates missing digest)
- Sync is always incremental via `.sync-state.json`. Delete that file to force a wider re-fetch on next run.
- Digests are written by Claude itself within the session (via Read + Write tools), guided by the prompt in `SKILL.md`. There's no Python LLM wrapper - the session IS the derivation engine.
- Replay MUST preserve the raw block byte-for-byte. Only the digest block is rewritten.

## ✍️ Style when generating digests

- Present tense for live incidents, past for retrospectives
- Name participants by their chat handle (no `@`; Telegram senders don't use handles)
- No hedging; no em-dashes; no marketing language; no financial advice
- Cite external links inline as `([post-mortem](url))` so the reader can follow up
