"""Tests for the Config hub MEMORY ``●N`` sub-tab badge (`watermark-tui`).

The badge shows the launch project scope's unreviewed count, computed
off-thread after the warm-up and on token drift, and hides at zero or
with no watermark. Headless tests mount the production host
(``ConfigCenterModal`` + ``ConfigHubPane``) with stub children and a
stub history service: no git, no core.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from sase.ace.testing import wait_for
from sase.ace.tui.modals.config_center_modal import ConfigCenterModal
from sase.ace.tui.modals.config_hub_pane import ConfigHubPane
from sase.ace.tui.modals.config_hub_session import ConfigHubEntry
from sase.ace.tui.widgets.panel_tab_strip import PanelTabStrip
from tests.ace.tui._config_center_tabs_helpers import _HostApp
from tests.ace.tui._config_hub_pane_helpers import _patch_hub_children

_T0 = 1790486400


def _wire(*, new_count: int = 2, watermark: bool = True) -> dict[str, Any]:
    return {
        "scopes": [
            {
                "scope_key": "project:sase",
                "watermark": (
                    {
                        "commit": "w" * 40,
                        "committer_time": _T0,
                        "marked_at": _T0,
                    }
                    if watermark
                    else None
                ),
                "new_count": new_count,
                "newest_commit": "n" * 40,
            }
        ]
    }


def _fake_history(wire: dict[str, Any]) -> SimpleNamespace:
    service = SimpleNamespace(
        project_scope=lambda _root: SimpleNamespace(
            scope_key="project:sase", repo_root="/tmp/sase"
        ),
        review_state=lambda _scopes: wire,
    )
    return SimpleNamespace(service=service, change_token=lambda _scope: ("tok",))


def _patch_history(monkeypatch: pytest.MonkeyPatch, wire: dict[str, Any]) -> None:
    import sase.ace.tui.memory_history as memory_history_module

    fake = _fake_history(wire)
    monkeypatch.setattr(memory_history_module, "ace_memory_history", lambda _app: fake)


def _memory_tab_labels(hub: ConfigHubPane) -> tuple[str, str, str]:
    strip = hub.query_one("#config-hub-tabs", PanelTabStrip)
    tab = next(tab for tab in strip._tabs if tab.id == "memory")
    return (
        tab.label,
        tab.compact_label or "",
        tab.micro_label or "",
    )


async def _mount_hub(monkeypatch: pytest.MonkeyPatch):
    """Mount the hub with stub children; return ``(hub, pilot, exit)``."""
    _patch_hub_children(monkeypatch)
    pilot_context = _HostApp().run_test(size=(120, 40))
    pilot = await pilot_context.__aenter__()
    try:
        modal = ConfigCenterModal(
            initial_tab="config",
            config_entry=ConfigHubEntry(subtab="misc"),
        )
        pilot.app.push_screen(modal)
        await wait_for(pilot, lambda: modal._active_tab == "config")
        hub = modal.query_one("#config", ConfigHubPane)
        await wait_for(pilot, lambda: "misc" in hub._panes)
        return hub, pilot, pilot_context
    except Exception:
        await pilot_context.__aexit__(None, None, None)
        raise


async def _wait_badge_idle(pilot, hub: ConfigHubPane) -> None:  # noqa: ANN001, ANN202
    await wait_for(
        pilot,
        lambda: (
            hub._memory_badge_worker is not None
            and hub._memory_badge_worker.is_finished
        ),
    )
    await pilot.pause()


async def test_apply_memory_badge_labels_and_hides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Direct applies badge and unbadge the MEMORY tab at every tier."""
    # Zeros on mount: the mount worker is a no-op, so only the direct
    # applies below write the strip (no worker race).
    _patch_history(monkeypatch, _wire(new_count=0))
    hub, _pilot, pilot_context = await _mount_hub(monkeypatch)
    try:
        hub._apply_memory_badge(3)
        assert hub._memory_badge_count == 3
        assert _memory_tab_labels(hub) == ("●3 Memory", "●3 Memory", "●3 Mem")
        # A second identical apply is a no-op (no strip repaint needed).
        hub._apply_memory_badge(3)
        assert _memory_tab_labels(hub) == ("●3 Memory", "●3 Memory", "●3 Mem")
        hub._apply_memory_badge(None)
        assert hub._memory_badge_count is None
        assert _memory_tab_labels(hub) == ("Memory", "Memory", "Mem")
        hub._apply_memory_badge(0)
        assert _memory_tab_labels(hub) == ("Memory", "Memory", "Mem")
    finally:
        await pilot_context.__aexit__(None, None, None)


async def test_badge_worker_sets_strip(monkeypatch: pytest.MonkeyPatch) -> None:
    """The mount refresh paints ``●2 Memory`` from the review state."""
    _patch_history(monkeypatch, _wire(new_count=2))
    hub, pilot, pilot_context = await _mount_hub(monkeypatch)
    try:
        await _wait_badge_idle(pilot, hub)
        assert hub._memory_badge_count == 2
        assert _memory_tab_labels(hub) == ("●2 Memory", "●2 Memory", "●2 Mem")
    finally:
        await pilot_context.__aexit__(None, None, None)


async def test_badge_worker_hides_at_zero_and_unmarked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Zero new and never-marked scopes leave the tab bare."""
    _patch_history(monkeypatch, _wire(new_count=0))
    hub, pilot, pilot_context = await _mount_hub(monkeypatch)
    try:
        await _wait_badge_idle(pilot, hub)
        assert hub._memory_badge_count is None
        assert _memory_tab_labels(hub) == ("Memory", "Memory", "Mem")
    finally:
        await pilot_context.__aexit__(None, None, None)


async def test_badge_tick_skips_when_hub_hidden(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The quiet-time tick never schedules while the hub is hidden."""
    _patch_history(monkeypatch, _wire(new_count=5))
    hub, pilot, pilot_context = await _mount_hub(monkeypatch)
    try:
        await _wait_badge_idle(pilot, hub)
        assert hub._memory_badge_count == 5
        hub._memory_badge_worker = None
        hub._host_visible = False
        hub._memory_badge_tick()
        await pilot.pause()
        assert hub._memory_badge_worker is None
        assert hub._memory_badge_count == 5
    finally:
        await pilot_context.__aexit__(None, None, None)
