#!/bin/bash
# Diff current EVENTS.md event ids against the last-announced snapshot.
# Send (via `openclaw message send`) any new ids, then update the snapshot.
# First run (no snapshot file) just establishes a baseline silently.
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

CURRENT_IDS=$(grep -oE 'Event id:\*\* `[^`]+`' "$EVENTS_FILE" | sed 's/.*`\(.*\)`.*/\1/' | sort -u)
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
while IFS= read -r id; do
  [ -z "$id" ] && continue
  line=$(grep -B6 -F "\`$id\`" "$EVENTS_FILE" | grep -m1 '^## ' | sed 's/^## //')
  HEADLINES+="• ${line:-$id}"$'\n'
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
