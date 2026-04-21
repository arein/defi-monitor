#!/usr/bin/env python3
"""
Incremental Telegram sync for the ETHSecurity Community channel.

Flow:
  1. Read .sync-state.json for the last known message ID (if any).
  2. Invoke `telegram read "ETHSecurity Community" --since Nd -n M --json`,
     pick a wider --since window on first run, narrower on incremental.
  3. Strip ANSI + gramJS log lines from stdout, parse the JSON envelope.
  4. Drop messages whose id is <= last_known_id.
  5. Partition remaining messages by local day (UTC+7).
  6. For each day, read logs/YYYY-MM-DD.md (create with skeleton if missing),
     parse existing message IDs out of the raw block (encoded as
     `<!-- id=N -->` trailing comments), merge new messages, rewrite the
     raw block in chronological order.
  7. Update .sync-state.json with the new high-water message ID.
  8. Print a human-readable summary.

Stdlib only. Python 3.9+.

Usage:
    python3 scripts/sync.py              # normal incremental sync
    python3 scripts/sync.py --since 30d  # override fetch window (bootstrap wider history)
    python3 scripts/sync.py --limit 5000 # override --n passed to telegram read
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Iterable

# ─────────────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).resolve().parent.parent
LOGS_DIR = REPO_ROOT / "logs"
STATE_FILE = REPO_ROOT / ".sync-state.json"

CHAT_NAME = "ETHSecurity Community"


def resolve_telegram_bin() -> str:
    """Find the telegram CLI without assuming a host (macOS vs Linux).

    Resolution order:
      1. TELEGRAM_BIN env var (absolute path override)
      2. `telegram` on PATH (works for Homebrew on macOS and standard
         Linux installs - apt, npm -g, /usr/local/bin, etc.)

    Exits with a clear error if neither is set. The telegram CLI also
    needs an authenticated session on whichever host runs this script -
    that's a one-time `telegram login` or equivalent, out of scope here.
    """
    env_bin = os.environ.get("TELEGRAM_BIN")
    if env_bin:
        if not Path(env_bin).exists():
            print(
                f"✗ TELEGRAM_BIN is set to {env_bin!r} but that file does not exist",
                file=sys.stderr,
            )
            sys.exit(1)
        return env_bin
    found = shutil.which("telegram")
    if found:
        return found
    print(
        "✗ telegram CLI not found. Install it, or set TELEGRAM_BIN=<absolute path>.",
        file=sys.stderr,
    )
    print(
        "  Hints: macOS Homebrew → /opt/homebrew/bin/telegram",
        file=sys.stderr,
    )
    print(
        "         Linux (npm -g) → /usr/local/bin/telegram or ~/.npm-global/bin/telegram",
        file=sys.stderr,
    )
    sys.exit(1)

# UTC+7 - Derek's local day boundary
LOCAL_TZ = timezone(timedelta(hours=7))

DEFAULT_FIRSTRUN_SINCE = "7d"
DEFAULT_INCREMENTAL_SINCE = "2d"  # overlap window, dedup handles duplicates
DEFAULT_LIMIT = 5000

# Block markers - must match SKILL.md and CLAUDE.md exactly
DIGEST_START = "<!-- digest:start -->"
DIGEST_END = "<!-- digest:end -->"
RAW_START = "<!-- raw:start -->"
RAW_END = "<!-- raw:end -->"

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
LOG_LINE_RE = re.compile(r"^\[\d{4}-\d{2}-\d{2}T.*\]")
MSG_ID_RE = re.compile(r"<!-- id=(\d+) -->")


# ─────────────────────────────────────────────────────────────────────────────
# Types
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Message:
    id: int
    utc_date: datetime
    sender: str
    text: str
    media_type: str | None

    @property
    def local_date(self) -> str:
        return self.utc_date.astimezone(LOCAL_TZ).strftime("%Y-%m-%d")

    @property
    def local_time_hms(self) -> str:
        return self.utc_date.astimezone(LOCAL_TZ).strftime("%H:%M:%S")

    def render_bullet(self) -> str:
        sender = self.sender.strip() or "unknown"
        if self.text:
            body = self.text.replace("\n", "  \n    ")  # markdown soft-break + indent
            bullet = f"- **{self.local_time_hms}** `{sender}`: {body}"
        else:
            media = self.media_type or "media"
            bullet = f"- **{self.local_time_hms}** `{sender}`: _[{media}]_"
        return f"{bullet} <!-- id={self.id} -->"


# ─────────────────────────────────────────────────────────────────────────────
# Telegram CLI
# ─────────────────────────────────────────────────────────────────────────────


def fetch_messages(since: str, limit: int) -> list[Message]:
    """Invoke the telegram CLI and return parsed messages, newest-first as given."""
    telegram_bin = resolve_telegram_bin()
    cmd = [
        telegram_bin,
        "read",
        CHAT_NAME,
        "--since",
        since,
        "-n",
        str(limit),
        "--json",
    ]
    print(f"  → {' '.join(cmd)}", file=sys.stderr)
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
            timeout=600,
        )
    except subprocess.TimeoutExpired:
        print("✗ telegram CLI timed out after 10 minutes", file=sys.stderr)
        sys.exit(1)
    except subprocess.CalledProcessError as e:
        print(f"✗ telegram CLI exited {e.returncode}", file=sys.stderr)
        print(e.stderr, file=sys.stderr)
        sys.exit(1)

    payload = _extract_json_payload(proc.stdout)
    raw_messages = payload.get("messages", [])
    return [m for m in (_parse_message(r) for r in raw_messages) if m is not None]


def _extract_json_payload(stdout: str) -> dict:
    """Strip ANSI + log lines from stdout, parse the remaining JSON envelope."""
    cleaned_lines: list[str] = []
    for line in stdout.splitlines():
        stripped = ANSI_RE.sub("", line)
        if LOG_LINE_RE.match(stripped):
            continue
        if stripped.startswith("- Fetching"):
            continue
        cleaned_lines.append(stripped)
    text = "\n".join(cleaned_lines).strip()
    if not text:
        return {"messages": []}
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        print("✗ failed to parse JSON from telegram CLI:", e, file=sys.stderr)
        print("─── cleaned stdout (first 2000 chars) ───", file=sys.stderr)
        print(text[:2000], file=sys.stderr)
        sys.exit(1)


def _parse_message(raw: dict) -> Message | None:
    try:
        return Message(
            id=int(raw["id"]),
            utc_date=_parse_iso8601(raw["date"]),
            sender=str(raw.get("sender") or raw.get("senderId") or "unknown"),
            text=str(raw.get("text") or ""),
            media_type=raw.get("mediaType"),
        )
    except (KeyError, ValueError, TypeError) as e:
        print(f"  ⚠ skipping malformed message: {e}", file=sys.stderr)
        return None


def _parse_iso8601(s: str) -> datetime:
    # gramJS writes "2026-04-20T19:34:22.000Z" - make it Python-parseable
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)


# ─────────────────────────────────────────────────────────────────────────────
# Per-day log files
# ─────────────────────────────────────────────────────────────────────────────


def log_path(date_str: str) -> Path:
    return LOGS_DIR / f"{date_str}.md"


def read_existing_ids(date_str: str) -> set[int]:
    """Parse message IDs out of the raw block of an existing log file."""
    path = log_path(date_str)
    if not path.exists():
        return set()
    body = path.read_text(encoding="utf-8")
    raw_block = _slice_between(body, RAW_START, RAW_END)
    if raw_block is None:
        return set()
    return {int(m.group(1)) for m in MSG_ID_RE.finditer(raw_block)}


def upsert_day(
    date_str: str,
    new_messages: list[Message],
    last_msg_id: int,
    synced_at: datetime,
) -> int:
    """Merge new messages into the day's log file. Returns count actually added."""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    path = log_path(date_str)
    existing_ids = read_existing_ids(date_str)
    fresh = [m for m in new_messages if m.id not in existing_ids]
    if not fresh:
        return 0

    if path.exists():
        body = path.read_text(encoding="utf-8")
    else:
        body = _new_day_skeleton(date_str)

    # Combine existing raw bullets with new ones, sort by message id ascending
    # (ascending id ≈ ascending time in this channel; reliable as a total order).
    prior_raw = _slice_between(body, RAW_START, RAW_END) or ""
    prior_bullets: list[tuple[int, str]] = []
    for line in prior_raw.splitlines():
        m = MSG_ID_RE.search(line)
        if m:
            prior_bullets.append((int(m.group(1)), line.rstrip()))

    fresh_bullets = [(m.id, m.render_bullet()) for m in fresh]
    merged = sorted(prior_bullets + fresh_bullets, key=lambda x: x[0])

    new_raw_block = _render_raw_block(merged, last_msg_id, synced_at)
    new_body = _replace_between(body, RAW_START, RAW_END, new_raw_block)
    path.write_text(new_body, encoding="utf-8")
    return len(fresh)


