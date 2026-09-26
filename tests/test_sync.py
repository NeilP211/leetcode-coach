import copy
from datetime import timedelta

from conftest import MON, SUN
from leetcode_coach import state as st
from leetcode_coach.debrief import log_attempt, unrated
from leetcode_coach.sync import sync, task_text


def seed(state, catalog, names, when, interval=7):
    for n in names:
        st.add_event(state, "seed", catalog.find(n).id, when, interval=interval)


def kinds(state, day):
    return sorted(state["tasks"][t]["kind"] for t in state["days"][str(day)]["tasks"])


def test_first_sync_creates_new_problems(state, catalog, todoist):
    targets, created, _ = sync(state, catalog, todoist, SUN)
    assert targets["new"] == 2 and targets["review"] == 0
    assert [c[0] for c in created] == ["new", "new"]
    assert len(todoist.tasks) == 2
    t = next(iter(todoist.tasks.values()))
    assert t["content"].startswith("New: [Contains Duplicate](https://neetcode.io/")
    assert t["labels"] == ["leetcode"] and t["priority"] == 3


def test_second_sync_same_day_adds_nothing(state, catalog, todoist):
    sync(state, catalog, todoist, SUN)
    for tid in list(todoist.tasks):
        todoist.complete(tid, SUN)
    _, created, _ = sync(state, catalog, todoist, SUN)
    assert created == []
    assert len(todoist.tasks) == 2


def test_completion_becomes_unrated_attempt(state, catalog, todoist):
    sync(state, catalog, todoist, SUN)
    tid = next(iter(todoist.tasks))
    todoist.complete(tid, SUN)
    _, _, log = sync(state, catalog, todoist, MON)
    attempts = [e for e in state["events"] if e["kind"] == "attempt"]
    assert len(attempts) == 1 and attempts[0]["date"] == str(SUN)
    assert "grade" not in attempts[0]
    assert state["tasks"][tid]["status"] == "done"
    assert any(line.startswith("done:") for line in log)
    assert len(unrated(state, catalog, today=MON)) == 1


def test_unfinished_tasks_carry_over_and_count(state, catalog, todoist):
    sync(state, catalog, todoist, SUN)
    first, second = list(todoist.tasks)
    todoist.complete(first, SUN)
    _, created, log = sync(state, catalog, todoist, MON)
    assert todoist.tasks[second]["due"]["date"] == str(MON)
    assert second in state["days"][str(MON)]["tasks"]
    # one new slot is taken by the carried task, so only one new problem is added
    assert [c[0] for c in created].count("new") == 1
    assert any("carried over" in line for line in log)


def test_deleted_task_frees_the_problem(state, catalog, todoist):
    sync(state, catalog, todoist, SUN)
    first = next(iter(todoist.tasks))
    pid = state["tasks"][first]["problem"]
    todoist.delete(first)
    _, created, _ = sync(state, catalog, todoist, MON)
    assert state["tasks"][first]["status"] == "gone"
    assert pid in [c[1] for c in created]


def test_due_redos_get_scheduled(state, catalog, todoist):
    seed(state, catalog, ["Two Sum", "Valid Anagram", "3Sum"], SUN - timedelta(days=30))
    targets, created, _ = sync(state, catalog, todoist, SUN)
    # three due is one more than the base, so a redo borrows a new slot
    assert (targets["review"], targets["new"]) == (3, 1)
    reviews = [c for c in created if c[0] == "review"]
    assert len(reviews) == 3
    task = todoist.tasks[reviews[0][2]]
    assert task["content"].startswith("Redo: ") and task["priority"] == 4


def test_more_adds_extra_new(state, catalog, todoist):
    sync(state, catalog, todoist, SUN)
    _, created, _ = sync(state, catalog, todoist, SUN, extra_new=1)
    assert [c[0] for c in created] == ["new"]


def test_dry_run_touches_nothing_remote(state, catalog, todoist):
    before = copy.deepcopy(state["events"])
    _, created, _ = sync(state, catalog, None, SUN, dry_run=True)
    assert len(created) == 2 and state["events"] == before


def test_log_rates_the_todoist_completion(state, catalog, todoist):
    sync(state, catalog, todoist, SUN)
    tid = next(iter(todoist.tasks))
    name = catalog[state["tasks"][tid]["problem"]].name
    todoist.complete(tid, SUN)
    sync(state, catalog, todoist, MON)
    msg = log_attempt(state, catalog, todoist, name, video=True, minutes=50,
                      insight="set of seen values", when=MON)
    assert msg.startswith("rated")
    attempts = [e for e in state["events"] if e["kind"] == "attempt"]
    assert len(attempts) == 1 and attempts[0]["grade"] == "again" and attempts[0]["video"]
    card = st.cards(state)[attempts[0]["problem"]]
    assert card.due == SUN + timedelta(days=2)
    assert state["insights"][attempts[0]["problem"]] == "set of seen values"


def test_log_closes_open_task(state, catalog, todoist):
    sync(state, catalog, todoist, SUN)
    tid = next(iter(todoist.tasks))
    name = catalog[state["tasks"][tid]["problem"]].name
    msg = log_attempt(state, catalog, todoist, name, grade="good", when=SUN)
    assert "closed its task" in msg
    assert todoist.tasks[tid]["checked"]
    assert state["tasks"][tid]["status"] == "done"
    # the next sync must not double count it
    sync(state, catalog, todoist, MON)
    assert sum(1 for e in state["events"] if e["kind"] == "attempt") == 1


def test_log_off_list_problem(state, catalog):
    msg = log_attempt(state, catalog, None, "LRU Cache", grade="hard", when=SUN)
    assert msg == "logged: LRU Cache = hard"
    assert st.cards(state)[catalog.find("lru").id].interval == 3


def test_task_text_hides_topic_on_redos(catalog):
    p = catalog.find("Car Fleet")
    content, desc = task_text(p, "review")
    assert "Stack" not in content + desc
    _, desc = task_text(p, "new")
    assert desc.startswith("Stack.")
    content, desc = task_text(p, "mock")
    assert "Stack" not in content + desc and "25 minute" in desc


def test_redo_text_for_old_solves_and_logged_ones(state, catalog):
    p = catalog.find("Car Fleet")
    st.add_event(state, "seed", p.id, SUN, interval=7)
    _, desc = task_text(p, "review", st.cards(state)[p.id])
    assert "before this list started" in desc
    st.add_event(state, "attempt", p.id, MON, grade="again", video=True)
    _, desc = task_text(p, "review", st.cards(state)[p.id])
    assert "Redo #2. Last time (Sep 28): needed the video." in desc
