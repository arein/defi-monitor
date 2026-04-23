# 🛡️ defi-monitor

A Claude Code skill that archives the **ETHSecurity Community** Telegram channel into per-day markdown logs, derives a prose digest of DeFi security events per day, and rolls up noteworthy incidents into a global [`EVENTS.md`](./EVENTS.md) at the repo root.

No servers, no DB, no auth. Just a local repo + the `telegram` CLI + Claude Code.

## 🚀 Quick start

```bash
git clone <this-repo> defi-monitor
cd defi-monitor
claude                 # opens Claude Code in this repo, auto-loads the skill
```

Then in the Claude Code session:

```
/defi-monitor                      # status: last sync, archived dates, missing digests
/defi-monitor sync                 # incremental pull + auto-digest yesterday+ + refresh EVENTS.md
/defi-monitor backfill 50          # deep pull last 50 days, bypasses watermark, (re)digests each day
/defi-monitor digest 2026-04-19    # (re)generate the digest for one date
/defi-monitor replay 2026-04-15 2026-04-21   # rewrite digests for a range
/defi-monitor events               # rebuild EVENTS.md from existing digests
```

## 🎯 I want to…

### …do a fresh 50-day backfill from scratch

```
/defi-monitor backfill 50
```

This fetches 50 days of history (bypassing the `lastMessageId` watermark), writes messages into per-day log files, runs a fresh digest on each past day, and rebuilds `EVENTS.md`. Open `EVENTS.md` — expect the Resolv depeg, Drift exploit, Kelp DAO signer change and any other noteworthy incidents from that window to show up (conditional on the channel actually covering them).

### …run the routine incremental tick

```
/defi-monitor sync
```

Pulls only messages newer than `.sync-state.json`'s `lastMessageId`, auto-digests any pre-today date whose digest is still empty, and rebuilds `EVENTS.md` if anything changed.

### …rebuild `EVENTS.md` without fetching or re-digesting

```
/defi-monitor events
```

Parses the events-block from every existing `logs/*.md` digest and regenerates `EVENTS.md`. Instant, no LLM call.

### …re-digest a specific date or range (e.g. after tuning the prompt)

```
/defi-monitor digest 2026-04-19
/defi-monitor replay 2026-04-15 2026-04-21
```

## 📦 What's in the repo

| Path | What it does |
|---|---|
| `.claude/skills/defi-monitor/SKILL.md` | The skill prompt — dispatches on `sync` / `backfill` / `digest` / `replay` / `events`, owns the digest prompt + events-block schema |
| `scripts/sync.py` | Incremental Telegram fetch, partitions by UTC+7 day, upserts per-day raw blocks. `--backfill --days N` for deep bootstrap. Stdlib only. |
| `scripts/events.py` | Parses the events-block JSON from every digest, aggregates severity ≥ med incidents, writes `EVENTS.md`. No LLM call. Stdlib only. |
| `logs/YYYY-MM-DD.md` | One file per day: raw messages at the bottom, digest prose (plus a machine-parseable events-block) at the top |
| `EVENTS.md` | Global rollup of noteworthy incidents, most-recent-first. Auto-regenerated. Don't hand-edit. |
| `.sync-state.json` | Checkpoint of the last synced message ID (gitignored) |
| `CLAUDE.md` | Project conventions — if you're another Claude session, start here |

## 🔑 Prerequisites

- **`telegram` CLI v0.9+ authenticated** — `telegram chats` should succeed. Installed via Homebrew on macOS or via `npm -g telegram` / equivalent on Linux. The sync script finds it via `TELEGRAM_BIN` env var or `PATH`, so no path is hardcoded.
- **Python 3.9+** on `python3` — stdlib only, no third-party deps for either script
- **Claude Code** — the skill runs inside a Claude Code session

## 🖥️ Portable across hosts

Designed to run on any Unix-ish machine with the prerequisites above:

- **Local (macOS)**: normal everyday use via `claude` in the repo
- **Linux server**: same commands work. Authenticate the `telegram` CLI once on the server, then run `python3 scripts/sync.py` directly from cron, a systemd timer, or a `loop` remote agent. Logs live in `logs/` (git-tracked), so `git pull` carries the archive between hosts. The sync checkpoint `.sync-state.json` is gitignored; scp it manually if you want the new host to resume from the same message ID instead of re-fetching the default window.

Nothing in the code hardcodes a machine-specific path. Override the telegram binary location with `TELEGRAM_BIN=/abs/path/to/telegram` if needed.

