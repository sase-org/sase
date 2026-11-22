"""Countdown ticks republish the Services and Patch info panels only on change.

The one-second countdown callback re-sends every info-panel field (host
chrome, position, mode, countdown). Only a changed rendered text may reach
``Static.update``: an identical update still rebuilds the visual and requests
a layout refresh. Visible values keep their one-second cadence.
"""

from __future__ import annotations

from unittest.mock import patch

from rich.text import Text

from sase.ace.tui.widgets.axe_info_panel import AxeInfoPanel
from sase.ace.tui.widgets.patch_info_panel import PatchInfoPanel

_TICKS = 10


def _axe_tick(panel: AxeInfoPanel, countdown: int, interval: int) -> None:
    """Mirror ``_update_axe_info_panel`` for the plain Services view."""
    panel.update_host_chrome(None, status_error=None)
    panel.update_status(False)
    panel.update_countdown(countdown, interval)


def _patch_tick(panel: PatchInfoPanel, countdown: int, interval: int) -> None:
    """Mirror ``_update_info_panel`` on the Artifacts (Patches) tab."""
    panel.update_position(1, 5, 0)
    panel.update_hidden_counts(0, 0)
    panel.update_grouping_mode("by project")
    panel.update_countdown(countdown, interval)
    panel.update_reveal(None)


def test_axe_info_panel_publishes_once_per_countdown_tick() -> None:
    panel = AxeInfoPanel()
    published: list[str] = []
    with patch.object(panel, "update", lambda text: published.append(text.plain)):
        _axe_tick(panel, 10, 10)
        first_tick = len(published)
        for countdown in range(9, 9 - _TICKS, -1):
            _axe_tick(panel, countdown, 10)

    # Three update_* calls per tick used to publish three times each tick.
    assert len(published) - first_tick == _TICKS
    assert published[-1].endswith(f"(auto-refresh in {9 - _TICKS + 1}s)")


def test_axe_info_panel_quiet_without_auto_refresh() -> None:
    """With auto-refresh disabled (``-r 0``) an idle tick publishes nothing."""
    panel = AxeInfoPanel()
    published: list[str] = []
    with patch.object(panel, "update", lambda text: published.append(text.plain)):
        _axe_tick(panel, 0, 0)
        settled = len(published)
        for _ in range(_TICKS):
            _axe_tick(panel, 0, 0)

    assert len(published) == settled
    assert "auto-refresh" not in published[-1]


def test_axe_info_panel_republishes_changed_state_and_loading() -> None:
    panel = AxeInfoPanel()
    published: list[str] = []
    with patch.object(panel, "update", lambda text: published.append(text.plain)):
        panel.set_loading(True)
        assert published == ["Services …"]
        panel._update_display()
        assert published == ["Services …"]
        panel.set_loading(False)
        _axe_tick(panel, 5, 10)
        count = len(published)

        panel.update_host_chrome(None, status_error="status unavailable")
        assert len(published) == count + 1
        assert "status unavailable" in published[-1]

        panel.update_lumberjack_status("hooks", 0, 2)
        assert len(published) == count + 2
        assert "[hooks]" in published[-1]
        panel.update_lumberjack_status("hooks", 0, 2)
        assert len(published) == count + 2


def test_axe_info_panel_content_width_tracks_published_text() -> None:
    panel = AxeInfoPanel()
    with patch.object(panel, "update", lambda text: None):
        _axe_tick(panel, 10, 10)
        width_ten = panel.content_width
        _axe_tick(panel, 9, 10)
        assert panel.content_width == width_ten - 1
        _axe_tick(panel, 9, 10)
        assert panel.content_width == width_ten - 1


def test_patch_info_panel_publishes_only_the_countdown_change() -> None:
    panel = PatchInfoPanel()
    published: list[Text] = []
    with patch.object(panel, "update", published.append):
        _patch_tick(panel, 10, 10)
        first_tick = len(published)
        for countdown in range(9, 9 - _TICKS, -1):
            _patch_tick(panel, countdown, 10)

    # update_position and update_countdown each published every tick before.
    assert len(published) - first_tick == _TICKS
    assert f"(auto-refresh in {9 - _TICKS + 1}s)" in published[-1].plain


def test_patch_info_panel_quiet_without_auto_refresh() -> None:
    panel = PatchInfoPanel()
    published: list[Text] = []
    with patch.object(panel, "update", published.append):
        _patch_tick(panel, 0, 0)
        settled = len(published)
        for _ in range(_TICKS):
            _patch_tick(panel, 0, 0)

    assert len(published) == settled
    assert "auto-refresh" not in published[-1].plain


def test_patch_info_panel_republishes_position_and_mark_changes() -> None:
    panel = PatchInfoPanel()
    published: list[Text] = []
    with patch.object(panel, "update", published.append):
        _patch_tick(panel, 5, 10)
        count = len(published)

        panel.update_position(2, 5, 0)
        assert len(published) == count + 1
        assert "2/5" in published[-1].plain

        panel.update_position(2, 5, 1)
        assert len(published) == count + 2
        assert "[1 marked]" in published[-1].plain

        panel.update_position(2, 5, 1)
        assert len(published) == count + 2
