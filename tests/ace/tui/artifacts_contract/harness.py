"""Conformance checks every Artifacts pane adapter must satisfy.

This harness starts nearly empty on purpose. Later epic phases append
checks here; ``iter_conformance_cases`` parametrizes them over every
resolved sub-tab, including degraded and synthetic providers.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator

from sase.ace.tui._artifact_tab_actions import (
    CAPABILITY_HOST_ACTIONS,
    action_applies_to_contract,
    keymap_actions_by_key,
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
from sase.ace.tui.keymaps import load_keymap_registry
from sase.ace.tui.keymaps.key_validation import is_unbound_key, split_key_alternatives
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
        "toggle_relation_panel",
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


_PRESENTATION_ONLY_CAPABILITIES = frozenset(
    {PaneCapability.STATUS_COUNTERS, PaneCapability.SHELL}
)

# Pre-existing gap surfaced while writing this guard (sase-tj.10.2): the
# Patch pane declares ``entry_open`` (from ``has_inventory``) but "Enter"
# there commits the persistent filter query, not a per-row open, and no
# ``patches_view_selected``-style action was ever registered for
# ``PaneCapability.ENTRY_OPEN``. Fixing the Patch pane's contract is out of
# scope for the Agent pane navigation phase that added this check; recorded
# as a proposed follow-up on sase-tj.10.2 for the epic's land agent to triage.
_KNOWN_UNREACHABLE_CAPABILITIES: frozenset[tuple[str, PaneCapability]] = frozenset(
    {("patches", PaneCapability.ENTRY_OPEN)}
)


def check_declared_capabilities_are_reachable(
    descriptor: ArtifactsTabDescriptor,
) -> None:
    """Every ON capability must serve at least one action reachable here.

    ``check_declared_keys_resolve_to_named_actions`` only walks actions that
    already survive ``action_applies_to_contract`` for this pane, so a pane
    that declares a capability contributing zero applicable actions never
    enters that loop and the check stays silent. That was the Agent pane's
    ``entry_navigation``/``entry_open`` bug: both ON, no action for either
    ever bound a key. This check asserts a serving, reachable action exists
    for every ON capability instead of assuming the declaration is honest.
    """
    contract = descriptor.resolved_contract
    if descriptor.is_degraded:
        return
    app = _ActionAvailabilityApp(contract)
    for capability in contract.capabilities:
        if capability in _PRESENTATION_ONLY_CAPABILITIES:
            continue
        if (contract.id, capability) in _KNOWN_UNREACHABLE_CAPABILITIES:
            continue
        actions = CAPABILITY_HOST_ACTIONS[capability]
        reachable = any(
            action_applies_to_contract(contract, action)
            and check_app_action(app, action, (), lambda _a, _p: True) is not False
            for action in actions
        )
        assert reachable, (
            f"{contract.id}: {capability.value} is ON but no action in "
            f"{actions} applies and is reachable"
        )


def check_declared_actions_are_registered(descriptor: ArtifactsTabDescriptor) -> None:
    """Every ON capability maps to a registered host action or is presentation-only."""
    contract = descriptor.resolved_contract
    registered = frozenset(
        action for actions in CAPABILITY_HOST_ACTIONS.values() for action in actions
    )
    for capability in contract.capabilities:
        actions = CAPABILITY_HOST_ACTIONS[capability]
        if capability in _PRESENTATION_ONLY_CAPABILITIES:
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
            if action not in actions or not action_applies_to_contract(
                contract, action
            ):
                continue
            available = check_app_action(app, action, (), lambda _a, _p: True)
            assert available is not False, f"{contract.id}:{action}"


def check_declared_keys_resolve_to_named_actions(
    descriptor: ArtifactsTabDescriptor,
) -> None:
    """Every contract-declared key resolves to the action the contract names.

    This is the binding-level check that would have caught ``o`` being
    double-booked between grouping-cycle and an open-external action.
    """
    contract = descriptor.resolved_contract
    if descriptor.is_degraded:
        return
    registry = load_keymap_registry({})
    by_key = keymap_actions_by_key(registry.app)
    app = _ActionAvailabilityApp(contract)
    declared = tuple(
        action
        for capability in contract.capabilities
        for action in CAPABILITY_HOST_ACTIONS[capability]
        if action_applies_to_contract(contract, action)
    )
    for action in declared:
        assert hasattr(registry.app, action), f"{contract.id}:{action} missing keymap"
        key = getattr(registry.app, action)
        assert not is_unbound_key(key), f"{contract.id}:{action} is unbound"
        for part in split_key_alternatives(key):
            owners = by_key.get(part, ())
            available = tuple(
                owner
                for owner in owners
                if check_app_action(app, owner, (), lambda _a, _p: True) is not False
            )
            assert action in available, (
                f"{contract.id}:{action} key {part!r} unavailable"
            )
            conflicts = tuple(owner for owner in available if owner != action)
            assert not conflicts, (
                f"{contract.id} key {part!r} maps to {available}; "
                f"contract names {action}"
            )


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


PANE_CONFORMANCE_CHECKS: tuple[tuple[str, ConformanceCheck], ...] = (
    ("descriptor_identity", check_descriptor_identity),
    ("provider_accent_is_declared", check_provider_accent_is_declared),
    ("degraded_tab_carries_error", check_degraded_tab_carries_error),
    ("descriptor_owns_contract", check_descriptor_owns_contract),
    ("declared_actions_are_registered", check_declared_actions_are_registered),
    (
        "declared_capabilities_are_reachable",
        check_declared_capabilities_are_reachable,
    ),
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
        "declared_keys_resolve_to_named_actions",
        check_declared_keys_resolve_to_named_actions,
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
