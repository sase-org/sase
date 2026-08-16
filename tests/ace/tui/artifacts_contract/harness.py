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
from sase.ace.tui._app_action_availability import check_app_action
from sase.ace.tui._artifact_tab_descriptors import _provider_accent_for_kind
from sase.ace.tui._artifact_tab_model import ArtifactsPaneContract
from sase.ace.tui.artifact_tabs import (
    ARTIFACTS_ACCENTS,
    ArtifactsTabDescriptor,
    PaneCapability,
    resolve_artifacts_subtabs,
)
from sase.ace.tui.copy_targets import copy_target_for
from sase.ace.tui.models.artifact_groups import build_grouped_rows
from sase.ace.tui.models.group_fold import GroupFoldRegistry
from sase.ace.tui.widgets.artifacts.shell import build_degraded_card, build_shell_scope
from sase.core.artifact_entry_target import ArtifactEntryTarget
from sase.core.artifact_relations import RelationEdge, build_relation_index

ConformanceCheck = Callable[[ArtifactsTabDescriptor], None]

_RELATION_REACHABILITY_ACTIONS = frozenset(
    {
        "start_ancestor_mode",
        "start_child_mode",
        "start_sibling_mode",
        "beads_open_plan",
        "plans_open_bead",
    }
)
_GROUPING_REACHABILITY_ACTIONS = frozenset(
    {
        "expand_or_layout",
        "hooks_or_collapse",
        "hooks_or_collapse_all",
        "expand_all_folds",
        "cycle_grouping_mode",
        "cycle_grouping_mode_reverse",
    }
)


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
        if capability in {PaneCapability.STATUS_COUNTERS, PaneCapability.SHELL}:
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


def check_declared_relation_edges_resolve(
    descriptor: ArtifactsTabDescriptor,
) -> None:
    """Every declared relation can produce a resolved target or diagnostic."""
    contract = descriptor.resolved_contract
    if not contract.has(PaneCapability.RELATIONS):
        assert contract.relations == ()
        return
    assert contract.relations
    origin = ArtifactEntryTarget(contract.id, ("origin",))
    known_targets = {origin}
    for relation in contract.relations:
        target = ArtifactEntryTarget(
            relation.target_pane or contract.id,
            ("target", relation.name),
        )
        if target.pane_id == contract.id:
            known_targets.add(target)
        index = build_relation_index(
            pane_id=contract.id,
            relations=contract.relations,
            edges=(
                RelationEdge(
                    kind=relation.kind,
                    relation=relation.name,
                    label=relation.label,
                    source=origin,
                    target=target,
                ),
            ),
            known_targets=frozenset(known_targets),
        )
        resolved = index.edges_for_relation(origin, relation.name)
        diagnostics = tuple(
            item for item in index.diagnostics if item.relation == relation.name
        )
        assert resolved or diagnostics
        assert not any(item.code == "undeclared_relation" for item in diagnostics)


def check_declared_grouping_banners_are_navigable(
    descriptor: ArtifactsTabDescriptor,
) -> None:
    """Declared grouping modes emit foldable banner targets."""
    contract = descriptor.resolved_contract
    if not contract.has(PaneCapability.GROUPING):
        assert contract.grouping.modes == ()
        return
    assert contract.grouping.modes
    for mode in contract.grouping.modes:
        items = _grouping_sample_items(mode.keys)
        expanded = build_grouped_rows(
            items,
            pane_id=contract.id,
            mode_id=mode.id,
            keys=mode.keys,
            key_values=lambda item: item,
            label_for=lambda _level, value: value,
            target_for=lambda item: ArtifactEntryTarget(contract.id, ("row", *item)),
        )
        banners = tuple(row.banner for row in expanded.rows if row.banner is not None)
        assert banners
        first = banners[0]
        assert first.target in {banner.target for banner in banners}
        registry = GroupFoldRegistry()
        assert registry.collapse(first.group_key)
        collapsed = build_grouped_rows(
            items,
            pane_id=contract.id,
            mode_id=mode.id,
            keys=mode.keys,
            key_values=lambda item: item,
            label_for=lambda _level, value: value,
            target_for=lambda item: ArtifactEntryTarget(contract.id, ("row", *item)),
            fold_registry=registry,
        )
        collapsed_banners = tuple(
            row.banner for row in collapsed.rows if row.banner is not None
        )
        assert any(
            banner.group_key == first.group_key and banner.collapsed
            for banner in collapsed_banners
        )
        visible_targets = tuple(
            row.banner.target
            for row in collapsed.rows
            if row.kind == "banner" and row.banner is not None and row.banner.collapsed
        )
        assert first.target in visible_targets
        assert registry.expand(first.group_key)


def check_declared_relation_and_grouping_actions_are_reachable(
    descriptor: ArtifactsTabDescriptor,
) -> None:
    """Declared relation/grouping actions must pass Textual availability."""
    contract = descriptor.resolved_contract
    app = _ActionAvailabilityApp(contract)
    for capability, actions in (
        (PaneCapability.RELATIONS, _RELATION_REACHABILITY_ACTIONS),
        (PaneCapability.GROUPING, _GROUPING_REACHABILITY_ACTIONS),
    ):
        if not contract.has(capability):
            continue
        for action in CAPABILITY_HOST_ACTIONS[capability]:
            if action not in actions or not _action_applies_to_contract(
                contract, action
            ):
                continue
            available = check_app_action(app, action, (), lambda _a, _p: True)
            assert available is not False, f"{contract.id}:{action}"


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


def _grouping_sample_items(keys: tuple[str, ...]) -> tuple[tuple[str, ...], ...]:
    if not keys:
        return ()
    if len(keys) == 1:
        return (("alpha",), ("alpha",), ("beta",))
    return (
        ("alpha", "one", *("x" for _ in keys[2:])),
        ("alpha", "two", *("x" for _ in keys[2:])),
        ("beta", "one", *("x" for _ in keys[2:])),
    )


class _ActionAvailabilityApp:
    class _Screen:
        _blocks_global_config_center_open = False

    def __init__(self, contract: ArtifactsPaneContract) -> None:
        self.screen = self._Screen()
        self.focused = None
        self._screen_stack = ()
        self.current_tab = "artifacts"
        self.current_artifacts_pane_key = contract.id
        self.current_artifacts_subtab = contract.id
        self.active_artifacts_contract = contract

    def _prompt_input_active(self) -> bool:
        return False


def _action_applies_to_contract(
    contract: ArtifactsPaneContract,
    action: str,
) -> bool:
    if action == "beads_open_plan":
        return contract.id == "beads"
    if action == "plans_open_bead":
        return contract.is_plan_adapter()
    return True


PANE_CONFORMANCE_CHECKS: tuple[tuple[str, ConformanceCheck], ...] = (
    ("descriptor_identity", check_descriptor_identity),
    ("provider_accent_is_declared", check_provider_accent_is_declared),
    ("degraded_tab_carries_error", check_degraded_tab_carries_error),
    ("descriptor_owns_contract", check_descriptor_owns_contract),
    ("declared_actions_are_registered", check_declared_actions_are_registered),
    ("declared_relation_edges_resolve", check_declared_relation_edges_resolve),
    (
        "declared_grouping_banners_are_navigable",
        check_declared_grouping_banners_are_navigable,
    ),
    (
        "declared_relation_and_grouping_actions_are_reachable",
        check_declared_relation_and_grouping_actions_are_reachable,
    ),
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
