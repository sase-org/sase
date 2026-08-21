"""Focused LaunchPane host and session contract tests."""

from __future__ import annotations

from unittest.mock import MagicMock

from textual.app import App, ComposeResult

from sase.ace.tui.modals.models_panel import (
    LaunchPane,
    LaunchPaneSessionState,
    ModelsPanelResult,
)
from tests._models_panel_helpers import (
    highlight_row,
    make_alias_view,
    patch_alias_views,
    wait_for,
)


class _LaunchPaneHost:
    result: ModelsPanelResult | None = None

    def request_launch_close(self, result: ModelsPanelResult) -> None:
        self.result = result


class _BusyWorker:
    is_finished = False

    def cancel(self) -> None:
        self.is_finished = True


class _LaunchPaneTestApp(App[None]):
    ENABLE_COMMAND_PALETTE = False

    def __init__(self, pane: LaunchPane) -> None:
        super().__init__()
        self.pane = pane

    def compose(self) -> ComposeResult:
        yield self.pane


async def test_launch_pane_reports_result_through_host(monkeypatch) -> None:
    patch_alias_views(monkeypatch, [make_alias_view("large", "role")])
    host = _LaunchPaneHost()
    pane = LaunchPane(host=host)

    async with _LaunchPaneTestApp(pane).run_test() as pilot:
        await wait_for(pilot, lambda: "large" in pane._row_by_id)
        pane._mark_changed(provider_routing_changed=True)
        pane.action_close()

    assert host.result == ModelsPanelResult(
        changed=True,
        provider_routing_changed=True,
    )


async def test_launch_pane_refuses_close_while_write_busy(monkeypatch) -> None:
    patch_alias_views(monkeypatch, [make_alias_view("large", "role")])
    host = _LaunchPaneHost()
    pane = LaunchPane(host=host)

    async with _LaunchPaneTestApp(pane).run_test() as pilot:
        await wait_for(pilot, lambda: "large" in pane._row_by_id)
        pane.notify = MagicMock()  # type: ignore[method-assign]
        pane._override_worker = _BusyWorker()  # type: ignore[assignment]

        pane.action_close()

        assert host.result is None
        pane.notify.assert_called_once_with(
            "An override update is still in progress.",
            severity="warning",
        )


async def test_launch_pane_clock_refresh_is_inactive_while_hidden(monkeypatch) -> None:
    patch_alias_views(monkeypatch, [make_alias_view("large", "role")])
    pane = LaunchPane()

    async with _LaunchPaneTestApp(pane).run_test() as pilot:
        await wait_for(pilot, lambda: "large" in pane._row_by_id)
        pane.on_center_tab_visibility_changed(False)
        pane._refresh_effort_clock = MagicMock()  # type: ignore[method-assign]
        pane._refresh_runner_limit_clock = MagicMock()  # type: ignore[method-assign]
        pane._refresh_provider_clock = MagicMock()  # type: ignore[method-assign]

        pane._refresh_models_clock()
        pane.on_center_tab_visibility_changed(True)
        pane._refresh_models_clock()

        pane._refresh_effort_clock.assert_called_once()
        pane._refresh_runner_limit_clock.assert_called_once()
        pane._refresh_provider_clock.assert_called_once()


async def test_launch_pane_restores_session_row_after_snapshot(
    monkeypatch,
) -> None:
    patch_alias_views(
        monkeypatch,
        [
            make_alias_view("large", "role"),
            make_alias_view("writer", "user", configured=True),
        ],
    )
    session = LaunchPaneSessionState(selected_row_id="writer")
    pane = LaunchPane(session_state=session)

    async with _LaunchPaneTestApp(pane).run_test() as pilot:
        await wait_for(pilot, lambda: "writer" in pane._row_by_id)

        assert pane._highlighted_row_id() == "writer"

        highlight_row(pane, "large")  # type: ignore[arg-type]

        assert session.selected_row_id == "large"
        assert session.active_bucket is None