def _new_day_skeleton(date_str: str) -> str:
    return (
        f"# {date_str} (UTC+7)\n\n"
        f"{DIGEST_START}\n"
        f"## Digest\n\n"
        f"_not yet generated_\n"
        f"{DIGEST_END}\n\n"
        f"{RAW_START}\n"
        f"## Raw messages\n\n"
        f"{RAW_END}\n"
    )


def _render_raw_block(
    bullets: Iterable[tuple[int, str]],
    last_msg_id: int,
    synced_at: datetime,
) -> str:
    header = f"## Raw messages\n\n_last synced {synced_at.strftime('%Y-%m-%dT%H:%M:%SZ')} (last_msg_id={last_msg_id})_\n\n"
    body_lines = [line for _id, line in bullets]
    body = "\n".join(body_lines) + ("\n" if body_lines else "")
    return header + body


def _slice_between(body: str, start: str, end: str) -> str | None:
    i = body.find(start)
    if i < 0:
        return None
    j = body.find(end, i + len(start))
    if j < 0:
        return None
    return body[i + len(start) : j]


def _replace_between(body: str, start: str, end: str, new_inner: str) -> str:
    i = body.find(start)
    if i < 0:
        raise ValueError(f"missing {start!r} marker")
    j = body.find(end, i + len(start))
    if j < 0:
        raise ValueError(f"missing {end!r} marker")
    return body[: i + len(start)] + "\n" + new_inner.rstrip() + "\n" + body[j:]


