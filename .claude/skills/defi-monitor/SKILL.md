---
name: defi-monitor
description: Archive the ETHSecurity Community Telegram channel into per-day markdown logs, derive a prose digest of DeFi security events for each day, and roll up noteworthy incidents into a global EVENTS.md. Supports historical backfill. Use when the user wants to sync the channel, read yesterday's incidents, replay past days, or rebuild the events index.
allowed-tools: Bash, Read, Write, Edit, Grep, Glob
---

# defi-monitor

Archive the **ETHSecurity Community** Telegram channel and derive a daily prose digest of DeFi security events. Source of truth is `logs/YYYY-MM-DD.md`. The rolled-up incident index lives at `EVENTS.md` in the repo root.

## 🎛️ Sub-commands

The user invokes this skill with a sub-command. Dispatch as follows.

### `sync`

**When:** user types `/defi-monitor`, `/defi-monitor sync`, or asks to "sync" / "pull the latest" / "update the archive".

**Do:**
1. Run `python3 scripts/sync.py` from the repo root. The script handles the Telegram fetch and writes messages into `logs/YYYY-MM-DD.md` under the `raw:start` / `raw:end` block. It prints a JSON summary on stdout with `datesTouched` (only dates where new messages were actually added).
2. For every date in `datesTouched` that is **before today (UTC+7)** AND whose digest section still reads `_not yet generated_`, run the `digest` sub-command. Skip today's file — it's partial until UTC+7 midnight.
3. If any digests were written in step 2, run the `events` sub-command to refresh `EVENTS.md`.
4. Summarize: dates touched, message counts per date, digests generated, events total after rebuild.

### `backfill <days>`

**When:** user types `/defi-monitor backfill 50`, `/defi-monitor sync --days 50`, or asks to "backfill the last N days" / "bootstrap history" / "fetch old messages I missed".

**Do:**
1. Run `python3 scripts/sync.py --backfill --days <N>`. This bypasses the `lastMessageId` watermark so older-than-last-sync messages get pulled. Per-day file dedup still protects against duplicates.
2. For EVERY date in the returned `datesTouched` that is before today (UTC+7), run `digest` — regardless of whether a prior digest already exists. Backfill re-derives history from scratch.
3. Run the `events` sub-command to rebuild `EVENTS.md`.
4. Report: date range touched, message count per date, digests (re)generated, final event count.

Typical use: on a fresh clone, or when the user wants to recover incidents they missed (e.g. the Resolv depeg or Kelp DAO exploit from weeks ago). Budget for backfill: `telegram read` with `-n <days*300>` may take a minute or two; digest per day is one Claude turn each.

### `digest <YYYY-MM-DD>`

**When:** user types `/defi-monitor digest 2026-04-19` or asks to "digest" / "summarize" / "write up" a specific day.

**Do:**
1. Read `logs/<date>.md`. If it doesn't exist, tell the user and stop.
2. Extract the block between `<!-- raw:start -->` and `<!-- raw:end -->`. Count the bulleted messages.
3. If zero messages, write a digest that's literally the events-block empty plus a `_Quiet day — no messages archived._` body (see **Digest output format** below), then stop.
4. Otherwise, compose the digest following the **Digest prompt** below. `Edit` to replace **only** the text between `<!-- digest:start -->` and `<!-- digest:end -->`. The raw block MUST remain byte-identical.
5. **If invoked directly by the user**, run the `events` sub-command to refresh `EVENTS.md`. **If invoked as part of a batch by `sync` / `backfill` / `replay`, skip this step** — those callers run `events` once at the end of the batch to avoid N redundant rebuilds. Default assumption when in doubt: direct invocation.

### `replay <from> <to>`

**When:** user types `/defi-monitor replay 2026-04-15 2026-04-20` or `/defi-monitor replay 2026-04-19` (single-date form → treat `to` as equal to `from`).

