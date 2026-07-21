"""Shared Artifacts sub-tab types and presentation constants.

This module intentionally has no Textual widget or keymap dependencies so the
canonical order can safely drive both rendering and fixed app bindings.
"""

from __future__ import annotations

from typing import Literal

ArtifactsSubTab = Literal["prs", "commits", "bugs", "plans"]

DEFAULT_ARTIFACTS_SUBTAB: ArtifactsSubTab = "commits"
ARTIFACTS_SUBTAB_ORDER: tuple[ArtifactsSubTab, ...] = (
    "commits",
    "plans",
    "bugs",
    "prs",
)
ARTIFACTS_PANE_IDS: dict[ArtifactsSubTab, str] = {
    "prs": "artifacts-prs-pane",
    "commits": "artifacts-commits-pane",
    "bugs": "artifacts-bugs-pane",
    "plans": "artifacts-plans-pane",
}
ARTIFACTS_ACCENTS: dict[ArtifactsSubTab, str] = {
    "prs": "#00D7AF",
    "commits": "#FFD700",
    "bugs": "#FF5F5F",
    "plans": "#AF87FF",
}

__all__ = [
    "ARTIFACTS_ACCENTS",
    "ARTIFACTS_PANE_IDS",
    "ARTIFACTS_SUBTAB_ORDER",
    "ArtifactsSubTab",
    "DEFAULT_ARTIFACTS_SUBTAB",
]
