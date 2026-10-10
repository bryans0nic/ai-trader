#!/usr/bin/env bash
# Deploys merged PRs to this Mac: when origin/main has moved, fast-forward this checkout, sync packages if the
# lockfile changed, and restart the dashboard service. Run every 2 minutes by launchd (install-mac.sh); safe to
# run by hand. Same pattern as ClaudeOS / SocialOS.
set -euo pipefail

DIR="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$DIR"
LABEL=com.aitrader.dashboard
LOCK="$DIR/.deploy.lock"
log() { printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"; }

[ "$(git branch --show-current)" = main ] || exit 0 # someone is working on another branch here
GIT_TERMINAL_PROMPT=0 git fetch --quiet origin main
OLD="$(git rev-parse HEAD)"
NEW="$(git rev-parse origin/main)"
[ "$OLD" != "$NEW" ] || exit 0

mkdir "$LOCK" 2>/dev/null || exit 0 # a deploy is already running
trap 'rmdir "$LOCK"' EXIT

if ! git merge --ff-only --quiet "$NEW"; then
  log "can't deploy $(git rev-parse --short "$NEW"): local changes or commits are in the way (see git status)"
  exit 1
fi
log "deployed $(git rev-parse --short "$OLD")..$(git rev-parse --short "$NEW"): $(git log -1 --format=%s "$NEW")"

if ! git diff --quiet "$OLD" "$NEW" -- uv.lock pyproject.toml; then
  log "packages changed, running uv sync"
  uv sync --frozen
fi
launchctl kickstart -k "gui/$(id -u)/$LABEL"
log "restarted $LABEL"
