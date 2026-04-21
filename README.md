# 🛡️ defi-monitor

A Claude Code skill that archives the **ETHSecurity Community** Telegram channel into per-day markdown logs and derives a prose digest of DeFi security events.

No servers, no DB, no auth. Just a local repo + the `telegram` CLI + Claude Code.

## 🚀 Quick start

```bash
cd ~/Code/defi-monitor
claude                 # opens Claude Code in this repo, auto-loads the skill
```

Then in the Claude Code session:

```
/defi-monitor sync
/defi-monitor replay 2026-04-19 2026-04-19
```

## 📦 What's in the repo

| Path | What it does |
|---|---|
| `.claude/skills/defi-monitor/SKILL.md` | The skill prompt — dispatches on `sync` / `digest` / `replay` |
| `scripts/sync.py` | Incremental Telegram fetch, partitions messages by UTC+7 day, appends to per-day logs |
| `logs/YYYY-MM-DD.md` | One file per day: raw messages on the bottom, prose digest on top |
| `.sync-state.json` | Checkpoint of the last synced message ID (gitignored) |
| `PLAN.md` | Design doc |
| `CLAUDE.md` | Project conventions for Claude Code |

## 🔑 Prerequisites

- **`telegram` CLI authenticated** — `/opt/homebrew/bin/telegram` v0.9+ (run `telegram chats` to verify your session is live)
- **Python 3.9+** on `python3` — used only for the sync script (no third-party deps)
- **Claude Code** — the skill runs inside a Claude Code session

## 📖 See also

- [`PLAN.md`](./PLAN.md) — full design rationale
- [`CLAUDE.md`](./CLAUDE.md) — project conventions (timezone, log format)
