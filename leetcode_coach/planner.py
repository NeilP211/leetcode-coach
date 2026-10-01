"""Decides what goes on the list each day. Pure functions, no I/O."""

from dataclasses import dataclass
from datetime import date, timedelta

from . import srs
from .catalog import CORE, EXTRA, LIGHT_TRACK, LIGHT_UNLOCK_AFTER, MAIN_TRACK, WARMUP

WEAK_SCORE = 0.6  # topic average below this counts as weak
WEAK_MIN_RATED = 3
LIGHT_EVERY = 4  # once unlocked, every 4th new problem comes from the light track
LOOKAHEAD_DAYS = 3  # quiet days pull redos this close to due forward


@dataclass
class Targets:
    review: int
    new: int
    mock: int
    reason: str = ""

    def as_dict(self):
        return {"review": self.review, "new": self.new, "mock": self.mock, "reason": self.reason}


def due_cards(cards, today, ahead=0):
    until = today + timedelta(days=ahead)
    return [c for c in cards.values() if c.due and c.due <= until and not c.retired]


def pullable(cards, today):
    """Problems due in the next few days that a quiet day may pull forward."""
    return [c for c in due_cards(cards, today, LOOKAHEAD_DAYS) if c.due <= today or c.interval >= 7]


def targets(config, due_count, today, interview=None, soon_count=0):
    """How many redos, new problems and mocks to hand out today.

    The base is review_per_day redos plus new_per_day new problems. When more
    redos are due than the base allows, redos borrow new-problem slots but at
    least min_new new problems stay, so progress never fully stalls. If the pile
    reaches three days' worth, the day becomes a catch-up day with no new
    problems. Inside the cram window before an interview, new problems drop
    to one and a redo slot is added. Mocks are opt in through mock_weekday. On a quiet day, redos due in the next
    few days fill the empty redo slots, which also flattens later spikes.
    """
    rbase, nbase = config["review_per_day"], config["new_per_day"]
    keep = min(nbase, config.get("min_new", 1))
    reason = []
    cram = False
    if interview:
        days_left = (date.fromisoformat(interview["date"]) - today).days
        if 0 <= days_left <= config["cram_days"]:
            cram = True
            rbase, nbase = rbase + 1, min(nbase, 1)
            reason.append(f"cram mode, {interview['company']} in {days_left}d")
    budget = rbase + nbase
    if due_count >= 3 * budget:
        review, new = min(due_count, budget + 1), 0
        reason.append(f"catch-up day, {due_count} redos due")
    else:
        review = min(max(due_count, soon_count), rbase)
        if due_count > rbase:
            review += min(due_count - rbase, max(0, nbase - keep))
            if review > rbase:
                reason.append(f"{due_count} redos due, borrowed {review - rbase} new slot(s)")
        new = max(0, min(nbase, budget - review))
    mock = 0
    weekday = config.get("mock_weekday")
    if new > 0 and weekday is not None and (
        today.weekday() == weekday or (cram and today.toordinal() % 2 == 0)
    ):
        mock, new = 1, new - 1
    return Targets(review, new, mock, "; ".join(reason))


def pick_reviews(cards, today, k, exclude=(), cram=False, early=False):
    """The k most at-risk due problems, pulling shaky ones forward when cramming.

    early (an explicit ask for more redos) fills any gap with the soonest due
    problems not touched in the last two days.
    """
    exclude = set(exclude)
    due = [c for c in due_cards(cards, today) if c.problem not in exclude]

    def risk(c):
        overdue = (today - c.due).days
        return (-(overdue + 1) / max(c.interval, 1), -c.lapses, c.due, c.problem)

    picked = sorted(due, key=risk)[:k]
    if len(picked) < k:
        # Short gaps are deliberate (a fresh `again` waits its 2 days), so only
        # problems on a gap of a week or more get pulled in early.
        soon = [c for c in due_cards(cards, today, LOOKAHEAD_DAYS)
                if c.problem not in exclude and c.due > today and c.interval >= 7]
        picked += sorted(soon, key=lambda c: (c.due, -c.lapses, c.problem))[: k - len(picked)]
    if cram and len(picked) < k:
        taken = exclude | {c.problem for c in picked}
        ahead = [
            c for c in cards.values()
            if c.problem not in taken and c.due and c.due > today and not c.retired
        ]
        ahead.sort(key=lambda c: (not c.shaky, c.due, c.problem))
        picked += ahead[: k - len(picked)]
    if early and len(picked) < k:
        taken = exclude | {c.problem for c in picked}
        recent = today - timedelta(days=1)
        ahead = [
            c for c in cards.values()
            if c.problem not in taken and c.due and not c.retired and not (c.last and c.last >= recent)
        ]
        ahead.sort(key=lambda c: (c.due, -c.lapses, c.problem))
        picked += ahead[: k - len(picked)]
    return [c.problem for c in picked]


