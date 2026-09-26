"""Minimal Todoist API v1 client on the standard library."""

import json
import os
import subprocess
import urllib.error
import urllib.parse
import urllib.request
import uuid

API = "https://api.todoist.com/api/v1"
KEYCHAIN_SERVICE = "leetcode-coach-todoist"


class TodoistError(RuntimeError):
    pass


def load_token():
    """TODOIST_TOKEN from the environment, else the macOS login keychain."""
    token = os.environ.get("TODOIST_TOKEN", "").strip()
    if token:
        return token
    try:
        out = subprocess.run(
            ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-w"],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out.stdout.strip() or None


def _urllib_transport(method, url, headers, body):
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as res:
            return res.status, res.read().decode("utf-8")
    except urllib.error.HTTPError as err:
        return err.code, err.read().decode("utf-8", "replace")


class Todoist:
    def __init__(self, token, transport=_urllib_transport):
        if not token:
            raise TodoistError(
                "No Todoist token. Set TODOIST_TOKEN or store it in the keychain:\n"
                f"  security add-generic-password -a \"$USER\" -s {KEYCHAIN_SERVICE} -w \"$(pbpaste)\""
            )
        self.token = token
        self.transport = transport

    def _call(self, method, path, params=None, body=None, ok_404=False):
        url = API + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        headers = {"authorization": f"Bearer {self.token}"}
        data = None
        if body is not None:
            headers["content-type"] = "application/json"
            headers["x-request-id"] = str(uuid.uuid4())
            data = json.dumps(body).encode("utf-8")
        status, text = self.transport(method, url, headers, data)
        if status == 404 and ok_404:
            return None
        if status >= 400:
            raise TodoistError(f"Todoist {method} {path} HTTP {status}: {text[:200]}")
        return json.loads(text) if text.strip() else {}

    def active_tasks(self, label):
        """All open tasks carrying the label, following pagination."""
        tasks, cursor = [], None
        while True:
            params = {"label": label, "limit": 200}
            if cursor:
                params["cursor"] = cursor
            page = self._call("GET", "/tasks", params)
            tasks.extend(page.get("results", []))
            cursor = page.get("next_cursor")
            if not cursor:
                return tasks

    def get_task(self, task_id):
        """The task, including completed ones, or None if it no longer exists."""
        return self._call("GET", f"/tasks/{task_id}", ok_404=True)

    def create_task(self, content, description, due_date, priority, labels, project_id=None):
        body = {
            "content": content,
            "description": description,
            "due_date": due_date,
            "priority": priority,
            "labels": labels,
        }
        if project_id:
            body["project_id"] = project_id
        return self._call("POST", "/tasks", body=body)

    def set_due(self, task_id, due_date):
        return self._call("POST", f"/tasks/{task_id}", body={"due_date": due_date})

    def close_task(self, task_id):
        return self._call("POST", f"/tasks/{task_id}/close", body={})

    def delete_task(self, task_id):
        return self._call("DELETE", f"/tasks/{task_id}", ok_404=True)


def task_status(task):
    """'open', 'done' or 'gone' for a task dict from get_task (None is gone)."""
    if task is None:
        return "gone"
    if task.get("checked") or task.get("completed_at"):
        return "done"  # checked off then deleted still counts as done
    return "gone" if task.get("is_deleted") else "open"
