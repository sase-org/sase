"""Pane resolution for the Artifacts Agent pane's copy-mode actions.

Selection/entry navigation, marks, and relation/grouping actions all reach
this pane already through the generic ``_artifacts_entry_navigator()``
resolver (see ``artifacts_navigation.py``); this mixin supplies only the
by-id lookup the clipboard actions need, mirroring ``_files_pane()`` /
``_beads_pane()``.
"""

from __future__ import annotations

from ..widgets.artifacts.agents_pane import ArtifactsAgentsPane


class ArtifactsAgentsActionsMixin:
    """Actions mixed into :class:`ArtifactsMixin` for the Agent pane."""

    def _agents_pane(self) -> ArtifactsAgentsPane | None:
        try:
            return self.query_one("#artifacts-agents-pane", ArtifactsAgentsPane)  # type: ignore[attr-defined]
        except Exception:
            return None


__all__ = ["ArtifactsAgentsActionsMixin"]
