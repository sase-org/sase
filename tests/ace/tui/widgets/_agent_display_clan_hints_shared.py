"""Shared helpers for the split clan-hint tests.

The tests formerly lived in a single ``test_agent_display_clan_hints`` module.
Helpers needed by more than one split module live here under public names;
the ``test_agent_display_clan_hints_*`` modules import only these public names
(never ``_``-prefixed names from each other).
"""

from __future__ import annotations

from types import SimpleNamespace

from sase.ace.tui.models._agent_clan_sections import ClanSectionSnapshot
from sase.ace.tui.models.agent import Agent
from sase.ace.tui.models.fold_state import FoldLevel
from sase.ace.tui.widgets.prompt_panel._agent_clan_aggregation import (
    cache_clan_disk_snapshot,
    prepare_clan_section_snapshot,
)
from tests.ace.tui.widgets._agent_display_helpers import FakePromptPanel

__all__ = [
    "fold_app",
    "warm_clan_snapshot",
]


def fold_app(level: FoldLevel) -> SimpleNamespace:
    return SimpleNamespace(
        panel_fold_level=level,
        _panel_fold_overrides=SimpleNamespace(snapshot=lambda: {}),
    )


def warm_clan_snapshot(
    panel: FakePromptPanel,
    container: Agent,
    snapshot: ClanSectionSnapshot,
) -> None:
    prepare_clan_section_snapshot(panel, container)
    disk = snapshot.disk
    assert disk is not None
    assert cache_clan_disk_snapshot(panel, container, disk) is not None
