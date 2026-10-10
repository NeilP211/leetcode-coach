#!/bin/zsh
# Daily run: sync Todoist, then back up the progress file.
# Progress lives outside this repo (~/.leetcode-coach by default). If that
# folder is a git repo, the updated state is committed and pushed there.
set -u
cd "$(dirname "$0")/.."
echo "== $(date '+%Y-%m-%d %H:%M:%S')"
# The 6:00 run can fire the moment the Mac wakes, before the network is up, and
# Todoist has the odd bad minute. A failed sync saves nothing, so trying again is safe.
tries=0
until ./bin/lc sync; do
  tries=$((tries + 1))
  if [ "$tries" -ge 4 ]; then
    echo "sync failed $tries times, giving up until the next run"
    exit 1
  fi
  echo "sync failed, trying again in ${LC_RETRY_WAIT:-60}s"
  sleep "${LC_RETRY_WAIT:-60}"
done
DATA="$(dirname "${LC_STATE:-$HOME/.leetcode-coach/state.json}")"
if [ -d "$DATA/.git" ] && ! git -C "$DATA" diff --quiet -- state.json; then
  git -C "$DATA" add state.json
  git -C "$DATA" commit -q -m "Progress $(date '+%b %-d')" && git -C "$DATA" push -q || echo "push failed, will retry next run"
fi
