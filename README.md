# leetcode-coach

[![tests](https://github.com/NeilP211/leetcode-coach/actions/workflows/test.yml/badge.svg)](https://github.com/NeilP211/leetcode-coach/actions/workflows/test.yml)

A spaced repetition coach for the [NeetCode 250](https://neetcode.io/practice/practice/neetcode250).
Every morning it puts one task on my Todoist with that day's exact problems: a couple of redos of
problems I am about to forget, plus the next new problems on the roadmap. Anything I don't finish
rolls into the next day's task until it's done. After a session I log how each problem went
(clean, a fight, needed the video), and that decides when each one comes back.

The point: doing a problem once and moving on doesn't stick. Problems I needed the video for
come back two days later, from a blank editor. Problems I get clean come back less and less
often until they stick for three weeks or more.

## A day on the list

One task, everything in the description:

```
LeetCode Sep 27: 2 redos, 2 new                                    p1

About 120 minutes. Redos first while you are fresh, then new problems.

Redos (topic hidden on purpose: spotting the pattern cold is the point)
1. Search In Rotated Sorted Array, Medium: redo #2, last time (Sep 25) you needed the video
2. Reorder List, Medium: first redo since you solved it before this list started

New
3. Sliding Window Maximum, Hard, Sliding Window (LeetCode, video after a real attempt)
4. Time Based Key Value Store, Medium, Binary Search (rolled over from Sep 26)
```

- **Redos** hide the topic on purpose. Spotting the pattern cold is half of a real interview,
  and doing problems in topic order hides that part.
- **New problems** include the topic, NeetCode and LeetCode links, and the video link for after a
  real 30 to 40 minute attempt.
- **Mocks** are off by default. `lc config mock_weekday 5` makes Saturdays swap one new problem
  for an unseen medium from a topic I've mostly covered, with the topic hidden.
- **150 only:** `lc config only_150 true` keeps new problems and mocks inside the NeetCode 150,
  so a weak topic no longer pulls in a practice problem from the 250 extras.
- **Focus list:** `lc focus set "number of islands" "coin change"` puts hand-picked problems at
  the front of the new problem queue, in that order. `lc focus clear` goes back to the usual track.
- **Pause:** `lc config pause_until 2026-10-08` stops new lists and rollovers until that day (the open task just moves to it). `lc config pause_until off` ends it early.
- **Snooze:** `lc snooze "lru" --until 2026-10-08` holds one problem off the daily lists until a date (say, after an interview). It comes back as a normal redo then.
- **Checking the task off** records every problem on it as done. `lc skip` puts back one I didn't
  actually get to. If I don't check it off, tomorrow's task is the same task, rewritten with
  today's leftovers plus whatever slots are still free.

## How it decides

### When a problem comes back

Every solve is an event in an append-only log (`~/.leetcode-coach/state.json`). A problem's schedule is never
stored; it is rebuilt by replaying its events, so rating a solve a day late or correcting a
rating is just an edit and a replay.

The scheduler is an SM-2 variant with four grades:

| Grade | Meaning | Next redo |
|---|---|---|
| again | needed the video, or couldn't get it | 2 days |
| hard | got it, but with a hint, bugs, or way over time | first time 3 days, then gap x 1.2 |
| good | got it on my own in normal time | first time 7 days, then gap x ease |
| easy | instant | first time 14 days, then gap x ease x 1.3 |

Ease starts at 2.5, drops on struggles and rises on easy solves, so a problem I keep fumbling
comes back more often than one I always get. Gaps cap at 60 days during recruiting season, and
redos done late get partial credit for the extra time they survived.

New due dates are nudged within about 10 percent of the ideal gap onto the least loaded day, so
problems solved on the same day don't all come back on the same day.

### How much each day

The base is 2 redos and 2 new problems.

- More than 2 redos due: redos borrow new-problem slots, but at least `min_new` new problems
  (default 1) stay so the roadmap keeps moving. `lc config min_new 2` stops the borrowing.
- Three days' worth of redos due: a catch-up day with no new problems.
- A quiet day with nothing due pulls in redos due in the next 3 days, which flattens later spikes.
- Anything left over from earlier days counts toward today's slots instead of stacking on top.
- An interview within 10 days switches to cram mode: 1 new problem, an extra redo slot, and
  shaky problems (last graded again or hard) pulled forward.

### Which new problem is next

1. **Core first.** The NeetCode 150 easies and mediums plus the hards that come up often
   (Minimum Window Substring, Sliding Window Maximum, Merge K Sorted Lists, Serialize and
   Deserialize Binary Tree, and a few more), topic by topic: Sliding Window, Binary Search, Linked
   List, Trees, Tries, Heap, Backtracking, Graphs, 1-D DP, Advanced Graphs, 2-D DP.
2. **Light topics mixed in.** After Heap, every 4th new problem comes from Intervals, Greedy, Bit
   Manipulation or Math as a change of pace.
3. **Weak topics get extra reps.** Each topic gets a score from the latest grade of every problem
   in it. If a topic the roadmap has already moved past scores under 0.6, the next new problem is
   an unseen one from that topic's extra 100, to practice the same pattern on something fresh.
4. **Second pass.** Once the core is done: the remaining hards and the extras, then the warmup
   easies.

## Commands

```
lc                         status: today's list, what's due, progress by topic
lc sync                    record completed tasks and fill today's list
lc log "koko" -g again -v -m 45 -i "binary search on the answer, check feasibility"
lc log 146 -g good         problems resolve by name, fuzzy name, or LeetCode number
lc skip "lru"              checked the day off but didn't do this one: back on the list
lc snooze "lru" --until 2026-10-08   hold a problem off the lists until that date (--clear releases it)
lc more 1                  one more new problem today
lc more 2 --redo           two more redos today (soonest due, skipping anything done in the last 2 days)
lc show "lru cache"        history and saved insight for one problem
lc next 10                 preview the new problem queue
lc sheet                   every saved one line insight, grouped by topic
lc report                  progress by topic as a markdown table
lc interview add Acme 2026-10-20
lc config new_per_day 3
lc config only_150 true     stick to the NeetCode 150
lc focus set "number of islands" "coin change"   these come first as new problems
lc retire "two sum"        stop scheduling redos of something trivial
lc import-neetcode         pick up problems checked off on neetcode.io
```

`lc log` rates the attempt that checking off the task already recorded, or marks the problem
done if the task is still open, then rewrites the daily task (or closes it once everything on it
is logged). A video means `again` unless I say otherwise.

## Setup

Python 3.10+, no dependencies.

1. Todoist token (Settings, Integrations, Developer), stored in the macOS keychain:
   ```
   security add-generic-password -a "$USER" -s leetcode-coach-todoist -w "$(pbpaste)"
   ```
2. Link the command: `ln -s "$PWD/bin/lc" ~/.local/bin/lc`
3. Import what's already done from an open NeetCode tab (needs Chrome's View, Developer, Allow
   JavaScript from Apple Events):
   ```
   lc import-neetcode --seed --well "Arrays & Hashing" --recent "Two Pointers"
   ```
   Old solves are scheduled with a guessed gap by how well I know the topic, then spread so they
   come back a couple a day.
4. `scripts/install_launchd.sh` runs `scripts/daily.sh` at 6:00 and 17:00 (and on wake if the
   Mac was asleep).

Progress stays out of this repo. It lives in `~/.leetcode-coach/state.json` (or wherever
`LC_STATE` points), and if that folder is its own git repo, the daily run commits and pushes it
there, so a private repo makes a good backup.

`scripts/fetch_problems.py` rebuilds `data/problems.json` from neetcode.io, which ships the list
inside its JavaScript bundle.

## Tests

```
python3 -m pytest -q
```
