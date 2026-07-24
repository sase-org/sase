"""Pure and mounted coverage for the agents-sync top-bar indicator."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest

from sase.ace.tui.widgets import AgentsSyncIndicator
from sase.agents_sync.models import (
    CapturedIncomingHood,
    ProjectSyncStatus,
    SyncStatusSnapshot,
)


def _snapshot(*statuses: ProjectSyncStatus) -> SyncStatusSnapshot:
    return SyncStatusSnapshot(1.0, statuses)


def _captured(
    project_key: str,
    project: str,
    hood: str,
    *,
    machine: str = "zeus",
    runs: int = 2,
    families: int = 1,
) -> CapturedIncomingHood:
    return CapturedIncomingHood(
        project_key=project_key,
        project=project,
        fetched_ref="refs/remotes/origin/main",
        fetched_sha="a" * 40,
        cache_id=f"cache-{project_key}-{hood}",
        format_version=2,
        source_owner_kind="exact",
        source_username="alice",
        source_machine=machine,
        top_hood=hood,
        hood_digest="b" * 64,
        run_count=runs,
        family_count=families,
        cache_created_at=1.0,
    )


def test_indicator_shows_pending_projects_and_deterministic_tooltip() -> None:
    indicator = AgentsSyncIndicator()
    alpha_updates = (
        _captured("a", "Alpha", "foo"),
        _captured("a", "Alpha", "bar", machine="hera", runs=1, families=0),
    )

    indicator.set_status(
        _snapshot(
            ProjectSyncStatus("z", "Zulu", "error", error="fetch failed"),
            ProjectSyncStatus(
                "a",
                "Alpha",
                "ready",
                ahead=1,
                behind=2,
                pending_updates=alpha_updates,
            ),
            ProjectSyncStatus("current", "Current", "ready", 0, 0, 0),
            ProjectSyncStatus("local", "Local", "ready", ahead=3),
            ProjectSyncStatus("off", "Disabled", "disabled"),
        )
    )

    assert indicator.pending_count == 2
    rendered = indicator._build_content(indicator.pending_projects)
    assert rendered.plain == " ⇅ 2 "
    assert "#5FD787" in repr(rendered.spans)
    assert str(indicator.tooltip) == (
        "Cached foreign agent updates ready to import:\n"
        "Alpha:\n"
        "  alice.hera.bar — 1 run, 0 families\n"
        "  alice.zeus.foo — 2 runs, 1 family\n"
        "Click to import this captured cache without fetching. Press ,U "
        "for the comprehensive cached update."
    )


def test_indicator_clear_and_idempotent_projection() -> None:
    indicator = AgentsSyncIndicator()
    update = _captured("a", "Alpha", "foo")
    pending = _snapshot(
        ProjectSyncStatus("a", "Alpha", "ready", pending_updates=(update,))
    )
    indicator.set_status(pending)
    tooltip = indicator.tooltip
    indicator.set_status(SyncStatusSnapshot(99.0, pending.projects))

    assert indicator.pending_projects == pending.projects
    assert indicator.tooltip == tooltip
    indicator.set_status(_snapshot(ProjectSyncStatus("a", "Alpha", "ready", 0, 0, 0)))
    assert indicator.pending_count == 0
    assert indicator._build_content(indicator.pending_projects).plain == ""
    assert indicator.tooltip == (
        "No cached foreign agent updates are waiting to be imported"
    )


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
                pending_updates=(_captured("a", "Alpha", "foo"),),
            )
        )
    )

    assert indicator._build_content(indicator.pending_projects).plain == " ⇅ 1 "
    assert "alice.zeus.foo" in str(indicator.tooltip)


async def test_indicator_click_dispatches_sync_action() -> None:
    from textual.app import App, ComposeResult

    calls: list[str] = []

    class _TestApp(App[None]):
        def compose(self) -> ComposeResult:
            yield AgentsSyncIndicator(id="agents-sync-indicator")

        def action_integrate_cached_agents(self) -> None:
            calls.append("cached")

    app = _TestApp()
    async with app.run_test() as pilot:
        indicator = pilot.app.query_one(
            "#agents-sync-indicator",
            AgentsSyncIndicator,
        )
        indicator.set_status(
            _snapshot(
                ProjectSyncStatus(
                    "a",
                    "Alpha",
                    "ready",
                    pending_updates=(_captured("a", "Alpha", "foo"),),
                )
            )
        )
        await pilot.click("#agents-sync-indicator")
        await pilot.pause()

    assert calls == ["cached"]


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
        pending = _snapshot(
            ProjectSyncStatus(
                "a",
                "Alpha",
                "ready",
                pending_updates=(_captured("a", "Alpha", "foo"),),
            )
        )

        indicator.set_status(pending)
        indicator.set_status(SyncStatusSnapshot(99.0, pending.projects))

        assert update.call_count == 1
