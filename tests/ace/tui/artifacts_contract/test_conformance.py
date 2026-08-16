"""Parametrized conformance suite over every resolved Artifacts sub-tab."""

from __future__ import annotations

import pytest

from sase.ace.tui.artifact_tabs import ArtifactsTabDescriptor, resolve_artifacts_subtabs

from .harness import PANE_CONFORMANCE_CHECKS, ConformanceCheck


def test_conformance_harness_is_registered() -> None:
    """The suite exists from day one so later phases can extend it."""
    assert PANE_CONFORMANCE_CHECKS
    assert resolve_artifacts_subtabs()


def _collected_conformance_cases() -> list[
    tuple[ArtifactsTabDescriptor, str, ConformanceCheck]
]:
    """Bind checks to the descriptors collected with this module.

    Later tests may reset the subtab cache; collected descriptors stay
    stable so the matrix does not KeyError mid-session.
    """
    return [
        (descriptor, name, check)
        for descriptor in resolve_artifacts_subtabs()
        for name, check in PANE_CONFORMANCE_CHECKS
    ]


_CONFORMANCE_CASES = _collected_conformance_cases()


@pytest.mark.parametrize(
    ("descriptor", "check_name", "check"),
    _CONFORMANCE_CASES,
    ids=[
        f"{descriptor.id}:{check_name}"
        for descriptor, check_name, _check in _CONFORMANCE_CASES
    ],
)
def test_artifacts_pane_conformance(
    descriptor: ArtifactsTabDescriptor,
    check_name: str,
    check: ConformanceCheck,
) -> None:
    """Run every registered check against every resolved sub-tab."""
    del check_name
    check(descriptor)
