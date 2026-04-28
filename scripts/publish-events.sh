#!/bin/bash
# Auto-publish EVENTS.md to origin/main so the GitHub Pages site at
# https://arein.github.io/defi-monitor/ stays in sync with the latest
# rollup.
#
# Idempotent: no-op if EVENTS.md is unchanged or only the rebuild
# timestamp changed.
#
# Invoked by the openclaw cron defi-monitor job after notify-new-events.sh.

set -u

REPO="${DEFI_MONITOR_REPO:-/home/openclaw/code/defi-monitor}"
cd "$REPO" || { echo "cd $REPO failed" >&2; exit 1; }

# Refuse to publish if any tracked file other than EVENTS.md is dirty.
# Keeps the auto-publish path narrowly scoped to the rollup.
OTHER_DIRTY=$(git status --porcelain -- ':(exclude)EVENTS.md' | grep -v '^??' || true)
if [ -n "$OTHER_DIRTY" ]; then
  echo "refusing to auto-publish: other tracked files are dirty:" >&2
  echo "$OTHER_DIRTY" >&2
  exit 1
fi

# Smart diff: ignore the "_Last rebuild: ..._" line which changes every run.
SUBSTANTIVE=$(git diff -- EVENTS.md \
  | grep -E '^[+-]' \
  | grep -vE '^(---|\+\+\+) ' \
  | grep -vE '^[+-]_Last rebuild:' || true)

if [ -z "$SUBSTANTIVE" ]; then
  if ! git diff --quiet EVENTS.md; then
    # Only the rebuild timestamp changed; revert it so we don't stage noise.
    git checkout -- EVENTS.md
  fi
  echo "EVENTS.md unchanged (or timestamp-only); nothing to publish"
  exit 0
fi

# Pull the latest before pushing. Fast-forward only - if rebase would be
# needed, bail and let a human resolve.
if ! git fetch origin main --quiet; then
  echo "git fetch failed; aborting" >&2
  exit 1
fi
if ! git pull --ff-only origin main --quiet; then
  echo "git pull --ff-only failed; local diverged from origin/main, aborting" >&2
  exit 1
fi

# Stage + commit (signing disabled here is the operator's responsibility:
# set commit.gpgsign=false on this clone, or configure a non-YubiKey GPG
# key for the cron user). We don't pass --no-verify or -c gpgsign=false so
# misconfiguration surfaces loudly rather than silently producing unsigned
# commits.
git add EVENTS.md
COMMIT_MSG="events: auto-publish $(date -u +%Y-%m-%dT%H:%MZ)"
if ! git commit -m "$COMMIT_MSG"; then
  echo "git commit failed (signing config? unset author?); aborting" >&2
  exit 1
fi

# Push. If the push fails (auth, network), the commit stays in the local
# branch and the next run will retry by stacking another commit on top.
if ! git push origin main; then
  echo "git push failed; local commit kept, will retry next run" >&2
  exit 1
fi

echo "EVENTS.md published"
