"""The README's test table must match what the suites actually collect.

This test exists because the table failed exactly once, and in the worst possible way. Its header says
"Counts below are mechanically produced, not maintained by hand" — and then the commit that added the
read-only middleware added seven integration tests without regenerating it, leaving the README claiming
255 where the suite collected 262. A reviewer found it in thirty seconds by running the command printed
in the next column.

A promise that a number cannot go stale is worth nothing unless something enforces it. `demo-numbers.md`
got that treatment for the *demo* figures; the *structural* figures never did. This is that guard.

It shells out to a collection-only pytest run rather than counting `def test_` with an AST, because
`@pytest.mark.parametrize` means the two numbers are not the same and the one the README should print
is the one a reader gets when they run the command.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[2]
README = API_ROOT.parents[1] / "README.md"


def _collected(target: str) -> int:
    """Number of tests pytest collects under `target`, via a subprocess that runs nothing."""
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", target, "--collect-only", "-q", "-p", "no:cacheprovider"],
        cwd=API_ROOT,
        capture_output=True,
        text=True,
        timeout=300,
    )
    # `-q` prints one "tests/path/to/file.py: N" line per module. Anchor on the `tests/` prefix: a
    # looser pattern also matches the `site-packages/foo.py:53` lines in pytest's warnings summary,
    # which silently inflates the total — the first version of this guard did exactly that.
    counts = [int(m.group(1)) for m in re.finditer(r"^tests/\S+\.py:\s*(\d+)\s*$", proc.stdout, re.M)]
    assert counts, f"collected nothing from {target}; pytest said:\n{proc.stdout[-2000:]}\n{proc.stderr[-2000:]}"
    return sum(counts)


def _readme_row(label: str) -> int:
    """The count cell of the README Tests-table row whose first cell starts with `label`."""
    text = README.read_text()
    row = re.search(rf"^\|\s*{re.escape(label)}[^|]*\|\s*\*\*(\d[\d,]*)\*\*\s*\|", text, re.M)
    assert row, f"no README Tests-table row starting with {label!r}"
    return int(row.group(1).replace(",", ""))


@pytest.mark.parametrize(
    ("label", "target"),
    [
        ("Backend unit", "tests/unit"),
        ("Backend integration", "tests/integration"),
    ],
)
def test_readme_matches_what_the_suite_collects(label: str, target: str) -> None:
    claimed = _readme_row(label)
    actual = _collected(target)
    assert claimed == actual, (
        f"README says {label} = {claimed}; `pytest {target} --collect-only` finds {actual}. "
        "Update the table in README.md (and the counts repeated in docs/phase4-handoff.md and "
        "docs/resume.md) rather than this test."
    )


def test_the_table_promises_this_and_must_keep_promising_it() -> None:
    """If the promise is ever softened, this guard has lost its justification and should be deleted.

    Deliberately pinned: the sentence is the reason a reader trusts the table enough to check it.
    """
    assert "mechanically produced, not maintained by hand" in README.read_text()