## 🤖 Automation (cron / systemd)

The two Python scripts are fully non-interactive and safe to run unattended. **What you can and can't automate without Claude Code attended:**

| Step | Automatable? | Why |
|---|---|---|
| `scripts/sync.py` (fetch raw messages into `logs/`) | ✅ yes | Pure Python, no LLM |
| `scripts/events.py` (rebuild `EVENTS.md`) | ✅ yes | Pure Python, no LLM |
| Digest generation (the prose + events-block) | ⚠️ requires Claude | Only `claude -p` headless mode can automate this |

The common pattern is "cron keeps the raw archive current; a human runs `/defi-monitor sync` in Claude Code when they want digests." This keeps cost bounded: no LLM calls fire unless someone opens the repo.

### Cron — raw fetch every hour

```cron
# /etc/cron.d/defi-monitor  (or `crontab -e` for user-level)
# Env: adjust REPO and pick a user with the authenticated telegram CLI session
REPO=/srv/defi-monitor
TELEGRAM_BIN=/usr/local/bin/telegram
PATH=/usr/local/bin:/usr/bin:/bin

# Hourly incremental sync (uses --since 2d overlap + lastMessageId watermark)
5 * * * *   runuser -u ethsec -- /usr/bin/python3 $REPO/scripts/sync.py        >> $REPO/sync.log 2>&1

# Rebuild EVENTS.md daily at 01:15 UTC (after any digests you wrote the day before)
15 1 * * *  runuser -u ethsec -- /usr/bin/python3 $REPO/scripts/events.py      >> $REPO/sync.log 2>&1
```

**Notes:**
- Use absolute paths in cron entries — cron's `PATH` is minimal. Either set `PATH=` at the top of the crontab (as above) or point directly at `/abs/path/to/telegram` via `TELEGRAM_BIN`.
- Each host needs its own authenticated telegram CLI session. Run `telegram chats` once interactively as the cron user to confirm login before enabling the cron.
- Cron's stdout and stderr are swallowed by default — always redirect to a log file you actually read (`>> $REPO/sync.log 2>&1`), or pipe through `logger -t defi-monitor` for the system journal.

### Systemd timer — same cadence, better logging

```ini
# /etc/systemd/system/defi-monitor-sync.service
[Unit]
Description=defi-monitor hourly Telegram sync
After=network-online.target

[Service]
Type=oneshot
User=ethsec
WorkingDirectory=/srv/defi-monitor
Environment=TELEGRAM_BIN=/usr/local/bin/telegram
ExecStart=/usr/bin/python3 /srv/defi-monitor/scripts/sync.py
```

```ini
# /etc/systemd/system/defi-monitor-sync.timer
[Unit]
Description=Run defi-monitor sync hourly

[Timer]
OnCalendar=hourly
Persistent=true

[Install]
WantedBy=timers.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now defi-monitor-sync.timer
journalctl -u defi-monitor-sync -n 50    # inspect recent runs
```

### Full automation with `claude -p` (optional)

If you want cron to also write digests, Claude Code supports a headless `-p` mode that runs a prompt and exits. Requires an `ANTHROPIC_API_KEY` in the environment and a billing-aware mental model (each run costs LLM tokens).

**Do not paste the API key into a crontab.** Cron spool files are often world-readable, backed up, and processes spawned from cron command-lines leak their args to `ps`/`/proc`. Put the key in a `0600` env file and reference it:

```bash
# /etc/defi-monitor.env  (chmod 600, owned by the user running the cron)
ANTHROPIC_API_KEY=sk-ant-...
```

Then the cron / systemd job loads it without the literal key ever touching the command line or `ps` output:

```cron
# crontab — source the env file inside the child shell, never on the command line
30 1 * * *  runuser -u ethsec -- bash -c \
              'set -a; . /etc/defi-monitor.env; set +a; \
               claude -p "/defi-monitor sync" --cwd $REPO' \
              >> $REPO/digest.log 2>&1
```

```ini
# Or preferred: let systemd read the env file for you
# /etc/systemd/system/defi-monitor-digest.service
[Service]
Type=oneshot
User=ethsec
WorkingDirectory=/srv/defi-monitor
EnvironmentFile=/etc/defi-monitor.env
ExecStart=/usr/local/bin/claude -p "/defi-monitor sync"
```

The headless run will invoke the skill end-to-end (sync → auto-digest → EVENTS.md rebuild). Verify interactively a few times before trusting it unattended; look for token-spend and prompt-drift surprises.

