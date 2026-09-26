"""The single JSON file that holds config, the event log and task bookkeeping."""

import copy
import fcntl
import json
import os
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path

from . import srs

# Progress is personal, so it lives outside the code repo (in its own private
# git repo, see scripts/daily.sh). LC_STATE points somewhere else if needed.
STATE_FILE = Path(os.environ.get("LC_STATE", Path.home() / ".leetcode-coach" / "state.json"))

DEFAULT_CONFIG = {
    "review_per_day": 2,
    "new_per_day": 2,
    "mock_weekday": None,  # mocks are off; 0 to 6 (Monday is 0) turns on a weekly one
    "max_interval": srs.DEFAULT_MAX_INTERVAL,
    "cram_days": 10,  # how close an interview has to be to switch to cram mode
    "label": "leetcode",
    "project_id": None,  # None means the Inbox
}

EMPTY = {
    "version": 1,
    "config": DEFAULT_CONFIG,
    "events": [],
    "assignments": {},
    "daily": {},
    "days": {},
    "interviews": [],
    "insights": {},
    "sessions": [],
    "next_seq": 1,
    "next_aid": 1,
}


def fresh():
    return copy.deepcopy(EMPTY)


def load(path=None):
    path = Path(path or STATE_FILE)
    state = json.loads(path.read_text()) if path.exists() else fresh()
    for key, value in EMPTY.items():
        state.setdefault(key, copy.deepcopy(value))
    state["config"] = {**DEFAULT_CONFIG, **state["config"]}
    return state


def save(state, path=None):
    path = Path(path or STATE_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=1) + "\n")
    os.replace(tmp, path)


@contextmanager
def locked(path=None):
    """Load, yield, and save the state while holding an exclusive file lock."""
    path = Path(path or STATE_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path.with_suffix(".lock"), "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        state = load(path)
        yield state
        save(state, path)


def add_event(state, kind, problem, when, **fields):
    ev = {"seq": state["next_seq"], "date": str(when), "problem": problem, "kind": kind}
    ev.update({k: v for k, v in fields.items() if v is not None})
    state["next_seq"] += 1
    state["events"].append(ev)
    return ev


def cards(state):
    return srs.replay(state["events"], state["config"]["max_interval"])


def open_assignments(state):
    return {aid: a for aid, a in state["assignments"].items() if a["status"] == "open"}


def next_interview(state, today):
    upcoming = sorted(
        (i for i in state["interviews"] if date.fromisoformat(i["date"]) >= today),
        key=lambda i: i["date"],
    )
    return upcoming[0] if upcoming else None


def prune_days(state, today, keep=60):
    cutoff = str(today - timedelta(days=keep))
    state["days"] = {k: v for k, v in state["days"].items() if k >= cutoff}
