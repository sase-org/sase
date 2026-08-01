"""Shared Artifacts sub-tab types and presentation constants.

This module intentionally has no Textual widget or keymap dependencies so the
canonical order can safely drive both rendering and fixed app bindings.
"""

from __future__ import annotations

from typing import Literal

ArtifactsSubTab = Literal["prs", "commits", "bugs", "beads", "files"]
FilesSubTab = Literal["plans", "chats", "other"]
ArtifactsPaneKey = Literal[
    "prs",
    "commits",
    "bugs",
    "beads",
    "plans",
    "chats",
    "other",
]

DEFAULT_ARTIFACTS_SUBTAB: ArtifactsSubTab = "commits"
ARTIFACTS_SUBTAB_ORDER: tuple[ArtifactsSubTab, ...] = (
    "commits",
    "beads",
    "bugs",
    "prs",
    "files",
)
ARTIFACTS_PANE_IDS: dict[ArtifactsSubTab, str] = {
    "prs": "artifacts-prs-pane",
    "commits": "artifacts-commits-pane",
    "bugs": "artifacts-bugs-pane",
    "beads": "artifacts-beads-pane",
    "files": "artifacts-files-view",
}

DEFAULT_FILES_SUBTAB: FilesSubTab = "plans"
FILES_SUBTAB_ORDER: tuple[FilesSubTab, ...] = ("plans", "chats", "other")
FILES_PANE_IDS: dict[FilesSubTab, str] = {
    "plans": "artifacts-plans-pane",
    "chats": "artifacts-chats-pane",
    "other": "artifacts-files-pane",
}

ARTIFACTS_ACCENTS: dict[ArtifactsPaneKey | Literal["files"], str] = {
    "prs": "#00D7AF",
    "commits": "#FFD700",
    "bugs": "#FF5F5F",
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


__all__ = [
    "ARTIFACTS_ACCENTS",
    "ARTIFACTS_PANE_IDS",
    "ARTIFACTS_SUBTAB_ORDER",
    "FILES_PANE_IDS",
    "FILES_SUBTAB_ORDER",
    "ArtifactsPaneKey",
    "ArtifactsSubTab",
    "DEFAULT_ARTIFACTS_SUBTAB",
    "DEFAULT_FILES_SUBTAB",
    "FilesSubTab",
    "artifacts_pane_key",
]