## 🔍 Evaluating the output

After a run, here's the checklist to decide whether the pipeline did the right thing:

### Quick status probe

```bash
# What's there, what's missing, when did we last sync?
python3 scripts/events.py --out /tmp/events.preview.md   # dry-run parse, writes to /tmp
grep -c "_not yet generated_" logs/*.md || echo "all days digested"
jq . .sync-state.json                                    # lastMessageId, lastSyncAt, chat
```

The top of `EVENTS.md` tells you three things at a glance:

```
_Last rebuild: 2026-04-23T00:15:12Z · spans 2026-02-27 → 2026-04-23 · 40 events at severity ≥ med._
```

- **spans** — the date range of `logs/` files that have been parsed. A gap means the sync didn't reach that far back; run `backfill --days N` with a larger N.
- **events count** — sanity-check against your own memory of the week. A busy week should surface ≥ 3 incidents; 0 in a week is a red flag (see below).

### Spot-check a single digest

Pick a day you remember, open `logs/YYYY-MM-DD.md`, and verify:

1. **Prose matches raw.** Every claim in the Incidents or Discussion section should be traceable to a bullet in the raw block below. If a digest names `banteg` and quotes `$290M`, search the raw block for that handle and number.
2. **Events-block is valid JSON.** `events.py` already checks this — if `{"warnings":[...]}` comes back non-empty, the day's digest has a malformed block and should be replayed.
3. **Events-block agrees with prose.** Every `id` in the JSON array should map to a named incident in the prose; inverse should also hold. If prose mentions a Kelp exploit but the events array is empty, the digest has drifted.

### Validate events-block JSON across all days

```bash
# Extract every events-block JSON array and run it through jq for schema sanity
for f in logs/*.md; do
  awk '/<!-- events:start -->/{flag=1; next} /<!-- events:end -->/{flag=0} flag' "$f" \
    | jq -e 'type=="array" and all(.[]; has("severity") and has("type") and has("protocol"))' \
    > /dev/null || echo "BAD: $f"
done
```

### Red flags and what they mean

| Symptom | Likely cause | Fix |
|---|---|---|
| `_not yet generated_` on any pre-today date | Digest pass skipped or failed | `/defi-monitor digest YYYY-MM-DD` |
| Parse warnings from `events.py` | Malformed events-block JSON in that day | `/defi-monitor replay YYYY-MM-DD YYYY-MM-DD` |
| `EVENTS.md` span doesn't include today | Raw sync didn't fire or had 0 new messages | Check `.sync-state.json` `lastSyncAt`; re-run `scripts/sync.py` |
| Same incident appears as 3 dupe rows | Digest authors didn't reuse the event `id` | Edit the later days to match the first day's `id`, rerun `events.py` |
| Zero events for a week you know was busy | Digest prompt or severity threshold misfired | Spot-check a raw block; replay the day and compare |
| Digest claims something not in the raw | LLM hallucination | Replay with a stricter "attribute every claim to a message" pass; flag in `SKILL.md` |

### Sanity-check against external weekly roundups

The channel regularly ingests BlockSec and Breach Ledger weekly summaries. After a backfill, scan `EVENTS.md` for the week and compare counts and dollar amounts to those summaries — they're the easiest ground-truth. Large deltas mean either the channel didn't cover an incident (acceptable, this archive is scope-limited to what ETHSecurity Community discussed) or the digest missed it (not acceptable; replay).

## 📜 `EVENTS.md` — the global rollup

[`EVENTS.md`](./EVENTS.md) at the repo root is the human-readable log of noteworthy DeFi security incidents, aggregated from every day's digest. Each entry shows severity, type, protocol, title, driving participants, and a link back to the source day's log.

- Generated by `scripts/events.py` parsing the JSON events-block inside each digest.
- Filtered to incidents at severity ≥ med and type ∈ `{exploit, depeg, governance_attack, phishing, infrastructure}`.
- Auto-rebuilt at the end of every `sync` / `backfill` / `digest` / `replay` that wrote new digests.
- Manually rebuild: `/defi-monitor events` or `python3 scripts/events.py`.
- **Don't hand-edit** — the next rebuild overwrites.

## 📖 See also

- [`CLAUDE.md`](./CLAUDE.md) — project conventions (timezone, log format, events-block schema)
- [`.claude/skills/defi-monitor/SKILL.md`](./.claude/skills/defi-monitor/SKILL.md) — the digest prompt and sub-command dispatch
