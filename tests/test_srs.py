from datetime import date, timedelta

import pytest

from leetcode_coach import srs
from leetcode_coach.srs import Scheduler, replay

D0 = date(2026, 10, 1)


def ev(seq, day, pid, kind="attempt", **kw):
    return {"seq": seq, "date": str(D0 + timedelta(days=day)), "problem": pid, "kind": kind, **kw}


def test_video_means_redo_in_two_days():
    card = replay([ev(1, 0, "a", grade="again")])["a"]
    assert card.due == D0 + timedelta(days=2)
    assert card.lapses == 1 and card.reps == 0


@pytest.mark.parametrize("grade,days", [("hard", 3), ("good", 7), ("easy", 14)])
def test_first_clean_solve_gaps(grade, days):
    card = replay([ev(1, 0, "a", grade=grade)])["a"]
    assert card.interval == days
    assert abs((card.due - D0).days - days) <= max(1, round(days * 0.1))


def test_gap_grows_by_ease_on_good():
    cards = replay([ev(1, 0, "a", grade="good"), ev(2, 7, "a", grade="good")])
    assert cards["a"].interval == round(7 * srs.START_EASE)


def test_hard_shrinks_ease_and_grows_slowly():
    cards = replay([ev(1, 0, "a", grade="good"), ev(2, 7, "a", grade="hard")])
    card = cards["a"]
    assert card.ease == pytest.approx(srs.START_EASE - 0.15)
    assert 8 <= card.interval <= 9


def test_lapse_resets_streak_but_ease_floor_holds():
    events = [ev(i, i * 2, "a", grade="again") for i in range(1, 10)]
    card = replay(events)["a"]
    assert card.ease == srs.MIN_EASE
    assert card.lapses == 9 and card.interval == srs.AGAIN_DAYS


def test_video_then_clean_follows_the_redo_ladder():
    card = replay([ev(1, 0, "a", grade="again"), ev(2, 2, "a", grade="good"),
                   ev(3, 9, "a", grade="good")])["a"]
    assert card.reps == 2
    assert card.interval == round(7 * (srs.START_EASE - 0.2))


def test_unrated_counts_as_good_and_is_flagged():
    card = replay([ev(1, 0, "a")])["a"]
    assert card.interval == 7 and card.unrated == 1 and card.last_grade == "good"


def test_interval_capped():
    events = [ev(1, 0, "a", grade="easy")]
    day = 0
    for i in range(2, 8):
        day += 70
        events.append(ev(i, day, "a", grade="easy"))
    assert replay(events, max_interval=45)["a"].interval == 45


def test_late_review_gets_partial_credit():
    on_time = replay([ev(1, 0, "a", grade="good"), ev(2, 7, "a", grade="good")])["a"]
    late = replay([ev(1, 0, "a", grade="good"), ev(2, 27, "a", grade="good")])["a"]
    assert late.interval > on_time.interval


def test_replay_orders_by_date_not_insertion():
    events = [ev(2, 7, "a", grade="good"), ev(1, 0, "a", grade="again")]
    card = replay(events)["a"]
    assert card.last_grade == "good" and card.reps == 1


def test_mastered_needs_two_clean_solves_and_long_gap():
    card = replay([ev(1, 0, "a", grade="good"), ev(2, 7, "a", grade="good")])["a"]
    assert card.mastered is False
    card = replay([ev(1, 0, "a", grade="good"), ev(2, 7, "a", grade="good"),
                   ev(3, 25, "a", grade="good")])["a"]
    assert card.mastered is True


def test_retire_clears_due_and_unretire_restores():
    cards = replay([ev(1, 0, "a", grade="good"), ev(2, 1, "a", kind="retire")])
    assert cards["a"].due is None and cards["a"].retired
    cards = replay([ev(1, 0, "a", grade="good"), ev(2, 1, "a", kind="retire"),
                    ev(3, 2, "a", kind="unretire")])
    assert cards["a"].due is not None and not cards["a"].retired


def test_load_balancing_spreads_same_day_solves():
    events = [ev(i, 0, f"p{i}", grade="good") for i in range(1, 11)]
    cards = replay(events)
    per_day = {}
    for c in cards.values():
        per_day[c.due] = per_day.get(c.due, 0) + 1
    assert max(per_day.values()) <= 4
    assert all(abs((c.due - D0).days - 7) <= 1 for c in cards.values())


def test_seeds_trickle_in():
    sch = Scheduler()
    for i in range(40):
        sch.seed(f"p{i}", D0, 21)
    per_day = {}
    for c in sch.cards.values():
        assert D0 + timedelta(days=6) <= c.due <= D0 + timedelta(days=32)
        per_day[c.due] = per_day.get(c.due, 0) + 1
    assert max(per_day.values()) <= 2


def test_rescheduling_frees_old_slot():
    sch = Scheduler()
    sch.attempt("a", D0, "good")
    first = sch.cards["a"].due
    sch.attempt("a", first, "good")
    assert sch.load.get(first, 0) == 0


def test_bad_grade_rejected():
    with pytest.raises(ValueError):
        replay([ev(1, 0, "a", grade="meh")])


def test_unknown_event_kind_rejected():
    with pytest.raises(ValueError):
        replay([ev(1, 0, "a", kind="bogus")])
