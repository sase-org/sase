"""Retire-pane coverage: pane query migration, redirect, and notice."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from sase.ace import _agents_pane_query_migration as migration
from sase.ace._agents_pane_query_migration import _convert_agents_pane_query
from sase.ace.query_record import QueryRecord
from sase.feature_flags import override_flags


def test_convert_prepends_scope_and_rewrites_terms() -> None:
    assert (
        _convert_agents_pane_query("linked:true tribe:core limit:100")
        == "in:archive linked:true clan_tribe:core"
    )
    assert _convert_agents_pane_query("state:dismissed AND revivable:true") is None
    assert _convert_agents_pane_query("") == "in:archive"
    assert _convert_agents_pane_query("  ") == "in:archive"


def test_convert_drops_dismissed_markers_and_keeps_quotes() -> None:
    assert (
        _convert_agents_pane_query('dismissed:true name:"my agent"')
        == 'in:archive name:"my agent"'
    )
    assert (
        _convert_agents_pane_query("LIMIT:10 status:done") == "in:archive status:done"
    )
    assert _convert_agents_pane_query("-tribe:core") == "in:archive -clan_tribe:core"
    assert _convert_agents_pane_query("a OR b") is None
    assert _convert_agents_pane_query("(a b)") is None


@pytest.fixture
def _migration_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import sase.ace.query_history as history
    import sase.ace.saved_queries as slots

    # Suppress the load-path migration while fixtures seed the old stores.
    monkeypatch.setattr(migration, "_migration_done_this_process", True)
    with (
        patch.object(slots, "_SAVED_QUERIES_FILE", tmp_path / "saved_queries.json"),
        patch.object(history, "_QUERY_HISTORY_FILE", tmp_path / "query_history.json"),
        patch.object(migration, "_MARKER_FILE", tmp_path / "migrated"),
    ):
        yield tmp_path


def test_migration_moves_slots_and_history_once(
    _migration_files: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sase.ace.query_history as history
    import sase.ace.saved_queries as slots

    assert slots.save_query("agents", "1", "linked:true limit:50", "linked:true")
    assert slots.save_query("agents", "2", "a OR b", "a OR b")
    assert history.save_query_history(
        "agents",
        history.QueryHistoryStacks(
            prev=[QueryRecord(source="tribe:core", canonical="tribe:core")],
            next=[],
        ),
    )
    monkeypatch.setattr(migration, "_migration_done_this_process", False)
    with override_flags(artifacts_agent_pane_retired=True):
        assert migration.ensure_agents_pane_queries_migrated() is True
        # Second call is a no-op: the marker makes it idempotent.
        assert migration.ensure_agents_pane_queries_migrated() is False

    live = slots.load_saved_queries("agents-live")
    assert live["0"].source == "in:archive linked:true"
    # Boolean entries stay in the old namespace.
    assert set(slots.load_saved_queries("agents")) == {"2"}
    live_history = history.load_query_history("agents-live")
    assert [record.source for record in live_history.prev] == [
        "in:archive clan_tribe:core"
    ]
    assert history.load_query_history("agents").prev == []


def test_migration_never_overwrites_live_slots(
    _migration_files: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sase.ace.saved_queries as slots

    assert slots.save_query(
        "agents-live", "0", "in:archive linked:true", "in:archive linked:true"
    )
    assert slots.save_query("agents", "1", "linked:true", "linked:true")
    monkeypatch.setattr(migration, "_migration_done_this_process", False)
    with override_flags(artifacts_agent_pane_retired=True):
        assert migration.ensure_agents_pane_queries_migrated() is True

    live = slots.load_saved_queries("agents-live")
    assert set(live) == {"0"}
    assert live["0"].source == "in:archive linked:true"


def test_migration_skipped_while_pane_alive(
    _migration_files: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sase.ace.saved_queries as slots

    assert slots.save_query("agents", "1", "linked:true", "linked:true")
    monkeypatch.setattr(migration, "_migration_done_this_process", False)
    with override_flags(artifacts_agent_pane_retired=False):
        assert migration.ensure_agents_pane_queries_migrated() is False
    assert set(slots.load_saved_queries("agents")) == {"1"}
    assert slots.load_saved_queries("agents-live") == {}


def test_show_artifacts_agents_redirects_to_archive_when_retired() -> None:
    from sase.ace.tui.actions.artifacts_navigation import (
        ArtifactsNavigationActionsMixin,
    )

    opened: list[str] = []

    class _Owner(ArtifactsNavigationActionsMixin):
        def action_open_agents_archive(self) -> None:
            opened.append("archive")

        def _switch_artifacts_subtab(self, subtab: str) -> None:
            opened.append(subtab)

    with override_flags(artifacts_agent_pane_retired=True):
        _Owner().action_show_artifacts_agents()
    assert opened == ["archive"]
    with override_flags(artifacts_agent_pane_retired=False):
        _Owner().action_show_artifacts_agents()
    assert opened == ["archive", "agents"]


def test_pane_retirement_notice_marker(tmp_path: Path) -> None:
    from sase.ace.tui import _artifacts_agent_pane_notice as notice

    marker = tmp_path / "notice"
    with patch.object(notice, "_marker_path", lambda: marker):
        assert notice.has_shown_artifacts_agent_pane_notice() is False
        notice.mark_artifacts_agent_pane_notice_shown()
        assert notice.has_shown_artifacts_agent_pane_notice() is True


def test_startup_toast_fires_once_then_silences_while_retired(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.ace.tui import _artifacts_agent_pane_notice as notice
    from sase.ace.tui.actions._startup_loads_maintenance import (
        StartupLoadsMaintenanceMixin,
    )

    marker = tmp_path / "notice"
    monkeypatch.setattr(notice, "_marker_path", lambda: marker, raising=False)

    shown: list[str] = []

    class _App(StartupLoadsMaintenanceMixin):
        def notify(self, message: str, **kwargs: object) -> None:
            shown.append(message)

    with override_flags(artifacts_agent_pane_retired=True):
        _App()._maybe_show_artifacts_agent_pane_toast()
    assert shown == ["Agent history moved to the Agents tab · ,a opens the Archive"]
    with override_flags(artifacts_agent_pane_retired=True):
        _App()._maybe_show_artifacts_agent_pane_toast()
    assert len(shown) == 1


def test_pane_show_agents_explains_the_move(capsys: pytest.CaptureFixture[str]) -> None:
    from sase.artifact_cli.pane import _handle_show

    args = SimpleNamespace(pane_id="agents", json=False)
    with override_flags(artifacts_agent_pane_retired=True):
        assert _handle_show(args) == 0
    out = capsys.readouterr().out
    assert "Agent history moved to the Agents tab" in out
    assert ",a" in out
