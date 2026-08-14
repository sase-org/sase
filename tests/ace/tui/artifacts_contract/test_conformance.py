"""Parametrized conformance suite over every resolved Artifacts sub-tab."""

from __future__ import annotations

from sase.ace.tui.artifact_tabs import resolve_artifacts_subtabs

from .harness import PANE_CONFORMANCE_CHECKS, iter_conformance_cases


def test_conformance_harness_is_registered() -> None:
    """The suite exists from day one so later phases can extend it."""
    assert PANE_CONFORMANCE_CHECKS
    assert resolve_artifacts_subtabs()


def test_artifacts_pane_conformance() -> None:
    """Run every registered check against the tabs resolved for this process."""
    cases = list(iter_conformance_cases())
    assert cases
    descriptors = {item.id: item for item in resolve_artifacts_subtabs()}
    for pane_id, _check_name, check in cases:
        check(descriptors[pane_id])
