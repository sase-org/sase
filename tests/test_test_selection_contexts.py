"""Unit tests for coverage-context ground truth in the diff-scoped selector.

Every assertion runs against the synthetic repository from
``tests._test_selection_fixtures`` and a coverage database this module builds
itself, so nothing here depends on the real repository's import graph or on a
baseline downloaded from CI.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from coverage import CoverageData

from tests._test_selection import (
    Selection,
    SelectionOptions,
    select_tests,
)
from tests._test_selection_contexts import (
    CONTEXTS_DIR_ENV,
    CONTEXTS_DISABLED_ENV,
    CONTEXTS_MAX_DISTANCE_ENV,
    RULE_CONTEXT_BASELINE_MISSING,
    RULE_CONTEXT_BASELINE_STALE,
    RULE_CONTEXT_SELECTION,
    ContextSelection,
    baseline_changed_lines,
    baseline_path,
    cached_baselines,
    context_test_file,
    find_tests_touching,
    normalize_measured_file,
    parse_baseline_lines,
    select_from_contexts,
)
from tests._test_selection_fixtures import _git, _write, build_fixture_repo
from tests._test_selection_report import context_line


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    return build_fixture_repo(tmp_path)


@pytest.fixture
def contexts_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "store" / "contexts"
    directory.mkdir(parents=True)
    return directory


def _store_for(contexts_dir: Path) -> Path:
    """The health store whose sibling ``contexts/`` directory is ``contexts_dir``."""
    return contexts_dir.parent / "project"


def _write_baseline(path: Path, coverage_map: dict[str, dict[str, list[int]]]) -> None:
    """Write a coverage database recording ``{file: {context: lines}}``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = CoverageData(basename=str(path))
    # An always-present row keeps the database on disk even when the caller
    # only cares that *a* baseline exists.
    data.set_context("tests/test_placeholder.py::test_placeholder|run")
    data.add_lines({"src/pkg/never_changed.py": [1]})
    for measured_file, contexts in coverage_map.items():
        for context, lines in contexts.items():
            data.set_context(context)
            data.add_lines({measured_file: lines})
    data.write()