# ─────────────────────────────────────────────────────────────────────────────
# Sync state
# ─────────────────────────────────────────────────────────────────────────────


def read_state() -> dict:
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        print("⚠ .sync-state.json is malformed, ignoring", file=sys.stderr)
        return {}


def write_state(last_msg_id: int, last_sync_at: datetime) -> None:
    STATE_FILE.write_text(
        json.dumps(
            {
                "lastMessageId": last_msg_id,
                "lastSyncAt": last_sync_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "chat": CHAT_NAME,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────


def main() -> int:
    ap = argparse.ArgumentParser(description="Incremental Telegram sync for defi-monitor")
    ap.add_argument(
        "--since",
        help="Override the --since window (e.g. '7d', '30d'). Default: 7d on first run, 2d incremental.",
    )
    ap.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_LIMIT,
        help=f"Max messages to fetch per run (default {DEFAULT_LIMIT})",
    )
    args = ap.parse_args()

    state = read_state()
    last_known_id = int(state.get("lastMessageId") or 0)
    first_run = last_known_id == 0

    since = args.since or (DEFAULT_FIRSTRUN_SINCE if first_run else DEFAULT_INCREMENTAL_SINCE)
    print(
        f"› sync starting ({'first run' if first_run else f'resuming from id={last_known_id}'})",
        f"window={since} limit={args.limit}",
        file=sys.stderr,
    )

    messages = fetch_messages(since=since, limit=args.limit)
    print(f"  fetched {len(messages)} messages from Telegram", file=sys.stderr)

    # Filter to unseen (strict >), since telegram read can overlap the last run
    fresh = [m for m in messages if m.id > last_known_id]
    if not fresh:
        print("› nothing new since last sync", file=sys.stderr)
        return 0

    high_water = max(m.id for m in fresh)
    synced_at = datetime.now(tz=timezone.utc)

    # Partition by local day
    by_day: dict[str, list[Message]] = {}
    for m in fresh:
        by_day.setdefault(m.local_date, []).append(m)

    print(f"› partitioned into {len(by_day)} day(s)", file=sys.stderr)
    for date_str in sorted(by_day.keys()):
        added = upsert_day(date_str, by_day[date_str], high_water, synced_at)
        print(f"  {date_str}: +{added} new message(s)", file=sys.stderr)

    write_state(high_water, synced_at)
    print(f"› sync complete - last_msg_id={high_water}", file=sys.stderr)

    # machine-readable summary on stdout for the skill
    print(
        json.dumps(
            {
                "ok": True,
                "datesTouched": sorted(by_day.keys()),
                "messageCount": len(fresh),
                "lastMessageId": high_water,
                "syncedAt": synced_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
