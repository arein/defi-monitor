#!/bin/bash
# Diff current EVENTS.md against the last-announced snapshot and send any
# new incidents to Telegram via `openclaw message send`. First run (no
# snapshot file) just establishes a baseline silently.
#
# Fingerprint format: "{first_date}|{protocol}|{title}", parsed from the
# `## {emoji} {first_date}[ → {last_date}] - {protocol}: {title}` headings
# rendered by scripts/events.py:render_events_md. The pre-2026-04-29 format
# embedded `Event id:** \`<id>\`` markers in the body; events.py no longer
# emits those, so the heading is now the only stable identifier in the
# rendered file.
#
# Invoked by the openclaw cron defi-monitor job after /defi-monitor sync.

set -u

REPO="/home/openclaw/code/defi-monitor"
EVENTS_FILE="$REPO/EVENTS.md"
IDS_SNAPSHOT="$REPO/.events.known-ids"

# Telegram target: shared Openclaw group also used by /pulse + WCT alerts.
TG_CHANNEL="telegram"
TG_TARGET="-1003710151864"
SEND_TIMEOUT=60

export PATH="/home/openclaw/.local/bin:/home/openclaw/.npm-global/bin:/usr/local/bin:/usr/bin:/bin"

cd "$REPO" || { echo "cd $REPO failed" >&2; exit 1; }

if [ ! -f "$EVENTS_FILE" ]; then
  echo "EVENTS.md missing, nothing to notify"
  exit 0
fi

CURRENT_IDS=$(grep -E '^## ' "$EVENTS_FILE" \
  | sed -nE 's/^## [^[:alnum:]]*([0-9]{4}-[0-9]{2}-[0-9]{2})( → [0-9]{4}-[0-9]{2}-[0-9]{2})? - ([^:]+): (.+)$/\1|\3|\4/p' \
  | sort -u)
TOTAL_IDS=$(printf '%s\n' "$CURRENT_IDS" | grep -c .)

if [ ! -f "$IDS_SNAPSHOT" ]; then
  printf '%s\n' "$CURRENT_IDS" >"$IDS_SNAPSHOT"
  echo "baseline established ($TOTAL_IDS ids); no announce"
  exit 0
fi

NEW_IDS=$(comm -13 <(sort -u "$IDS_SNAPSHOT") <(printf '%s\n' "$CURRENT_IDS"))

if [ -z "$NEW_IDS" ]; then
  echo "no new event ids ($TOTAL_IDS known)"
  exit 0
fi

COUNT=$(printf '%s\n' "$NEW_IDS" | grep -c .)
HEADLINES=""
while IFS= read -r fp; do
  [ -z "$fp" ] && continue
  # fp = "{date}|{protocol}|{title}" - render as "{date} - {protocol}: {title}"
  date_part="${fp%%|*}"
  rest="${fp#*|}"
  protocol_part="${rest%%|*}"
  title_part="${rest#*|}"
  HEADLINES+="• ${date_part} - ${protocol_part}: ${title_part}"$'\n'
done <<<"$NEW_IDS"

MSG="🛡️ DeFi Monitor: $COUNT new incident(s)"$'\n'"$HEADLINES"
MSG+="See: $EVENTS_FILE"

# Delivery semantics (mirrors the rule in pulse/SKILL.md step 5a):
#   - rc 0           → delivered cleanly; advance snapshot.
#   - rc 124/137/143 → timeout/SIGKILL/SIGTERM. Telegram may have already
#                      accepted the POST before we killed the process. Prefer
#                      under-delivery to duplicates: advance snapshot anyway.
#   - other rc       → CLI returned an error; not delivered. Keep snapshot so
#                      next run retries.
timeout "$SEND_TIMEOUT" openclaw message send \
  --channel "$TG_CHANNEL" \
  --target "$TG_TARGET" \
  --message "$MSG"
RC=$?

case "$RC" in
  0)
    printf '%s\n' "$CURRENT_IDS" >"$IDS_SNAPSHOT"
    echo "sent $COUNT new incident(s) to telegram:$TG_TARGET; snapshot updated"
    ;;
  124|137|143)
    printf '%s\n' "$CURRENT_IDS" >"$IDS_SNAPSHOT"
    echo "send timed out (rc=$RC); assuming delivered, snapshot advanced to avoid duplicate" >&2
    ;;
  *)
    echo "send failed (rc=$RC); keeping old snapshot for retry next run" >&2
    exit 1
    ;;
esac
