"""Human readable views of the state: status, progress table, cheat sheet."""

from datetime import date, timedelta

from . import planner
from . import state as st
from .catalog import CORE, LIGHT_TRACK, MAIN_TRACK

def bar(done, total, width=12):
    if not total:
        return ""
    full = round(width * done / total)
    return "█" * full + "░" * (width - full)


def topic_rows(catalog, cards):
    scores = planner.topic_scores(catalog, cards)
    rows = []
    for topic in MAIN_TRACK + LIGHT_TRACK:
        ps = catalog.in_topic(topic)
        solved = [p for p in ps if p.id in cards and cards[p.id].seen]
        core = [p for p in ps if p.tier == CORE]
        core_done = [p for p in core if p in solved]
        mastered = [p for p in solved if cards[p.id].mastered]
        score = scores.get(topic)
        rows.append({
            "topic": topic, "solved": len(solved), "total": len(ps),
            "core_done": len(core_done), "core": len(core), "mastered": len(mastered),
            "score": round(score[0], 2) if score else None,
        })
    return rows


def streak(state, today):
    days = {ev["date"] for ev in state["events"] if ev["kind"] == "attempt"}
    n, d = 0, today
    if str(d) not in days:
        d -= timedelta(days=1)
    while str(d) in days:
        n += 1
        d -= timedelta(days=1)
    return n


def summary(state, catalog, today):
    cards = st.cards(state)
    seen = [c for c in cards.values() if c.seen]
    return {
        "solved": len(seen),
        "total": len(catalog.problems),
        "core_done": sum(1 for c in seen if c.problem in catalog.by_id and catalog[c.problem].tier == CORE),
        "core": sum(1 for p in catalog.problems if p.tier == CORE),
        "mastered": sum(1 for c in seen if c.mastered),
        "attempts": sum(1 for ev in state["events"] if ev["kind"] == "attempt"),
        "streak": streak(state, today),
        "due_today": len(planner.due_cards(cards, today)),
        "weak": planner.weak_topics(catalog, cards),
    }


def status_data(state, catalog, today):
    cards = st.cards(state)
    today_ids = state["days"].get(str(today), {}).get("assignments", [])
    todays = []
    for aid in today_ids:
        a = state["assignments"].get(aid)
        if a:
            todays.append({"assignment": aid, "kind": a["kind"], "status": a["status"],
                           "problem": catalog[a["problem"]].name, "since": a["assigned"]})
    ahead = {}
    for c in cards.values():
        if c.due and not c.retired and today < c.due <= today + timedelta(days=7):
            ahead[str(c.due)] = ahead.get(str(c.due), 0) + 1
    from .debrief import unrated
    return {
        "date": str(today),
        "summary": summary(state, catalog, today),
        "targets": state["days"].get(str(today), {}).get("targets"),
        "today": todays,
        "unrated": unrated(state, catalog, today=today),
        "due_next_7_days": dict(sorted(ahead.items())),
        "next_new": [p.name for p in planner.new_queue(
            catalog, cards, {a["problem"] for a in st.open_assignments(state).values()},
            sum(1 for c in cards.values() if c.seen),
            bool(state["config"].get("only_150")))[:5]],
        "interview": st.next_interview(state, today),
        "topics": topic_rows(catalog, cards),
        "config": state["config"],
    }


def status_text(data):
    s = data["summary"]
    out = [
        f"{data['date']}  solved {s['solved']}/{s['total']}  core {s['core_done']}/{s['core']}  "
        f"mastered {s['mastered']}  streak {s['streak']}d  redos due {s['due_today']}",
    ]
    if data["interview"]:
        i = data["interview"]
        out.append(f"next interview: {i['company']} on {i['date']}")
    if data["targets"]:
        t = data["targets"]
        line = f"today's plan: {t['review']} redo, {t['new']} new, {t['mock']} mock"
        out.append(line + (f" ({t['reason']})" if t.get("reason") else ""))
    for item in data["today"]:
        mark = {"open": "[ ]", "done": "[x]", "gone": "[-]"}[item["status"]]
        since = f" (since {item['since']})" if item["since"] != data["date"] else ""
        out.append(f"  {mark} {item['kind']:6} {item['problem']}{since}")
    if data["unrated"]:
        out.append("waiting for a rating: " + ", ".join(u["problem"] for u in data["unrated"]))
    if data["due_next_7_days"]:
        out.append("redos coming up: " + ", ".join(
            f"{k[5:]}: {v}" for k, v in data["due_next_7_days"].items()))
    if data["next_new"]:
        out.append("next new: " + ", ".join(data["next_new"]))
    if s["weak"]:
        out.append("weak topics: " + ", ".join(s["weak"]))
    out.append("")
    out.append(f"{'topic':26} {'solved':>9} {'core':>7} {'mastered':>8}  score")
    for r in data["topics"]:
        score = "" if r["score"] is None else f"{r['score']:.2f}"
        out.append(f"{r['topic']:26} {r['solved']:>4}/{r['total']:<4} {r['core_done']:>3}/{r['core']:<3} "
                   f"{r['mastered']:>8}  {score}")
    return "\n".join(out)


def progress_markdown(state, catalog, today):
    cards = st.cards(state)
    s = summary(state, catalog, today)
    lines = [
        f"**{s['solved']} / {s['total']}** NeetCode 250 problems solved, "
        f"**{s['core_done']} / {s['core']}** of the core set, "
        f"**{s['mastered']}** mastered (survived a 3 week gap). "
        f"{s['attempts']} logged attempts. Updated {today.strftime('%b %-d, %Y')}.",
        "",
        "| Topic | Solved | Progress | Mastered |",
        "|---|---:|---|---:|",
    ]
    for r in topic_rows(catalog, cards):
        lines.append(f"| {r['topic']} | {r['solved']}/{r['total']} | "
                     f"`{bar(r['solved'], r['total'])}` | {r['mastered']} |")
    return "\n".join(lines)


def cheat_sheet(state, catalog):
    out = ["# Key insights", ""]
    for topic in MAIN_TRACK + LIGHT_TRACK:
        items = [(p, state["insights"][p.id]) for p in catalog.in_topic(topic) if p.id in state["insights"]]
        if items:
            out.append(f"## {topic}")
            out += [f"- **{p.name}**: {text}" for p, text in items]
            out.append("")
    return "\n".join(out)


def show_problem(state, catalog, query, today=None):
    today = today or date.today()
    p = catalog.find(query)
    card = st.cards(state).get(p.id)
    out = [f"{p.name} ({p.difficulty}, {p.topic}, {p.number})", p.neetcode, p.leetcode]
    if card and card.seen:
        out.append(f"attempts {card.attempts}, lapses {card.lapses}, ease {card.ease:.2f}, "
                   f"gap {card.interval}d, due {card.due}, last {card.last} ({card.last_grade})"
                   + (", mastered" if card.mastered else "") + (", retired" if card.retired else ""))
        for ev in card.history:
            bits = [ev["date"], ev["kind"], ev.get("grade", "unrated" if ev["kind"] == "attempt" else "")]
            if ev.get("video"):
                bits.append("video")
            if ev.get("minutes"):
                bits.append(f"{ev['minutes']}m")
            if ev.get("notes"):
                bits.append(ev["notes"])
            out.append("  " + "  ".join(b for b in bits if b))
    else:
        out.append("not solved yet")
    if p.id in state["insights"]:
        out.append(f"insight: {state['insights'][p.id]}")
    return "\n".join(out)
