import json

import pytest

from leetcode_coach.catalog import CORE, Catalog, EXTRA, LIGHT_TRACK, MAIN_TRACK, SECOND_PASS, WARMUP


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


def _write_extras(tmp_path, rows):
    path = tmp_path / "extra_problems.json"
    path.write_text(json.dumps(rows))
    return path


def test_extras_load_after_the_250(tmp_path):
    path = _write_extras(tmp_path, [
        {"id": "1801-number-of-orders-in-the-backlog", "name": "Number of Orders in the Backlog",
         "topic": "Heap / Priority Queue", "difficulty": "Medium",
         "leetcode": "https://leetcode.com/problems/number-of-orders-in-the-backlog/"},
        {"id": "9001-order-ledger", "name": "Order Ledger", "topic": "Arrays & Hashing",
         "difficulty": "Medium", "leetcode": "https://example.com/order-ledger"},
    ])
    cat = Catalog.load(extras=path)
    assert len(cat.problems) == 252
    ledger = cat.find("order ledger")
    assert ledger.id == cat.find("9001").id == "9001-order-ledger"
    assert not ledger.nc150 and ledger.tier == EXTRA and ledger.video is None
    assert ledger.neetcode == ledger.leetcode == "https://example.com/order-ledger"
    assert cat.problems[-1] is ledger and ledger.order == 251


def test_extras_missing_file_or_clash(tmp_path):
    assert len(Catalog.load(extras=tmp_path / "nope.json").problems) == 250
    path = _write_extras(tmp_path, [{"id": "0146-lru-cache", "name": "LRU Again", "topic": "Linked List",
                                     "difficulty": "Medium", "leetcode": "https://example.com/lru"}])
    with pytest.raises(ValueError):
        Catalog.load(extras=path)
