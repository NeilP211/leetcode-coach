"""Spaced repetition over an append-only event log.

Every solve, redo, seed and retirement is an event. A problem's schedule is
never stored directly: it is rebuilt by replaying the events in order. That
makes a late or corrected rating cheap to apply (edit the event and replay)
and keeps the history honest.

Scheduling is an SM-2 variant with four grades:

    again  needed the video, or could not get it
    hard   got it, but with a hint, bugs, or way over time
    good   got it on my own in a normal time
    easy   instant, barely had to think

An `again` brings the problem back in 2 days. Each clean solve after that
stretches the gap by the problem's ease factor (2.5 to start), which drifts
down on struggles and up on easy solves. New due dates are nudged within
about 10 percent of the ideal gap onto the least loaded day, so redos do not
bunch up.
"""

import hashlib
from dataclasses import dataclass, field
from datetime import date, timedelta

GRADES = ("again", "hard", "good", "easy")
SCORE = {"again": 0.0, "hard": 0.5, "good": 0.85, "easy": 1.0}

AGAIN_DAYS = 2
FIRST_DAYS = {"hard": 3, "good": 7, "easy": 14}
START_EASE, MIN_EASE, MAX_EASE = 2.5, 1.3, 3.0
DEFAULT_MAX_INTERVAL = 60
MASTERED_DAYS = 21


def d(s):
    return s if isinstance(s, date) else date.fromisoformat(s)


def _unit(*parts):
    """Deterministic number in [0, 1) from the given parts."""
    h = hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()
    return int(h[:8], 16) / 0x100000000


@dataclass
class Card:
    problem: str
    reps: int = 0  # clean solves in a row since the last `again`
    lapses: int = 0
    attempts: int = 0
    ease: float = START_EASE
    interval: int = 0
    due: date | None = None
    last: date | None = None
    last_grade: str | None = None
    first_seen: date | None = None
    retired: bool = False
    unrated: int = 0  # attempts still waiting for a rating
    history: list = field(default_factory=list)

    @property
    def seen(self):
        return self.first_seen is not None

    @property
    def mastered(self):
        return self.seen and self.reps >= 2 and self.interval >= MASTERED_DAYS

    @property
    def shaky(self):
        return self.last_grade in ("again", "hard")


class Scheduler:
    """Replays events into cards while tracking how many redos land per day."""

    def __init__(self, max_interval=DEFAULT_MAX_INTERVAL):
        self.max_interval = max_interval
        self.cards = {}
        self.load = {}

    def card(self, pid):
        if pid not in self.cards:
            self.cards[pid] = Card(pid)
        return self.cards[pid]

    def _place(self, card, target, lo, hi):
        """Set card.due to the least loaded day in [lo, hi], nearest target on ties."""
        if card.due is not None:
            self.load[card.due] = self.load.get(card.due, 1) - 1
        span = [lo + timedelta(days=i) for i in range((hi - lo).days + 1)]
        best = min(span, key=lambda day: (self.load.get(day, 0), abs((day - target).days), day))
        card.due = best
        self.load[best] = self.load.get(best, 0) + 1

    def _schedule(self, card, when, days):
        days = max(1, min(int(round(days)), self.max_interval))
        card.interval = days
        target = when + timedelta(days=days)
        if days < 3:
            self._place(card, target, target, target)
            return
        wiggle = max(1, round(days * 0.1))
        lo = max(when + timedelta(days=1), target - timedelta(days=wiggle))
        self._place(card, target, lo, target + timedelta(days=wiggle))

    def seed(self, pid, when, interval):
        """A problem solved before this tool existed, with a guessed gap.

        Seeds can land anywhere from 30 percent to 150 percent of the gap, on
        the least loaded day, so a batch of old problems trickles back a
        couple a day instead of landing together.
        """
        when = d(when)
        card = self.card(pid)
        card.reps, card.interval, card.last = 1, interval, when
        card.first_seen = card.first_seen or when
        card.last_grade = card.last_grade or "good"
        target = when + timedelta(days=interval)
        lo = when + timedelta(days=round(interval * 0.3))
        self._place(card, target, lo, when + timedelta(days=round(interval * 1.5)))

    def attempt(self, pid, when, grade):
        """Apply one solve. grade None means not rated yet and counts as good."""
        when = d(when)
        card = self.card(pid)
        g = grade or "good"
        if g not in GRADES:
            raise ValueError(f"unknown grade {grade!r}")
        card.attempts += 1
        card.first_seen = card.first_seen or when
        if grade is None:
            card.unrated += 1
        elapsed = (when - card.last).days if card.last else 0
        if g == "again":
            card.lapses += 1
            card.reps = 0
            card.ease = max(MIN_EASE, card.ease - 0.2)
            days = AGAIN_DAYS
        elif card.reps == 0:
            days = FIRST_DAYS[g]
            card.reps = 1
        else:
            late = max(0, elapsed - card.interval)
            if g == "hard":
                card.ease = max(MIN_EASE, card.ease - 0.15)
                days = max(card.interval + 1, (card.interval + late / 4) * 1.2)
            elif g == "good":
                days = (card.interval + late / 2) * card.ease
            else:
                days = (card.interval + late) * card.ease * 1.3
                card.ease = min(MAX_EASE, card.ease + 0.15)
            card.reps += 1
        card.last, card.last_grade = when, g
        if not card.retired:
            self._schedule(card, when, days)

    def retire(self, pid, flag=True):
        card = self.card(pid)
        card.retired = flag
        if flag and card.due is not None:
            self.load[card.due] = self.load.get(card.due, 1) - 1
            card.due = None
        elif not flag and card.due is None and card.last is not None:
            self._schedule(card, card.last, max(card.interval, 1))


def replay(events, max_interval=DEFAULT_MAX_INTERVAL):
    """Rebuild every card from the event log. Returns {problem_id: Card}."""
    sch = Scheduler(max_interval)
    for ev in sorted(events, key=lambda e: (e["date"], e["seq"])):
        pid, kind = ev["problem"], ev["kind"]
        if kind == "seed":
            sch.seed(pid, ev["date"], ev["interval"])
        elif kind == "attempt":
            sch.attempt(pid, ev["date"], ev.get("grade"))
        elif kind == "retire":
            sch.retire(pid, True)
        elif kind == "unretire":
            sch.retire(pid, False)
        else:
            raise ValueError(f"unknown event kind {kind!r}")
        sch.card(pid).history.append(ev)
    return sch.cards
