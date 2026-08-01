"""Compatibility facade for per-subtab artifact copy targets."""

from __future__ import annotations

from ._artifact_target_selected import ClipboardArtifactSelectedTargetsMixin


class ClipboardArtifactTargetsMixin(ClipboardArtifactSelectedTargetsMixin):
    """Copy individual fields from visible or marked artifact entries."""


__all__ = ["ClipboardArtifactTargetsMixin"]
