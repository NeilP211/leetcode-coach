#!/bin/zsh
# Daily run: sync Todoist, then commit and push the updated progress.
set -u
cd "$(dirname "$0")/.."
echo "== $(date '+%Y-%m-%d %H:%M:%S')"
./bin/lc sync || exit 1
if ! git diff --quiet -- data/state.json README.md; then
  git add data/state.json README.md
  git commit -q -m "Progress update $(date '+%b %-d')" && git push -q || echo "push failed, will retry next run"
fi
