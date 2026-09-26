import pytest

from leetcode_coach.catalog import CORE, EXTRA, LIGHT_TRACK, MAIN_TRACK, SECOND_PASS, WARMUP


def test_full_list(catalog):
    assert len(catalog.problems) == 250
    assert sum(p.nc150 for p in catalog.problems) == 150
    assert set(catalog.topics) == set(MAIN_TRACK + LIGHT_TRACK)


def test_ids_unique_and_links_look_right(catalog):
    assert len(catalog.by_id) == 250
    for p in catalog.problems:
        assert p.leetcode.startswith("https://leetcode.com/problems/")
        assert p.neetcode.startswith("https://neetcode.io/problems/")


def test_tiers(catalog):
    tiers = {p.name: p.tier for p in catalog.problems}
    assert tiers["Minimum Window Substring"] == CORE
    assert tiers["Median of Two Sorted Arrays"] == SECOND_PASS
    assert tiers["Subarray Sum Equals K"] == EXTRA
    assert tiers["Concatenation of Array"] == WARMUP
    assert tiers["Two Sum"] == CORE


@pytest.mark.parametrize("query,name", [
    ("two sum", "Two Sum"),
    ("Two Sum II Input Array Is Sorted", "Two Sum II Input Array Is Sorted"),
    ("146", "LRU Cache"),
    ("lru", "LRU Cache"),
    ("min window substring", "Minimum Window Substring"),
    ("koko", "Koko Eating Bananas"),
    ("0217-contains-duplicate", "Contains Duplicate"),
    ("serialize and deserialize", "Serialize And Deserialize Binary Tree"),
])
def test_find(catalog, query, name):
    assert catalog.find(query).name == name


def test_find_ambiguous_suggests(catalog):
    with pytest.raises(LookupError) as err:
        catalog.find("robber")
    assert "House Robber" in str(err.value)


def test_find_nothing(catalog):
    with pytest.raises(LookupError):
        catalog.find("definitely not a problem")
