"""Container and marks restore proof through the real revive path.

The Archive column runs on a real list model over the model corpus, so a
collapsed container really has no loaded members and the restore resolver
must ask the corpus for them. Restores go through the real
``AgentReviveExecutionMixin._do_revive_agents`` with artifact files written
under a redirected ``SASE_HOME``; only the bundle load is wired to fixed
agents. The chooser test proves the Restore label's count is the executed
restore's count.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sase.ace.tui.actions.agents._archive_restore import (
    CHOICE_RESTORE,
    open_archive_chooser,
    run_archive_restore,
)
from sase.ace.tui.actions.agents._archive_view import route_archive_key
from sase.ace.tui.models.agent import AgentType
from sase.ace.tui.models.agent_archive_view import INTENT_EXPAND
from tests._agent_revive_helpers import RealArtifactReviveApp, make_agent
from tests._conftest_environment import redirect_sase_home
from tests.ace.tui._agent_archive_column_actions_helpers import clan_rows, opened
from tests.ace.tui._agent_archive_column_helpers import ColumnHarness

_CONTAINER = "container:clan:swarm:1"
_MEMBERS = ["swarm.one", "swarm.three", "swarm.two"]
_NOW = datetime(2026, 10, 10, 20, 0, tzinfo=UTC)


def _agent(tmp_path: Path, name: str, raw_suffix: str) -> Any:
    project_dir = tmp_path / "proj"
    return make_agent(
        agent_type=AgentType.RUNNING,
        cl_name=name,
        agent_name=name,
        project_file=str(project_dir / "proj.sase"),
        status="DONE",
        start_time=_NOW,
        raw_suffix=raw_suffix,
        artifacts_dir=str(project_dir / "artifacts" / "ace-run" / raw_suffix),
    )


async def _container_app(
    tmp_path: Path, monkeypatch: Any, *, expand: bool = False
) -> tuple[RealArtifactReviveApp, ColumnHarness]:
    """Return a revive app sharing a real Archive column over ``clan_rows``.

    The cursor starts on the collapsed ``swarm`` clan container (three
    members), above the solo run ``loner``.
    """
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    rows = clan_rows()
    harness = await opened(rows)
    if expand:
        route_archive_key(harness.owner, INTENT_EXPAND)
        await harness.settle()
    app = RealArtifactReviveApp()
    for name, value in vars(harness.owner).items():
        if name.startswith(("_agents_archive", "_archive")):
            setattr(app, name, value)
    agents = {
        row["agent_name"]: _agent(tmp_path, row["agent_name"], f"2026052712000{i}")
        for i, row in enumerate(rows)
    }
    app._dismissed_agents = {agent.identity for agent in agents.values()}
    app._dismissed_agent_objects = list(agents.values())
    app._agents = []
    app.loaded_agents = list(agents.values())
    import sase.ace.tui.actions.agents._archive_reader as reader

    monkeypatch.setattr(
        reader,
        "_load_archive_bundle",
        lambda _owner, row: {"unreadable": False, "agent": agents[row["agent_name"]]},
    )
    return app, harness


def _restored_names(summary: Any) -> list[str]:
    return sorted(name for _key, name in summary.restored)


async def test_collapsed_container_restores_members_from_the_corpus(
    tmp_path: Path, monkeypatch: Any
) -> None:
    app, harness = await _container_app(tmp_path, monkeypatch)
    assert app._agents_archive_view.archive.selected_key == _CONTAINER
    assert app._agents_archive_view.archive.expanded_containers == ()

    summary = run_archive_restore(app)

    assert _restored_names(summary) == _MEMBERS
    assert summary.skipped == () and summary.failed == ()
    assert harness.corpus.rows_calls[-1]["expanded"] == ("clan:swarm:1",)
    assert "in:archive" not in harness.corpus.queries


async def test_expanded_container_restores_its_loaded_members(
    tmp_path: Path, monkeypatch: Any
) -> None:
    app, harness = await _container_app(tmp_path, monkeypatch, expand=True)
    assert app._agents_archive_view.archive.expanded_containers == ("clan:swarm:1",)
    rows_calls = len(harness.corpus.rows_calls)

    summary = run_archive_restore(app)

    assert _restored_names(summary) == _MEMBERS
    # Loaded members answer without a second corpus query.
    assert len(harness.corpus.rows_calls) == rows_calls


async def test_only_a_collapsed_container_marked_restores_its_members(
    tmp_path: Path, monkeypatch: Any
) -> None:
    app, _harness = await _container_app(tmp_path, monkeypatch)
    archive = app._agents_archive_view.archive
    archive.selected_key = "u.m@solo"
    archive.marks = frozenset({_CONTAINER})

    summary = run_archive_restore(app)

    # The marked container's members, never the cursor's solo run.
    assert _restored_names(summary) == _MEMBERS
    assert summary.skipped == () and summary.failed == ()


async def test_container_and_run_both_marked_restore_together(
    tmp_path: Path, monkeypatch: Any
) -> None:
    app, _harness = await _container_app(tmp_path, monkeypatch)
    app._agents_archive_view.archive.marks = frozenset({_CONTAINER, "u.m@solo"})

    summary = run_archive_restore(app)

    assert _restored_names(summary) == sorted([*_MEMBERS, "loner"])


async def test_chooser_label_count_is_the_executed_restore_count(
    tmp_path: Path, monkeypatch: Any
) -> None:
    import sase.ace.tui.modals.agent_action_chooser_modal as modal_module

    app, harness = await _container_app(tmp_path, monkeypatch)
    app._agents_archive_view.archive.marks = frozenset({_CONTAINER, "u.m@solo"})
    pushed: list[tuple[Any, Any]] = []
    app.push_screen = lambda modal, callback: pushed.append((modal, callback))  # type: ignore[attr-defined]

    class _FakeChooser:
        def __init__(self, choices: Any, *, title: str, initial_index: int = 0) -> None:
            self.choices = tuple(choices)

    monkeypatch.setattr(modal_module, "AgentActionChooserModal", _FakeChooser)

    assert open_archive_chooser(app, _CONTAINER) is True
    await harness.settle()
    assert len(pushed) == 1
    chooser, on_choice = pushed[0]
    restore = next(c for c in chooser.choices if c.result == CHOICE_RESTORE)
    assert restore.label == "Restore 4 marked"

    on_choice(CHOICE_RESTORE)
    await harness.settle()

    assert app._agents_archive_view.archive.restored_keys == {
        "u.m@m1",
        "u.m@m2",
        "u.m@m3",
        "u.m@solo",
    }
    assert app.notifications[-1] == (
        "Restored 4 · skipped 0 · failed 0",
        "information",
    )
