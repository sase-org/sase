"""Composed event refresh mixin."""

from __future__ import annotations

from ._auto_refresh import EventAutoRefreshMixin


class EventRefreshMixin(EventAutoRefreshMixin):
    """Mixin providing watcher, daemon, and refresh timer callbacks."""
