import importlib.util
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from conftest import SUN
from leetcode_coach import cli
from leetcode_coach import report
from leetcode_coach import state as st
from leetcode_coach.cli import main
from leetcode_coach.todoist import Todoist, TodoistError, task_status

ROOT = Path(__file__).resolve().parent.parent


def load_fetch():
    spec = importlib.util.spec_from_file_location("fetch", ROOT / "scripts" / "fetch_problems.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_js_literal_to_json():
    fetch = load_fetch()
    src = 'x=[{problem:"Two Sum",n:1,ok:!0,bad:!1,s:\'it\\\'s "q"\',a:[{b:"c:d"}]}];'
    start = src.index("[")
    out = fetch.js_to_json(fetch.cut_array(src, start))
    assert out == [{"problem": "Two Sum", "n": 1, "ok": True, "bad": False,
                    "s": "it's \"q\"", "a": [{"b": "c:d"}]}]


def test_task_status():
    assert task_status(None) == "gone"
    assert task_status({"is_deleted": True}) == "gone"
    assert task_status({"checked": True}) == "done"
    assert task_status({"completed_at": "2026-09-26T10:00:00Z"}) == "done"
    assert task_status({"checked": False}) == "open"
    assert task_status({"checked": True, "is_deleted": True}) == "done"


def test_client_needs_token():
    try:
        Todoist(None)
    except TodoistError as err:
        assert "keychain" in str(err)
    else:
        raise AssertionError("expected TodoistError")


def test_client_paginates_and_handles_404():
    pages = {
        None: '{"results":[{"id":"1"}],"next_cursor":"c1"}',
        "c1": '{"results":[{"id":"2"}],"next_cursor":null}',
    }
    seen = []

    def transport(method, url, headers, body):
        seen.append((method, url, headers))
        if "/tasks/404" in url:
            return 404, "not found"
        cursor = url.split("cursor=")[1] if "cursor=" in url else None
        return 200, pages[cursor]

    client = Todoist("tok", transport)
    assert [t["id"] for t in client.active_tasks("leetcode")] == ["1", "2"]
    assert client.get_task("404") is None
    assert seen[0][2]["authorization"] == "Bearer tok"
    assert "label=leetcode" in seen[0][1]


def test_client_raises_on_error():
    client = Todoist("tok", lambda *a: (500, "boom"))
    try:
        client.create_task("x", "", "2026-09-26", 4, ["leetcode"])
    except TodoistError as err:
        assert "500" in str(err)
    else:
        raise AssertionError("expected TodoistError")


def test_progress_markdown(state, catalog):
    st.add_event(state, "attempt", catalog.find("two sum").id, SUN, grade="good")
    text = report.progress_markdown(state, catalog, SUN)
    assert "**1 / 250**" in text and "| Arrays & Hashing | 1/22 |" in text


def test_cheat_sheet_groups_by_topic(state, catalog):
    state["insights"][catalog.find("two sum").id] = "hashmap of value to index"
    sheet = report.cheat_sheet(state, catalog)
    assert "## Arrays & Hashing" in sheet and "hashmap of value to index" in sheet


def test_status_and_show(state, catalog):
    st.add_event(state, "attempt", catalog.find("koko").id, SUN, grade="again", video=True)
    data = report.status_data(state, catalog, SUN)
    assert data["summary"]["solved"] == 1
    text = report.status_text(data)
    assert "Binary Search" in text
    shown = report.show_problem(state, catalog, "koko", SUN)
    assert "again" in shown and "video" in shown


def test_streak(state, catalog):
    for i, name in enumerate(["two sum", "3sum", "lru"]):
        st.add_event(state, "attempt", catalog.find(name).id, SUN.replace(day=SUN.day - i), grade="good")
    assert report.streak(state, SUN) == 3


def test_state_roundtrip_and_lock(tmp_path):
    path = tmp_path / "state.json"
    with st.locked(path) as s:
        s["config"]["new_per_day"] = 3
    assert st.load(path)["config"]["new_per_day"] == 3
    assert st.load(path)["config"]["review_per_day"] == 2


def test_cli_offline_commands(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(st, "STATE_FILE", tmp_path / "state.json")
    main(["log", "two sum", "-g", "easy", "--offline", "--date", "2026-09-26", "-i", "complement map"])
    main(["interview", "add", "Acme", "2026-10-20"])
    main(["config", "new_per_day", "3"])
    main(["config", "mock_weekday", "5"])
    main(["config", "mock_weekday", "off"])
    main(["status"])
    main(["sheet"])
    main(["report"])
    main(["next", "3"])
    out = capsys.readouterr().out
    assert "logged: Two Sum = easy" in out
    assert "new_per_day = 3" in out
    assert "mock_weekday = 5" in out and out.rstrip().count("mock_weekday = None") >= 1
    assert "next interview: Acme on 2026-10-20" in out
    assert "complement map" in out


def test_default_state_lives_outside_the_repo():
    if "LC_STATE" not in os.environ:
        assert st.STATE_FILE == Path.home() / ".leetcode-coach" / "state.json"
    assert ROOT not in st.STATE_FILE.parents


def test_a_failed_run_saves_nothing(tmp_path):
    path = tmp_path / "state.json"
    with st.locked(path) as s:
        s["config"]["new_per_day"] = 3
    with pytest.raises(RuntimeError):
        with st.locked(path) as s:
            s["config"]["new_per_day"] = 9
            raise RuntimeError("Todoist is down")
    assert st.load(path)["config"]["new_per_day"] == 3


def test_more_needs_a_count_of_one_or_more(tmp_path, monkeypatch):
    monkeypatch.setattr(st, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(cli, "client", lambda: pytest.fail("reached Todoist"))
    for n in ("0", "-2"):
        with pytest.raises(SystemExit) as err:
            main(["more", n])
        assert "1 or more" in str(err.value)


def run_daily(root, lc_script):
    lc = root / "bin" / "lc"
    lc.write_text(lc_script)
    lc.chmod(0o755)
    calls = root / "calls"
    calls.unlink(missing_ok=True)
    env = {**os.environ, "LC_STATE": str(root / "data" / "state.json"), "LC_RETRY_WAIT": "0"}
    run = subprocess.run(["zsh", str(root / "scripts" / "daily.sh")], env=env,
                         capture_output=True, text=True, timeout=60)
    return run, calls.read_text().count("x")


@pytest.mark.skipif(shutil.which("zsh") is None, reason="daily.sh is a zsh script")
def test_daily_job_retries_a_failed_sync(tmp_path):
    (tmp_path / "scripts").mkdir()
    (tmp_path / "bin").mkdir()
    shutil.copy(ROOT / "scripts" / "daily.sh", tmp_path / "scripts" / "daily.sh")
    # down twice, then fine: the third try goes through
    run, tries = run_daily(tmp_path, '#!/bin/sh\necho x >> calls\n[ "$(wc -l < calls)" -ge 3 ]\n')
    assert (run.returncode, tries) == (0, 3), run.stdout + run.stderr
    # down for good: a few tries, then it gives up until the next scheduled run
    run, tries = run_daily(tmp_path, "#!/bin/sh\necho x >> calls\nexit 1\n")
    assert (run.returncode, tries) == (1, 4), run.stdout + run.stderr
    assert "giving up" in run.stdout
