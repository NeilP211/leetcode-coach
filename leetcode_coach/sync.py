"""Keeps Todoist in step with the plan.

Each day's problems are "assignments" tracked here, and Todoist gets exactly
one task per day that lists all of them. One sync does five things:

1. Looks at the daily task. If it was checked off, every open assignment on
   it becomes an attempt in the event log (unrated until a debrief says how
   it went). If it was deleted without being checked, nothing is lost: its
   problems stay open and roll into the next list.
2. Rolls every open assignment from earlier days into today, so a problem
   keeps showing up until it is done.
3. Works out today's targets once and freezes them, so running sync again
   later in the day never piles on more work.
4. Tops up whatever slots today still has open.
5. Writes the one daily task: creates it, rewrites it in place, or closes it
   once a debrief has logged everything on it.
"""

import hashlib
from datetime import date, datetime, timedelta

from . import planner
from . import state as st
from .todoist import task_status

PRIORITY = 4  # shows as p1 in the app
KIND_ORDER = {"review": 0, "new": 1, "mock": 2}


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


def _plural(n, word):
    return f"{n} {word}" + ("" if n == 1 else "s")


def redo_note(card):
    if card is None or card.attempts == 0:
        return "first redo since you solved it before this list started"
    how = GRADE_WORDS.get(card.last_grade, "solved it")
    return f"redo #{card.attempts + 1}, last time ({_fmt(card.last)}) you {how}"


def render_daily(items, catalog, cards, day, done_names=()):
    """(content, description) for the day's single task.

    items: [(kind, problem_id, since_date)] still to do, in display order.
    """
    counts = {k: sum(1 for i in items if i[0] == k) for k in KIND_ORDER}
    parts = []
    if counts["review"]:
        parts.append(_plural(counts["review"], "redo"))
    if counts["new"]:
        parts.append(f"{counts['new']} new")
    if counts["mock"]:
        parts.append("mock")
    content = f"LeetCode {_fmt(day)}: " + ", ".join(parts)

    minutes = 20 * counts["review"] + 40 * counts["new"] + 30 * counts["mock"]
    lines = [f"About {minutes} minutes. Redos first while you are fresh, then new problems."]
    n = 0

    def rolled(since):
        return f" (rolled over from {_fmt(date.fromisoformat(since))})" if since != str(day) else ""

    reviews = [i for i in items if i[0] == "review"]
    if reviews:
        lines += ["", "**Redos** (topic hidden on purpose: spotting the pattern cold is the point)",
                  "Blank editor, no notes. Say the pattern and key idea out loud before coding. "
                  "Aim for 20 minutes each."]
        for _, pid, since in reviews:
            n += 1
            p = catalog[pid]
            lines.append(f"{n}. [{p.name}]({p.neetcode}), {p.difficulty}: "
                         f"{redo_note(cards.get(pid))}{rolled(since)}")

    news = [i for i in items if i[0] == "new"]
    if news:
        lines += ["", "**New**",
                  "Give each a real 30 to 40 minutes on your own. If you need the video, watch it, "
                  "close it, then write it from scratch. End with a one line key insight."]
        for _, pid, since in news:
            n += 1
            p = catalog[pid]
            video = f", [video]({p.video}) after a real attempt" if p.video else ""
            lines.append(f"{n}. [{p.name}]({p.neetcode}), {p.difficulty}, {p.topic}"
                         f"{rolled(since)} ([LeetCode]({p.leetcode}){video})")

    mocks = [i for i in items if i[0] == "mock"]
    for _, pid, since in mocks:
        n += 1
        p = catalog[pid]
        lines += ["", "**Mock interview**",
                  f"{n}. [{p.name}]({p.neetcode}), {p.difficulty}{rolled(since)}. 25 minute timer, "
                  "talk out loud the whole time. Unseen problem, topic hidden. Clarify, brute "
                  "force, improve, code, walk a test case."]

    if done_names:
        lines += ["", "Already done today: " + ", ".join(done_names) + "."]
    lines += ["", "Check this off when you finish, then debrief how each one went. "
                  "Anything you skip rolls over to tomorrow."]
    return content, "\n".join(lines)


def _new_assignment(state, pid, kind, today):
    aid = f"a{state['next_aid']}"
    state["next_aid"] += 1
    state["assignments"][aid] = {"problem": pid, "kind": kind, "assigned": str(today),
                                 "status": "open"}
    return aid


def reconcile(state, client, today):
    """Read the daily task's fate and roll open work into today. Returns a log list."""
    log = []
    daily = state["daily"]
    if daily.get("task"):
        task = client.get_task(daily["task"])
        status = task_status(task)
        if status == "done":
            when = local_date(task.get("completed_at")) or today
            for aid in daily.get("assignments", []):
                a = state["assignments"].get(aid)
                if a and a["status"] == "open":
                    a["status"], a["done_on"] = "done", str(when)
                    st.add_event(state, "attempt", a["problem"], when, mode=a["kind"],
                                 source="todoist", assignment=aid)
                    log.append(f"done: {a['problem']} ({a['kind']}) on {when}")
            state["daily"] = {"completed_on": str(when)}
        elif status == "gone":
            log.append("daily task was deleted; its problems roll over")
            state["daily"] = {}

    day = state["days"].setdefault(str(today), {"assignments": []})
    for aid, a in st.open_assignments(state).items():
        if aid not in day["assignments"]:
            day["assignments"].append(aid)
            if a["assigned"] < str(today):
                log.append(f"rolled over: {a['problem']}")
    return log