def _head(repo: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def _add_dynamic_pair(repo: Path) -> None:
    """Add a src module and a test that never imports it, then commit both.

    This is the shape the static closure cannot see: the test reaches the
    module through something an ``import`` statement does not name.
    """
    _write(repo, "src/pkg/dynamic.py", "VALUE = 1\n")
    _write(repo, "tests/test_dynamic.py", "def test_it() -> None:\n    pass\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "dynamic pair")


def _select(repo: Path, contexts_dir: Path, **kwargs: object) -> Selection:
    options = SelectionOptions(base_ref="HEAD", depth=2, max_ratio=1.0)
    return select_tests(
        repo,
        options,
        contexts_store=_store_for(contexts_dir),
        **kwargs,  # type: ignore[arg-type]
    )


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

    lines = baseline_changed_lines(repo, _head(repo), ["src/pkg/a.py"])

    assert lines["src/pkg/a.py"] == {1}


def test_baseline_changed_lines_ignores_files_outside_the_change_set(
    repo: Path,
) -> None:
    """Between the baseline and the merge base, other people changed other files."""
    (repo / "src" / "pkg" / "a.py").write_text("VALUE = 2\n", encoding="utf-8")
    (repo / "src" / "pkg" / "hub.py").write_text("HUB = 2\n", encoding="utf-8")

    lines = baseline_changed_lines(repo, _head(repo), ["src/pkg/a.py"])

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
    _write_baseline(
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


# --------------------------------------------------------------------------
# Baseline resolution
# --------------------------------------------------------------------------


def test_cached_baselines_ignores_unfamiliar_files(contexts_dir: Path) -> None:
    (contexts_dir / "0123456789abcdef.sqlite").write_bytes(b"")
    (contexts_dir / "notes.txt").write_text("hello", encoding="utf-8")
    (contexts_dir / "not-a-sha.sqlite").write_bytes(b"")

    assert [baseline.sha for baseline in cached_baselines(contexts_dir)] == [
        "0123456789abcdef"
    ]


def test_a_missing_baseline_is_recorded_not_raised(
    repo: Path, contexts_dir: Path
) -> None:
    selection = _select(repo, contexts_dir)

    assert RULE_CONTEXT_BASELINE_MISSING in selection.rules
    assert selection.manifest["contexts"]["baseline"] is None


def test_the_contexts_directory_env_var_overrides_the_store(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    _write_baseline(baseline_path(elsewhere, _head(repo)), {})
    monkeypatch.setenv(CONTEXTS_DIR_ENV, str(elsewhere))

    result = select_from_contexts(
        repo,
        store=tmp_path / "unused",
        changed_paths=(),
        known_test_files=frozenset(),
    )

    assert result.baseline_sha == _head(repo)


# --------------------------------------------------------------------------
# Selection
# --------------------------------------------------------------------------


def test_contexts_select_a_test_the_static_closure_cannot_reach(
    repo: Path, contexts_dir: Path
) -> None:
    _add_dynamic_pair(repo)
    _write_baseline(
        baseline_path(contexts_dir, _head(repo)),
        {"src/pkg/dynamic.py": {"tests/test_dynamic.py::test_it|run": [1]}},
    )
    (repo / "src" / "pkg" / "dynamic.py").write_text("VALUE = 2\n", encoding="utf-8")

    with_contexts = _select(repo, contexts_dir)

    assert "tests/test_dynamic.py" in with_contexts.selected
    assert RULE_CONTEXT_SELECTION in with_contexts.rules
    assert with_contexts.contexts.matched_files == ("src/pkg/dynamic.py",)


def test_disabling_contexts_loses_that_test_again(
    repo: Path, contexts_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _add_dynamic_pair(repo)
    _write_baseline(
        baseline_path(contexts_dir, _head(repo)),
        {"src/pkg/dynamic.py": {"tests/test_dynamic.py::test_it|run": [1]}},
    )
    (repo / "src" / "pkg" / "dynamic.py").write_text("VALUE = 2\n", encoding="utf-8")
    monkeypatch.setenv(CONTEXTS_DISABLED_ENV, "1")

    assert "tests/test_dynamic.py" not in _select(repo, contexts_dir).selected


def test_contexts_union_the_static_closure_rather_than_replacing_it(
    repo: Path, contexts_dir: Path
) -> None:
    _add_dynamic_pair(repo)
    _write_baseline(
        baseline_path(contexts_dir, _head(repo)),
        {"src/pkg/dynamic.py": {"tests/test_dynamic.py::test_it|run": [1]}},
    )
    (repo / "src" / "pkg" / "dynamic.py").write_text("VALUE = 2\n", encoding="utf-8")
    (repo / "src" / "pkg" / "a.py").write_text("VALUE = 2\n", encoding="utf-8")

    selected = _select(repo, contexts_dir).selected

    # The closure's own answer for `pkg.a` survives alongside the context hit.
    assert "tests/test_dynamic.py" in selected
    assert "tests/test_a.py" in selected


def test_contexts_never_return_a_visual_test(repo: Path, contexts_dir: Path) -> None:
    _write_baseline(
        baseline_path(contexts_dir, _head(repo)),
        {
            "src/pkg/a.py": {
                "tests/ace/tui/visual/test_visual.py::test_v|run": [1],
            }
        },
    )
    (repo / "src" / "pkg" / "a.py").write_text("VALUE = 2\n", encoding="utf-8")

    selection = _select(repo, contexts_dir)

    assert not any(
        path.startswith("tests/ace/tui/visual/") for path in selection.selected
    )


def test_contexts_ignore_a_test_file_deleted_since_the_baseline(
    repo: Path, contexts_dir: Path
) -> None:
    _write_baseline(
        baseline_path(contexts_dir, _head(repo)),
        {"src/pkg/a.py": {"tests/test_since_deleted.py::test_x|run": [1]}},
    )
    (repo / "src" / "pkg" / "a.py").write_text("VALUE = 2\n", encoding="utf-8")

    selection = _select(repo, contexts_dir)

    assert "tests/test_since_deleted.py" not in selection.selected
    assert RULE_CONTEXT_SELECTION not in selection.rules


def test_a_stale_baseline_is_used_and_flagged(
    repo: Path, contexts_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _add_dynamic_pair(repo)
    baseline_sha = _head(repo)
    _write_baseline(
        baseline_path(contexts_dir, baseline_sha),
        {"src/pkg/dynamic.py": {"tests/test_dynamic.py::test_it|run": [1]}},
    )
    _git(repo, "commit", "-q", "--allow-empty", "-m", "move on")
    (repo / "src" / "pkg" / "dynamic.py").write_text("VALUE = 2\n", encoding="utf-8")
    monkeypatch.setenv(CONTEXTS_MAX_DISTANCE_ENV, "0")

    selection = _select(repo, contexts_dir)

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
    _add_dynamic_pair(repo)
    _write_baseline(
        baseline_path(contexts_dir, "0" * 40),
        {"src/pkg/dynamic.py": {"tests/test_dynamic.py::test_it|run": [1]}},
    )
    (repo / "src" / "pkg" / "dynamic.py").write_text("VALUE = 2\n", encoding="utf-8")

    selection = _select(repo, contexts_dir)

    assert RULE_CONTEXT_BASELINE_STALE in selection.rules
    assert selection.manifest["contexts"]["distance"] is None
    assert selection.contexts.selected == ()


def test_a_file_added_since_the_baseline_contributes_no_contexts(
    repo: Path, contexts_dir: Path
) -> None:
    """A module the baseline never measured has no rows to find."""
    baseline_sha = _head(repo)
    _add_dynamic_pair(repo)
    _write_baseline(
        baseline_path(contexts_dir, baseline_sha),
        {"src/pkg/dynamic.py": {"tests/test_dynamic.py::test_it|run": [1]}},
    )
    (repo / "src" / "pkg" / "dynamic.py").write_text("VALUE = 2\n", encoding="utf-8")

    selection = _select(repo, contexts_dir)

    assert selection.contexts.selected == ()
    assert RULE_CONTEXT_SELECTION not in selection.rules


def test_an_ancestor_baseline_wins_over_an_unrelated_one(
    repo: Path, contexts_dir: Path
) -> None:
    _add_dynamic_pair(repo)
    ancestor = _head(repo)
    _write_baseline(baseline_path(contexts_dir, ancestor), {})
    _write_baseline(baseline_path(contexts_dir, "0" * 40), {})

    result = select_from_contexts(
        repo,
        store=_store_for(contexts_dir),
        changed_paths=(),
        known_test_files=frozenset(),
    )

    assert result.baseline_sha == ancestor


def test_contexts_can_push_a_selection_over_the_escalation_ratio(
    repo: Path, contexts_dir: Path
) -> None:
    _add_dynamic_pair(repo)
    _write_baseline(
        baseline_path(contexts_dir, _head(repo)),
        {"src/pkg/dynamic.py": {"tests/test_dynamic.py::test_it|run": [1]}},
    )
    (repo / "src" / "pkg" / "dynamic.py").write_text("VALUE = 2\n", encoding="utf-8")

    options = SelectionOptions(base_ref="HEAD", depth=2, max_ratio=0.001)
    selection = select_tests(repo, options, contexts_store=_store_for(contexts_dir))

    assert selection.escalated
    assert selection.selected == ()


def test_a_docs_only_change_matches_no_context(repo: Path, contexts_dir: Path) -> None:
    _write_baseline(
        baseline_path(contexts_dir, _head(repo)),
        {"src/pkg/a.py": {"tests/test_a.py::test_x|run": [1]}},
    )
    (repo / "docs" / "development.md").write_text("# changed\n", encoding="utf-8")

    selection = _select(repo, contexts_dir)

    assert selection.manifest["contexts"]["matched_files"] == []
    assert RULE_CONTEXT_SELECTION not in selection.rules


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------


def test_context_line_names_the_missing_baseline_remedy() -> None:
    line = context_line(ContextSelection())

    assert "no baseline cached" in line
    assert "refresh-contexts-baseline" in line


def test_context_line_reports_freshness_and_yield() -> None:
    line = context_line(
        ContextSelection(
            selected=("tests/test_a.py",),
            baseline_sha="0123456789abcdef",
            stale=True,
            distance=87,
            matched_files=("src/pkg/a.py",),
        )
    )

    assert "0123456789ab" in line
    assert "stale" in line
    assert "87 commits" in line
    assert "1 test file(s)" in line