**Do:**
1. Enumerate every date in `[from, to]` inclusive.
2. For each date, run the `digest` sub-command (which overwrites any prior digest). The sub-command already regenerates EVENTS.md after each digest; for replay over many dates, **defer the events rebuild to the end** — just run `python3 scripts/events.py` once after all digests are done, instead of after each one.
3. Report: `{dates processed, digests rewritten, dates with no messages (skipped), events total, any errors}`.

### `events`

**When:** user types `/defi-monitor events` or asks to "regenerate EVENTS.md" / "rebuild the events index".

**Do:**
1. Run `python3 scripts/events.py`. It parses the `events:start` / `events:end` block from every `logs/*.md` digest and writes `EVENTS.md` at the repo root.
2. If the script emits parse warnings on stderr, surface them — typically they mean a digest has a malformed events block and the date should be replayed.
3. Report the JSON summary the script prints on stdout (`eventCount`, `daysScanned`, `warnings`).

### bare `/defi-monitor` (status, no args)

No sub-command → show status:
- Last sync time (from `.sync-state.json`)
- Date range of `logs/` directory
- Dates in `logs/` whose digest is still `_not yet generated_`
- Message count in today's file so far
- Event count currently in `EVENTS.md` (run events.py's `--out` to a tmp file just to count, or just parse the existing file)

Then ask whether they want to run `sync` or `backfill`.

---

## 📝 Digest prompt

You are writing a concise **end-of-day DeFi security digest** from raw chat messages in the ETHSecurity Community Telegram channel. The reader is a crypto investor who wants to know: "Did anything I hold get exploited today, and what was the broader security conversation?"

### Digest output format (strict)

The digest section must follow this exact structure. The `events:start` / `events:end` block is **required** — it's the machine-parseable source of truth for `EVENTS.md`. Claude emits it based on the prose below; the two must describe the same events.

```markdown
## Digest

_generated <ISO-timestamp-now> from N messages_

<!-- events:start -->
[
  {
    "id": "kelp-rseth-lz-apr2026",
    "severity": "critical",
    "type": "exploit",
    "protocol": "Kelp DAO",
    "title": "rsETH LayerZero DVN misconfiguration exploit",
    "participants": ["james-prestwich", "primo-layerzero", "banteg"]
  },
  {
    "id": "resolv-usr-depeg-apr2026",
    "severity": "med",
    "type": "depeg",
    "protocol": "Resolv",
    "title": "USR partial depeg to 0.94",
    "participants": ["samczsun"]
  }
]
<!-- events:end -->

### Headline

<one sentence>

### Incidents

<1-3 sentences per incident>

### Discussion

<2-3 sentences on broader conversation>

_Also mentioned: X, Y, Z._
```

**Events-block rules:**
- Must be a valid JSON array (empty `[]` is allowed and means "no incidents today").
- One object per incident or noteworthy infrastructure/research event. Do NOT include general "discussion" items here unless they're genuinely noteworthy beyond this day.
- `id` is a **stable dedup key**. Required whenever an incident spans more than one day (exploit + next-day post-mortem + later-day recovery action are all the same `id`). Format: `protocol-slug-topic-monYYYY` lowercase kebab-case (e.g. `kelp-rseth-lz-apr2026`, `vercel-supply-chain-apr2026`). Look at the previous day's events-block before inventing a new id; if the incident already has one, reuse it byte-for-byte so `events.py` can merge them. Pick an id that will still be unique if the same protocol gets exploited again next year. For a brand-new one-off event you can omit `id`, but incidents that will keep getting discussed should always carry one.
- `severity` ∈ `"critical" | "high" | "med" | "low"`. Use the same scale as the prose. When merging by `id`, the highest severity across days wins in `EVENTS.md`.
- `type` ∈ `"exploit" | "depeg" | "governance_attack" | "phishing" | "infrastructure" | "discussion" | "other"`. `events.py` filters `discussion` and `other` out of `EVENTS.md`, so only emit those if you think the item matters enough to surface in the prose but not the global index.
- `protocol` is freeform (e.g. `"Kelp DAO"`, `"Resolv"`), not a slug. Use the common display name.
- `title` is 4-12 words, declarative, past-tense-if-resolved, present-tense-if-active. Same style as the prose Incidents heading.
- `participants` is optional: chat handles who drove the discussion. No leading `@`. Omit the field entirely if you don't have clear attribution. When the same `id` appears across days, `events.py` unions the participant lists chronologically.

**Prose section rules:**
- **Headline** — one sentence. The single most important thing of the day. If nothing of note happened, say so plainly.
- **Incidents** — each active or emerging incident gets 1-3 sentences: the protocol, the incident type, severity judgment, named contracts or amounts if mentioned, and which participants broke or drove the discussion. Omit this section if the events array is empty or only has `discussion`/`other`.
- **Discussion** — 2-3 sentences on the broader conversation: post-mortems, infrastructure debates, tool releases, research threads, audit news. Omit if sparse.
- **Noise line** — one sentence at the end: `_Also mentioned: X, Y, Z._` for off-topic chatter worth acknowledging. Omit if not worth noting.

**Style rules:**

- Present tense for live incidents, past for retrospectives.
- Attribute specific claims to the participant who made them: `banteg called out the DVN misconfig`.
- No hedging ("seems to", "appears to"); state what the messages say or stay silent.
- **No em-dashes or en-dashes** — use regular hyphens, periods, or commas.
- No marketing language, no financial advice (except "users should withdraw" style advisories when severity is critical and a participant explicitly said so).
- Cite external links inline: `... ([post-mortem](https://example.com/url))`.
- Target length: 150-300 words for a normal day; shorter is fine.

**What counts as an incident (goes in the events array):**

- Active exploits with funds draining
- Confirmed past-tense exploits from today
- Stablecoin or pegged-asset depegs
- Governance attacks, signer changes, admin-key compromises
- Active phishing campaigns tied to a named protocol
- Infrastructure failures with material funds at risk (bridges, oracles, DVNs)

**What is NOT an incident (keep in prose Discussion, NOT in events array):**

- Retrospective discussion of past incidents
- Audit announcements (not an incident unless the audit itself flagged an exploit)
- General security tips / PSAs
- Drainer kit discussion unless tied to a specific active campaign
- Price commentary, airdrop talk, macro takes

---

## 🛠️ Implementation notes

- `scripts/sync.py` (stdlib only) partitions messages by UTC+7 day via the `date` field on each Telegram message. It maintains `.sync-state.json` with `{lastMessageId, lastSyncAt}`. First run uses `--since 7d`; subsequent runs use `--since 2d` as an overlap window and rely on in-file dedup.
- `scripts/sync.py --backfill --days N` bypasses the `lastMessageId` watermark and auto-scales `-n` to cover N days. Per-day file dedup still prevents duplicates.
- `scripts/events.py` (stdlib only) walks `logs/*.md`, parses each digest's events-block, filters to incidents at severity ≥ med, and writes `EVENTS.md`. No LLM call — aggregation is pure text parsing.
- File boundary markers (`<!-- digest:start -->` / `<!-- digest:end -->` / `<!-- raw:start -->` / `<!-- raw:end -->` / `<!-- events:start -->` / `<!-- events:end -->`) are load-bearing. Never edit around them — always `Edit` the content between them.
- Messages with no `text` field (media-only) are written as `- **HH:MM:SS** `sender`: _[<mediaType>]_` by sync.py.

## 🔁 When auto-events runs

Auto-rebuild `EVENTS.md` (via `python3 scripts/events.py` or the `events` sub-command) at the end of any operation that writes one or more digests:

| Operation | Auto-events? |
|---|---|
| `sync` (no digests written — today's file only, or nothing new) | No |
| `sync` that auto-digests yesterday+ | Yes, once at the end |
| `backfill` | Yes, once at the end |
| `digest <date>` | Yes, once |
| `replay <from> <to>` | Yes, once at the end (not per-date) |
| `events` | It IS the rebuild |

This keeps `EVENTS.md` in sync without doing redundant work on routine incremental ticks that only touch today's file.
