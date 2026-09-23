"""Backward-compatible re-exports for the split Artifacts panes.

Canonical definitions now live in :mod:`patches_pane`,
:mod:`placeholder_pane`, :mod:`degraded_pane`, and :mod:`patches_probe`.
Import from those modules in new code; this module stays so existing
``from .panes import ...`` imports keep resolving.
"""

from __future__ import annotations

from .degraded_pane import ArtifactsDegradedPane
from .lifecycle import ArtifactsPaneLifecycle
from .patches_pane import ArtifactsPatchesPane
from .placeholder_pane import ArtifactPlaceholderPane


__all__ = [
    "ArtifactPlaceholderPane",
    "ArtifactsDegradedPane",
    "ArtifactsPaneLifecycle",
    "ArtifactsPatchesPane",
]
