"""Conformance checks every Artifacts pane adapter must satisfy.

This harness starts nearly empty on purpose. Later epic phases append
checks here; ``iter_conformance_cases`` parametrizes them over every
resolved sub-tab, including degraded and synthetic providers.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator

from sase.ace.tui._artifact_tab_actions import (
    CAPABILITY_HOST_ACTIONS,
    registered_host_actions,
)
from sase.ace.tui._artifact_tab_descriptors import _provider_accent_for_kind
from sase.ace.tui.artifact_tabs import (
    ARTIFACTS_ACCENTS,
    ArtifactsTabDescriptor,
    PaneCapability,
    resolve_artifacts_subtabs,
)
from sase.ace.tui.copy_targets import copy_target_for
from sase.ace.tui.widgets.artifacts.shell import build_degraded_card, build_shell_scope

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


def check_descriptor_owns_contract(descriptor: ArtifactsTabDescriptor) -> None:
    """Every resolved pane owns one compiled contract with a full verdict set."""
    contract = descriptor.contract
    assert contract is not None
    assert contract.id == descriptor.id
    assert contract.label == descriptor.label
    assert contract.digit == descriptor.digit_shortcut
    assert [verdict.capability for verdict in contract.verdicts] == list(PaneCapability)


def check_declared_actions_are_registered(descriptor: ArtifactsTabDescriptor) -> None:
    """Every ON capability maps to a registered host action or later-phase empty."""
    contract = descriptor.resolved_contract
    registered = registered_host_actions()
    for capability in contract.capabilities:
        actions = CAPABILITY_HOST_ACTIONS[capability]
        if capability in {
            PaneCapability.RELATIONS,
            PaneCapability.GROUPING,
            PaneCapability.STATUS_COUNTERS,
            PaneCapability.SHELL,
        }:
            assert actions == ()
            continue
        assert actions
        assert all(action in registered for action in actions)


def check_declared_copy_targets_are_registered(
    descriptor: ArtifactsTabDescriptor,
) -> None:
    """Every contract-declared copy target has a host implementation."""
    contract = descriptor.resolved_contract
    for target in contract.copy_targets:
        assert copy_target_for(contract.copy_group, target) is not None


def check_unavailable_actions_have_off_verdicts(
    descriptor: ArtifactsTabDescriptor,
) -> None:
    """Every OFF capability is explained by a named verdict."""
    contract = descriptor.resolved_contract
    for capability in PaneCapability:
        if capability in contract.capabilities:
            continue
        verdict = contract.verdict_for(capability)
        assert verdict is not None
        assert verdict.enabled is False
        assert verdict.rule


def check_pane_renders_shared_shell(descriptor: ArtifactsTabDescriptor) -> None:
    """Every descriptor renders through the shared shell from its contract.

    This never mounts a Textual widget or runs provider code; it proves the
    shell's pure Rich renderers can identify and (for a degraded tab)
    explain a pane using only the compiled contract/descriptor, with the
    descriptor's own accent rather than a hard-coded pane id lookup.
    """
    if descriptor.is_degraded:
        hero, card = build_degraded_card(
            provider_kind=descriptor.provider_kind or descriptor.id,
            provider_label=descriptor.label,
            error=descriptor.error or "Provider failed to load",
            error_code=descriptor.error_code,
            error_source=descriptor.error_source,
        )
        assert descriptor.label in hero.plain
        assert (descriptor.error or "Provider failed to load") in card.plain
        return
    contract = descriptor.resolved_contract
    header = build_shell_scope(
        label=contract.label,
        accent=contract.accent,
        scope_label="All projects",
    )
    assert contract.label in header.plain
    assert any(contract.accent in str(span.style) for span in header.spans)


PANE_CONFORMANCE_CHECKS: tuple[tuple[str, ConformanceCheck], ...] = (
    ("descriptor_identity", check_descriptor_identity),
    ("provider_accent_is_declared", check_provider_accent_is_declared),
    ("degraded_tab_carries_error", check_degraded_tab_carries_error),
    ("descriptor_owns_contract", check_descriptor_owns_contract),
    ("declared_actions_are_registered", check_declared_actions_are_registered),
    (
        "declared_copy_targets_are_registered",
        check_declared_copy_targets_are_registered,
    ),
    (
        "unavailable_actions_have_off_verdicts",
        check_unavailable_actions_have_off_verdicts,
    ),
    ("pane_renders_shared_shell", check_pane_renders_shared_shell),
)


def iter_conformance_cases() -> Iterator[tuple[str, str, ConformanceCheck]]:
    """Yield ``(pane_id, check_name, check)`` for every resolved sub-tab."""
    for descriptor in resolve_artifacts_subtabs():
        for name, check in PANE_CONFORMANCE_CHECKS:
            yield descriptor.id, name, check
