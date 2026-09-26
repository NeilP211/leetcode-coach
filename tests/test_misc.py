import importlib.util
from pathlib import Path

from conftest import SUN
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


def test_readme_block_replaced(tmp_path, state, catalog):
    readme = tmp_path / "README.md"
    readme.write_text(f"intro\n{report.START}\nold\n{report.END}\noutro\n")
    st.add_event(state, "attempt", catalog.find("two sum").id, SUN, grade="good")
    assert report.update_readme(readme, report.progress_markdown(state, catalog, SUN))
    text = readme.read_text()
    assert "**1 / 250**" in text and "old" not in text and text.endswith("outro\n")


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
    main(["status"])
    main(["sheet"])
    main(["next", "3"])
    out = capsys.readouterr().out
    assert "logged: Two Sum = easy" in out
    assert "new_per_day = 3" in out
    assert "next interview: Acme on 2026-10-20" in out
    assert "complement map" in out


def test_interviews_and_notes_stay_private(tmp_path):
    path = tmp_path / "state.json"
    with st.locked(path) as s:
        s["interviews"].append({"company": "Acme", "date": "2026-10-20", "notes": ""})
        s["sessions"].append({"date": "2026-09-26", "text": "rough day"})
    assert "Acme" not in path.read_text() and "rough" not in path.read_text()
    again = st.load(path)
    assert again["interviews"][0]["company"] == "Acme"
    assert again["sessions"][0]["text"] == "rough day"
