"""Reads solved problems from an open neetcode.io tab in Chrome.

NeetCode keeps progress in the account, not on disk, so the only local way to
read it is from a logged-in tab. This runs a small script in that tab through
AppleScript, which needs Chrome's View > Developer > Allow JavaScript from
Apple Events turned on.
"""

import json
import subprocess

READ_JS = r"""
(() => JSON.stringify(
  [...document.querySelectorAll('button.neeter-status-toggle')]
    .filter(b => b.getAttribute('aria-pressed') === 'true')
    .map(b => b.getAttribute('aria-label').replace(/^Toggle /, '').replace(/ solved status$/, ''))
))()
"""

APPLESCRIPT = """
on run argv
  set js to item 1 of argv
  tell application "Google Chrome"
    repeat with w in windows
      repeat with t in tabs of w
        if URL of t contains "neetcode.io/practice" then
          return execute t javascript js
        end if
      end repeat
    end repeat
  end tell
  error "No neetcode.io/practice tab is open in Chrome."
end run
"""


def read_solved():
    """Names of every problem checked off on the open NeetCode practice tab."""
    out = subprocess.run(
        ["osascript", "-e", APPLESCRIPT, READ_JS],
        capture_output=True, text=True, timeout=30,
    )
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip() or "osascript failed")
    return json.loads(out.stdout.strip())
