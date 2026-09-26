import copy
from datetime import timedelta

from conftest import MON, SAT, SUN
from leetcode_coach import state as st
from leetcode_coach.debrief import log_attempt, skip, unrated
from leetcode_coach.sync import render_daily, sync

TUE = MON + timedelta(days=1)


def seed(state, catalog, names, when, interval=7):
    for n in names:
        st.add_event(state, "seed", catalog.find(n).id, when, interval=interval)


def only_task(todoist):
    tasks = todoist.open_tasks()
    assert len(tasks) == 1, tasks
    return tasks[0]


def attempts(state):
    return [e for e in state["events"] if e["kind"] == "attempt"]


def test_first_sync_makes_one_detailed_task(state, catalog, todoist):
    targets, created, _ = sync(state, catalog, todoist, SUN)
    assert targets["new"] == 2 and [c[0] for c in created] == ["new", "new"]
    t = only_task(todoist)
    assert t["content"] == "LeetCode Sep 27: 2 new"
    assert "[Contains Duplicate](https://neetcode.io/" in t["description"]
    assert "[Valid Anagram]" in t["description"]
    assert t["labels"] == ["leetcode"] and t["priority"] == 4
    assert t["due"]["date"] == str(SUN)


def test_resync_same_day_changes_nothing(state, catalog, todoist):
    sync(state, catalog, todoist, SUN)
    todoist.calls.clear()
    _, created, _ = sync(state, catalog, todoist, SUN)
    assert created == [] and todoist.calls == []


def test_checking_off_records_every_problem(state, catalog, todoist):
    sync(state, catalog, todoist, SUN)
    todoist.complete(only_task(todoist)["id"], SUN)
    sync(state, catalog, todoist, MON)
    done = attempts(state)
    assert len(done) == 2 and all(e["date"] == str(SUN) and "grade" not in e for e in done)
    assert len(unrated(state, catalog, today=MON)) == 2
    # Monday gets a fresh single task
    assert only_task(todoist)["content"].startswith("LeetCode Sep 28")


def test_unfinished_day_rolls_into_same_task(state, catalog, todoist):
    sync(state, catalog, todoist, SUN)
    tid = only_task(todoist)["id"]
    _, created, log = sync(state, catalog, todoist, MON)
    t = only_task(todoist)
    assert t["id"] == tid and t["due"]["date"] == str(MON)
    assert created == []  # both new slots are taken by Sunday's leftovers
    assert "rolled over from Sep 27" in t["description"]
    assert any("rolled over" in line for line in log)


def test_deleted_task_keeps_problems(state, catalog, todoist):
    sync(state, catalog, todoist, SUN)
    first = only_task(todoist)
    todoist.delete(first["id"])
    sync(state, catalog, todoist, MON)
    t = only_task(todoist)
    assert t["id"] != first["id"] and "Contains Duplicate" in t["description"]
    assert attempts(state) == []


def test_logging_everything_closes_the_task(state, catalog, todoist):
    sync(state, catalog, todoist, SUN)
    log_attempt(state, catalog, "contains duplicate", grade="easy", when=SUN)
    sync(state, catalog, todoist, SUN)
    t = only_task(todoist)
    assert "Contains Duplicate" not in t["content"] and "Already done today: Contains Duplicate" in t["description"]
    assert t["content"] == "LeetCode Sep 27: 1 new"
    log_attempt(state, catalog, "valid anagram", video=True, when=SUN)
    sync(state, catalog, todoist, SUN)
    assert todoist.open_tasks() == []
    assert [e["grade"] for e in attempts(state)] == ["easy", "again"]
    # and closing it ourselves must not record the problems twice
    sync(state, catalog, todoist, MON)
    assert len(attempts(state)) == 2


def test_log_rates_a_checked_off_problem(state, catalog, todoist):
    sync(state, catalog, todoist, SUN)
    todoist.complete(only_task(todoist)["id"], SUN)
    sync(state, catalog, todoist, MON)
    msg = log_attempt(state, catalog, "valid anagram", video=True, minutes=50,
                      insight="count chars", when=MON)
    assert msg.startswith("rated")
    ev = [e for e in attempts(state) if e["problem"] == catalog.find("valid anagram").id]
    assert len(ev) == 1 and ev[0]["grade"] == "again" and ev[0]["video"]
    assert st.cards(state)[ev[0]["problem"]].due == SUN + timedelta(days=2)
    assert state["insights"][ev[0]["problem"]] == "count chars"


