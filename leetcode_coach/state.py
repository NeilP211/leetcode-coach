"""The single JSON file that holds config, the event log and task bookkeeping."""

import copy
import fcntl
import json
import os
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path

from . import srs

STATE_FILE = Path(os.environ.get(
    "LC_STATE", Path(__file__).resolve().parent.parent / "data" / "state.json"
))

DEFAULT_CONFIG = {
    "review_per_day": 2,
    "new_per_day": 2,
    "mock_weekday": 5,  # Monday is 0, so Saturday
    "max_interval": srs.DEFAULT_MAX_INTERVAL,
    "cram_days": 10,  # how close an interview has to be to switch to cram mode
    "label": "leetcode",
    "project_id": None,  # None means the Inbox
}

# Kept in a gitignored side file so the public repo never shows who I am
# interviewing with or my raw session notes.
PRIVATE_KEYS = ("interviews", "sessions")

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


def private_path(path):
    return Path(path).with_name(Path(path).stem + ".private.json")


def load(path=None):
    path = Path(path or STATE_FILE)
    state = json.loads(path.read_text()) if path.exists() else fresh()
    priv = private_path(path)
    if priv.exists():
        state.update(json.loads(priv.read_text()))
    for key, value in EMPTY.items():
        state.setdefault(key, copy.deepcopy(value))
    state["config"] = {**DEFAULT_CONFIG, **state["config"]}
    return state


def _write(path, data):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1) + "\n")
    os.replace(tmp, path)


def save(state, path=None):
    path = Path(path or STATE_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    public = {k: v for k, v in state.items() if k not in PRIVATE_KEYS}
    _write(path, public)
    _write(private_path(path), {k: state[k] for k in PRIVATE_KEYS})


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