def topic_scores(catalog, cards):
    """{topic: (average score of rated problems, count)} from each problem's latest grade."""
    out = {}
    for topic in catalog.topics:
        grades = [
            srs.SCORE[cards[p.id].last_grade]
            for p in catalog.in_topic(topic)
            if p.id in cards and cards[p.id].last_grade
        ]
        if grades:
            out[topic] = (sum(grades) / len(grades), len(grades))
    return out


def weak_topics(catalog, cards):
    scores = topic_scores(catalog, cards)
    weak = [(s, t) for t, (s, n) in scores.items() if n >= WEAK_MIN_RATED and s < WEAK_SCORE]
    return [t for _, t in sorted(weak)]


def _unseen(catalog, cards, exclude):
    return [
        p for p in catalog.problems
        if p.id not in exclude
        and not (p.id in cards and (cards[p.id].seen or cards[p.id].retired))
    ]


def new_queue(catalog, cards, exclude=(), intro_count=0, only_150=False, focus=()):
    """The ordered list of problems to introduce next.

    focus is a hand-picked list of problem ids that jump the queue, in the
    order given (interview prep for a specific company, say). The rest of
    the queue follows as usual.

    First pass: core problems topic by topic along the main track, with the
    light track mixed in every few problems once trees and heaps are done.
    Weak topics that the main track has already moved past get one extra
    same-pattern problem from the 250 extras. After the core is finished:
    the remaining hards and the extras by topic, then the warmup easies.
    only_150 drops everything outside the NeetCode 150, extras included.
    """
    exclude = set(exclude)
    unseen = _unseen(catalog, cards, exclude)
    if only_150:
        unseen = [p for p in unseen if p.nc150]
    topic_rank = {t: i for i, t in enumerate(MAIN_TRACK + LIGHT_TRACK)}

    def by_track(problems):
        return sorted(problems, key=lambda p: (topic_rank.get(p.topic, 99), p.order))

    main = by_track([p for p in unseen if p.tier == CORE and p.topic in MAIN_TRACK])
    light = by_track([p for p in unseen if p.tier == CORE and p.topic in LIGHT_TRACK])
    unlock_rank = MAIN_TRACK.index(LIGHT_UNLOCK_AFTER)
    light_on = not main or topic_rank[main[0].topic] > unlock_rank

    queue = []
    frontier = main[0].topic if main else None
    for topic in weak_topics(catalog, cards):
        behind = frontier is None or topic_rank.get(topic, 99) < topic_rank.get(frontier, 99)
        if behind and not any(p.topic == topic for p in main):
            extra = [p for p in unseen if p.topic == topic and p.tier == EXTRA]
            if extra:
                queue.append(min(extra, key=lambda p: (p.difficulty == "Hard", p.order)))
                break

    n = intro_count
    while main or light:
        use_light = light and (not main or (light_on and n % LIGHT_EVERY == LIGHT_EVERY - 1))
        queue.append((light if use_light else main).pop(0))
        n += 1

    later = by_track([p for p in unseen if p.tier not in (CORE, WARMUP)])
    warm = by_track([p for p in unseen if p.tier == WARMUP])
    seen_ids = {p.id for p in queue}
    queue += [p for p in later + warm if p.id not in seen_ids]
    if focus:
        unseen_ids = {p.id for p in _unseen(catalog, cards, exclude)}
        front = [catalog[pid] for pid in dict.fromkeys(focus) if pid in unseen_ids]
        front_ids = {p.id for p in front}
        queue = front + [p for p in queue if p.id not in front_ids]
    return queue


def pick_new(catalog, cards, k, exclude=(), intro_count=0, only_150=False, focus=()):
    return [p.id for p in new_queue(catalog, cards, exclude, intro_count, only_150, focus)[:k]]


def pick_mock(catalog, cards, today, exclude=(), only_150=False):
    """An unseen medium from a topic that is mostly covered, so it feels like an interview.

    Falls back to a medium already solved that is not due soon.
    """
    exclude = set(exclude)
    unseen = [p for p in _unseen(catalog, cards, exclude)
              if p.difficulty == "Medium" and (p.nc150 or not only_150)]
    covered = set()
    for topic in catalog.topics:
        core = [p for p in catalog.in_topic(topic) if p.tier == CORE]
        seen = [p for p in core if p.id in cards and cards[p.id].seen]
        if core and len(seen) / len(core) >= 0.6:
            covered.add(topic)
    pool = [p for p in unseen if p.topic in covered]
    pool.sort(key=lambda p: (p.tier != CORE, p.order))
    pool = pool[:12]
    if pool:
        return pool[int(srs._unit("mock", today) * len(pool))].id
    solved = [
        catalog[c.problem] for c in cards.values()
        if c.seen and not c.retired and c.problem not in exclude and c.problem in catalog.by_id
        and catalog[c.problem].difficulty == "Medium"
    ]
    if not solved:
        return None
    solved.sort(key=lambda p: (-(cards[p.id].due or today).toordinal(), p.order))
    return solved[0].id
