"""Unit tests for the depth-bounded closure the selection engine walks.

What a changed file reaches at each depth, how cycles terminate, how changed,
new, and deleted test files are handled, and the visual suite the closure must
never return.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from tests._test_selection_engine_helpers import (
    neutral_timings_environment,  # noqa: F401 (imported for fixture discovery)
    repo_fixture,  # noqa: F401 (imported for fixture discovery)
    select,
)
from tests._test_selection_fixtures import RING_SIZE, _git, _touch, _write
from tests._test_selection_rules import (
    RULE_CONTRACT_SET_ONLY,
    RULE_RENAME_OR_DELETE,
)


# --------------------------------------------------------------------------
# Depth-bounded closure
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("depth", "expected"),
    [
        (0, {"tests/test_a.py"}),
        (1, {"tests/test_a.py", "tests/test_b.py", "tests/test_via_helper.py"}),
        (
            2,
            {
                "tests/test_a.py",
                "tests/test_b.py",
                "tests/test_c.py",
                "tests/test_cycle.py",
                "tests/test_via_helper.py",
            },
        ),
    ],
)
def test_depth_bounding_stops_where_it_should(
    repo: Path, depth: int, expected: set[str]
) -> None:
    _touch(repo, "src/pkg/a.py")

    selection = select(repo, depth=depth)

    assert set(selection.selected) == expected
    assert "tests/test_d.py" not in selection.selected


def test_closure_traverses_test_support_modules(repo: Path) -> None:
    """A test importing no production module is only reachable via helpers."""
    _touch(repo, "src/pkg/a.py")

    selection = select(repo, depth=1)

    assert "tests/test_via_helper.py" in selection.selected
    assert selection.explanations["tests/test_via_helper.py"][0] == "pkg.a"


def test_cycles_terminate_and_do_not_explode_the_selection(repo: Path) -> None:
    _touch(repo, "src/pkg/ring0.py")

    selection = select(repo, depth=2)

    ring_tests = {path for path in selection.selected if "test_ring" in path}
    assert ring_tests == {
        "tests/test_ring0.py",
        f"tests/test_ring{RING_SIZE - 1}.py",
        f"tests/test_ring{RING_SIZE - 2}.py",
    }
    assert len(ring_tests) < RING_SIZE


def test_mutual_cycle_terminates(repo: Path) -> None:
    _touch(repo, "src/pkg/cycle_x.py")

    selection = select(repo, depth=3)

    assert "tests/test_cycle.py" in selection.selected


def test_changed_test_files_are_always_selected(repo: Path) -> None:
    _touch(repo, "tests/test_d.py")

    selection = select(repo)

    assert "tests/test_d.py" in selection.selected


def test_untracked_new_test_file_is_selected(repo: Path) -> None:
    _write(repo, "tests/test_untracked.py", "from pkg import d\n")

    selection = select(repo)

    assert "tests/test_untracked.py" in selection.selected


def test_deleted_test_file_is_not_selected(repo: Path) -> None:
    """A deleted path must not reach pytest, which exits 4 on a missing file."""
    _git(repo, "rm", "-q", "tests/test_d.py")

    selection = select(repo)

    assert "tests/test_d.py" not in selection.selected
    assert RULE_RENAME_OR_DELETE in selection.rules


def test_docs_only_change_selects_nothing(repo: Path) -> None:
    _touch(repo, "docs/development.md")

    selection = select(repo)

    assert selection.selected == ()
    assert RULE_CONTRACT_SET_ONLY in selection.rules
    assert not selection.escalated


# --------------------------------------------------------------------------
# Visual exclusion
# --------------------------------------------------------------------------


def test_visual_tests_are_never_selected(repo: Path) -> None:
    _touch(repo, "tests/_helper.py")

    selection = select(repo)

    assert "tests/ace/tui/visual/test_visual.py" not in selection.selected
    assert not any(
        path.startswith("tests/ace/tui/visual/") for path in selection.selected
    )


def test_changed_visual_test_is_still_excluded(repo: Path) -> None:
    _touch(repo, "tests/ace/tui/visual/test_visual.py")

    selection = select(repo)

    assert selection.selected == ()


def test_visual_tests_are_outside_the_universe(repo: Path) -> None:
    selection = select(repo)

    assert selection.universe_count == selection.manifest["universe_count"]
    assert "tests/ace/tui/visual/test_visual.py" not in selection.selected
    assert selection.universe_count == 8 + RING_SIZE
