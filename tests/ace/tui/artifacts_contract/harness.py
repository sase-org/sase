"""Conformance checks every Artifacts pane adapter must satisfy.

This harness starts nearly empty on purpose. Later epic phases append
checks here; ``iter_conformance_cases`` parametrizes them over every
resolved sub-tab, including degraded and synthetic providers.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator

from sase.ace.tui._artifact_tab_descriptors import _provider_accent_for_kind
from sase.ace.tui.artifact_tabs import (
    ARTIFACTS_ACCENTS,
    ArtifactsTabDescriptor,
    resolve_artifacts_subtabs,
)

ConformanceCheck = Callable[[ArtifactsTabDescriptor], None]


def check_descriptor_identity(descriptor: ArtifactsTabDescriptor) -> None:
    """Every pane has a stable id, label, accent, and mounted pane id."""
    assert descriptor.id
    assert descriptor.label
    assert descriptor.accent
    assert descriptor.pane_id


def check_provider_accent_is_declared(descriptor: ArtifactsTabDescriptor) -> None:
    """Provider accents come from the hash/pin helper, never a module write."""
    if descriptor.provider_kind is None:
        return
    assert descriptor.accent == _provider_accent_for_kind(descriptor.provider_kind)
    if not descriptor.is_degraded:
        assert f"ref:{descriptor.provider_kind}" not in ARTIFACTS_ACCENTS or (
            ARTIFACTS_ACCENTS.get(f"ref:{descriptor.provider_kind}")
            == descriptor.accent
        )


def check_degraded_tab_carries_error(descriptor: ArtifactsTabDescriptor) -> None:
    """A degraded tab stays named and carries the failure that produced it."""
    if not descriptor.is_degraded:
        assert descriptor.error is None
        return
    assert descriptor.error
    assert descriptor.error_code
    assert descriptor.label


PANE_CONFORMANCE_CHECKS: tuple[tuple[str, ConformanceCheck], ...] = (
    ("descriptor_identity", check_descriptor_identity),
    ("provider_accent_is_declared", check_provider_accent_is_declared),
    ("degraded_tab_carries_error", check_degraded_tab_carries_error),
)


def iter_conformance_cases() -> Iterator[tuple[str, str, ConformanceCheck]]:
    """Yield ``(pane_id, check_name, check)`` for every resolved sub-tab."""
    for descriptor in resolve_artifacts_subtabs():
        for name, check in PANE_CONFORMANCE_CHECKS:
            yield descriptor.id, name, check
