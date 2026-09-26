"""Keeps Todoist in step with the plan.

One sync does four things, in order:

1. Checks every task it created that is still open in its books. Completed
   ones become attempts in the event log (unrated until a debrief says how
   it went). Deleted ones are dropped and the problem goes back in the pool.
2. Moves anything still open from an earlier day onto today, so a problem
   keeps showing up until it is done.
3. Works out today's targets once and freezes them, so running sync again
   later in the day never piles on more work.
4. Tops up whatever slots today still has open with new tasks.
"""

from datetime import date, datetime

from . import planner
from . import state as st
from .todoist import task_status

PRIORITY = {"review": 4, "mock": 4, "new": 3}  # 4 shows as p1 in the app


def local_date(ts):
    """Todoist timestamps are UTC ISO strings. Returns the local calendar date."""
    if not ts:
        return None
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    return dt.astimezone().date()


def _fmt(d):
    return d.strftime("%b %-d")


GRADE_WORDS = {
    "again": "needed the video",
    "hard": "got it, but it was a fight",
    "good": "solved it clean",
    "easy": "solved it fast",
}


def task_text(problem, kind, card=None):
    """(content, description) for a Todoist task."""
    links = f"LeetCode: {problem.leetcode}"
    if kind == "review":
        content = f"Redo: [{problem.name}]({problem.neetcode})"
        lines = [
            "Blank editor, no notes. Say the pattern and the key idea out loud before you code. "
            "Aim for 20 minutes.",
        ]
        if card and card.last:
            how = GRADE_WORDS.get(card.last_grade, "solved it")
            lines.append(f"Redo #{card.attempts + 1}. Last time ({_fmt(card.last)}): {how}.")
        lines.append(links)
    elif kind == "mock":
        content = f"Mock interview: [{problem.name}]({problem.neetcode}) ({problem.difficulty})"
        lines = [
            "25 minute timer, talk out loud the whole time. The topic is hidden on purpose: "
            "figuring out the pattern is part of the test.",
            "Clarify the problem, give a brute force, improve it, code it, then walk a test case.",
            links,
        ]
    else:
        content = f"New: [{problem.name}]({problem.neetcode}) ({problem.difficulty})"
        lines = [
            f"{problem.topic}. Give it a real 30 to 40 minutes on your own first. If you need "
            "the video, watch it, close it, then write the solution from scratch. Finish with a "
            "one line key insight.",
            links,
        ]
        if problem.video:
            lines.append(f"Video (only after a real attempt): {problem.video}")
    return content, "\n\n".join(lines)


def reconcile(state, client, today):
    """Record completions and deletions, carry leftovers to today. Returns a log list."""
    log = []
    tracked = st.open_tasks(state)
    if not tracked:
        return log
    active = {t["id"]: t for t in client.active_tasks(state["config"]["label"])}
    for tid, info in tracked.items():
        if tid in active:
            continue
        task = client.get_task(tid)
        status = task_status(task)
        if status == "open":
            active[tid] = task  # open but lost its label, keep tracking
            continue
        info["status"] = status
        if status == "done":
            when = local_date(task.get("completed_at")) or today
            info["done_on"] = str(when)
            st.add_event(state, "attempt", info["problem"], when,
                         mode=info["kind"], source="todoist", task=tid)
            log.append(f"done: {info['problem']} ({info['kind']}) on {when}")
        else:
            log.append(f"deleted in Todoist: {info['problem']} ({info['kind']})")

    day = state["days"].setdefault(str(today), {"tasks": []})
    for tid, info in st.open_tasks(state).items():
        task = active.get(tid, {})
        due = (task.get("due") or {}).get("date", info.get("due"))
        if due and due[:10] < str(today):
            client.set_due(tid, str(today))
            info["due"] = str(today)
            log.append(f"carried over: {info['problem']}")
        if tid not in day["tasks"]:
            day["tasks"].append(tid)
    return log


def plan_today(state, catalog, today, extra_new=0):
    """What to add today, given what is already on today's list.

    Returns (targets, [(kind, problem_id)]) without touching Todoist.
    """
    cards = st.cards(state)
    interview = st.next_interview(state, today)
    day = state["days"].setdefault(str(today), {"tasks": []})
    if "targets" not in day:
        due = len(planner.due_cards(cards, today))
        soon = len(planner.due_cards(cards, today, planner.LOOKAHEAD_DAYS))
        day["targets"] = planner.targets(state["config"], due, today, interview, soon).as_dict()
    day["targets"]["new"] += extra_new
    t = day["targets"]

    have = {"review": 0, "new": 0, "mock": 0}
    for tid in day["tasks"]:
        info = state["tasks"].get(tid)
        if info:
            have[info["kind"]] += 1

    busy = {info["problem"] for info in st.open_tasks(state).values()}
    cram = "cram" in t.get("reason", "")
    intro = sum(1 for c in cards.values() if c.seen)
    adds = []
    for pid in planner.pick_reviews(cards, today, t["review"] - have["review"], busy, cram):
        adds.append(("review", pid))
        busy.add(pid)
    new_slots = t["new"] - have["new"]
    if t["mock"] > have["mock"]:
        pid = planner.pick_mock(catalog, cards, today, busy)
        if pid:
            adds.append(("mock", pid))
            busy.add(pid)
        else:
            new_slots += 1  # nothing mock-worthy yet, so it stays a new problem
    for pid in planner.pick_new(catalog, cards, new_slots, busy, intro):
        adds.append(("new", pid))
    return t, adds


def sync(state, catalog, client, today=None, extra_new=0, dry_run=False):
    today = today or date.today()
    log = [] if dry_run else reconcile(state, client, today)
    targets, adds = plan_today(state, catalog, today, extra_new)
    cards = st.cards(state)
    created = []
    for kind, pid in adds:
        problem = catalog[pid]
        content, desc = task_text(problem, kind, cards.get(pid))
        if dry_run:
            created.append((kind, pid, None))
            continue
        task = client.create_task(
            content, desc, str(today), PRIORITY[kind],
            [state["config"]["label"]], state["config"]["project_id"],
        )
        tid = task["id"]
        state["tasks"][tid] = {
            "problem": pid, "kind": kind, "assigned": str(today),
            "due": str(today), "status": "open",
        }
        state["days"][str(today)]["tasks"].append(tid)
        created.append((kind, pid, tid))
        log.append(f"added {kind}: {problem.name}")
    if not dry_run:
        st.prune_days(state, today)
    return targets, created, log
