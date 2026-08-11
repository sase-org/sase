"""External issue action helpers for Artifacts Beads."""

from __future__ import annotations

from unittest.mock import Mock

from sase.ace.tui.actions._artifacts_beads_issue_mutations import (
    _attach_external_ref,
    _refs_with_canonical_bug_ref,
)
from sase.bead.model import Issue


def test_refs_with_canonical_bug_ref_appends_once_and_preserves_order() -> None:
    refs = ("plans:202608/beads.md",)

    updated = _refs_with_canonical_bug_ref(
        refs,
        "bug:alpha#42",
        "alpha",
        display_project="alpha",
    )
    repeated = _refs_with_canonical_bug_ref(
        updated,
        "bug:alpha#42",
        "alpha",
        display_project="alpha",
    )

    assert updated == ("plans:202608/beads.md", "bug:alpha#42")
    assert repeated == updated


def test_refs_with_canonical_bug_ref_deduplicates_equivalent_refs() -> None:
    updated = _refs_with_canonical_bug_ref(
        ["bug:alpha#42"],
        "bug:alpha#42",
        "alpha",
        display_project="alpha",
    )

    assert updated == ("bug:alpha#42",)


def test_refs_with_canonical_bug_ref_appends_display_project_name() -> None:
    updated = _refs_with_canonical_bug_ref(
        [],
        "bug:gh_acme__widgets#42",
        "gh_acme__widgets",
        display_project="widgets",
    )

    assert updated == ("bug:widgets#42",)


def test_attach_external_ref_separates_display_ref_from_stable_identity() -> None:
    project = Mock()
    issue = Issue("sase-task", "Task")
    project.update.return_value = issue

    result = _attach_external_ref(
        project,
        issue,
        "bug:gh_acme__widgets#42",
        "gh_acme__widgets",
        "widgets",
    )

    assert result is issue
    project.update.assert_called_once_with(
        issue.id,
        refs=["bug:widgets#42"],
        external_ref="bug:gh_acme__widgets#42",
    )
