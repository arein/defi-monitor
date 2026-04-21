# 🛡️ defi-monitor — Plan

## 🎯 Context

Stepping away from the `wallet-monitor` multi-plane architecture in favor of something radically simpler: a Claude Code skill that treats the ETHSecurity Community Telegram channel as the single source of truth for DeFi security events. The skill archives the channel to local markdown and uses Claude to derive a daily prose digest. Later, X becomes a second source.

**Why this shape:**
- No servers, no Postgres, no webhooks, no auth. Just a local repo + Claude Code.
- Leverages existing `telegram` CLI which is already authenticated.
- The proven pattern from `chief-of-staff/.claude/skills/gm-content/` — which already reads ETHSecurity Community — becomes the starting point, narrowed to this channel only and deepened for replay.
- Replay is cheap and meaningful: re-run the LLM against archived raw messages for any past date to test "would we have caught Kelp DAO?" without re-hitting Telegram.
- When X joins later, both sources write into the same per-day log; the digest step doesn't care where the raw came from.

**Decisions locked in:**
- Location: `~/Code/defi-monitor/`
- Output: one markdown file per day containing both raw messages and the derived digest
- Derivation: prose digest (not structured JSON for v0)
- Replay: re-run derivation over already-archived raw messages (no re-fetching)
- Timezone for day boundaries: Derek's local, UTC+7

---

## 📦 Directory structure

```
~/Code/defi-monitor/
├── .claude/
│   └── skills/
│       └── defi-monitor/
│           └── SKILL.md              # the skill prompt — the heart of the project
├── scripts/
│   ├── sync.py                       # incremental Telegram sync, partitions by UTC+7 day
│   └── digest.py                     # runs Claude against a day's raw, writes digest section
├── logs/
│   ├── 2026-04-19.md                 # one file per day (raw + digest)
│   ├── 2026-04-20.md
│   └── ...
├── .sync-state.json                  # last-synced message ID per source (gitignored)
├── .gitignore
├── CLAUDE.md                         # project instructions (tz, conventions)
├── README.md
└── PLAN.md                           # this file
```

The scripts are deliberately small and deterministic (fetch + file IO only). The "thinking" lives in `SKILL.md` — Claude does the actual digest work using Read + Write, not a Python LLM wrapper.

---

## 📄 Log file format

Each `logs/YYYY-MM-DD.md` has two sections separated by a fenced marker. Replay only rewrites the Digest section.

```markdown
# 2026-04-19 (UTC+7)

<!-- digest:start -->
## Digest

_generated 2026-04-20 09:14 from 247 messages_

On Apr 19, the channel centered on the **Kelp DAO rsETH LayerZero exploit**. Early
signals from james-prestwich around 14:03 UTC flagged the DVN misconfiguration...

Secondary threads: EigenLayer vesting cliff discussion, a brief rehash of the 2024
Euler incident, and two unrelated wallet-drainer warnings.
<!-- digest:end -->

<!-- raw:start -->
## Raw messages

_synced from Telegram at 2026-04-20 06:00:12 UTC (last_msg_id=153729)_

- **14:03:01** `james-prestwich`: LayerZero has a 2/3 admin multisig that can bypass all DVNs...
- **14:05:22** `primo-layerzero`: Confirmed: nobody should be on 1/1 DVN in production...
- **14:11:47** `banteg`: Kelp rsETH Unichain-to-Ethereum path shows no source-side burn...
<!-- raw:end -->
```

**Format rules:**
- `<!-- digest:start -->` / `<!-- digest:end -->` bracket the digest — replay rewrites everything between these
- `<!-- raw:start -->` / `<!-- raw:end -->` bracket the raw — sync appends into here, digest reads from here
- Both sections must exist on disk even if empty; sync creates the file on first hit for a day

---

## ⚙️ Skill behavior

`/defi-monitor` accepts three sub-commands. The skill prompt tells Claude how to dispatch on args.

