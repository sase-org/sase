"""Unit tests for what a resolved baseline contributes to a scoped selection.

Contexts exist to catch the tests the static import closure cannot reach, so
most of these run against a src module and a test that never import each other.
Which baseline gets resolved in the first place is
``tests/test_test_selection_contexts_baseline.py``'s subject.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from tests._test_selection import SelectionOptions, select_tests
from tests._test_selection_contexts import (
    CONTEXTS_DISABLED_ENV,
    CONTEXTS_MAX_DISTANCE_ENV,
    RULE_CONTEXT_BASELINE_STALE,
    RULE_CONTEXT_SELECTION,
    baseline_path,
)
from tests._test_selection_contexts_helpers import (
    add_dynamic_pair,
    contexts_dir_fixture,  # noqa: F401 (imported for fixture discovery)
    head,
    repo_fixture,  # noqa: F401 (imported for fixture discovery)
    select,
    store_for,
)
from tests._test_selection_fixtures import _git, write_contexts_baseline


def test_contexts_select_a_test_the_static_closure_cannot_reach(
    repo: Path, contexts_dir: Path
) -> None:
    add_dynamic_pair(repo)
    write_contexts_baseline(
        baseline_path(contexts_dir, head(repo)),
        {"src/pkg/dynamic.py": {"tests/test_dynamic.py::test_it|run": [1]}},
    )
    (repo / "src" / "pkg" / "dynamic.py").write_text("VALUE = 2\n", encoding="utf-8")

    with_contexts = select(repo, contexts_dir)

    assert "tests/test_dynamic.py" in with_contexts.selected
    assert RULE_CONTEXT_SELECTION in with_contexts.rules
    assert with_contexts.contexts.matched_files == ("src/pkg/dynamic.py",)


def test_disabling_contexts_loses_that_test_again(
    repo: Path, contexts_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    add_dynamic_pair(repo)
    write_contexts_baseline(
        baseline_path(contexts_dir, head(repo)),
        {"src/pkg/dynamic.py": {"tests/test_dynamic.py::test_it|run": [1]}},
    )
    (repo / "src" / "pkg" / "dynamic.py").write_text("VALUE = 2\n", encoding="utf-8")
    monkeypatch.setenv(CONTEXTS_DISABLED_ENV, "1")

    assert "tests/test_dynamic.py" not in select(repo, contexts_dir).selected


def test_contexts_union_the_static_closure_rather_than_replacing_it(
    repo: Path, contexts_dir: Path
) -> None:
    add_dynamic_pair(repo)
    write_contexts_baseline(
        baseline_path(contexts_dir, head(repo)),
        {"src/pkg/dynamic.py": {"tests/test_dynamic.py::test_it|run": [1]}},
    )
    (repo / "src" / "pkg" / "dynamic.py").write_text("VALUE = 2\n", encoding="utf-8")
    (repo / "src" / "pkg" / "a.py").write_text("VALUE = 2\n", encoding="utf-8")

    selected = select(repo, contexts_dir).selected

    # The closure's own answer for `pkg.a` survives alongside the context hit.
    assert "tests/test_dynamic.py" in selected
    assert "tests/test_a.py" in selected


def test_contexts_never_return_a_visual_test(repo: Path, contexts_dir: Path) -> None:
    write_contexts_baseline(
        baseline_path(contexts_dir, head(repo)),
        {
            "src/pkg/a.py": {
                "tests/ace/tui/visual/test_visual.py::test_v|run": [1],
            }
        },
    )
    (repo / "src" / "pkg" / "a.py").write_text("VALUE = 2\n", encoding="utf-8")

    selection = select(repo, contexts_dir)

    assert not any(
        path.startswith("tests/ace/tui/visual/") for path in selection.selected
    )


def test_contexts_ignore_a_test_file_deleted_since_the_baseline(
    repo: Path, contexts_dir: Path
) -> None:
    write_contexts_baseline(
        baseline_path(contexts_dir, head(repo)),
        {"src/pkg/a.py": {"tests/test_since_deleted.py::test_x|run": [1]}},
    )
    (repo / "src" / "pkg" / "a.py").write_text("VALUE = 2\n", encoding="utf-8")

    selection = select(repo, contexts_dir)

    assert "tests/test_since_deleted.py" not in selection.selected
    assert RULE_CONTEXT_SELECTION not in selection.rules


def test_a_stale_baseline_is_used_and_flagged(
    repo: Path, contexts_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    add_dynamic_pair(repo)
    baseline_sha = head(repo)
    write_contexts_baseline(
        baseline_path(contexts_dir, baseline_sha),
        {"src/pkg/dynamic.py": {"tests/test_dynamic.py::test_it|run": [1]}},
    )
    _git(repo, "commit", "-q", "--allow-empty", "-m", "move on")
    (repo / "src" / "pkg" / "dynamic.py").write_text("VALUE = 2\n", encoding="utf-8")
    monkeypatch.setenv(CONTEXTS_MAX_DISTANCE_ENV, "0")

    selection = select(repo, contexts_dir)

    assert RULE_CONTEXT_BASELINE_STALE in selection.rules
    assert selection.manifest["contexts"]["distance"] == 1
    # Stale is a warning, not a veto: the test is still selected.
    assert "tests/test_dynamic.py" in selection.selected


def test_a_baseline_for_an_unknown_commit_contributes_nothing(
    repo: Path, contexts_dir: Path
) -> None:
    """A commit git cannot resolve yields no baseline-side line numbers.

    The database might be full of useful rows, but without the diff there is no
    way to know *which* rows, so the honest answer is to record the baseline as
    stale and fall through to the static closure.
    """
    add_dynamic_pair(repo)
    write_contexts_baseline(
        baseline_path(contexts_dir, "0" * 40),
        {"src/pkg/dynamic.py": {"tests/test_dynamic.py::test_it|run": [1]}},
    )
    (repo / "src" / "pkg" / "dynamic.py").write_text("VALUE = 2\n", encoding="utf-8")

    selection = select(repo, contexts_dir)

    assert RULE_CONTEXT_BASELINE_STALE in selection.rules
    assert selection.manifest["contexts"]["distance"] is None
    assert selection.contexts.selected == ()


def test_a_file_added_since_the_baseline_contributes_no_contexts(
    repo: Path, contexts_dir: Path
) -> None:
    """A module the baseline never measured has no rows to find."""
    baseline_sha = head(repo)
    add_dynamic_pair(repo)
    write_contexts_baseline(
        baseline_path(contexts_dir, baseline_sha),
        {"src/pkg/dynamic.py": {"tests/test_dynamic.py::test_it|run": [1]}},
    )
    (repo / "src" / "pkg" / "dynamic.py").write_text("VALUE = 2\n", encoding="utf-8")

    selection = select(repo, contexts_dir)

    assert selection.contexts.selected == ()
    assert RULE_CONTEXT_SELECTION not in selection.rules


def test_contexts_can_push_a_selection_over_the_escalation_ratio(
    repo: Path, contexts_dir: Path
) -> None:
    add_dynamic_pair(repo)
    write_contexts_baseline(
        baseline_path(contexts_dir, head(repo)),
        {"src/pkg/dynamic.py": {"tests/test_dynamic.py::test_it|run": [1]}},
    )
    (repo / "src" / "pkg" / "dynamic.py").write_text("VALUE = 2\n", encoding="utf-8")

    options = SelectionOptions(base_ref="HEAD", depth=2, max_ratio=0.001)
    selection = select_tests(repo, options, contexts_store=store_for(contexts_dir))

    assert selection.escalated
    assert selection.selected == ()


def test_a_docs_only_change_matches_no_context(repo: Path, contexts_dir: Path) -> None:
    write_contexts_baseline(
        baseline_path(contexts_dir, head(repo)),
        {"src/pkg/a.py": {"tests/test_a.py::test_x|run": [1]}},
    )
    (repo / "docs" / "development.md").write_text("# changed\n", encoding="utf-8")

    selection = select(repo, contexts_dir)

    assert selection.manifest["contexts"]["matched_files"] == []
    assert RULE_CONTEXT_SELECTION not in selection.rules
