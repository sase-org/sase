"""Patch loading, filtering, and reload logic for sase's TUI app.

This module remains the public import facade for
:class:`PatchLoadingMixin`; the implementation is split into focused
private mixins so each file stays small.
"""

from __future__ import annotations

import time as time  # Re-export: tests patch ``_loading.time``.

from ._loading_refresh import PatchLoadingRefreshMixin


class PatchLoadingMixin(PatchLoadingRefreshMixin):
    """Mixin providing patch loading, filtering, and reload methods."""
