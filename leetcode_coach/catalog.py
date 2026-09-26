"""The NeetCode 250 problem list plus the study order laid on top of it."""

import difflib
import json
import re
from dataclasses import dataclass
from pathlib import Path

PROBLEMS_FILE = Path(__file__).resolve().parent.parent / "data" / "problems.json"

# The main track, in the order topics build on each other. Earlier topics are
# listed so any leftover core problems in them still get picked up first.
MAIN_TRACK = [
    "Arrays & Hashing",
    "Two Pointers",
    "Sliding Window",
    "Stack",
    "Binary Search",
    "Linked List",
    "Trees",
    "Tries",
    "Heap / Priority Queue",
    "Backtracking",
    "Graphs",
    "1-D Dynamic Programming",
    "Advanced Graphs",
    "2-D Dynamic Programming",
]

# Small, self-contained topics that get mixed in as a change of pace once the
# main track is past the tree and heap foundations.
LIGHT_TRACK = ["Intervals", "Greedy", "Bit Manipulation", "Math & Geometry"]
LIGHT_UNLOCK_AFTER = "Heap / Priority Queue"

# Hards that come up often enough to do on the first pass. Every other hard
# waits for the second pass, once every pattern has been seen.
FIRST_PASS_HARDS = {
    "Trapping Rain Water",
    "Minimum Window Substring",
    "Sliding Window Maximum",
    "Merge K Sorted Lists",
    "Binary Tree Maximum Path Sum",
    "Serialize And Deserialize Binary Tree",
    "Find Median From Data Stream",
    "Word Ladder",
}

# Tier 1: core (NeetCode 150 easy/medium plus the first-pass hards)
# Tier 2: the remaining NeetCode 150 hards
# Tier 3: the extra 100 from the 250 list, mediums and hards
# Tier 4: the extra 100, easies
CORE, SECOND_PASS, EXTRA, WARMUP = 1, 2, 3, 4
TIER_NAMES = {CORE: "core", SECOND_PASS: "second pass", EXTRA: "extra", WARMUP: "warmup"}


@dataclass(frozen=True)
class Problem:
    id: str
    name: str
    topic: str
    difficulty: str
    nc150: bool
    blind75: bool
    leetcode: str
    neetcode: str
    video: str | None
    order: int

    @property
    def tier(self):
        if self.nc150:
            if self.difficulty != "Hard" or self.name in FIRST_PASS_HARDS:
                return CORE
            return SECOND_PASS
        return WARMUP if self.difficulty == "Easy" else EXTRA

    @property
    def number(self):
        return int(self.id.split("-", 1)[0])


def _norm(text):
    return re.sub(r"[^a-z0-9]", "", text.lower())


class Catalog:
    def __init__(self, problems):
        self.problems = problems
        self.by_id = {p.id: p for p in problems}
        self._by_norm = {_norm(p.name): p for p in problems}
        self.topics = list(dict.fromkeys(p.topic for p in problems))

    @classmethod
    def load(cls, path=PROBLEMS_FILE):
        raw = json.loads(Path(path).read_text())
        return cls([Problem(order=i, **r) for i, r in enumerate(raw)])

    def __getitem__(self, pid):
        return self.by_id[pid]

    def in_topic(self, topic):
        return [p for p in self.problems if p.topic == topic]

    def find(self, query):
        """Resolve a problem from an id, a LeetCode number, or a loose name.

        Returns the Problem or raises LookupError with close suggestions.
        """
        q = query.strip()
        if q in self.by_id:
            return self.by_id[q]
        if q.isdigit():
            hits = [p for p in self.problems if p.number == int(q)]
            if hits:
                return hits[0]
        n = _norm(q)
        if n in self._by_norm:
            return self._by_norm[n]
        contains = [p for key, p in self._by_norm.items() if n and n in key]
        if len(contains) == 1:
            return contains[0]
        close = difflib.get_close_matches(n, self._by_norm, n=3, cutoff=0.75)
        if len(close) == 1 or (close and not contains):
            best = difflib.SequenceMatcher(None, n, close[0]).ratio()
            if best >= 0.85:
                return self._by_norm[close[0]]
        options = [p.name for p in contains] or [self._by_norm[c].name for c in close]
        hint = f" Did you mean: {', '.join(options[:5])}?" if options else ""
        raise LookupError(f"No problem matches '{query}'.{hint}")
