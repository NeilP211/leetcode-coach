"""Turning "here's how today went" into events."""

from datetime import date, timedelta

from . import state as st
from .srs import GRADES

RATE_WINDOW_DAYS = 4  # an unrated completion this recent gets the rating


def _recent_unrated(state, pid, when):
    cutoff = str(when - timedelta(days=RATE_WINDOW_DAYS))
    return [
        ev for ev in state["events"]
        if ev["problem"] == pid and ev["kind"] == "attempt" and "grade" not in ev
        and cutoff <= ev["date"] <= str(when)
    ]


def log_attempt(state, catalog, query, grade=None, when=None, video=False,
                minutes=None, notes=None, insight=None):
    """Record how an attempt went. Returns a one line summary.

    If checking off the daily task already recorded the attempt, that attempt
    gets the rating instead of a second one being added. If the problem is
    still open on the list, it is marked done (the next sync rewrites or
    closes the daily task). Watching the video means `again` unless a grade
    says otherwise.
    """
    problem = catalog.find(query)
    pid = problem.id
    when = when or date.today()
    if grade is None:
        grade = "again" if video else "good"
    if grade not in GRADES:
        raise ValueError(f"grade must be one of {', '.join(GRADES)}")
    detail = dict(grade=grade, video=video or None, minutes=minutes, notes=notes)

    unrated = _recent_unrated(state, pid, when)
    if unrated:
        ev = max(unrated, key=lambda e: (e["date"], e["seq"]))
        ev.update({k: v for k, v in detail.items() if v is not None})
        ev["rated_via"] = "log"
        action = "rated"
    else:
        aid, mode = None, None
        for key, a in st.open_assignments(state).items():
            if a["problem"] == pid:
                aid, mode = key, a["kind"]
                a["status"], a["done_on"] = "done", str(when)
                break
        if mode is None:
            seen = any(e["problem"] == pid and e["kind"] in ("attempt", "seed") for e in state["events"])
            mode = "review" if seen else "new"
        st.add_event(state, "attempt", pid, when, mode=mode, source="log", assignment=aid, **detail)
        action = "logged" + (", checked off the list" if aid else "")
    if insight:
        state["insights"][pid] = insight.strip()
    return f"{action}: {problem.name} = {grade}"


def skip(state, catalog, query, when=None):
    """Undo a completion for a problem that was not actually done.

    Used when the whole daily task got checked off but one problem on it was
    skipped. The recorded attempt is removed and the problem goes back on the
    list, keeping its original assigned date.
    """
    problem = catalog.find(query)
    when = when or date.today()
    unrated = [ev for ev in _recent_unrated(state, problem.id, when) if ev.get("assignment")]
    if not unrated:
        return f"nothing to undo for {problem.name}; if it is still on the list it rolls over anyway"
    ev = max(unrated, key=lambda e: (e["date"], e["seq"]))
    state["events"].remove(ev)
    a = state["assignments"][ev["assignment"]]
    a["status"] = "open"
    a.pop("done_on", None)
    return f"back on the list: {problem.name}"


def snooze(state, catalog, query, until=None):
    """Hold a problem back from the daily lists until a date (None clears the hold).

    An open copy comes off the list now; it returns as a normal redo on or
    after that date because its card is still due.
    """
    problem = catalog.find(query)
    held = state.setdefault("snooze", {})
    if until is None:
        held.pop(problem.id, None)
        return f"released: {problem.name}"
    held[problem.id] = str(until)
    for a in st.open_assignments(state).values():
        if a["problem"] == problem.id:
            a["status"] = "snoozed"
    return f"holding back {problem.name} until {until}"


def unrated(state, catalog, since_days=7, today=None):
    today = today or date.today()
    cutoff = str(today - timedelta(days=since_days))
    out = []
    for ev in state["events"]:
        if ev["kind"] == "attempt" and "grade" not in ev and ev["date"] >= cutoff:
            out.append({"problem": catalog[ev["problem"]].name, "date": ev["date"],
                        "mode": ev.get("mode"), "seq": ev["seq"]})
    return out
