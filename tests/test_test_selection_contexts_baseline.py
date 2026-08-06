"""Unit tests for choosing which cached baseline a scoped run should read.

Resolution is a ranking problem, not a lookup: several databases can all be
ancestors of ``HEAD``, and the useful one is not always the nearest or the
newest. What the winner then contributes to a selection is
``tests/test_test_selection_contexts_selection.py``'s subject.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests._test_selection_contexts import (
    CONTEXTS_DIR_ENV,
    RULE_CONTEXT_BASELINE_MISSING,
    baseline_path,
    breadth_path,
    cached_baselines,
    measure_breadth,
    prune_baselines,
    resolve_baseline,
    select_from_contexts,
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
    selection = select(repo, contexts_dir)

    assert RULE_CONTEXT_BASELINE_MISSING in selection.rules
    assert selection.manifest["contexts"]["baseline"] is None


def test_the_contexts_directory_env_var_overrides_the_store(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    write_contexts_baseline(baseline_path(elsewhere, head(repo)), {})
    monkeypatch.setenv(CONTEXTS_DIR_ENV, str(elsewhere))

    result = select_from_contexts(
        repo,
        store=tmp_path / "unused",
        changed_paths=(),
        known_test_files=frozenset(),
    )

    assert result.baseline_sha == head(repo)


def test_an_ancestor_baseline_wins_over_an_unrelated_one(
    repo: Path, contexts_dir: Path
) -> None:
    add_dynamic_pair(repo)
    ancestor = head(repo)
    write_contexts_baseline(baseline_path(contexts_dir, ancestor), {})
    write_contexts_baseline(baseline_path(contexts_dir, "0" * 40), {})

    result = select_from_contexts(
        repo,
        store=store_for(contexts_dir),
        changed_paths=(),
        known_test_files=frozenset(),
    )

    assert result.baseline_sha == ancestor


# --------------------------------------------------------------------------
# Breadth
# --------------------------------------------------------------------------
#
# Two databases can both be complete runs of the whole suite at ancestors of
# HEAD and still hold wildly different amounts of ground truth — coverage's
# `sysmon` core credits only the first test to reach a line, `ctrace` credits
# every one. Ranking on recency alone cannot tell them apart, and the thin one
# is usually the newer, because it is the locally recorded one.


def _write_broad_baseline(path: Path, contexts: int) -> None:
    """A baseline attributing ``src/pkg/dynamic.py`` to ``contexts`` test files."""
    write_contexts_baseline(
        path,
        {
            "src/pkg/dynamic.py": {
                f"tests/test_dynamic.py::test_{index}|run": [1]
                for index in range(contexts)
            }
        },
    )


def test_measure_breadth_counts_what_a_database_attributes(tmp_path: Path) -> None:
    database = tmp_path / "baseline.sqlite"
    _write_broad_baseline(database, contexts=4)

    breadth = measure_breadth(database)

    assert breadth is not None
    # Four contexts over `dynamic.py`, plus the fixture's placeholder row over
    # `never_changed.py`: five contexts, five pairs, two measured files.
    assert (breadth.contexts, breadth.attributions, breadth.files) == (5, 5, 2)
    assert breadth.density == 2.5


def test_measure_breadth_reports_an_unreadable_database_as_unmeasurable(
    tmp_path: Path,
) -> None:
    database = tmp_path / "broken.sqlite"
    database.write_text("not a database", encoding="utf-8")

    assert measure_breadth(database) is None


def test_a_thin_baseline_does_not_displace_a_broader_ancestor(
    repo: Path, contexts_dir: Path
) -> None:
    """The regression this ranking exists for, in miniature.

    Both baselines are ancestors of ``HEAD`` and the thin one is both nearer and
    newer, which is exactly the shape that used to win.
    """
    add_dynamic_pair(repo)
    broad = head(repo)
    _git(repo, "commit", "-q", "--allow-empty", "-m", "move on")
    thin = head(repo)
    _write_broad_baseline(baseline_path(contexts_dir, broad), contexts=20)
    _write_broad_baseline(baseline_path(contexts_dir, thin), contexts=1)

    resolved = resolve_baseline(repo, contexts_dir)

    assert resolved is not None
    assert resolved.sha == broad


def test_the_nearest_ancestor_wins_when_breadth_is_comparable(
    repo: Path, contexts_dir: Path
) -> None:
    """Breadth gates; distance decides. Recency of the *file* decides nothing."""
    add_dynamic_pair(repo)
    older = head(repo)
    _git(repo, "commit", "-q", "--allow-empty", "-m", "move on")
    nearer = head(repo)
    _write_broad_baseline(baseline_path(contexts_dir, nearer), contexts=20)
    # Written last, so it holds the newest mtime by some margin.
    _write_broad_baseline(baseline_path(contexts_dir, older), contexts=20)

    resolved = resolve_baseline(repo, contexts_dir)

    assert resolved is not None
    assert resolved.sha == nearer


def test_an_unreadable_baseline_never_displaces_a_readable_one(
    repo: Path, contexts_dir: Path
) -> None:
    """A database that measures as nothing contributes nothing when read, too."""
    add_dynamic_pair(repo)
    readable = head(repo)
    _write_broad_baseline(baseline_path(contexts_dir, readable), contexts=4)
    _git(repo, "commit", "-q", "--allow-empty", "-m", "move on")
    baseline_path(contexts_dir, head(repo)).write_text("junk", encoding="utf-8")

    resolved = resolve_baseline(repo, contexts_dir)

    assert resolved is not None
    assert resolved.sha == readable


def test_breadth_is_measured_once_and_reused_from_the_sidecar(
    contexts_dir: Path,
) -> None:
    """Every scoped run resolves the cache; none of them re-counts 50 MB of rows."""
    database = baseline_path(contexts_dir, "0" * 40)
    _write_broad_baseline(database, contexts=4)
    cached_baselines(contexts_dir)

    sidecar = json.loads(breadth_path(database).read_text(encoding="utf-8"))
    sidecar["attributions"] = 4321
    breadth_path(database).write_text(json.dumps(sidecar), encoding="utf-8")

    breadth = cached_baselines(contexts_dir)[0].breadth
    assert breadth is not None
    assert breadth.attributions == 4321


def test_a_re_recorded_database_is_measured_again(contexts_dir: Path) -> None:
    """`just test-contexts` re-records the same SHA; stale numbers would stick."""
    database = baseline_path(contexts_dir, "0" * 40)
    _write_broad_baseline(database, contexts=1)
    thin = cached_baselines(contexts_dir)[0].breadth
    database.unlink()
    _write_broad_baseline(database, contexts=20)

    reread = cached_baselines(contexts_dir)[0].breadth

    assert thin is not None and reread is not None
    assert reread.attributions > thin.attributions


def test_pruning_takes_the_breadth_sidecar_with_the_database(
    contexts_dir: Path,
) -> None:
    """A sidecar outliving its database would describe whatever lands next."""
    for index in range(3):
        _write_broad_baseline(baseline_path(contexts_dir, f"{index:040x}"), contexts=2)
    cached_baselines(contexts_dir)

    prune_baselines(contexts_dir, keep=1)

    survivor = cached_baselines(contexts_dir)[0]
    assert sorted(entry.name for entry in contexts_dir.iterdir()) == sorted(
        [survivor.path.name, breadth_path(survivor.path).name]
    )
