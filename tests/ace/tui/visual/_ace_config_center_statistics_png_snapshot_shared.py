"""Shared Statistics PNG snapshot helpers.

Public helpers for the ``test_ace_png_snapshots_config_center_statistics*``
split. This module is private (``_``-prefixed); the helpers are public so
each split test module can import them without importing a ``_``-prefixed
name across modules.
"""

from __future__ import annotations

import pytest

from tests.ace.tui.visual._ace_config_center_png_snapshot_helpers import (
    _open_statistics_modal as open_statistics_modal,
    _patch_config_view,
    _patch_macro_sources,
    _patch_plugins_catalog,
    _patch_statistics_empty as patch_statistics_empty,
    _patch_statistics_footprint as patch_statistics_footprint,
    _patch_statistics_loading as patch_statistics_loading,
    _patch_statistics_perf_degraded as patch_statistics_perf_degraded,
    _patch_statistics_populated as patch_statistics_populated,
    _patch_statistics_projects_measuring_code as patch_statistics_projects_measuring_code,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import patch_startup_loaders


def patch_siblings(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_startup_loaders(monkeypatch)
    _patch_macro_sources(monkeypatch)
    _patch_plugins_catalog(monkeypatch)
    _patch_config_view(monkeypatch, None)


__all__ = [
    "open_statistics_modal",
    "patch_siblings",
    "patch_statistics_empty",
    "patch_statistics_footprint",
    "patch_statistics_loading",
    "patch_statistics_perf_degraded",
    "patch_statistics_populated",
    "patch_statistics_projects_measuring_code",
]
