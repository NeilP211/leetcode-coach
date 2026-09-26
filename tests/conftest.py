import itertools
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from leetcode_coach import state as st  # noqa: E402
from leetcode_coach.catalog import Catalog  # noqa: E402


@pytest.fixture(scope="session")
def catalog():
    return Catalog.load()


@pytest.fixture
def state():
    return st.fresh()


SAT = date(2026, 9, 26)
SUN = date(2026, 9, 27)
MON = date(2026, 9, 28)


class FakeTodoist:
    """In-memory stand-in for the Todoist client."""

    def __init__(self):
        self.tasks = {}
        self.ids = (str(i) for i in itertools.count(100))
        self.calls = []

    def active_tasks(self, label):
        return [t for t in self.tasks.values()
                if not t["checked"] and not t["is_deleted"] and label in t["labels"]]

    def get_task(self, task_id):
        t = self.tasks.get(task_id)
        return t

    def create_task(self, content, description, due_date, priority, labels, project_id=None):
        tid = next(self.ids)
        self.tasks[tid] = {"id": tid, "content": content, "description": description,
                           "due": {"date": due_date}, "priority": priority, "labels": labels,
                           "checked": False, "is_deleted": False, "completed_at": None}
        self.calls.append(("create", tid))
        return self.tasks[tid]

    def update_task(self, task_id, content=None, description=None, due_date=None):
        t = self.tasks[task_id]
        if content is not None:
            t["content"] = content
        if description is not None:
            t["description"] = description
        if due_date is not None:
            t["due"] = {"date": due_date}
        self.calls.append(("update", task_id))

    def open_tasks(self):
        return [t for t in self.tasks.values() if not t["checked"] and not t["is_deleted"]]

    def close_task(self, task_id):
        self.complete(task_id, None)
        self.calls.append(("close", task_id))

    def complete(self, task_id, when):
        t = self.tasks[task_id]
        t["checked"] = True
        t["completed_at"] = f"{when}T15:00:00Z" if when else None

    def delete(self, task_id):
        self.tasks[task_id]["is_deleted"] = True


@pytest.fixture
def todoist():
    return FakeTodoist()
