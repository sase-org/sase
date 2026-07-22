"""Pure and mounted coverage for the agents-sync top-bar indicator."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest

from sase.ace.tui.widgets import AgentsSyncIndicator
from sase.agents_sync.models import ProjectSyncStatus, SyncStatusSnapshot


def _snapshot(*statuses: ProjectSyncStatus) -> SyncStatusSnapshot:
    return SyncStatusSnapshot(1.0, statuses)


def test_indicator_shows_pending_projects_and_deterministic_tooltip() -> None:
    indicator = AgentsSyncIndicator()

    indicator.set_status(
        _snapshot(
            ProjectSyncStatus("z", "Zulu", "error", error="fetch failed"),
            ProjectSyncStatus("a", "Alpha", "ready", ahead=1, behind=2),
            ProjectSyncStatus("current", "Current", "ready", 0, 0, 0),
            ProjectSyncStatus("off", "Disabled", "disabled"),
        )
    )

    assert indicator.pending_count == 2
    rendered = indicator._build_content(indicator.pending_projects)
    assert rendered.plain == " ⇅ 2 "
    assert "#5FD787" in repr(rendered.spans)
    assert str(indicator.tooltip) == (
        "Agents repositories need synchronization:\n"
        "Alpha: behind 2, ahead 1\n"
        "Zulu: error: fetch failed\n"
        "Click to synchronize agents repositories. Press ,U for the "
        "comprehensive update."
    )


def test_indicator_clear_and_idempotent_projection() -> None:
    indicator = AgentsSyncIndicator()
    pending = _snapshot(ProjectSyncStatus("a", "Alpha", "ready", behind=1))
    indicator.set_status(pending)
    tooltip = indicator.tooltip
    indicator.set_status(SyncStatusSnapshot(99.0, pending.projects))

    assert indicator.pending_projects == pending.projects
    assert indicator.tooltip == tooltip
    indicator.set_status(_snapshot(ProjectSyncStatus("a", "Alpha", "ready", 0, 0, 0)))
    assert indicator.pending_count == 0
    assert indicator._build_content(indicator.pending_projects).plain == ""
    assert indicator.tooltip == "All enabled agents repositories are synchronized"


def test_indicator_projection_performs_no_io(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("indicator projection must stay in-memory")

    monkeypatch.setattr(Path, "read_text", fail)
    monkeypatch.setattr(subprocess, "run", fail)
    indicator = AgentsSyncIndicator()

    indicator.set_status(
        _snapshot(
            ProjectSyncStatus(
                "a",
                "Alpha",
                "ready",
                unexported_agents=3,
            )
        )
    )

    assert indicator._build_content(indicator.pending_projects).plain == " ⇅ 1 "
    assert "3 unexported agents" in str(indicator.tooltip)


async def test_indicator_click_dispatches_sync_action() -> None:
    from textual.app import App, ComposeResult

    calls: list[str] = []

    class _TestApp(App[None]):
        def compose(self) -> ComposeResult:
            yield AgentsSyncIndicator(id="agents-sync-indicator")

        def action_sync_agents(self) -> None:
            calls.append("sync")

    app = _TestApp()
    async with app.run_test() as pilot:
        indicator = pilot.app.query_one(
            "#agents-sync-indicator",
            AgentsSyncIndicator,
        )
        indicator.set_status(
            _snapshot(ProjectSyncStatus("a", "Alpha", "ready", behind=1))
        )
        await pilot.click("#agents-sync-indicator")
        await pilot.pause()

    assert calls == ["sync"]


async def test_mounted_indicator_updates_once_for_same_projection() -> None:
    from textual.app import App, ComposeResult

    class _TestApp(App[None]):
        def compose(self) -> ComposeResult:
            yield AgentsSyncIndicator(id="agents-sync-indicator")

    app = _TestApp()
    async with app.run_test() as pilot:
        indicator = pilot.app.query_one(
            "#agents-sync-indicator",
            AgentsSyncIndicator,
        )
        original_update = indicator.update
        update = Mock(wraps=original_update)
        indicator.update = update  # type: ignore[method-assign]
        pending = _snapshot(ProjectSyncStatus("a", "Alpha", "ready", behind=1))

        indicator.set_status(pending)
        indicator.set_status(SyncStatusSnapshot(99.0, pending.projects))

        assert update.call_count == 1
