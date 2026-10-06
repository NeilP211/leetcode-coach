"""lc: the command line for leetcode-coach."""

import argparse
import json
import sys
from datetime import date

from . import report
from . import state as st
from .catalog import Catalog
from .debrief import log_attempt, skip, snooze
from .srs import GRADES
from .sync import sync
from .todoist import Todoist, load_token

SEED_DAYS = {  # guessed gaps for problems solved before this tool existed
    "well": {"Easy": 45, "Medium": 21, "Hard": 14},
    "recent": {"Easy": 30, "Medium": 10, "Hard": 7},
    "other": {"Easy": 21, "Medium": 7, "Hard": 5},
}


def _date(s):
    return date.fromisoformat(s) if s else date.today()


def client():
    return Todoist(load_token())


def cmd_sync(args, catalog):
    today = _date(args.date)
    if args.dry_run:
        targets, created, log = sync(st.load(), catalog, None, today, dry_run=True)
    else:
        todoist = client()
        with st.locked() as state:
            targets, created, log = sync(state, catalog, todoist, today,
                                         extra_new=getattr(args, "extra", 0),
                                         extra_review=getattr(args, "extra_review", 0))
    for line in log:
        print(line)
    if args.dry_run:
        for kind, pid in created:
            print(f"would add {kind}: {catalog[pid].name}")
    print(f"targets: {targets['review']} redo, {targets['new']} new, {targets['mock']} mock"
          + (f" ({targets['reason']})" if targets.get("reason") else ""))


def cmd_more(args, catalog):
    args.dry_run = False
    if args.redo:
        args.extra, args.extra_review = 0, args.n
    else:
        args.extra, args.extra_review = args.n, 0
    cmd_sync(args, catalog)


def cmd_log(args, catalog):
    with st.locked() as state:
        msg = log_attempt(state, catalog, args.problem, grade=args.grade, when=_date(args.date),
                          video=args.video, minutes=args.minutes, notes=args.notes,
                          insight=args.insight)
    print(msg)
    _resync(args)


def cmd_skip(args, catalog):
    with st.locked() as state:
        print(skip(state, catalog, args.problem, _date(args.date)))
    _resync(args)


def cmd_snooze(args, catalog):
    until = None if args.clear else _date(args.until)
    if until is None and not args.clear:
        raise SystemExit("give --until DATE, or --clear to release it")
    with st.locked() as state:
        print(snooze(state, catalog, args.problem, until))
    _resync(args)


def _resync(args):
    """Refresh the daily task after a change, unless told to stay offline."""
    if not args.offline:
        cmd_sync(argparse.Namespace(dry_run=False, date=None), Catalog.load())


def cmd_status(args, catalog):
    state = st.load()
    data = report.status_data(state, catalog, _date(args.date))
    print(json.dumps(data, indent=1, default=str) if args.json else report.status_text(data))


def cmd_show(args, catalog):
    print(report.show_problem(st.load(), catalog, args.problem))


def cmd_next(args, catalog):
    from . import planner
    state = st.load()
    cards = st.cards(state)
    busy = {a["problem"] for a in st.open_assignments(state).values()}
    queue = planner.new_queue(catalog, cards, busy, sum(1 for c in cards.values() if c.seen),
                              bool(state["config"].get("only_150")), state.get("focus", ()))
    for p in queue[: args.n]:
        print(f"{p.name:50} {p.difficulty:7} {p.topic}")


def cmd_retire(args, catalog, flag=True):
    p = catalog.find(args.problem)
    with st.locked() as state:
        st.add_event(state, "retire" if flag else "unretire", p.id, _date(None))
    print(("retired" if flag else "back in rotation") + f": {p.name}")


