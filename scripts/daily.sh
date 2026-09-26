#!/bin/zsh
# Daily run: sync Todoist, then back up the progress file.
# Progress lives outside this repo (~/.leetcode-coach by default). If that
# folder is a git repo, the updated state is committed and pushed there.
set -u
cd "$(dirname "$0")/.."
echo "== $(date '+%Y-%m-%d %H:%M:%S')"
./bin/lc sync || exit 1
DATA="$(dirname "${LC_STATE:-$HOME/.leetcode-coach/state.json}")"
if [ -d "$DATA/.git" ] && ! git -C "$DATA" diff --quiet -- state.json; then
  git -C "$DATA" add state.json
  git -C "$DATA" commit -q -m "Progress $(date '+%b %-d')" && git -C "$DATA" push -q || echo "push failed, will retry next run"
fi
