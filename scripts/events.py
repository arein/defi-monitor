#!/usr/bin/env python3
"""
Roll up noteworthy DeFi security events from every `logs/YYYY-MM-DD.md` into
a single `EVENTS.md` at the repo root.

Source of truth: a JSON array between `<!-- events:start -->` and
`<!-- events:end -->` markers inside each day's digest section. The digest
prompt in SKILL.md instructs Claude to emit that block alongside the prose
when writing a digest. This script parses the blocks, aggregates across
days, and writes EVENTS.md.

No LLM call. Pure stdlib. Fast to run at the end of every sync / digest /
replay invocation.

Event schema (per object in the JSON array):
    {
      "id": "kelp-rseth-lz-apr2026",         // optional stable key; events
                                             //   sharing an id across days are
                                             //   merged into one EVENTS.md row
      "severity": "critical" | "high" | "med" | "low",
      "type": "exploit" | "depeg" | "governance_attack" | "phishing"
              | "infrastructure" | "discussion" | "other",
      "protocol": "Kelp DAO",                // freeform name
      "title": "rsETH LayerZero DVN exploit",  // 4-12 words
      "participants": ["james-prestwich", ...]  // optional
    }

When `id` is set on multiple days, this script keeps the highest severity,
the first-seen type / protocol / title, the union of participants, and the
full set of dates where the incident appeared. Events without an `id` are
treated as unique (legacy behavior).

Usage:
    python3 scripts/events.py               # rebuild EVENTS.md from all logs
    python3 scripts/events.py --min-severity med   # filter (default med)
    python3 scripts/events.py --out /tmp/events.md # alternate output
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LOGS_DIR = REPO_ROOT / "logs"
DEFAULT_OUTPUT = REPO_ROOT / "EVENTS.md"

EVENTS_START = "<!-- events:start -->"
EVENTS_END = "<!-- events:end -->"
DIGEST_START = "<!-- digest:start -->"
DIGEST_END = "<!-- digest:end -->"

DATE_FILE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\.md$")

SEVERITY_RANK = {"low": 0, "med": 1, "high": 2, "critical": 3}
SEVERITY_EMOJI = {"critical": "🔴", "high": "🟠", "med": "🟡", "low": "🟢"}

# Types we show in EVENTS.md. "discussion" and "other" are emitted by the
# digest but filtered out of the rollup — they're not incidents.
INCIDENT_TYPES = {"exploit", "depeg", "governance_attack", "phishing", "infrastructure"}


@dataclass(frozen=True)
class Event:
    date: str  # YYYY-MM-DD (UTC+7, matches the log filename)
    severity: str
    type: str
    protocol: str
    title: str
    participants: tuple[str, ...]
    id: str = ""  # optional stable key for cross-day dedup

    def severity_rank(self) -> int:
        return SEVERITY_RANK.get(self.severity, -1)


@dataclass
class MergedEvent:
    """One row in EVENTS.md. May span multiple days if events shared an id."""
    id: str
    severity: str  # highest
    type: str
    protocol: str
    title: str
    participants: tuple[str, ...]
    dates: list[str]  # ascending, unique

    @property
    def first_date(self) -> str:
        return self.dates[0]

    @property
    def last_date(self) -> str:
        return self.dates[-1]

    def severity_rank(self) -> int:
        return SEVERITY_RANK.get(self.severity, -1)


def merge_events(events: list[Event]) -> list[MergedEvent]:
    """Group by id; events without an id are treated as singletons."""
    by_id: dict[str, list[Event]] = {}
    singletons: list[Event] = []
    for e in events:
        if e.id:
            by_id.setdefault(e.id, []).append(e)
        else:
            singletons.append(e)

    merged: list[MergedEvent] = []

    for group_id, group in by_id.items():
        # Highest severity wins for the display rank.
        top = max(group, key=lambda g: g.severity_rank())
        # Earliest-date occurrence supplies the canonical type/protocol/title
        # (the first reporter usually frames the incident most accurately).
        earliest = min(group, key=lambda g: g.date)
        dates = sorted({e.date for e in group})
        # Union participants, preserving order of first appearance across the
        # dates (roughly chronological). Case-insensitive dedup so "Tay" and
        # "tay" don't both show up.
        seen: set[str] = set()
        participants: list[str] = []
        for e in sorted(group, key=lambda g: g.date):
            for p in e.participants:
                key = p.lower()
                if p and key not in seen:
                    seen.add(key)
                    participants.append(p)
        merged.append(
            MergedEvent(
                id=group_id,
                severity=top.severity,
                type=earliest.type,
                protocol=earliest.protocol,
                title=earliest.title,
                participants=tuple(participants),
                dates=dates,
            )
        )

    for e in singletons:
        merged.append(
            MergedEvent(
                id="",
                severity=e.severity,
                type=e.type,
                protocol=e.protocol,
                title=e.title,
                participants=e.participants,
                dates=[e.date],
            )
        )

    return merged


def _slice_between(body: str, start: str, end: str) -> str | None:
    i = body.find(start)
    if i < 0:
        return None
    j = body.find(end, i + len(start))
    if j < 0:
        return None
    return body[i + len(start) : j]


def parse_events_from_log(path: Path) -> tuple[list[Event], str | None]:
    """Return (events, error_or_none). error_or_none is a short diagnostic if
    parsing the JSON block failed — callers can log it without aborting the
    whole rollup."""
    m = DATE_FILE_RE.match(path.name)
    if not m:
        return [], None
    date = m.group(1)

    body = path.read_text(encoding="utf-8")
    digest_block = _slice_between(body, DIGEST_START, DIGEST_END)
    if digest_block is None:
        return [], None
    events_block = _slice_between(digest_block, EVENTS_START, EVENTS_END)
    if events_block is None:
        # Digest exists but no events block yet (older format, or empty day).
        return [], None

    raw = events_block.strip()
    if not raw or raw.lower() in {"[]", "_none_", "_quiet day_"}:
        return [], None

    # Tolerate fenced code blocks around the JSON.
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```\s*$", "", raw)

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        return [], f"{path.name}: events block is not valid JSON ({e.msg} at line {e.lineno})"

    if not isinstance(data, list):
        return [], f"{path.name}: events block must be a JSON array, got {type(data).__name__}"

    out: list[Event] = []
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            return out, f"{path.name}: events[{i}] is not an object"
        try:
            out.append(
                Event(
                    date=date,
                    severity=str(item.get("severity", "")).strip().lower(),
                    type=str(item.get("type", "")).strip().lower(),
                    protocol=str(item.get("protocol", "")).strip(),
                    title=str(item.get("title", "")).strip(),
                    participants=tuple(str(p).strip() for p in item.get("participants") or []),
                    id=str(item.get("id", "")).strip().lower(),
                )
            )
        except (TypeError, ValueError) as e:
            return out, f"{path.name}: events[{i}] malformed: {e}"
    return out, None


def collect_events(min_severity: str) -> tuple[list[MergedEvent], list[str], list[str]]:
    """Returns (filtered_merged_events, parse_warnings, dates_seen)."""
    if not LOGS_DIR.exists():
        return [], [], []

    threshold = SEVERITY_RANK.get(min_severity, 1)
    raw_events: list[Event] = []
    warnings: list[str] = []
    dates_seen: list[str] = []

    for path in sorted(LOGS_DIR.glob("*.md")):
        parsed, warning = parse_events_from_log(path)
        if warning:
            warnings.append(warning)
        m = DATE_FILE_RE.match(path.name)
        if m:
            dates_seen.append(m.group(1))
        raw_events.extend(parsed)

    merged = merge_events(raw_events)
    # Apply both the severity threshold AND the type filter after merging.
    # Filtering by type pre-merge would drop day-1 "discussion" entries that
    # later escalate to "exploit" on day 2, losing the earliest-seen date and
    # any first-day participants from the merged row.
    merged = [
        m for m in merged
        if m.severity_rank() >= threshold
        and (not m.type or m.type in INCIDENT_TYPES)
    ]

    # Sort: most-recent activity first, then severity desc, then title asc.
    # Stable-sort in reverse key priority so all three orderings land.
    merged.sort(key=lambda m: m.title)
    merged.sort(key=lambda m: m.severity_rank(), reverse=True)
    merged.sort(key=lambda m: m.last_date, reverse=True)
    return merged, warnings, dates_seen


def render_events_md(
    events: list[MergedEvent],
    dates_seen: list[str],
    warnings: list[str],
    min_severity: str,
) -> str:
    now = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    span = (
        f"{min(dates_seen)} → {max(dates_seen)}" if dates_seen else "(no logs yet)"
    )

    lines: list[str] = [
        "# 🛡️ DeFi Security Events",
        "",
        "Rolled up from every per-day digest by `scripts/events.py`",
        "(machine-local; the raw chat archive is not published here).",
        "**Don't hand-edit** - next run overwrites.",
        "",
        f"_Last rebuild: {now} · spans {span} · {len(events)} event"
        f"{'' if len(events) == 1 else 's'} at severity ≥ {min_severity}._",
        "",
        "Severity legend: 🔴 critical · 🟠 high · 🟡 med · 🟢 low",
        "",
        "---",
        "",
    ]

    if warnings:
        lines.append("> **Parse warnings:**")
        for w in warnings:
            lines.append(f"> - {w}")
        lines.append("")
        lines.append("---")
        lines.append("")

    if not events:
        lines.append(
            "_No incidents parsed yet. If you have log files, their digests may"
            " predate the events-block format — run `/defi-monitor replay <from>"
            " <to>` to rebuild them._"
        )
        lines.append("")
        return "\n".join(lines)

    for e in events:
        emoji = SEVERITY_EMOJI.get(e.severity, "⚪")
        title = e.title or "(untitled)"
        protocol = e.protocol or "(unknown protocol)"
        date_label = e.first_date if len(e.dates) == 1 else f"{e.first_date} → {e.last_date}"
        lines.append(f"## {emoji} {date_label} - {protocol}: {title}")
        lines.append("")
        lines.append(f"- **Severity:** {e.severity or 'unknown'}")
        lines.append(f"- **Type:** {e.type or 'unknown'}")
        if e.participants:
            lines.append(f"- **Driven by:** {', '.join(e.participants)}")
        lines.append("")

    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="Rebuild EVENTS.md from logs/")
    ap.add_argument(
        "--min-severity",
        default="med",
        choices=["low", "med", "high", "critical"],
        help="Only include events at this severity or higher (default: med)",
    )
    ap.add_argument(
        "--out",
        default=str(DEFAULT_OUTPUT),
        help=f"Output path (default: {DEFAULT_OUTPUT})",
    )
    args = ap.parse_args()

    events, warnings, dates_seen = collect_events(min_severity=args.min_severity)
    out_path = Path(args.out).resolve()
    out_path.write_text(
        render_events_md(events, dates_seen, warnings, args.min_severity),
        encoding="utf-8",
    )

    for w in warnings:
        print(f"⚠ {w}", file=sys.stderr)
    print(
        json.dumps(
            {
                "ok": True,
                "written": str(out_path),
                "eventCount": len(events),
                "daysScanned": len(dates_seen),
                "warnings": warnings,
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
