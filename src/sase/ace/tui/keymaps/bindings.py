"""Construct Textual bindings from configured keymaps."""

from textual.binding import Binding

from sase.ace.tui.artifact_tabs import resolve_artifacts_subtabs
from sase.ace.tui.keymaps.display import key_display_name
from sase.ace.tui.keymaps.app_keymaps import (
    AppKeymaps,
    GateModalKeymaps,
    GlossaryPanelKeymaps,
    ProjectsPaneKeymaps,
    StatisticsPaneKeymaps,
)
from sase.ace.tui.keymaps.key_validation import is_unbound_key
from sase.ace.tui.keymaps.metadata import (
    _BINDING_META,
    _GATE_BINDING_META,
    _GATE_INPUT_PANEL_BINDING_META,
    _GLOSSARY_BINDING_META,
    _PROJECTS_BINDING_META,
    _PROJECTS_INVENTORY_BINDING_META,
    _STATISTICS_BINDING_META,
)


_GATE_NUMBERED_BRANCH_KEYS = tuple(str(index) for index in range(1, 10))


def _artifact_subtab_bindings() -> list[Binding]:
    """Return non-configurable numbered Artifacts sub-tab bindings."""

    return [
        Binding(
            descriptor.digit_shortcut,
            f"show_artifacts_digit({descriptor.digit_shortcut})",
            f"Show {descriptor.label}",
            show=False,
        )
        for descriptor in resolve_artifacts_subtabs()
        if descriptor.digit_shortcut is not None
    ]


def build_app_bindings(app_km: AppKeymaps) -> list[Binding]:
    """Generate the Textual ``Binding`` list from an ``AppKeymaps`` instance.

    Preserves the original binding order, descriptions, and priority flags and
    appends the non-configurable numbered Artifacts sub-tab bindings.
    """
    bindings: list[Binding] = []
    for action, desc, priority in _BINDING_META:
        key = getattr(app_km, action)
        if is_unbound_key(key):
            continue
        bindings.append(Binding(key, action, desc, show=False, priority=priority))
    bindings.extend(_artifact_subtab_bindings())
    return bindings


def build_statistics_bindings(keymaps: StatisticsPaneKeymaps) -> list[Binding]:
    """Build instance-local bindings for the focused Statistics pane."""

    return [
        Binding(
            getattr(keymaps, action),
            action,
            description,
            show=False,
        )
        for action, description in _STATISTICS_BINDING_META
    ]


def build_gate_modal_bindings(keymaps: GateModalKeymaps) -> list[Binding]:
    """Build instance-local bindings for a branch-driven gate modal."""

    return [
        Binding(
            getattr(keymaps, action),
            action,
            description,
            show=False,
            priority=True,
        )
        for action, description in _GATE_BINDING_META
    ]


def build_gate_input_panel_bindings(keymaps: GateModalKeymaps) -> list[Binding]:
    """Build instance-local bindings for the gate input panel focus ring."""

    return [
        Binding(
            getattr(keymaps, action),
            action,
            description,
            show=False,
            priority=True,
        )
        for action, description in _GATE_INPUT_PANEL_BINDING_META
    ]


def build_glossary_bindings(keymaps: GlossaryPanelKeymaps) -> list[Binding]:
    """Build instance-local bindings for the Glossary panel."""

    return [
        Binding(
            getattr(keymaps, action),
            action,
            description,
            show=False,
        )
        for action, description in _GLOSSARY_BINDING_META
    ]


def glossary_help_bindings(
    keymaps: GlossaryPanelKeymaps,
) -> list[tuple[str, str]]:
    """Return effective Glossary panel keys and descriptions for help surfaces."""

    return [
        (key_display_name(getattr(keymaps, action)), description)
        for action, description in _GLOSSARY_BINDING_META
    ]


def build_projects_bindings(keymaps: ProjectsPaneKeymaps) -> list[Binding]:
    """Build instance-local bindings for the Projects sub-tab's own list."""

    return [
        Binding(
            getattr(keymaps, field),
            action,
            description,
            show=False,
        )
        for field, action, description in _PROJECTS_BINDING_META
    ]


def build_projects_inventory_bindings(keymaps: ProjectsPaneKeymaps) -> list[Binding]:
    """Build instance-local bindings shared by the Repos/Workspaces sub-tabs."""

    return [
        Binding(
            getattr(keymaps, field),
            action,
            description,
            show=False,
        )
        for field, action, description in _PROJECTS_INVENTORY_BINDING_META
    ]


def build_gate_numbered_branch_bindings() -> list[Binding]:
    """Build fixed, modal-scoped digit selectors for gate branches."""

    return [
        Binding(
            key,
            f"submit_numbered_branch({branch_index})",
            f"Submit branch {key}",
            show=False,
        )
        for branch_index, key in enumerate(_GATE_NUMBERED_BRANCH_KEYS)
    ]


def statistics_help_bindings(
    keymaps: StatisticsPaneKeymaps,
) -> list[tuple[str, str]]:
    """Return effective Statistics keys and descriptions for help surfaces."""

    return [
        (key_display_name(getattr(keymaps, action)), description)
        for action, description in _STATISTICS_BINDING_META
    ]
