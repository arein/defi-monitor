# CLAUDE.md

Project-local instructions for Claude Code when working in the `defi-monitor` repo.

## 🎯 What this repo is

A single Claude Code skill (`.claude/skills/defi-monitor/`) that archives the **ETHSecurity Community** Telegram channel into per-day markdown logs and produces a prose digest of DeFi security events. A companion script aggregates "noteworthy events" across every day's digest into a global `EVENTS.md` at the repo root. See [`SKILL.md`](./.claude/skills/defi-monitor/SKILL.md) for operational details.

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

<!-- events:start -->
[
  {"severity":"high","type":"exploit","protocol":"Kelp DAO","title":"rsETH LayerZero DVN exploit","participants":["banteg"]}
]
<!-- events:end -->

### Headline
<prose>

### Incidents
<prose>

### Discussion
<prose>

<!-- digest:end -->

<!-- raw:start -->
## Raw messages

_last synced <timestamp> (last_msg_id=<id>)_

- **HH:MM:SS** `sender`: message text <!-- id=NNNN -->
- **HH:MM:SS** `sender`: ... <!-- id=NNNN -->
<!-- raw:end -->
```

**Rules enforced by the scripts:**
- All four marker pairs (`digest:`, `events:`, `raw:`) must exist on disk once a day has a digest. `events:start`/`events:end` go **inside** `digest:start`/`digest:end`.
- `sync.py` only writes between `raw:start` and `raw:end`.
- Claude (via the `digest` sub-command) only writes between `digest:start` and `digest:end` — this includes the events-block within it.
- `events.py` only reads — it never writes to day log files. It parses the events-block from each digest and writes `EVENTS.md` at the repo root.
- Raw messages are ordered oldest-first and deduped by Telegram message ID (stored as `<!-- id=N -->` trailing comment).

## 📦 The two scripts

| Script | Language | Role |
|---|---|---|
| `scripts/sync.py` | Python stdlib only | Fetch Telegram messages, partition by UTC+7 day, upsert into per-day log files' raw block. Maintains `.sync-state.json` watermark. |
| `scripts/events.py` | Python stdlib only | Parse each `logs/*.md` digest's events-block, aggregate severity ≥ med incidents, write `EVENTS.md`. No LLM call. |

Both are deterministic, fast, side-effect-only scripts. The "thinking" (digest prose + events-block) lives in `SKILL.md` — Claude does that work via Read + Edit, not a Python LLM wrapper.

### Events-block schema

Each object in the JSON array between `events:start` / `events:end`:

```jsonc
{
  "id": "kelp-rseth-lz-apr2026",           // optional stable dedup key.
                                           // Events sharing an id across days
                                           // merge into one EVENTS.md row.
                                           // REQUIRED for multi-day incidents.
  "severity": "critical" | "high" | "med" | "low",
  "type": "exploit" | "depeg" | "governance_attack" | "phishing"
          | "infrastructure" | "discussion" | "other",
  "protocol": "Kelp DAO",                  // freeform display name
  "title": "rsETH LayerZero DVN exploit",  // 4-12 words
  "participants": ["banteg", "..."]        // optional
}
```

`events.py` filters to `type ∈ {exploit, depeg, governance_attack, phishing, infrastructure}` at severity ≥ med by default. `discussion`/`other` are allowed in the per-day block (so Claude can flag noteworthy non-incidents) but don't surface in `EVENTS.md`.

## 🔧 Telegram CLI

Portable resolution inside `scripts/sync.py`:

1. `TELEGRAM_BIN` env var (absolute path override - set in systemd units, crontabs, or Dockerfiles)
2. `telegram` on `PATH` (Homebrew on macOS, `npm -g` on Linux, etc.)

Each host needs its own authenticated session (the CLI keeps a local TDLib DB). That's a one-time setup per machine, out of scope for this repo.

Relevant subcommands:

- `telegram read "ETHSecurity Community" --since <N>d -n <limit> --json` - fetch messages. Messages come back newest-first.
- `telegram chats --limit 1000 --json` - list all chats (used to verify the channel name hasn't changed).

**stdout is polluted** with ANSI-colored log lines (INFO/WARN) from gramJS. `sync.py` filters these before JSON parsing - see the extraction pattern in the script.

`--since` takes offsets (`"7d"`, `"1h"`), not absolute dates.

## 🎛️ Skill conventions

- `/defi-monitor` with no args prints status (last sync, date range archived, dates missing digest, event count)
- **Incremental sync** (`sync`) is bounded by `.sync-state.json`. Delete that file to force a wider re-fetch on next run.
- **Backfill** (`backfill <days>`) bypasses the watermark. Use for deep history bootstrap on fresh clones or to recover incidents that preceded the current watermark.
- **Digests** are written by Claude itself within the session (via Read + Edit), guided by the prompt in `SKILL.md`. There's no Python LLM wrapper.
- **Replay** MUST preserve the raw block byte-for-byte. Only the digest block (which includes the events-block) is rewritten.
- **Auto-events:** `EVENTS.md` is rebuilt (via `scripts/events.py`) at the end of any operation that wrote one or more digests. See the **When auto-events runs** table in `SKILL.md`.

## ✍️ Style when generating digests

- Present tense for live incidents, past for retrospectives
- Name participants by their chat handle (no `@`; Telegram senders don't use handles)
- No hedging; no em-dashes; no marketing language; no financial advice
- Cite external links inline as `([post-mortem](url))` so the reader can follow up
- The events-block JSON and the prose Incidents section must describe the same events. If one says there's a Kelp exploit, the other must too.

## 🚨 Before marking work done

1. If you changed the digest prompt or events-block schema, run `python3 scripts/events.py` and verify no parse warnings.
2. If you touched `sync.py`, run `python3 -c "import py_compile; py_compile.compile('scripts/sync.py', doraise=True)"` to catch syntax errors before a real invocation.
3. If you regenerated digests (replay or digest sub-commands), run `/defi-monitor events` to refresh `EVENTS.md` and inspect it.
