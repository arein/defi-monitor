---
name: defi-monitor
description: Archive the ETHSecurity Community Telegram channel into per-day markdown logs and derive a prose digest of DeFi security events. Supports date-range replay to re-generate digests against archived raw messages. Use when the user wants to sync the channel, read yesterday's incidents, or replay past days.
allowed-tools: Bash, Read, Write, Edit, Grep, Glob
---

# defi-monitor

Archive the **ETHSecurity Community** Telegram channel and derive a daily prose digest of DeFi security events. Source of truth is `logs/YYYY-MM-DD.md`.

## 🎛️ Sub-commands

The user invokes this skill with a sub-command. Dispatch as follows.

### `sync`

**When:** user types `/defi-monitor`, `/defi-monitor sync`, or asks to "sync" / "pull the latest" / "update the archive".

**Do:**
1. Run `python3 scripts/sync.py` from the repo root. It handles the actual Telegram fetch and writes messages into `logs/YYYY-MM-DD.md` under the `raw:start` / `raw:end` block. It reports which dates were touched.
2. If the script reports dates that are **before today (UTC+7)** AND whose digest section is still `_not yet generated_`, automatically run the `digest` sub-command for each such date before reporting back.
3. Summarize: dates touched, message counts per date, digests generated.

**Do not:** re-run the digest for today's file, even if messages were added — today's file is a partial day until UTC+7 midnight.

### `digest <YYYY-MM-DD>`

**When:** user types `/defi-monitor digest 2026-04-19` or asks to "digest" / "summarize" / "write up" a specific day.

**Do:**
1. Read `logs/<date>.md`. If it doesn't exist, tell the user and stop.
2. Extract the block between `<!-- raw:start -->` and `<!-- raw:end -->`. Count the bulleted messages.
3. If zero messages, overwrite the digest section with `_Quiet day — no messages archived._` and stop.
4. Otherwise, compose a prose digest following the **Digest prompt** below, and use `Edit` to replace **only** the text between `<!-- digest:start -->` and `<!-- digest:end -->`. The raw block MUST remain byte-identical.
5. The digest section must begin with `## Digest\n\n_generated <ISO-timestamp-now> from N messages_\n\n` and then the digest body. Use the current machine time for the timestamp (`date -u +%Y-%m-%dT%H:%M:%SZ`).

### `replay <from> <to>`

**When:** user types `/defi-monitor replay 2026-04-15 2026-04-20` or `/defi-monitor replay 2026-04-19` (single-date form — treat `to` as equal to `from`).

**Do:**
1. Enumerate every date in `[from, to]` inclusive.
2. For each date, run the `digest` sub-command. Overwrite any existing digest section.
3. Report: `{dates processed, digests rewritten, dates with no messages (skipped), any errors}`.

### bare `/defi-monitor` (status, no args)

If the user invokes the skill with no sub-command at all, show status:
- Last sync time (from `.sync-state.json`)
- Date range of `logs/` directory
- Dates in `logs/` whose digest is still `_not yet generated_`
- Message count in today's file so far

Then ask whether they want to run `sync`.

---

## 📝 Digest prompt

You are writing a concise **end-of-day DeFi security digest** from raw chat messages in the ETHSecurity Community Telegram channel. The reader is a crypto investor who wants to know: "Did anything I hold get exploited today, and what was the broader security conversation?"

**Required structure (in this order):**

1. **Headline** — one sentence. The single most important thing of the day. If nothing of note happened, say so plainly (e.g. `Quiet day. Minor discussion about auditor hiring and one unrelated rug.`).
2. **Incidents** section — each active or emerging incident gets 1-3 sentences: the protocol, the incident type (exploit / depeg / governance attack / phishing / infrastructure failure), severity judgment, named contracts or amounts if mentioned, and which chat participants broke or drove the discussion (by their handle). Omit this section entirely if nothing qualifies.
3. **Discussion** section — 2-3 sentences on the broader conversation: post-mortems, infrastructure debates, tool releases, research threads, audit news. Omit if sparse.
4. **Noise** line — one sentence at the end: `Also mentioned: X, Y, Z.` for off-topic chatter worth acknowledging. Omit if not worth noting.

**Rules:**

- Present tense for live incidents, past for retrospectives.
- Attribute specific claims to the participant who made them: `banteg called out the DVN misconfig`.
- No hedging ("seems to", "appears to"); state what the messages say or stay silent.
- **No em-dashes or en-dashes** — use regular hyphens, periods, or commas.
- No marketing language, no financial advice (except "users should withdraw" style advisories when severity is critical and a participant explicitly said so).
- Cite external links inline: `... ([post-mortem](https://example.com/url))`.
- Target length: 150-300 words for a normal day; shorter is fine.

**What counts as an incident:**

- Active exploits with funds draining
- Confirmed past-tense exploits from today
- Stablecoin or pegged-asset depegs
- Governance attacks, signer changes, admin-key compromises
- Active phishing campaigns tied to a named protocol
- Infrastructure failures with material funds at risk (bridges, oracles, DVNs)

**What is NOT an incident:**

- Retrospective discussion of past incidents
- Audit announcements (not an incident unless the audit itself flagged an exploit)
- General security tips / PSAs
- Drainer kit discussion unless tied to a specific active campaign
- Price commentary, airdrop talk, macro takes

---

## 🛠️ Implementation notes

- The `sync.py` script is self-contained (stdlib only). It partitions by UTC+7 day using the `date` field on each Telegram message.
- The script maintains `.sync-state.json` — a single `{lastMessageId, lastSyncAt}` object. First run uses `telegram read --since 7d` to bootstrap; subsequent runs use the stored `lastMessageId` to only keep messages newer than the checkpoint.
- If `.sync-state.json` is deleted, the next `sync` re-bootstraps a 7-day window (but dedupes against existing raw blocks, so it won't duplicate messages).
- File boundary markers (`<!-- digest:start -->` / `<!-- digest:end -->` / `<!-- raw:start -->` / `<!-- raw:end -->`) are load-bearing. Never edit around them — always `Edit` the content between them.
- Messages with no `text` field (media-only) are written as `- **HH:MM:SS** `sender`: _[<mediaType>]_`.
