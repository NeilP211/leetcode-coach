"""Weeks of messy, random use against the fake Todoist.

Each seed plays out a different mix of finished days, days off, late logs,
setting changes, cram windows, pauses and asks for more. Whatever happens, a
sync may only fill the slots the day's targets leave open, and the one daily
task has to match what is still open.
"""

import random
from collections import Counter
from datetime import timedelta

import pytest

from conftest import SUN, FakeTodoist
from leetcode_coach import planner
from leetcode_coach import state as st
from leetcode_coach.debrief import log_attempt, skip, snooze
from leetcode_coach.srs import GRADES
from leetcode_coach.sync import sync

DAYS = 30
SEEDS = 8


def held_back(state, day):
    return {pid for pid, until in state.get("snooze", {}).items() if until > str(day)}


def checked_sync(state, catalog, todoist, day, extra_new=0, extra_review=0, twice=False):
    """One sync, then everything that has to be true after it. Returns what it added.

    twice runs a second plain sync right away, which must change nothing.
    """
    first_new = state["next_aid"]
    seen_before = {pid for pid, c in st.cards(state).items() if c.seen}
    targets, created, _ = sync(state, catalog, todoist, day,
                               extra_new=extra_new, extra_review=extra_review)
    if targets.get("reason", "").startswith("paused"):
        assert created == []
        return created

    A = state["assignments"]
    listed = state["days"][str(day)]["assignments"]
    made = [aid for aid in listed if int(aid[1:]) >= first_new]
    have = Counter(A[aid]["kind"] for aid in listed if int(aid[1:]) < first_new
                   and (A[aid]["status"] == "open" or A[aid].get("done_on") == str(day)))
    add = Counter(A[aid]["kind"] for aid in made)
    assert len(made) == len(created)

    # a sync only fills the slots the targets leave open, however many leftovers there are
    assert add["review"] <= max(0, targets["review"] - have["review"])
    assert add["mock"] <= max(0, targets["mock"] - have["mock"])
    spare = 1 if targets["mock"] > have["mock"] and not add["mock"] else 0
    assert add["new"] <= max(0, targets["new"] - have["new"] + spare)

    still_open = st.open_assignments(state)
    problems = [a["problem"] for a in still_open.values()]
    assert len(problems) == len(set(problems))          # never the same problem twice
    assert all(aid in listed for aid in still_open)     # nothing open is left off today
    assert not held_back(state, day) & set(problems)    # a held problem stays off the list
    for aid in made:
        if A[aid]["kind"] == "new":
            assert A[aid]["problem"] not in seen_before  # new means never solved

    tasks = todoist.open_tasks()
    if not still_open:
        assert tasks == []
    else:
        assert len(tasks) == 1
        task = tasks[0]
        assert state["daily"]["task"] == task["id"]
        assert sorted(state["daily"]["assignments"]) == sorted(still_open)
        n = Counter(a["kind"] for a in still_open.values())
        parts = []
        if n["review"]:
            parts.append(f"{n['review']} redo" + ("" if n["review"] == 1 else "s"))
        if n["new"]:
            parts.append(f"{n['new']} new")
        if n["mock"]:
            parts.append("mock")
        assert task["content"].split(": ", 1)[1] == ", ".join(parts)
        for a in still_open.values():
            assert f"[{catalog[a['problem']].name}]" in task["description"]

    if twice:
        todoist.calls.clear()
        _, again, _ = sync(state, catalog, todoist, day)
        assert again == [] and todoist.calls == []
    return created


def new_left(state, catalog, day):
    cards = st.cards(state)
    busy = {a["problem"] for a in st.open_assignments(state).values()} | held_back(state, day)
    return len(planner.new_queue(catalog, cards, busy, 0, bool(state["config"].get("only_150")),
                                 state.get("focus", ())))


@pytest.mark.parametrize("seed", range(SEEDS))
def test_random_weeks_never_overfill_a_day(catalog, seed):
    rng = random.Random(seed)
    state, todoist = st.fresh(), FakeTodoist()
    cfg = state["config"]
    cfg.update(only_150=rng.random() < 0.5, catch_up=rng.random() < 0.5)
    for p in rng.sample(catalog.problems, rng.randint(0, 40)):
        st.add_event(state, "seed", p.id, SUN - timedelta(days=rng.randint(1, 30)),
                     interval=rng.choice([3, 7, 14, 21]))

    for n in range(DAYS):
        day = SUN + timedelta(days=n)
        change = rng.random()
        if change < 0.12:
            cfg.update(review_per_day=rng.randint(0, 4), new_per_day=rng.randint(0, 4),
                       min_new=rng.randint(0, 3))
        elif change < 0.20:
            state["interviews"].append({"company": f"Co{n}", "notes": "",
                                        "date": str(day + timedelta(days=rng.randint(0, 12)))})
        elif change < 0.25:
            cfg["mock_weekday"] = rng.choice([None, day.weekday()])
        elif change < 0.28:
            cfg["pause_until"] = str(day + timedelta(days=rng.randint(1, 3)))
        checked_sync(state, catalog, todoist, day, twice=True)

        todo = list(st.open_assignments(state).values())
        task = state["daily"].get("task")
        did = rng.random()
        if todo and task and did < 0.35:    # checks the whole task off, rates most of it later
            todoist.complete(task, day)
            checked_sync(state, catalog, todoist, day)
            for a in todo:
                if rng.random() < 0.7:
                    log_attempt(state, catalog, a["problem"], grade=rng.choice(GRADES), when=day)
            if rng.random() < 0.3:
                skip(state, catalog, rng.choice(todo)["problem"], day)
        elif todo and did < 0.65:           # does some of it and logs each one
            for a in rng.sample(todo, rng.randint(1, len(todo))):
                log_attempt(state, catalog, a["problem"], grade=rng.choice(GRADES), when=day)
        elif todo and did < 0.72:
            snooze(state, catalog, rng.choice(todo)["problem"], day + timedelta(days=rng.randint(1, 4)))
        elif task and did < 0.77:
            todoist.delete(task)
        # anything else is a day off: it all rolls over

        if rng.random() < 0.3 and not str(day) < (cfg["pause_until"] or ""):
            more = rng.randint(1, 3)
            if rng.random() < 0.6:
                room = new_left(state, catalog, day)
                made = checked_sync(state, catalog, todoist, day, extra_new=more)
                # asking for N more always adds N, even when leftovers overflow the target
                assert sum(1 for kind, _ in made if kind == "new") >= min(more, room)
            else:
                checked_sync(state, catalog, todoist, day, extra_review=more)
        checked_sync(state, catalog, todoist, day, twice=True)
