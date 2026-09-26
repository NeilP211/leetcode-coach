"""Rebuild data/problems.json from the NeetCode 250 list on neetcode.io.

neetcode.io is an Angular app and the problem list ships inside its main
bundle as a JS object literal. This script finds the bundle, cuts that array
out, converts it to JSON and keeps the 250 problems.

    python3 scripts/fetch_problems.py
"""

import json
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "problems.json"
PAGE = "https://neetcode.io/practice/practice/neetcode250"
UA = {"user-agent": "leetcode-coach (+https://github.com/NeilP211/leetcode-coach)"}


def get(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as res:
        return res.read().decode("utf-8")


def cut_array(src, start):
    """Return the text of the bracketed array that opens at src[start]."""
    depth, i, quote = 0, start, None
    while i < len(src):
        c = src[i]
        if quote:
            if c == "\\":
                i += 2
                continue
            if c == quote:
                quote = None
        elif c in "\"'`":
            quote = c
        elif c in "[{":
            depth += 1
        elif c in "]}":
            depth -= 1
            if depth == 0:
                return src[start : i + 1]
        i += 1
    raise ValueError("unterminated array")


def js_to_json(text):
    """Convert a JS literal of plain objects, strings and !0/!1 to JSON."""
    out, i, quote = [], 0, None
    while i < len(text):
        c = text[i]
        if quote:
            if c == "\\":
                esc = text[i : i + 2]
                out.append("'" if esc == "\\'" else esc)
                i += 2
                continue
            if c == quote:
                quote = None
                out.append('"')
            elif c == '"':
                out.append('\\"')
            else:
                out.append(c)
            i += 1
            continue
        if c in "\"'":
            quote = c
            out.append('"')
            i += 1
            continue
        if text.startswith("!0", i):
            out.append("true")
            i += 2
            continue
        if text.startswith("!1", i):
            out.append("false")
            i += 2
            continue
        m = re.match(r"([A-Za-z_$][\w$]*)\s*:", text[i:])
        if m and out and out[-1] in "{,":
            out.append(f'"{m.group(1)}":')
            i += m.end()
            continue
        out.append(c)
        i += 1
    return json.loads("".join(out))


def convert(raw):
    """Map NeetCode's fields onto ours."""
    return {
        "id": raw["code"],
        "name": raw["problem"],
        "topic": raw["pattern"],
        "difficulty": raw["difficulty"],
        "nc150": bool(raw.get("neetcode150")),
        "blind75": bool(raw.get("blind75")),
        "leetcode": "https://leetcode.com/problems/" + raw["link"].strip("/") + "/",
        "neetcode": "https://neetcode.io/problems/" + raw["ncLink"].strip("/"),
        "video": "https://youtu.be/" + raw["video"] if raw.get("video") else None,
    }


def main():
    html = get(PAGE)
    bundle = re.search(r'src="(main\.[0-9a-f]+\.js)"', html)
    if not bundle:
        sys.exit("could not find the main bundle on the page")
    src = get("https://neetcode.io/" + bundle.group(1))
    anchor = src.find('[{problem:"Concatenation of Array"')
    if anchor < 0:
        sys.exit("problem list not found in the bundle")
    problems = [convert(p) for p in js_to_json(cut_array(src, anchor)) if p.get("neetcode250")]
    if len(problems) != 250:
        sys.exit(f"expected 250 problems, got {len(problems)}")
    OUT.write_text(json.dumps(problems, indent=1) + "\n")
    print(f"wrote {len(problems)} problems to {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
