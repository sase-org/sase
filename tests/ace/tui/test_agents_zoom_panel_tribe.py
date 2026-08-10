"""Tests for tribe-panel metadata zoom."""

from __future__ import annotations

from typing import Any

import pytest
from rich.text import Text
from textual.containers import VerticalScroll
from textual.widgets import Label, Static

from sase.ace.tui.modals import ZoomPanelModal, ZoomPanelSeed, ZoomPanelTarget
from sase.ace.tui.modals.zoom_panel_modal import (
    _renderable_to_text,
)
from sase.ace.tui.widgets.prompt_panel import AgentPromptPanel
from sase.ace.tui.widgets.prompt_panel._messages import TribeSectionSnapshotLoaded

from tests.ace.tui._agents_zoom_panel_helpers import (
    _FakeDetail,
    _FakeZoomApp,
    _make_agent,
    _make_tribe_snapshot,
    _ModalTestApp,
    _RecordingZoomPanelModal,
)


def test_action_zoom_panel_routes_whole_panel_focus_to_tribe_modal() -> None:
    detail = _FakeDetail(file_visible=True, tools_visible=True)
    snapshot = _make_tribe_snapshot("epic", status="RUNNING")
    app = _FakeZoomApp(agent=None, detail=detail)
    focused_snapshot = snapshot

    def focused_tribe_summary(*, with_entry_target: bool = True) -> Any:
        assert with_entry_target is False
        return focused_snapshot

    app._focused_tribe_summary = focused_tribe_summary  # type: ignore[attr-defined]

    app.action_zoom_panel()

    assert len(app.pushed) == 1
    modal = app.pushed[0]
    assert isinstance(modal, ZoomPanelModal)
    assert modal._is_tribe_zoom
    assert modal._target == ZoomPanelTarget.METADATA
    assert not modal._has_file_content
    assert not modal._has_tools_content
    assert _renderable_to_text(modal._seed.metadata_renderable) == "metadata"
    assert modal._seed.metadata_subtitle == "metadata · seeded"

    refreshed = _make_tribe_snapshot("epic", status="DONE")
    focused_snapshot = refreshed
    assert modal._tribe_provider() is refreshed

    focused_snapshot = _make_tribe_snapshot("review", status="DONE")
    assert modal._tribe_provider() is None


def test_action_zoom_panel_keeps_row_selection_in_agent_mode() -> None:
    agent = _make_agent()
    app = _FakeZoomApp(agent=agent)

    app.action_zoom_panel()

    modal = app.pushed[0]
    assert isinstance(modal, ZoomPanelModal)
    assert not modal._is_tribe_zoom
    assert modal._agent_provider() is agent


def test_tribe_zoom_is_metadata_only() -> None:
    snapshot = _make_tribe_snapshot()
    modal = ZoomPanelModal(
        tribe_provider=lambda: snapshot,
        initial_tribe=snapshot,
        initial_target=ZoomPanelTarget.FILE,
        seed=ZoomPanelSeed(has_file_content=True, has_tools_content=True),
        refresh_interval=10,
    )

    assert modal._target == ZoomPanelTarget.METADATA
    assert modal._available_targets() == [ZoomPanelTarget.METADATA]
    modal._cycle_target(step=1)
    assert modal._target == ZoomPanelTarget.METADATA


def test_zoom_modal_requires_exactly_one_provider() -> None:
    agent = _make_agent()
    snapshot = _make_tribe_snapshot()

    with pytest.raises(ValueError, match="exactly one"):
        ZoomPanelModal(
            initial_target=ZoomPanelTarget.METADATA,
            seed=ZoomPanelSeed(),
            refresh_interval=10,
        )

    with pytest.raises(ValueError, match="exactly one"):
        ZoomPanelModal(
            agent_provider=lambda: agent,
            initial_agent=agent,
            tribe_provider=lambda: snapshot,
            initial_tribe=snapshot,
            initial_target=ZoomPanelTarget.METADATA,
            seed=ZoomPanelSeed(),
            refresh_interval=10,
        )


async def test_tribe_zoom_modal_mounts_metadata_only_view() -> None:
    snapshot = _make_tribe_snapshot(status="RUNNING")
    modal = _RecordingZoomPanelModal(
        tribe_provider=lambda: snapshot,
        initial_tribe=snapshot,
        initial_target=ZoomPanelTarget.FILE,
        seed=ZoomPanelSeed(metadata_renderable=Text("seed tribe metadata")),
        refresh_interval=10,
    )

    async with _ModalTestApp().run_test(size=(120, 40)) as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()

        metadata_scroll = modal.query_one("#zoom-metadata-scroll", VerticalScroll)
        file_view = modal.query_one("#zoom-file-view")
        tools_scroll = modal.query_one("#zoom-tools-scroll", VerticalScroll)
        header = modal.query_one("#zoom-panel-agent", Static)
        hint = modal.query_one("#zoom-panel-hints", Label)

        assert not metadata_scroll.has_class("hidden")
        assert file_view.has_class("hidden")
        assert tools_scroll.has_class("hidden")
        assert snapshot.label in (_renderable_to_text(header.content) or "")
        assert "]/[" not in str(hint.content)
        assert "^N/^P" not in str(hint.content)

        await pilot.press("ctrl+n")
        await pilot.pause()

        assert modal.notifications == [("No files for a tribe panel", "warning")]


async def test_tribe_zoom_message_repaints_current_identity_and_stops(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = _make_tribe_snapshot("epic")
    modal = ZoomPanelModal(
        tribe_provider=lambda: snapshot,
        initial_tribe=snapshot,
        initial_target=ZoomPanelTarget.METADATA,
        seed=ZoomPanelSeed(metadata_renderable=Text("seed tribe metadata")),
        refresh_interval=10,
    )

    async with _ModalTestApp().run_test(size=(120, 40)) as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()

        panel = modal.query_one("#zoom-metadata-panel", AgentPromptPanel)
        calls: list[tuple[Any, dict[str, object]]] = []

        def record_update(snapshot_arg: Any, **kwargs: object) -> None:
            calls.append((snapshot_arg, kwargs))

        monkeypatch.setattr(panel, "update_tribe_display", record_update)

        stale = TribeSectionSnapshotLoaded(("panel", "review"))
        stale_stops: list[bool] = []
        monkeypatch.setattr(stale, "stop", lambda: stale_stops.append(True))
        modal.on_tribe_section_snapshot_loaded(stale)

        current = TribeSectionSnapshotLoaded(snapshot.container_identity)
        current_stops: list[bool] = []
        monkeypatch.setattr(current, "stop", lambda: current_stops.append(True))
        modal.on_tribe_section_snapshot_loaded(current)

        assert stale_stops == [True]
        assert current_stops == [True]
        assert calls == [
            (snapshot, {"publish_member_jump_map": False}),
        ]


async def test_tribe_zoom_unmount_cancels_modal_tribe_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = _make_tribe_snapshot()
    modal = ZoomPanelModal(
        tribe_provider=lambda: snapshot,
        initial_tribe=snapshot,
        initial_target=ZoomPanelTarget.METADATA,
        seed=ZoomPanelSeed(metadata_renderable=Text("seed tribe metadata")),
        refresh_interval=10,
    )

    async with _ModalTestApp().run_test(size=(120, 40)) as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()

        panel = modal.query_one("#zoom-metadata-panel", AgentPromptPanel)
        calls: list[bool] = []
        monkeypatch.setattr(
            panel,
            "_cancel_tribe_section_worker_for_agent_selection",
            lambda: calls.append(True),
        )

        modal.on_unmount()

        assert calls == [True]
