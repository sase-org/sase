"""Archive restore-run proof through the real revive path (phase archive-restore-run).

Each test drives :func:`run_archive_restore` into the real
``AgentReviveExecutionMixin._do_revive_agents`` on a fake app that keeps
the production scheduler shape (the delta refresh — and the quiet
completion — runs synchronously). Artifact files are really written under
a redirected ``SASE_HOME``; only the Archive column read and bundle load
are wired to fixed rows, the same way the mounted harness feeds them.

Covered: one toast for a single restore, parked-Inbox preservation,
bulk counts with skip reasons, failure reasons, the immediate pulse
bump, restore-and-show reveal after the refresh, the filtered-target
rule for a hiding Inbox filter, and the off-loop submit variant.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from sase.ace.tui.actions.agents._archive_restore import (
    run_archive_restore,
    run_archive_restore_async,
)
from sase.ace.tui.actions.agents._archive_view import init_agents_archive_view_state
from sase.ace.tui.models.agent import AgentType
from sase.ace.tui.actions.agents._archive_controller import archive_inbox_pulse
from sase.ace.tui.models.agent_archive_view import (
    AGENTS_VIEW_ARCHIVE,
    AGENTS_VIEW_INBOX,
    ARCHIVE_SECTION_LIST,
)
from tests._agent_revive_helpers import RealArtifactReviveApp, make_agent
from tests._conftest_environment import redirect_sase_home

_KEY = "u.m@r1"
_NOW = datetime(2026, 10, 10, 20, 0, tzinfo=UTC)


def _agent(tmp_path: Path, name: str = "restored.one", **overrides: Any) -> Any:
    project_dir = tmp_path / "proj"
    artifacts_dir = project_dir / "artifacts" / "ace-run" / "20260527120000"
    fields: dict[str, Any] = {
        "agent_type": AgentType.RUNNING,
        "cl_name": name,
        "agent_name": name,
        "project_file": str(project_dir / "proj.sase"),
        "status": "DONE",
        "start_time": _NOW,
        "raw_suffix": "20260527120000",
        "artifacts_dir": str(artifacts_dir),
    }
    fields.update(overrides)
    return make_agent(**fields)


def _app(
    tmp_path: Path, monkeypatch: Any, agent: Any, *, key: str = _KEY
) -> RealArtifactReviveApp:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    app = RealArtifactReviveApp()
    init_agents_archive_view_state(app)
    app._agents_archive_view.active_view = AGENTS_VIEW_ARCHIVE
    app._agents_archive_view.archive.selected_key = key
    app._agents_archive_view.archive.focused_section = ARCHIVE_SECTION_LIST
    app._dismissed_agents = {agent.identity}
    app._dismissed_agent_objects = [agent]
    row = {"agent_name": getattr(agent, "cl_name", "restored.one")}
    import sase.ace.tui.actions.agents._archive_column as column
    import sase.ace.tui.actions.agents._archive_reader as reader

    monkeypatch.setattr(column, "archive_light_row", lambda _o, _k: row)
    monkeypatch.setattr(
        reader,
        "_load_archive_bundle",
        lambda _o, _row: {"unreadable": False, "agent": agent},
    )
    return app


def test_proof_single_restore_emits_one_toast_and_marks_overlay(
    tmp_path: Path, monkeypatch: Any
) -> None:
    agent = _agent(tmp_path)
    app = _app(tmp_path, monkeypatch, agent)
    app._agents = []
    app.loaded_agents = [agent]

    summary = run_archive_restore(app)

    assert [name for _key, name in summary.restored] == ["restored.one"]
    assert summary.skipped == () and summary.failed == ()
    # Quiet mode: the batch emits no "Revived 1 agent" of its own.
    assert app.notifications == [
        ("restored.one is back in the inbox · no new run started", "information")
    ]
    assert _KEY in app._agents_archive_view.archive.restored_keys
    # The cursor never moves: the row stays in the Archive.
    assert app._agents_archive_view.active_view == AGENTS_VIEW_ARCHIVE
    assert app._agents_archive_view.archive.selected_key == _KEY
    assert agent.identity not in app._dismissed_agents


def test_proof_plain_restore_leaves_parked_inbox_untouched(
    tmp_path: Path, monkeypatch: Any
) -> None:
    agent = _agent(tmp_path)
    app = _app(tmp_path, monkeypatch, agent)
    parked = _agent(tmp_path, name="parked.inbox", raw_suffix="20260526120000")
    app._agents = [parked]
    app.loaded_agents = [parked, agent]
    app.current_idx = 0
    app._entry_jump_agents_anchor_stack = [("sentinel", 0)]  # type: ignore[attr-defined]
    app._entry_jump_agents_forward_anchor_stack = []  # type: ignore[attr-defined]

    run_archive_restore(app)

    assert app.current_idx == 0
    assert app._current_group_key is None
    assert app._entry_jump_agents_anchor_stack == [("sentinel", 0)]
    assert app._entry_jump_agents_forward_anchor_stack == []
    assert app.current_tab == "agents"
    # The cached-list patch still runs; only selection movement is skipped.
    assert app.refilter_count == 1
    assert len(app.notifications) == 1


def test_proof_bulk_reports_counts_with_reasons_in_one_toast(
    tmp_path: Path, monkeypatch: Any
) -> None:
    good = _agent(tmp_path, name="good.run")
    locked = _agent(tmp_path, name="locked.run", durably_revivable=False)
    gone = _agent(tmp_path, name="gone.run")
    app = _app(tmp_path, monkeypatch, good)
    app._dismissed_agents = {good.identity, locked.identity, gone.identity}
    app._dismissed_agent_objects = [good, locked, gone]
    rows = {
        "u.m@good": {"agent_name": "good.run"},
        "u.m@locked": {"agent_name": "locked.run"},
        "u.m@bad": {"agent_name": "gone.run"},
    }
    bundles = {"good.run": good, "locked.run": locked}
    import sase.ace.tui.actions.agents._archive_column as column
    import sase.ace.tui.actions.agents._archive_reader as reader

    monkeypatch.setattr(column, "archive_light_row", lambda _o, k: rows.get(k))
    monkeypatch.setattr(
        reader,
        "_load_archive_bundle",
        lambda _o, row: (
            {"unreadable": False, "agent": bundles[row["agent_name"]]}
            if row["agent_name"] in ("good.run", "locked.run")
            else {"unreadable": True, "agent": None}
        ),
    )

    summary = run_archive_restore(app, keys=["u.m@good", "u.m@locked", "u.m@bad"])

    assert [name for _key, name in summary.restored] == ["good.run"]
    assert len(summary.skipped) == 2
    assert len(app.notifications) == 1
    message, severity = app.notifications[0]
    assert message.startswith("Restored 1 · skipped 2 (")
    assert "can't restore" in message
    assert "bundle unreadable" in message
    assert "failed 0" in message
    assert severity == "information"


def test_proof_failure_reports_reason_in_one_toast(
    tmp_path: Path, monkeypatch: Any
) -> None:
    agent = _agent(tmp_path)
    app = _app(tmp_path, monkeypatch, agent)

    def _boom(_agent: Any, **_kwargs: Any) -> None:
        raise OSError("disk is gone")

    monkeypatch.setattr(app, "_restore_agent_artifacts", _boom)

    summary = run_archive_restore(app)

    assert summary.restored == ()
    assert len(summary.failed) == 1
    assert summary.failed[0][2] == "disk is gone"
    assert _KEY not in app._agents_archive_view.archive.restored_keys
    assert len(app.notifications) == 1
    message, severity = app.notifications[0]
    assert "Restored 0" in message
    assert "failed 1 (disk is gone)" in message
    assert severity == "warning"


def test_proof_pulse_bumps_as_soon_as_revive_lands(
    tmp_path: Path, monkeypatch: Any
) -> None:
    agent = _agent(tmp_path)
    app = _app(tmp_path, monkeypatch, agent)
    app._agents = []
    app.loaded_agents = [agent]
    before = archive_inbox_pulse(app)

    run_archive_restore(app)

    after = archive_inbox_pulse(app)
    assert before.total == 0
    assert after.total == 1


def test_proof_restore_and_show_reveals_after_refresh(
    tmp_path: Path, monkeypatch: Any
) -> None:
    agent = _agent(tmp_path)
    app = _app(tmp_path, monkeypatch, agent)
    active = _agent(tmp_path, name="active.inbox", raw_suffix="20260526120000")
    app._agents = [active]
    app.loaded_agents = [active, agent]
    from sase.ace.tui.models.agent_panels import AgentPanelGroup

    app._panel_group = AgentPanelGroup.from_agents(app._agents, None)
    app.current_idx = 0

    summary = run_archive_restore(app, and_show=True)

    assert summary.and_show is True
    assert [name for _key, name in summary.restored] == ["restored.one"]
    # The reveal waits for the revive refresh, then leaves the Archive.
    assert app._agents_archive_view.active_view == AGENTS_VIEW_INBOX
    assert app._agents[app.current_idx].identity == agent.identity
    assert app.notifications == [
        ("restored.one is back in the inbox · showing in Inbox", "information")
    ]


def test_proof_restore_and_show_hidden_by_filter_applies_filtered_rule(
    tmp_path: Path, monkeypatch: Any
) -> None:
    agent = _agent(tmp_path)
    app = _app(tmp_path, monkeypatch, agent)
    app._agents = []
    app._agents_with_children = [agent]
    app.loaded_agents = [agent]
    transitions: list[tuple[str, str]] = []
    commits: list[str] = []
    app._record_agents_live_query_transition = (  # type: ignore[attr-defined]
        lambda old, new: transitions.append((old, new))
    )
    app._record_explicit_agents_query_commit = commits.append  # type: ignore[attr-defined]
    app._agent_search_query = "status:FAILED"
    # The direct reveal cannot reach the row although it is loaded: the
    # parked Inbox filter hides it, so the filtered-target rule applies.
    app._select_revived_agent = lambda _agent: False  # type: ignore[attr-defined]
    app._reveal_loaded_agent = lambda _agent: False  # type: ignore[attr-defined]
    app._select_visible_loaded_agent = lambda _name: True  # type: ignore[attr-defined]

    run_archive_restore(app, and_show=True)

    assert app._agents_archive_view.active_view == AGENTS_VIEW_INBOX
    assert len(commits) == 1 and commits[0].startswith("name:")
    # The old query is pushed for ^ restoration.
    assert transitions == [("status:FAILED", commits[0])]
    assert len(app.notifications) == 1
    message, _severity = app.notifications[0]
    assert "^ restores your filter" in message


def test_proof_async_submit_hydrates_off_thread(
    tmp_path: Path, monkeypatch: Any
) -> None:
    agent = _agent(tmp_path)
    app = _app(tmp_path, monkeypatch, agent)
    app._agents = []
    app.loaded_agents = [agent]

    summary = asyncio.run(run_archive_restore_async(app, keys=[_KEY]))

    assert [name for _key, name in summary.restored] == ["restored.one"]
    assert len(app.notifications) == 1


def test_proof_async_submit_aborts_quietly_off_archive(
    tmp_path: Path, monkeypatch: Any
) -> None:
    agent = _agent(tmp_path)
    app = _app(tmp_path, monkeypatch, agent)
    app._agents_archive_view.active_view = AGENTS_VIEW_INBOX

    summary = asyncio.run(run_archive_restore_async(app, keys=[_KEY]))

    assert summary.restored == () and summary.failed == ()
    assert app.notifications == []


def test_proof_dimmed_restored_row_render() -> None:
    from sase.ace.tui.models.agent_archive_list import ITEM_ROW, ArchiveListItem
    from sase.ace.tui.widgets.agents_archive._rows import (
        ArchiveRenderContext,
        format_archive_item,
    )

    item = ArchiveListItem(
        kind=ITEM_ROW, key=_KEY, selectable=True, row={"agent_name": "restored.one"}
    )
    plain = format_archive_item(item, ArchiveRenderContext(width=56))
    dimmed = format_archive_item(
        item, ArchiveRenderContext(width=56, restored_keys=frozenset({_KEY}))
    )
    assert "⌂ restored" not in plain.plain
    assert "⌂ restored" in dimmed.plain
    name_spans = [
        span
        for span in dimmed.spans
        if "restored.one" in dimmed.plain[span.start : span.end]
    ]
    assert name_spans, "restored row must keep the run name"
    assert any("dim" in str(span.style) for span in name_spans)
