"""Unit tests for how a run reports what it did with contexts.

A run a rule forces to the full suite never reaches the baseline cache. The
distinction matters because every reader of the ``contexts`` block — the scoped
summary line, ``--explain``, and ``just selection-health``'s exposure count —
would otherwise report an escalated run as one that narrowed on the static
closure alone, which is the opposite of what it did.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from tests._test_selection_contexts import (
    RULE_CONTEXT_BASELINE_MISSING,
    ContextSelection,
    baseline_path,
    contexts_consulted,
)
from tests._test_selection_contexts_helpers import (
    contexts_dir_fixture,  # noqa: F401 (imported for fixture discovery)
    head,
    repo_fixture,  # noqa: F401 (imported for fixture discovery)
    select,
)
from tests._test_selection_fixtures import _write, write_contexts_baseline
from tests._test_selection_report import context_line


# --------------------------------------------------------------------------
# Consulted, versus missing
# --------------------------------------------------------------------------


def test_a_forced_full_suite_run_records_that_it_never_consulted_contexts(
    repo: Path, contexts_dir: Path
) -> None:
    write_contexts_baseline(baseline_path(contexts_dir, head(repo)), {})
    _write(repo, "Justfile", "recipe:\n    @true\n")

    selection = select(repo, contexts_dir)

    assert selection.escalated
    assert selection.contexts.consulted is False
    assert selection.manifest["contexts"]["consulted"] is False
    # Not charged with an absence: a baseline was cached and usable the whole
    # time; this run simply had no narrower selection to improve.
    assert RULE_CONTEXT_BASELINE_MISSING not in selection.rules


def test_a_scoped_run_records_that_it_did_consult_contexts(
    repo: Path, contexts_dir: Path
) -> None:
    _write(repo, "src/pkg/a.py", "VALUE = 2\n")

    selection = select(repo, contexts_dir)

    assert not selection.escalated
    assert selection.contexts.consulted is True
    assert selection.manifest["contexts"]["consulted"] is True
    assert RULE_CONTEXT_BASELINE_MISSING in selection.rules


@pytest.mark.parametrize(
    ("payload", "escalated", "expected"),
    [
        ({"consulted": False, "baseline": None}, True, False),
        ({"consulted": True, "baseline": None}, True, True),
        ({"consulted": True, "baseline": "abc"}, False, True),
        # Pre-schema-4 records carry no flag. An escalated one with no baseline
        # is the forced-full-suite shape, because a ratio escalation consults
        # contexts first and keeps whatever baseline it resolved.
        ({"baseline": None}, True, False),
        ({"baseline": "abc"}, True, True),
        ({"baseline": None}, False, True),
        ({}, False, True),
    ],
)
def test_contexts_consulted_reads_old_and_new_records(
    payload: dict[str, object], escalated: bool, expected: bool
) -> None:
    assert contexts_consulted(payload, escalated=escalated) is expected


# --------------------------------------------------------------------------
# The summary line
# --------------------------------------------------------------------------


def test_context_line_names_the_missing_baseline_remedy() -> None:
    line = context_line(ContextSelection())

    assert "no baseline cached" in line
    assert "refresh-contexts-baseline" in line


def test_context_line_does_not_prescribe_a_baseline_it_never_looked_for() -> None:
    line = context_line(ContextSelection(consulted=False))

    assert "not consulted" in line
    assert "refresh-contexts-baseline" not in line


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
