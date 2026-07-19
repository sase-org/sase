"""Construct Textual bindings from configured keymaps."""

from textual.binding import Binding

from sase.ace.tui.artifact_tabs import ARTIFACTS_SUBTAB_ORDER
from sase.ace.tui.keymaps.display import key_display_name
from sase.ace.tui.keymaps.types import (
    _BINDING_META,
    _GATE_BINDING_META,
    _STATISTICS_BINDING_META,
    AppKeymaps,
    GateModalKeymaps,
    StatisticsPaneKeymaps,
)


# Non-configurable numbered Artifacts sub-tab bindings.
_ARTIFACT_SUBTAB_BINDINGS: list[Binding] = [
    Binding(
        str(index),
        f"show_artifacts_{subtab}",
        f"Show {subtab.title()}",
        show=False,
    )
    for index, subtab in enumerate(ARTIFACTS_SUBTAB_ORDER, start=1)
]


def build_app_bindings(app_km: AppKeymaps) -> list[Binding]:
    """Generate the Textual ``Binding`` list from an ``AppKeymaps`` instance.

    Preserves the original binding order, descriptions, and priority flags and
    appends the non-configurable numbered Artifacts sub-tab bindings.
    """
    bindings: list[Binding] = []
    for action, desc, priority in _BINDING_META:
        key = getattr(app_km, action)
        bindings.append(Binding(key, action, desc, show=False, priority=priority))
    bindings.extend(_ARTIFACT_SUBTAB_BINDINGS)
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


def statistics_help_bindings(
    keymaps: StatisticsPaneKeymaps,
) -> list[tuple[str, str]]:
    """Return effective Statistics keys and descriptions for help surfaces."""

    return [
        (key_display_name(getattr(keymaps, action)), description)
        for action, description in _STATISTICS_BINDING_META
    ]
