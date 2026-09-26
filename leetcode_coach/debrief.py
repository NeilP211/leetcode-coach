"""Turning "here's how today went" into events."""

from datetime import date, timedelta

from . import state as st
from .srs import GRADES

RATE_WINDOW_DAYS = 4  # an unrated completion this recent gets the rating


def log_attempt(state, catalog, client, query, grade=None, when=None, video=False,
                minutes=None, notes=None, insight=None):
    """Record how an attempt went. Returns a one line summary.

    If Todoist already recorded the completion, that attempt gets the rating
    instead of a second attempt being added. If the problem still has an open
    task, the task is closed. Watching the video means `again` unless a
    grade says otherwise.
    """
    problem = catalog.find(query)
    pid = problem.id
    when = when or date.today()
    if grade is None:
        grade = "again" if video else "good"
    if grade not in GRADES:
        raise ValueError(f"grade must be one of {', '.join(GRADES)}")
    detail = dict(grade=grade, video=video or None, minutes=minutes, notes=notes)

    cutoff = str(when - timedelta(days=RATE_WINDOW_DAYS))
    unrated = [
        ev for ev in state["events"]
        if ev["problem"] == pid and ev["kind"] == "attempt" and "grade" not in ev
        and cutoff <= ev["date"] <= str(when)
    ]
    if unrated:
        ev = max(unrated, key=lambda e: (e["date"], e["seq"]))
        ev.update({k: v for k, v in detail.items() if v is not None})
        ev["rated_via"] = "log"
        action = "rated"
    else:
        task_id, mode = None, None
        for tid, info in st.open_tasks(state).items():
            if info["problem"] == pid:
                task_id, mode = tid, info["kind"]
                info["status"], info["done_on"] = "done", str(when)
                if client is not None:
                    client.close_task(tid)
                break
        if mode is None:
            seen = any(e["problem"] == pid and e["kind"] in ("attempt", "seed") for e in state["events"])
            mode = "review" if seen else "new"
        st.add_event(state, "attempt", pid, when, mode=mode, source="log", task=task_id, **detail)
        action = "logged" + (" and closed its task" if task_id else "")
    if insight:
        state["insights"][pid] = insight.strip()
    return f"{action}: {problem.name} = {grade}"


def unrated(state, catalog, since_days=7, today=None):
    today = today or date.today()
    cutoff = str(today - timedelta(days=since_days))
    out = []
    for ev in state["events"]:
        if ev["kind"] == "attempt" and "grade" not in ev and ev["date"] >= cutoff:
            out.append({"problem": catalog[ev["problem"]].name, "date": ev["date"],
                        "mode": ev.get("mode"), "seq": ev["seq"]})
    return out
