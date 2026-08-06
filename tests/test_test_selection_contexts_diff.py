"""Unit tests for the two halves of a contexts lookup: the diff, and the rows.

Reading ground truth means turning a change into baseline-side line numbers and
then asking the coverage database which tests ran them. Both halves are pure
functions over data this module writes itself; the selector-level behavior they
feed lives in ``tests/test_test_selection_contexts_selection.py``.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from tests._test_selection_contexts import (
    baseline_changed_lines,
    context_test_file,
    find_tests_touching,
    normalize_measured_file,
    parse_baseline_lines,
)
from tests._test_selection_contexts_helpers import (
    head,
    repo_fixture,  # noqa: F401 (imported for fixture discovery)
)
from tests._test_selection_fixtures import write_contexts_baseline


# --------------------------------------------------------------------------
# Diff parsing
# --------------------------------------------------------------------------


def test_parse_baseline_lines_reads_the_old_side_not_the_new_one() -> None:
    """Deletions and modifications must report baseline-side numbering.

    The new-side numbers here (``+2,3`` and ``+9``) are deliberately different
    from the old-side ones, because using them would read the wrong rows out of
    the contexts database.
    """
    diff = (
        "diff --git a/src/pkg/a.py b/src/pkg/a.py\n"
        "--- a/src/pkg/a.py\n"
        "+++ b/src/pkg/a.py\n"
        "@@ -4,3 +2,3 @@\n"
        "-one\n-two\n-three\n+ONE\n+TWO\n+THREE\n"
        "diff --git a/src/pkg/b.py b/src/pkg/b.py\n"
        "--- a/src/pkg/b.py\n"
        "+++ b/src/pkg/b.py\n"
        "@@ -10 +9 @@\n"
        "-old\n+new\n"
    )

    assert parse_baseline_lines(diff) == {
        "src/pkg/a.py": {4, 5, 6},
        "src/pkg/b.py": {10},
    }


def test_parse_baseline_lines_brackets_a_pure_insertion() -> None:
    """Inserted code has no baseline line, so both its neighbours stand in."""
    diff = "--- a/src/pkg/a.py\n+++ b/src/pkg/a.py\n@@ -7,0 +8,2 @@\n+new\n+new\n"

    assert parse_baseline_lines(diff) == {"src/pkg/a.py": {7, 8}}


def test_parse_baseline_lines_ignores_files_added_since_the_baseline() -> None:
    diff = "--- /dev/null\n+++ b/src/pkg/new.py\n@@ -0,0 +1,2 @@\n+new\n+new\n"

    assert parse_baseline_lines(diff) == {}


def test_baseline_changed_lines_covers_the_uncommitted_working_tree(
    repo: Path,
) -> None:
    (repo / "src" / "pkg" / "a.py").write_text("VALUE = 2\n", encoding="utf-8")

    lines = baseline_changed_lines(repo, head(repo), ["src/pkg/a.py"])

    assert lines["src/pkg/a.py"] == {1}


def test_baseline_changed_lines_ignores_files_outside_the_change_set(
    repo: Path,
) -> None:
    """Between the baseline and the merge base, other people changed other files."""
    (repo / "src" / "pkg" / "a.py").write_text("VALUE = 2\n", encoding="utf-8")
    (repo / "src" / "pkg" / "hub.py").write_text("HUB = 2\n", encoding="utf-8")

    lines = baseline_changed_lines(repo, head(repo), ["src/pkg/a.py"])

    assert set(lines) == {"src/pkg/a.py"}


# --------------------------------------------------------------------------
# Reading a baseline
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("context", "expected"),
    [
        ("tests/test_a.py::test_x|run", "tests/test_a.py"),
        ("tests/test_a.py::test_x|setup", "tests/test_a.py"),
        ("tests/test_a.py::TestC::test_x|teardown", "tests/test_a.py"),
        ("tests/test_a.py::test_x", "tests/test_a.py"),
        ("", None),
        ("|run", None),
        ("some-non-nodeid-context", None),
    ],
)
def test_context_test_file(context: str, expected: str | None) -> None:
    assert context_test_file(context) == expected


@pytest.mark.parametrize(
    ("measured", "expected"),
    [
        ("src/pkg/a.py", "src/pkg/a.py"),
        ("/home/runner/work/sase/sase/src/sase/a.py", "src/sase/a.py"),
        (r"C:\checkout\src\sase\a.py", "src/sase/a.py"),
        ("tests/test_a.py", None),
        ("/usr/lib/python3/site.py", None),
    ],
)
def test_normalize_measured_file(measured: str, expected: str | None) -> None:
    assert normalize_measured_file(measured) == expected


def test_find_tests_touching_only_returns_tests_that_ran_a_changed_line(
    tmp_path: Path,
) -> None:
    database = tmp_path / "baseline.sqlite"
    write_contexts_baseline(
        database,
        {
            "src/pkg/a.py": {
                "tests/test_hit.py::test_x|run": [1, 2],
                "tests/test_miss.py::test_y|run": [9],
                "": [1],
            }
        },
    )

    selected, matched = find_tests_touching(database, {"src/pkg/a.py": {2}})

    assert selected == {"tests/test_hit.py"}
    assert matched == {"src/pkg/a.py"}


def test_find_tests_touching_survives_an_unreadable_database(tmp_path: Path) -> None:
    database = tmp_path / "broken.sqlite"
    database.write_text("not a database", encoding="utf-8")

    assert find_tests_touching(database, {"src/pkg/a.py": {1}}) == (set(), set())
