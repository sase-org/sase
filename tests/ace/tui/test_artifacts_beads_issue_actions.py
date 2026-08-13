"""External issue action helpers for Artifacts Beads."""

from __future__ import annotations

from sase.ace.tui.actions._artifacts_beads_issue_mutations import (
    _refs_with_canonical_bug_ref,
)


def test_refs_with_canonical_bug_ref_appends_once_and_preserves_order() -> None:
    refs = ("plan:202608/beads.md",)

    updated = _refs_with_canonical_bug_ref(refs, "bug:alpha#42", "alpha")
    repeated = _refs_with_canonical_bug_ref(updated, "bug:alpha#42", "alpha")

    assert updated == ("plan:202608/beads.md", "bug:alpha#42")
    assert repeated == updated


def test_refs_with_canonical_bug_ref_deduplicates_equivalent_refs() -> None:
    updated = _refs_with_canonical_bug_ref(["bug:alpha#42"], "bug:alpha#42", "alpha")

    assert updated == ("bug:alpha#42",)
