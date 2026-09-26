#!/bin/zsh
# Installs a LaunchAgent that runs scripts/daily.sh at 6:00 and 17:00 every day.
# launchd runs a missed slot as soon as the Mac wakes up, so a closed laptop
# at 6:00 just means the list shows up when it opens.
set -eu
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LABEL="com.neilp211.leetcode-coach"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG="$HOME/Library/Logs/leetcode-coach.log"
mkdir -p "$HOME/Library/LaunchAgents" "$HOME/Library/Logs"
sed -e "s#__ROOT__#$ROOT#g" -e "s#__LOG__#$LOG#g" -e "s#__LABEL__#$LABEL#g" \
  "$ROOT/ops/launchd.plist" > "$PLIST"
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "installed $PLIST, logging to $LOG"