def test_skip_after_checking_off_puts_it_back(state, catalog, todoist):
    sync(state, catalog, todoist, SUN)
    todoist.complete(only_task(todoist)["id"], SUN)
    sync(state, catalog, todoist, SUN)  # evening sync records the completion
    assert todoist.open_tasks() == []
    assert skip(state, catalog, "valid anagram", SUN) == "back on the list: Valid Anagram"
    sync(state, catalog, todoist, SUN)
    t = only_task(todoist)
    # already checked off tonight, so the leftover waits for tomorrow
    assert t["due"]["date"] == str(MON) and "Valid Anagram" in t["description"]
    assert [catalog[e["problem"]].name for e in attempts(state)] == ["Contains Duplicate"]
    _, created, _ = sync(state, catalog, todoist, MON)
    t2 = only_task(todoist)
    assert t2["id"] == t["id"] and t2["due"]["date"] == str(MON)
    assert "rolled over from Sep 27" in t2["description"]
    assert [c[0] for c in created] == ["new"]


def test_skip_with_nothing_to_undo(state, catalog):
    assert "nothing to undo" in skip(state, catalog, "lru", SUN)


def test_due_redos_come_first(state, catalog, todoist):
    seed(state, catalog, ["Two Sum", "Valid Anagram", "3Sum"], SUN - timedelta(days=30))
    targets, created, _ = sync(state, catalog, todoist, SUN)
    # three due is one more than the base, so a redo borrows a new slot
    assert (targets["review"], targets["new"]) == (3, 1)
    t = only_task(todoist)
    assert t["content"] == "LeetCode Sep 27: 3 redos, 1 new"
    desc = t["description"]
    assert desc.index("**Redos**") < desc.index("**New**")
    assert "Arrays & Hashing" not in desc.split("**New**")[0]


def test_more_adds_to_today(state, catalog, todoist):
    sync(state, catalog, todoist, SUN)
    todoist.complete(only_task(todoist)["id"], SUN)
    _, created, _ = sync(state, catalog, todoist, SUN, extra_new=1)
    assert [c[0] for c in created] == ["new"]
    assert only_task(todoist)["due"]["date"] == str(SUN)


def test_dry_run_touches_nothing(state, catalog, todoist):
    before = copy.deepcopy(state["events"])
    _, created, _ = sync(state, catalog, None, SUN, dry_run=True)
    assert len(created) == 2 and state["events"] == before and state["assignments"] == {}


def test_saturday_mock_in_task(state, catalog, todoist):
    arrays = [p.name for p in catalog.problems if p.topic == "Arrays & Hashing" and p.tier == 1]
    seed(state, catalog, arrays, SAT - timedelta(days=1), interval=40)
    sync(state, catalog, todoist, SAT)
    t = only_task(todoist)
    assert "mock" in t["content"] and "**Mock interview**" in t["description"]
    mock_part = t["description"].split("**Mock interview**")[1]
    assert "Arrays & Hashing" not in mock_part


def test_log_off_list_problem(state, catalog):
    msg = log_attempt(state, catalog, "LRU Cache", grade="hard", when=SUN)
    assert msg == "logged: LRU Cache = hard"
    assert st.cards(state)[catalog.find("lru").id].interval == 3


def test_render_redo_notes(state, catalog):
    p = catalog.find("Car Fleet")
    st.add_event(state, "seed", p.id, SUN, interval=7)
    _, desc = render_daily([("review", p.id, str(SUN))], catalog, st.cards(state), SUN)
    assert "before this list started" in desc and "Stack" not in desc
    st.add_event(state, "attempt", p.id, MON, grade="again", video=True)
    _, desc = render_daily([("review", p.id, str(SUN))], catalog, st.cards(state), TUE)
    assert "redo #2, last time (Sep 28) you needed the video (rolled over from Sep 27)" in desc