def cmd_interview(args, catalog):
    with st.locked() as state:
        if args.action == "add":
            date.fromisoformat(args.date)
            state["interviews"] = [i for i in state["interviews"] if i["company"].lower() != args.company.lower()]
            state["interviews"].append({"company": args.company, "date": args.date, "notes": args.notes or ""})
            print(f"interview: {args.company} on {args.date}")
        elif args.action == "rm":
            state["interviews"] = [i for i in state["interviews"] if i["company"].lower() != args.company.lower()]
            print(f"removed {args.company}")
        for i in sorted(state["interviews"], key=lambda i: i["date"]):
            print(f"  {i['date']}  {i['company']}  {i['notes']}")


def cmd_focus(args, catalog):
    with st.locked() as state:
        if args.action == "set":
            state["focus"] = list(dict.fromkeys(catalog.find(q).id for q in args.problems))
        elif args.action == "add":
            ids = [catalog.find(q).id for q in args.problems]
            state["focus"] = list(dict.fromkeys(state["focus"] + ids))
        elif args.action == "clear":
            state["focus"] = []
        cards = st.cards(state)
        for pid in state["focus"]:
            done = pid in cards and cards[pid].seen
            print(f"  [{'x' if done else ' '}] {catalog[pid].name:45} {catalog[pid].topic}")
        if not state["focus"]:
            print("no focus list; new problems follow the usual track")


def cmd_config(args, catalog):
    with st.locked() as state:
        cfg = state["config"]
        if args.key:
            if args.key not in st.DEFAULT_CONFIG:
                sys.exit(f"unknown key {args.key}; keys: {', '.join(st.DEFAULT_CONFIG)}")
            if args.value is not None:
                old, value = cfg[args.key], args.value
                if isinstance(old, bool):
                    cfg[args.key] = value.lower() in ("true", "on", "yes", "1")
                elif value.lower() in ("none", "off"):
                    cfg[args.key] = None
                elif isinstance(old, (int, float)) or (old is None and value.lstrip("-").isdigit()):
                    cfg[args.key] = int(value) if value.lstrip("-").isdigit() else float(value)
                else:
                    cfg[args.key] = value
        for k, v in cfg.items():
            print(f"{k} = {v}")


def cmd_note(args, catalog):
    with st.locked() as state:
        state["sessions"].append({"date": str(_date(args.date)), "text": args.text})
    print("noted")


def cmd_report(args, catalog):
    print(report.progress_markdown(st.load(), catalog, date.today()))


def cmd_sheet(args, catalog):
    print(report.cheat_sheet(st.load(), catalog))


