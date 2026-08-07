"""Agent artifact-file viewer actions for the ace TUI app.

This compatibility module keeps the historical ``AgentPanelArtifactFileMixin``
import path while the implementation lives in smaller, responsibility-focused
modules: pane tracking, caching/discovery, opening, and the keybinding actions.
"""

from __future__ import annotations

from ._panel_artifact_actions import AgentArtifactFileActionMixin
from ._panel_artifact_cache import (
    ARTIFACT_FILE_PAGE_CACHE_MAX,
    AgentArtifactFileCacheMixin,
)
from ._panel_artifact_open import AgentArtifactFileOpenMixin
from ._panel_artifact_pane import AgentArtifactFilePaneMixin


class AgentPanelArtifactFileMixin(
    AgentArtifactFileActionMixin,
    AgentArtifactFileOpenMixin,
    AgentArtifactFileCacheMixin,
    AgentArtifactFilePaneMixin,
):
    """Mixin providing artifact-file viewer actions and tmux pane tracking."""


__all__ = [
    "ARTIFACT_FILE_PAGE_CACHE_MAX",
    "AgentPanelArtifactFileMixin",
]
