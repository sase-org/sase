"""Reactive selection and tab watchers for :class:`AceApp`."""

from __future__ import annotations

from ._app_watchers_footprint import FootprintTuiMixin
from ._app_watchers_selection import AppWatchersMixin

__all__: list[str] = ["AppWatchersMixin", "FootprintTuiMixin"]
