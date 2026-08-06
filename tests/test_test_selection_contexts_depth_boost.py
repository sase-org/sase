"""Unit tests for compensating for a baseline that is not there.

The fixture repository's import chain is ``a <- b <- c <- d``, so a change to
``src/pkg/a.py`` reaches ``tests/test_c.py`` at depth 2 and ``tests/test_d.py``
only at depth 3. That one file is the whole observable difference between
compensating and not, which is why every test below watches it.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from tests._test_selection_contexts import (
    CONTEXTS_MAX_DISTANCE_ENV,
    RULE_CONTEXT_BASELINE_MISSING,
    RULE_CONTEXT_BASELINE_STALE,
    baseline_path,
)
from tests._test_selection_contexts_helpers import (
    contexts_dir_fixture,  # noqa: F401 (imported for fixture discovery)
    head,
    repo_fixture,  # noqa: F401 (imported for fixture discovery)
    select,
)
from tests._test_selection_fixtures import _git, _write, write_contexts_baseline
from tests._test_selection_rules import (
    FULL_SUITE_RULES,
    RULE_NO_BASELINE_DEPTH_BOOST,
)


def test_no_baseline_buys_the_closure_an_extra_hop(
    repo: Path, contexts_dir: Path
) -> None:
    _write(repo, "src/pkg/a.py", "VALUE = 2\n")

    selection = select(repo, contexts_dir)

    assert RULE_CONTEXT_BASELINE_MISSING in selection.rules
    assert RULE_NO_BASELINE_DEPTH_BOOST in selection.rules
    assert selection.manifest["effective_depth"] == 3
    assert "tests/test_d.py" in selection.selected


def test_a_fresh_baseline_spends_no_extra_hop(repo: Path, contexts_dir: Path) -> None:
    """Ground truth is present, so the closure has no gap to compensate for."""
    write_contexts_baseline(baseline_path(contexts_dir, head(repo)), {})
    _write(repo, "src/pkg/a.py", "VALUE = 2\n")

    selection = select(repo, contexts_dir)

    assert RULE_NO_BASELINE_DEPTH_BOOST not in selection.rules
    assert selection.manifest["effective_depth"] == 2
    assert "tests/test_c.py" in selection.selected
    assert "tests/test_d.py" not in selection.selected


def test_a_stale_baseline_buys_the_hop_as_well(
    repo: Path, contexts_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Stale rows describe code that has since moved; they are not ground truth.

    The baseline is still queried and still contributes — see
    ``test_a_stale_baseline_is_used_and_flagged`` in
    ``tests/test_test_selection_contexts_selection.py`` — but it no longer
    counts as the second source that lets the closure stay shallow.
    """
    write_contexts_baseline(baseline_path(contexts_dir, head(repo)), {})
    _git(repo, "commit", "-q", "--allow-empty", "-m", "move on")
    monkeypatch.setenv(CONTEXTS_MAX_DISTANCE_ENV, "0")
    _write(repo, "src/pkg/a.py", "VALUE = 2\n")

    selection = select(repo, contexts_dir)

    assert RULE_CONTEXT_BASELINE_STALE in selection.rules
    assert RULE_NO_BASELINE_DEPTH_BOOST in selection.rules
    assert selection.manifest["effective_depth"] == 3


def test_the_depth_boost_widens_instead_of_escalating(
    repo: Path, contexts_dir: Path
) -> None:
    """The compensation must never be a full-suite rule.

    A workspace that is offline, or idle past the CI artifact's retention, has
    no baseline for as long as that lasts — so escalating on absence turns a
    persistent condition into a permanently full lane. The extra hop buys back
    a measured 91% of the closure's blind spot instead, for roughly double the
    selected files rather than the whole suite.
    """
    _write(repo, "src/pkg/a.py", "VALUE = 2\n")

    selection = select(repo, contexts_dir)

    assert RULE_NO_BASELINE_DEPTH_BOOST not in FULL_SUITE_RULES
    assert not selection.escalated


def test_the_boost_composes_with_the_rename_hop(repo: Path, contexts_dir: Path) -> None:
    """Two independent compensations, two hops — not one shared bump."""
    _git(repo, "rm", "-q", "src/pkg/hub.py")
    _write(repo, "src/pkg/a.py", "VALUE = 2\n")

    selection = select(repo, contexts_dir)

    assert selection.manifest["effective_depth"] == 4