def plan_today(state, catalog, today, extra_new=0, extra_review=0):
    """What to add today, given what is already on today's list.

    Returns (targets, [(kind, problem_id)]) without touching Todoist.
    """
    cards = st.cards(state)
    interview = st.next_interview(state, today)
    day = state["days"].setdefault(str(today), {"assignments": []})
    if "targets" not in day:
        due = len(planner.due_cards(cards, today))
        soon = len(planner.pullable(cards, today))
        day["targets"] = planner.targets(state["config"], due, today, interview, soon).as_dict()
    day["targets"]["new"] += extra_new
    day["targets"]["review"] += extra_review
    t = day["targets"]

    have = {"review": 0, "new": 0, "mock": 0}
    for aid in day["assignments"]:
        a = state["assignments"].get(aid)
        # work finished on an earlier day (logged late) does not use up today's slots
        if a and (a["status"] == "open" or a.get("done_on") == str(today)):
            have[a["kind"]] += 1

    busy = {a["problem"] for a in st.open_assignments(state).values()}
    busy |= {pid for pid, until in state.get("snooze", {}).items() if until > str(today)}
    cram = "cram" in t.get("reason", "")
    intro = sum(1 for c in cards.values() if c.seen)
    only_150 = bool(state["config"].get("only_150"))
    adds = []
    for pid in planner.pick_reviews(cards, today, t["review"] - have["review"], busy, cram,
                                    early=extra_review > 0):
        adds.append(("review", pid))
        busy.add(pid)
    new_slots = t["new"] - have["new"]
    if t["mock"] > have["mock"]:
        pid = planner.pick_mock(catalog, cards, today, busy, only_150)
        if pid:
            adds.append(("mock", pid))
            busy.add(pid)
        else:
            new_slots += 1  # nothing mock-worthy yet, so it stays a new problem
    for pid in planner.pick_new(catalog, cards, new_slots, busy, intro, only_150,
                                state.get("focus", ())):
        adds.append(("new", pid))
    return t, adds


def todays_items(state, today):
    """Open assignments on today's list, redos first."""
    day = state["days"].get(str(today), {"assignments": []})
    items = []
    for aid in day["assignments"]:
        a = state["assignments"].get(aid)
        if a and a["status"] == "open":
            items.append((a["kind"], a["problem"], a["assigned"]))
    return sorted(items, key=lambda i: (KIND_ORDER[i[0]], i[2]))


def publish(state, catalog, client, today, force_today=False):
    """Create, rewrite or close the single daily task to match today's open work."""
    items = todays_items(state, today)
    daily = state["daily"]
    log = []
    if not items:
        if daily.get("task"):
            client.close_task(daily["task"])
            state["daily"] = {"completed_on": str(today)}
            log.append("everything logged, closed the daily task")
        return log

    # Work reopened after today's task was already checked off waits for tomorrow,
    # unless it was explicitly asked for today.
    due = today
    if daily.get("completed_on") == str(today) and not daily.get("task") and not force_today:
        due = today + timedelta(days=1)
    day = state["days"][str(today)]
    done = [catalog[state["assignments"][aid]["problem"]].name for aid in day["assignments"]
            if state["assignments"].get(aid, {}).get("status") == "done"]
    content, desc = render_daily(items, catalog, st.cards(state), due, done)
    digest = hashlib.sha256(f"{content}\n{desc}\n{due}".encode()).hexdigest()[:16]
    aids = [aid for aid in day["assignments"] if state["assignments"][aid]["status"] == "open"]

    if daily.get("task"):
        if daily.get("digest") != digest:
            client.update_task(daily["task"], content=content, description=desc, due_date=str(due))
            log.append(f"updated daily task: {content}")
    else:
        task = client.create_task(content, desc, str(due), PRIORITY,
                                  [state["config"]["label"]], state["config"]["project_id"])
        daily = state["daily"] = {"task": task["id"]}
        log.append(f"created daily task: {content}")
    daily.update({"date": str(due), "digest": digest, "assignments": aids})
    return log


def sync(state, catalog, client, today=None, extra_new=0, dry_run=False, extra_review=0):
    today = today or date.today()
    until = state["config"].get("pause_until")
    if until and today < date.fromisoformat(until):
        log = [f"paused until {until}"]
        daily = state["daily"]
        if client and not dry_run and daily.get("task") and daily.get("date") != until:
            client.update_task(daily["task"], due_date=until)
            daily["date"] = until
            log.append(f"moved the open daily task to {until}")
        return {"review": 0, "new": 0, "mock": 0, "reason": f"paused until {until}"}, [], log
    log = [] if dry_run else reconcile(state, client, today)
    if dry_run:
        state["days"].setdefault(str(today), {"assignments": []})
    targets, adds = plan_today(state, catalog, today, extra_new, extra_review)
    created = []
    for kind, pid in adds:
        created.append((kind, pid))
        if not dry_run:
            aid = _new_assignment(state, pid, kind, today)
            state["days"][str(today)]["assignments"].append(aid)
            log.append(f"added {kind}: {catalog[pid].name}")
    if not dry_run:
        log += publish(state, catalog, client, today, force_today=extra_new + extra_review > 0)
        st.prune_days(state, today)
    return targets, created, log
