from datetime import date, timedelta

import pytest

from conftest import MON, SAT, SUN
from leetcode_coach import planner
from leetcode_coach import state as st
from leetcode_coach.srs import replay

CFG = dict(st.DEFAULT_CONFIG)


@pytest.mark.parametrize("due,review,new", [
    (0, 0, 2), (1, 1, 2), (2, 2, 2), (3, 3, 1), (7, 3, 1), (11, 3, 1), (12, 5, 0),
])
def test_targets_trade_new_for_redos(due, review, new):
    t = planner.targets(CFG, due, SUN)
    assert (t.review, t.new, t.mock) == (review, new, 0)


@pytest.mark.parametrize("due,review,new", [(3, 2, 2), (7, 2, 2), (12, 5, 0)])
def test_min_new_stops_borrowing(due, review, new):
    t = planner.targets({**CFG, "min_new": 2}, due, SUN)
    assert (t.review, t.new) == (review, new)


def test_quiet_day_pulls_upcoming_redos():
    t = planner.targets(CFG, 0, SUN, soon_count=5)
    assert t.review == 2


MOCKS = {**CFG, "mock_weekday": 5}


def test_no_mocks_by_default():
    t = planner.targets(CFG, 2, SAT)
    assert (t.review, t.new, t.mock) == (2, 2, 0)


def test_saturday_mock_when_turned_on():
    t = planner.targets(MOCKS, 2, SAT)
    assert (t.review, t.new, t.mock) == (2, 1, 1)


def test_no_mock_on_catch_up_day():
    t = planner.targets(MOCKS, 20, SAT)
    assert t.mock == 0 and t.new == 0


def test_cram_mode():
    t = planner.targets(CFG, 1, MON, {"company": "Acme", "date": str(MON + timedelta(days=5))})
    assert "cram" in t.reason
    assert t.new + t.mock == 1 and t.review == 1


def test_far_interview_is_normal():
    t = planner.targets(CFG, 0, MON, {"company": "Acme", "date": str(MON + timedelta(days=40))})
    assert t.reason == "" and t.new == 2


def events_for(catalog, names, day, grade="good", start=1):
    return [{"seq": start + i, "date": str(day), "problem": catalog.find(n).id,
             "kind": "attempt", "grade": grade} for i, n in enumerate(names)]


def test_pick_reviews_most_overdue_first(catalog):
    ev = events_for(catalog, ["Two Sum"], SAT - timedelta(days=30))
    ev += events_for(catalog, ["Valid Anagram"], SAT - timedelta(days=9), start=5)
    cards = replay(ev)
    picked = planner.pick_reviews(cards, SAT, 2)
    assert picked[0] == catalog.find("Two Sum").id
    assert len(picked) == 2


def test_pick_reviews_skips_excluded(catalog):
    cards = replay(events_for(catalog, ["Two Sum"], SAT - timedelta(days=30)))
    assert planner.pick_reviews(cards, SAT, 2, {catalog.find("Two Sum").id}) == []


def test_new_queue_starts_at_frontier(catalog):
    solved = [p.name for p in catalog.problems
              if p.topic in ("Arrays & Hashing", "Two Pointers", "Stack")]
    cards = replay(events_for(catalog, solved, SAT))
    q = [p.topic for p in planner.new_queue(catalog, cards)[:3]]
    assert q == ["Sliding Window"] * 3


def test_new_queue_skips_second_pass_hards_until_core_done(catalog):
    q = planner.new_queue(catalog, {})
    names = [p.name for p in q]
    core_count = sum(1 for p in catalog.problems if p.tier == 1)
    assert "Median of Two Sorted Arrays" not in names[:core_count]
    assert "Minimum Window Substring" in names[:core_count]
    assert names[-1] in {p.name for p in catalog.problems if p.tier == 4}
    assert len(q) == 250


def test_light_track_mixes_in_after_heap(catalog):
    early = [p.name for p in catalog.problems
             if p.tier == 1 and p.topic in planner.MAIN_TRACK[:9]]
    cards = replay(events_for(catalog, early, SAT))
    topics = [p.topic for p in planner.new_queue(catalog, cards, intro_count=0)[:8]]
    light = [t for t in topics if t in planner.LIGHT_TRACK]
    assert len(light) == 2
    assert topics[3] in planner.LIGHT_TRACK


def test_no_light_track_before_unlock(catalog):
    topics = [p.topic for p in planner.new_queue(catalog, {})[:40]]
    assert not any(t in planner.LIGHT_TRACK for t in topics)


def test_weak_topic_gets_extra_practice(catalog):
    stack = [p.name for p in catalog.problems if p.tier == 1 and p.topic in
             ("Arrays & Hashing", "Two Pointers", "Sliding Window", "Stack")]
    ev = events_for(catalog, stack, SAT, grade="good")
    two = [p.name for p in catalog.problems if p.topic == "Two Pointers" and p.tier == 1]
    ev += events_for(catalog, two, SAT + timedelta(days=5), grade="again", start=500)
    cards = replay(ev)
    assert "Two Pointers" in planner.weak_topics(catalog, cards)
    first = planner.new_queue(catalog, cards)[0]
    assert first.topic == "Two Pointers" and first.tier == 3


def test_mock_is_unseen_medium_from_covered_topic(catalog):
    arrays = [p.name for p in catalog.problems if p.topic == "Arrays & Hashing" and p.tier == 1]
    cards = replay(events_for(catalog, arrays, SAT))
    pid = planner.pick_mock(catalog, cards, SAT)
    p = catalog[pid]
    assert p.topic == "Arrays & Hashing" and p.difficulty == "Medium"
    assert pid not in cards


def test_mock_none_when_nothing_covered(catalog):
    assert planner.pick_mock(catalog, {}, SAT) is None


def test_fresh_again_is_never_pulled_forward(catalog):
    ev = events_for(catalog, ["Reorder List"], SAT, grade="again")
    cards = replay(ev)
    assert planner.pick_reviews(cards, SUN, 2) == []
    assert planner.pullable(cards, SUN) == []


def test_long_gap_redo_is_pulled_forward(catalog):
    cards = replay(events_for(catalog, ["Two Sum"], SAT - timedelta(days=6)))
    assert planner.pick_reviews(cards, SAT, 2) == [catalog.find("Two Sum").id]


def test_only_150_skips_weak_topic_extras(catalog):
    stack = [p.name for p in catalog.problems if p.tier == 1 and p.topic in
             ("Arrays & Hashing", "Two Pointers", "Sliding Window", "Stack")]
    ev = events_for(catalog, stack, SAT, grade="good")
    two = [p.name for p in catalog.problems if p.topic == "Two Pointers" and p.tier == 1]
    ev += events_for(catalog, two, SAT + timedelta(days=5), grade="again", start=500)
    cards = replay(ev)
    queue = planner.new_queue(catalog, cards, only_150=True)
    assert queue and all(p.nc150 for p in queue)
    assert len(queue) == sum(1 for p in catalog.problems if p.nc150 and p.id not in cards)


def test_focus_jumps_the_queue_in_order(catalog):
    focus = [catalog.find(n).id for n in ("Number of Islands", "Coin Change", "Two Sum")]
    cards = replay(events_for(catalog, ["Two Sum"], SAT))
    queue = planner.new_queue(catalog, cards, focus=focus)
    assert [p.id for p in queue[:2]] == focus[:2]
    assert len(queue) == len({p.id for p in queue}) == len(planner.new_queue(catalog, cards))
    assert planner.pick_new(catalog, cards, 1, exclude=focus[:1], focus=focus) == focus[1:2]
