"""ACE PNG visual snapshots for the Admin Center Telemetry tab."""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from tests.ace.tui.visual._ace_config_center_png_snapshot_helpers import (
    _open_telemetry_modal,
    _patch_config_view,
    _patch_plugins_catalog,
    _patch_telemetry_empty,
    _patch_telemetry_loading,
    _patch_telemetry_populated,
    _patch_xprompt_sources,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    changespecs,
    patch_startup_loaders,
    wait_for_startup,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


def _patch_siblings(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_startup_loaders(monkeypatch)
    _patch_xprompt_sources(monkeypatch)
    _patch_plugins_catalog(monkeypatch)
    _patch_config_view(monkeypatch, None)


async def test_config_center_telemetry_tab_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_siblings(monkeypatch)
    _patch_telemetry_populated(monkeypatch)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        _, pane = await _open_telemetry_modal(page)
        assert pane._last_result is not None
        assert pane._last_result.empty is False

        ace_png_visual.assert_page_png(
            page,
            "config_center_telemetry_tab_120x40",
            title="ACE SASE Admin Center — Telemetry tab",
        )


async def test_config_center_telemetry_empty_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_siblings(monkeypatch)
    _patch_telemetry_empty(monkeypatch)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        _, pane = await _open_telemetry_modal(page)
        assert pane._last_result is not None
        assert pane._last_result.empty is True

        ace_png_visual.assert_page_png(
            page,
            "config_center_telemetry_empty_120x40",
            title="ACE SASE Admin Center — Telemetry empty state",
        )


async def test_config_center_telemetry_loading_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_siblings(monkeypatch)
    _patch_telemetry_loading(monkeypatch)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        _, pane = await _open_telemetry_modal(page, wait_for_load=False)
        assert pane._loading is True
        assert pane._last_result is None

        ace_png_visual.assert_page_png(
            page,
            "config_center_telemetry_loading_120x40",
            title="ACE SASE Admin Center — Telemetry loading state",
        )