def cmd_import(args, catalog):
    from .neetcode import read_solved
    names = read_solved()
    today = _date(args.date)
    well = {t.strip() for t in (args.well or "").split(",") if t.strip()}
    recent = {t.strip() for t in (args.recent or "").split(",") if t.strip()}
    with st.locked() as state:
        known = {e["problem"] for e in state["events"] if e["kind"] in ("attempt", "seed")}
        added = []
        for name in names:
            p = catalog.find(name)
            if p.id in known:
                continue
            if args.seed:
                group = "well" if p.topic in well else "recent" if p.topic in recent else "other"
                st.add_event(state, "seed", p.id, today, interval=SEED_DAYS[group][p.difficulty],
                             source="neetcode")
            else:
                st.add_event(state, "attempt", p.id, today, mode="new", source="neetcode")
            added.append(p.name)
    print(f"NeetCode shows {len(names)} solved; {len(added)} new to the log")
    for name in added:
        print(f"  + {name}")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="lc", description="Spaced repetition LeetCode coach that plans your day in Todoist.")
    sub = ap.add_subparsers(dest="cmd")

    p = sub.add_parser("sync", help="record completions and fill today's Todoist list")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--date")
    p.set_defaults(fn=cmd_sync)

    p = sub.add_parser("more", help="add N more new problems (or redos with --redo) today")
    p.add_argument("n", type=int, nargs="?", default=1)
    p.add_argument("--redo", action="store_true", help="add redos instead of new problems")
    p.add_argument("--date")
    p.set_defaults(fn=cmd_more)

    p = sub.add_parser("log", help="record how a problem went")
    p.add_argument("problem")
    p.add_argument("-g", "--grade", choices=GRADES)
    p.add_argument("-v", "--video", action="store_true", help="needed the video")
    p.add_argument("-m", "--minutes", type=int)
    p.add_argument("-n", "--notes")
    p.add_argument("-i", "--insight", help="one line key insight")
    p.add_argument("--date")
    p.add_argument("--offline", action="store_true", help="do not sync Todoist afterwards")
    p.set_defaults(fn=cmd_log)

    p = sub.add_parser("skip", help="a problem on a checked-off list was not actually done")
    p.add_argument("problem")
    p.add_argument("--date")
    p.add_argument("--offline", action="store_true")
    p.set_defaults(fn=cmd_skip)

    p = sub.add_parser("snooze", help="hold a problem off the daily lists until a date")
    p.add_argument("problem")
    p.add_argument("--until")
    p.add_argument("--clear", action="store_true")
    p.add_argument("--offline", action="store_true")
    p.set_defaults(fn=cmd_snooze)

    p = sub.add_parser("status", help="today, progress by topic, what is coming")
    p.add_argument("--json", action="store_true")
    p.add_argument("--date")
    p.set_defaults(fn=cmd_status)

    p = sub.add_parser("show", help="one problem's history and insight")
    p.add_argument("problem")
    p.set_defaults(fn=cmd_show)

    p = sub.add_parser("next", help="preview the new problem queue")
    p.add_argument("n", type=int, nargs="?", default=10)
    p.set_defaults(fn=cmd_next)

    p = sub.add_parser("retire", help="stop scheduling redos of a problem")
    p.add_argument("problem")
    p.set_defaults(fn=cmd_retire)
    p = sub.add_parser("unretire", help="put a retired problem back in rotation")
    p.add_argument("problem")
    p.set_defaults(fn=lambda a, c: cmd_retire(a, c, False))

    p = sub.add_parser("interview", help="track interview dates (cram mode kicks in before them)")
    p.add_argument("action", choices=["add", "rm", "list"])
    p.add_argument("company", nargs="?")
    p.add_argument("date", nargs="?")
    p.add_argument("--notes")
    p.set_defaults(fn=cmd_interview)

    p = sub.add_parser("focus", help="problems that jump the new problem queue, in order")
    p.add_argument("action", choices=["list", "set", "add", "clear"], nargs="?", default="list")
    p.add_argument("problems", nargs="*")
    p.set_defaults(fn=cmd_focus)

    p = sub.add_parser("config", help="show or change settings")
    p.add_argument("key", nargs="?")
    p.add_argument("value", nargs="?")
    p.set_defaults(fn=cmd_config)

    p = sub.add_parser("note", help="save a free text note about a session")
    p.add_argument("text")
    p.add_argument("--date")
    p.set_defaults(fn=cmd_note)

    p = sub.add_parser("report", help="progress by topic as a markdown table")
    p.set_defaults(fn=cmd_report)

    p = sub.add_parser("sheet", help="print every saved key insight by topic")
    p.set_defaults(fn=cmd_sheet)

    p = sub.add_parser("import-neetcode", help="pull solved problems from an open NeetCode tab")
    p.add_argument("--seed", action="store_true", help="first import: schedule as old solves")
    p.add_argument("--well", help="comma separated topics known well (longer first gap)")
    p.add_argument("--recent", help="comma separated topics done recently")
    p.add_argument("--date")
    p.set_defaults(fn=cmd_import)

    args = ap.parse_args(argv)
    catalog = Catalog.load()
    if not args.cmd:
        args = ap.parse_args(["status"])
    try:
        args.fn(args, catalog)
    except LookupError as err:
        sys.exit(str(err).strip("'\""))


if __name__ == "__main__":
    main()