### `/defi-monitor sync`
- Runs `scripts/sync.py`
- Python invokes `telegram sync --chat "ETHSecurity Community" --resume --json`
- Partitions messages by UTC+7 day
- Appends to each touched `logs/YYYY-MM-DD.md` inside the `raw` block (creating the file with both empty sections if it doesn't exist)
- Writes `.sync-state.json` with the new last_msg_id
- Returns: list of dates touched + message counts
- After sync returns, Claude automatically runs `digest` for any yesterday-or-older date whose digest section is empty

### `/defi-monitor digest <YYYY-MM-DD>`
- Claude reads `logs/<date>.md`
- Extracts the raw section
- Composes a digest following the rules in SKILL.md (see below)
- Writes back into the digest section, preserving the raw section verbatim
- If no raw messages exist for the date → skip with a one-line note

### `/defi-monitor replay <from> <to>`
- Iterates each date in `[from, to]` (inclusive)
- For each date, runs digest, overwriting any existing digest section
- Reports a summary at the end: `{dates processed, digests rewritten, skipped, total tokens}`

### `/defi-monitor` (bare)
- Shows status: last sync time, date range of archive, dates missing digest

---

## 🧠 Derivation prompt (SKILL.md)

The SKILL.md system prompt for digest generation (v0):

> You are writing a concise **end-of-day DeFi security digest** from raw chat messages in the ETHSecurity Community Telegram channel. Your reader is a crypto investor who wants to know if anything they hold got exploited today, and what the broader security conversation was.
>
> **Structure (strict):**
> 1. One sentence headline — the single most important thing of the day. If nothing happened, say so plainly.
> 2. **Incidents** section — each active or emerging incident gets 1-3 sentences: what protocol, what type (exploit / depeg / governance / phishing), severity assessment, named contracts or amounts if mentioned, and which participants broke the story. Omit this section entirely if there are no incidents.
> 3. **Discussion** section — 2-3 sentences on the broader conversation: post-mortems, infrastructure debates, tool releases, research threads. Omit if sparse.
> 4. **Noise** line — one sentence at the end: "Also mentioned: X, Y, Z" for off-topic chatter worth acknowledging. Omit if not worth noting.
>
> **Rules:**
> - Present tense for live incidents, past for retrospectives.
> - Name participants by their handle (e.g. `@banteg`) when they broke specific news.
> - No hedging ("seems to", "appears"); state what the messages say or stay silent.
> - No em-dashes; use hyphens or periods.
> - No marketing language, no financial advice.
> - If someone links a post-mortem or thread, mention it in-line as `([post-mortem](url))` so the reader can follow up.

That prompt is good enough for v0. Tune after the first few real days of output.

---

## 🛠️ Scripts

### `scripts/sync.py` (~100 lines)
- Subprocess: `telegram sync --chat "ETHSecurity Community" --resume --json --output -`
- Parse JSON stream, for each message compute `local_day = (utc_ts + 7h).date()`
- Group by local_day
- For each day, open `logs/YYYY-MM-DD.md` (create with skeleton if missing), insert messages chronologically into the raw block (dedup against existing message IDs)
- Update `.sync-state.json`: `{lastMessageId, lastSyncAt, sourcesSynced: ["telegram:ethsec-community"]}`
- Print one-line summary per day touched

### `scripts/digest.py` (~60 lines)
- **Actually not needed as a script** — the skill prompt tells Claude to do this directly via Read + Write. Deferred.
- If it turns out Claude's freeform approach is inconsistent, promote to a script that calls the Anthropic API with a pinned prompt + tool-use for structure.

---

## 🧪 Verification

1. **First-time sync**: from empty repo, `/defi-monitor sync` populates ~30 days of logs with raw content and no digests. Inspect a few files — structure should be consistent.
2. **Incremental sync**: after a few hours, `/defi-monitor sync` pulls only the few dozen new messages, appends to today's file only. `.sync-state.json` advances.
3. **Digest on fresh day**: `/defi-monitor sync` auto-runs digest on yesterday's file (since it's now complete). Open `logs/2026-04-19.md` — digest section is populated, raw untouched.
4. **Replay a known incident**: `/defi-monitor replay 2026-04-19 2026-04-19` — re-runs digest, output should mention Kelp DAO / LayerZero / rsETH with roughly correct severity.
5. **Replay a boring day**: pick a day with no incidents — digest should say "Quiet day, no incidents of note."
6. **Raw preservation**: after multiple replays, raw section byte-for-byte unchanged.

---

## 🔮 Extensibility: adding X later

When X joins:
- `scripts/sync.py` grows a second fetcher (shells to `bird user-tweets` / `bird search`) and merges with Telegram into the same per-day files
- Raw section grows a sub-section marker: `### Telegram` / `### X` under the raw block
- Digest prompt learns to cite sources (`[Telegram]` vs `[X]`) when attributing
- `.sync-state.json` tracks two checkpoints: `telegram.lastMessageId` and `x.lastSearchTimestamp`

No change to the log format or replay semantics.

---

## 🛣️ Milestones (v0 build order)

| M | Goal | What lands |
|---|---|---|
| 0 | Repo init | `~/Code/defi-monitor/{.gitignore, README.md, CLAUDE.md, PLAN.md}`, `git init` |
| 1 | Skill shell | `.claude/skills/defi-monitor/SKILL.md` with all three sub-commands documented |
| 2 | Sync works | `scripts/sync.py` pulls from Telegram, writes per-day files with raw section. First real archive lands. |
| 3 | Digest works | `/defi-monitor digest <date>` produces a digest on a real day's log file. Prompt tuned against 2-3 days. |
| 4 | Replay works | `/defi-monitor replay` iterates. Verified against Kelp DAO day. |
| 5 | Polish | Status command, README, CLAUDE.md conventions, edge cases (gaps, missing messages) |

No M6+ for this project. X integration is a follow-up separate effort.

---

## ❓ Open questions (resolve during M0-M2)

- **First-run history depth**: `telegram sync --resume` on first run pulls everything. Limit to 30 days? 90? Let it rip?
- **Partial day at sync time**: if syncing at 14:00 UTC+7, today's file is partial. Skip today's digest or include an explicit "(partial, synced at 14:00)" note?
- **Rate limits on Telegram CLI**: cap on `--limit`? Chunking needed? Verify during M2.
