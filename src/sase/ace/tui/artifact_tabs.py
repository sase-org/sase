"""Shared Artifacts sub-tab types and presentation constants.

This module intentionally has no Textual widget or keymap dependencies so the
canonical order can safely drive both rendering and fixed app bindings.
"""

from __future__ import annotations

from typing import Any, Literal, cast

ArtifactsSubTab = Literal["patches", "stitches", "beads", "files"]
FilesSubTab = Literal["plans", "chats", "other"]
ArtifactsPaneKey = Literal[
    "patches",
    "stitches",
    "beads",
    "plans",
    "chats",
    "other",
]

DEFAULT_ARTIFACTS_SUBTAB: ArtifactsSubTab = "stitches"
ARTIFACTS_SUBTAB_ORDER: tuple[ArtifactsSubTab, ...] = (
    "stitches",
    "patches",
    "beads",
    "files",
)
ARTIFACTS_PANE_IDS: dict[ArtifactsSubTab, str] = {
    "patches": "artifacts-patches-pane",
    "stitches": "artifacts-stitches-pane",
    "beads": "artifacts-beads-pane",
    "files": "artifacts-files-view",
}

LEGACY_ARTIFACTS_SUBTABS: dict[str, ArtifactsSubTab] = {
    "prs": "patches",  # legacy compatibility alias
    "bugs": "beads",  # retired sub-tab, routed to its replacement
}


def normalize_artifacts_subtab(value: str) -> ArtifactsSubTab:
    """Map a possibly legacy sub-tab identifier to its canonical form."""

    legacy = LEGACY_ARTIFACTS_SUBTABS.get(value)
    if legacy is not None:
        return legacy
    return cast(ArtifactsSubTab, value)


DEFAULT_FILES_SUBTAB: FilesSubTab = "plans"
FILES_SUBTAB_ORDER: tuple[FilesSubTab, ...] = ("plans", "chats", "other")
FILES_PANE_IDS: dict[FilesSubTab, str] = {
    "plans": "artifacts-plans-pane",
    "chats": "artifacts-chats-pane",
    "other": "artifacts-files-pane",
}

EXTERNAL_ACCENT = "#FF5F5F"

ARTIFACTS_ACCENTS: dict[ArtifactsPaneKey | Literal["files"], str] = {
    "patches": "#00D7AF",
    "stitches": "#FFD700",
    "beads": "#D787FF",
    "plans": "#AF87FF",
    "chats": "#5FAFFF",
    "files": "#FFAF5F",
    "other": "#FFAF5F",
}


def artifacts_pane_key(
    subtab: ArtifactsSubTab,
    files_subtab: FilesSubTab,
) -> ArtifactsPaneKey:
    """Return the leaf pane that owns state for the visible Artifacts view."""

    if subtab != "files":
        return subtab
    return files_subtab


def switch_to_artifacts_subtab(app: Any, subtab: ArtifactsSubTab) -> None:
    """Show the Artifacts tab with *subtab* as its active leaf pane.

    Assigns ``current_artifacts_subtab`` before ``current_tab``. That order
    is load-bearing: when Artifacts is not yet the active tab, the subtab
    reactive is set first while Artifacts is still hidden, so the app's
    ``watch_current_tab`` activates only the requested pane instead of
    briefly activating whichever pane was last visible. When Artifacts is
    already active, ``watch_current_artifacts_subtab`` alone performs the
    pane swap, and the subsequent ``current_tab`` assignment is a no-op
    (Textual reactives skip the watcher when the value is unchanged).

    This function lives here — rather than alongside the Textual widget
    tree in ``actions/artifacts_navigation.py`` — so widget-free callers
    like ``actions/agents/_notification_navigation.py`` can reach it
    without pulling the widget tree into their import graph.
    """
    from .tab_order import ARTIFACTS_TAB

    app.current_artifacts_subtab = normalize_artifacts_subtab(subtab)
    app.current_tab = ARTIFACTS_TAB


__all__ = [
    "ARTIFACTS_ACCENTS",
    "ARTIFACTS_PANE_IDS",
    "ARTIFACTS_SUBTAB_ORDER",
    "FILES_PANE_IDS",
    "FILES_SUBTAB_ORDER",
    "LEGACY_ARTIFACTS_SUBTABS",
    "ArtifactsPaneKey",
    "ArtifactsSubTab",
    "DEFAULT_ARTIFACTS_SUBTAB",
    "DEFAULT_FILES_SUBTAB",
    "EXTERNAL_ACCENT",
    "FilesSubTab",
    "artifacts_pane_key",
    "normalize_artifacts_subtab",
    "switch_to_artifacts_subtab",
]
