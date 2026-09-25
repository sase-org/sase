"""Agent/File context queries and Agents-tab reveal for artifact link jumps."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.actions._link_follow_targets import LinkFollowTargetsMixin
from sase.ace.tui.models._agent_tree import agent_fold_key
from sase.ace.tui.models.agent_panels import AgentPanelGroup
from sase.ace.tui.models.fold_state import FoldLevel
from sase.ace.tui.widgets.artifacts import agents_pane, files_pane
from sase.ace.tui.widgets.artifacts.agents_data import AgentsSnapshot
from sase.ace.tui.widgets.artifacts.agents_navigation import AgentsNavigationMixin
from sase.ace.tui.widgets.artifacts.agents_pane import ArtifactsAgentsPane
from sase.ace.tui.widgets.artifacts.entry_navigation import ArtifactEntryTarget
from sase.ace.tui.widgets.artifacts.files_data import FilesSnapshot
from sase.ace.tui.widgets.artifacts.files_filtering import parse_files_filter_query
from sase.ace.tui.widgets.artifacts.files_navigation import FilesNavigationMixin
from sase.ace.tui.widgets.artifacts.files_pane import ArtifactsFilesPane
from tests._agent_catalog_helpers import make_agent_catalog_row
from tests.ace.tui._artifacts_files_helpers import (
    artifact_file,
    logical_file,
    snapshot,
)
from tests.ace.tui._link_follow_helpers import _App, _Pane, _chip
from tests.ace.tui._member_jump_navigation_helpers import (
    JumpHarness,
    make_agent,
    make_clan,
)


def _agent_rows() -> tuple:
    return (
        make_agent_catalog_row("atlas.1", project="alpha"),
        make_agent_catalog_row("atlas.2", project="alpha"),
        make_agent_catalog_row("atlas.3", project="alpha"),
        make_agent_catalog_row("other", project="alpha"),
    )


def _load_agents(rows: tuple):
    def load(project: str | None, limit: int | None = None) -> AgentsSnapshot:
        if limit is None:
            return AgentsSnapshot(
                project=project,
                rows=rows,
                total_row_count=len(rows),
                complete=True,
            )
        return AgentsSnapshot(
            project=project,
            rows=rows,
            total_row_count=len(rows) + 1,
            complete=False,
        )

    return load


async def _open_agents(
    page: AcePage, monkeypatch: pytest.MonkeyPatch, rows: tuple
) -> ArtifactsAgentsPane:
    monkeypatch.setattr(agents_pane, "load_agents_snapshot", _load_agents(rows))
    await page.press(page.artifacts_digit("agents"))
    pane = page.query_one_widget("#artifacts-agents-pane", ArtifactsAgentsPane)
    await page.wait_for(
        lambda _state: (
            pane.snapshot is not None
            and pane.snapshot.complete
            and pane._query_index is not None
        )
    )
    return pane


async def _open_files(
    page: AcePage, monkeypatch: pytest.MonkeyPatch, rows: tuple
) -> ArtifactsFilesPane:
    monkeypatch.setattr(
        files_pane,
        "load_files_snapshot",
        lambda project, _limit: snapshot(rows, project=project),
    )
    await page.press(page.artifacts_digit("files"))
    pane = page.query_one_widget("#artifacts-files-pane", ArtifactsFilesPane)
    await page.wait_for(lambda _state: pane.snapshot is not None)
    await page.wait_for(lambda _state: len(pane.entry_targets()) == len(rows))
    return pane


async def test_agent_hood_context_from_filtered_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with AcePage(initial_tab="patches") as page:
        pane = await _open_agents(page, monkeypatch, _agent_rows())
        before = ArtifactEntryTarget("agents", ("other",))
        assert pane.select_entry_target(before)
        pane._commit_agents_query("name:other limit:100")
        await page.wait_for(
            lambda _state: (
                ArtifactEntryTarget("agents", ("atlas.1",)) not in pane.entry_targets()
            )
        )

        app = page.app
        app._note_artifacts_selection_for_link_trail()
        origin = app._current_link_trail_origin()
        chip = ArtifactEntryTarget("agents", ("atlas.1",))
        app._follow_artifacts_target("agent:atlas.1", chip, origin)
        await page.wait_for(lambda _state: app._link_follow_transaction is None)

        target = ArtifactEntryTarget("agents", ("atlas.1",))
        assert pane.selected_entry_target() == target
        assert pane.host_limit_query() == "name:atlas.* limit:100"

        reveal = app._link_reveals["agents"]
        assert reveal.origin.canonical == "name:other limit:100"
        assert reveal.label == "atlas hood"

        app.action_prev_query()
        await page.wait_for(
            lambda _state: pane.host_limit_query() == "name:other limit:100"
        )
        assert pane.selected_entry_target() == before


async def test_agent_limit_raised_by_member_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with AcePage(initial_tab="patches") as page:
        pane = await _open_agents(page, monkeypatch, _agent_rows())
        pane._commit_agents_query("limit:1")
        target = ArtifactEntryTarget("agents", ("atlas.3",))
        await page.wait_for(
            lambda _state: (
                target not in pane.entry_targets() and len(pane.entry_targets()) == 1
            )
        )

        app = page.app
        app._note_artifacts_selection_for_link_trail()
        origin = app._current_link_trail_origin()
        chip = ArtifactEntryTarget("agents", ("atlas.3",))
        app._follow_artifacts_target("agent:atlas.3", chip, origin)
        await page.wait_for(lambda _state: app._link_follow_transaction is None)

        assert pane.selected_entry_target() == target
        assert pane.host_limit_query() == "name:atlas.* limit:100"


async def test_files_agent_context_from_filtered_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = (
        artifact_file("a", source_path="a.md", agent_name="atlas.1--code"),
        artifact_file("b", source_path="b.md", agent_name="atlas.1--code"),
        artifact_file("c", source_path="c.md", agent_name="other"),
    )
    async with AcePage(initial_tab="patches") as page:
        pane = await _open_files(page, monkeypatch, rows)
        before = ArtifactEntryTarget("files", ("c.md",))
        assert pane.select_entry_target(before)
        pane._commit_files_filter_values(parse_files_filter_query("agent:other"))
        target = ArtifactEntryTarget("files", ("a.md",))
        await page.wait_for(lambda _state: target not in pane.entry_targets())

        app = page.app
        app._note_artifacts_selection_for_link_trail()
        origin = app._current_link_trail_origin()
        app._follow_artifacts_target("file:a.md", target, origin)
        await page.wait_for(lambda _state: app._link_follow_transaction is None)

        assert pane.selected_entry_target() == target
        assert pane.host_limit_query() == "agent:atlas.1--code"

        reveal = app._link_reveals["files"]
        assert reveal.origin.canonical == "agent:other"
        assert reveal.label == "files from atlas.1--code"

        app.action_prev_query()
        await page.wait_for(lambda _state: pane.host_limit_query() == "agent:other")
        assert pane.selected_entry_target() == before


def _agents_stub(rows: tuple):
    snapshot = AgentsSnapshot(
        project=None, rows=rows, total_row_count=len(rows), complete=True
    )
    return SimpleNamespace(
        _snapshot=snapshot,
        project_scope=None,
        _current_snapshot=lambda: snapshot,
    )


def test_agent_family_shell_context() -> None:
    stub = _agents_stub(
        (
            make_agent_catalog_row("big--plan", project="alpha", agent_session="big"),
            make_agent_catalog_row("big--code", project="alpha", agent_session="big"),
            make_agent_catalog_row("other", project="alpha"),
        )
    )
    context = AgentsNavigationMixin.host_reveal_context(
        stub, ArtifactEntryTarget("agents", ("big--code",))
    )
    assert context is not None
    assert context.alternatives == (("session", "big"),)
    assert context.label == "family big"
    assert context.member_count == 2


def test_agent_hood_root_with_members_includes_root() -> None:
    stub = _agents_stub(
        (
            make_agent_catalog_row("atlas", project="alpha"),
            make_agent_catalog_row("atlas.1", project="alpha"),
            make_agent_catalog_row("atlas.2", project="alpha"),
        )
    )
    context = AgentsNavigationMixin.host_reveal_context(
        stub, ArtifactEntryTarget("agents", ("atlas",))
    )
    assert context is not None
    assert context.alternatives == (("name", "atlas"), ("name", "atlas.*"))
    assert context.label == "atlas hood"
    assert context.member_count == 3


def test_agent_hood_member_includes_root_only_when_present() -> None:
    with_root = _agents_stub(
        (
            make_agent_catalog_row("atlas", project="alpha"),
            make_agent_catalog_row("atlas.1", project="alpha"),
        )
    )
    context = AgentsNavigationMixin.host_reveal_context(
        with_root, ArtifactEntryTarget("agents", ("atlas.1",))
    )
    assert context is not None
    assert context.alternatives == (("name", "atlas"), ("name", "atlas.*"))
    assert context.member_count == 2

    without_root = _agents_stub((make_agent_catalog_row("atlas.1", project="alpha"),))
    context = AgentsNavigationMixin.host_reveal_context(
        without_root, ArtifactEntryTarget("agents", ("atlas.1",))
    )
    assert context is not None
    assert context.alternatives == (("name", "atlas.*"),)
    assert context.label == "atlas hood"
    assert context.member_count == 1


def test_agent_lone_name_context() -> None:
    stub = _agents_stub((make_agent_catalog_row("solo", project="alpha"),))
    context = AgentsNavigationMixin.host_reveal_context(
        stub, ArtifactEntryTarget("agents", ("solo",))
    )
    assert context is not None
    assert context.alternatives == (("name", "solo"),)
    assert context.label == "agent solo"
    assert context.member_count == 1


def test_files_id_fallback_without_creating_agent() -> None:
    row = artifact_file("orphan", source_path="orphan.md", agent_name=None)
    logical = logical_file(row)
    model = snapshot((row,), project=None)
    assert isinstance(model, FilesSnapshot)
    stub = SimpleNamespace(
        project_scope=None,
        _current_snapshot=lambda: model,
    )
    context = FilesNavigationMixin.host_reveal_context(
        stub, ArtifactEntryTarget("files", (logical.logical_id,))
    )
    assert context is not None
    assert context.alternatives == (("id", logical.logical_id),)
    assert context.member_count == 1


class _LoadedAgentHarness(JumpHarness, LinkFollowTargetsMixin):
    """Fold/reveal machinery plus the link-follow landing stubs."""

    def __init__(self, complete: list, container) -> None:
        super().__init__(complete, container)
        self.saved_positions = 0
        self.refreshed = 0
        self.rail_refreshed = 0
        self._link_follow_agents_tab_filtered = False

    def _save_current_tab_position(self) -> None:
        self.saved_positions += 1

    def _refresh_current_tab(self) -> None:
        self.refreshed += 1

    def refresh_link_rail(self) -> None:
        self.rail_refreshed += 1


def test_agents_tab_folded_agent_revealed_in_place() -> None:
    complete, container = make_clan(2)
    members = list(container.runtime_children)
    target = members[1]
    app = _LoadedAgentHarness(complete, container)

    clan_key = agent_fold_key(container)
    assert clan_key is not None
    app._fold_manager.collapse(clan_key)
    app._refilter_agents()
    assert all(agent.identity != target.identity for agent in app._agents)

    app.current_tab = "artifacts"
    assert app._follow_loaded_agent("member-1") is True

    assert app.current_tab == "agents"
    assert app._agents[app.current_idx].identity == target.identity
    assert app._fold_manager.get(clan_key) is not FoldLevel.COLLAPSED
    assert app.rail_refreshed == 1
    assert app._link_follow_agents_tab_filtered is False


def test_agents_tab_filtered_agent_reports_fallback() -> None:
    first = make_agent("atlas.1")
    second = make_agent("atlas.2")
    app = _LoadedAgentHarness([first, second], first)

    app._agents = [second]
    app._panel_group = AgentPanelGroup.from_agents(
        app._agents,
        app._panel_group.focused_key,
        merge_tribe_panels=app._agent_panels_grouped,
    )

    assert app._follow_loaded_agent("atlas.1") is False
    assert app._link_follow_agents_tab_filtered is True
    assert app.current_tab == "agents"


def test_agents_tab_fallback_reaches_reveal_outcome() -> None:
    target = ArtifactEntryTarget("agents", ("builder",))
    pane = _Pane(targets=(target,), selected=None, query="name:other")
    app = _App(
        chips=(_chip("agent:builder", target),),
        panes={"agents": pane},
    )
    seen: dict = {}
    original = app._build_reveal_outcome

    def capture(transaction, pane_arg, current, reveal):
        outcome = original(transaction, pane_arg, current, reveal)
        seen["outcome"] = outcome
        return outcome

    app._build_reveal_outcome = capture  # type: ignore[method-assign]
    app._link_trail_guard = False
    origin = app._current_link_trail_origin()
    app._follow_artifacts_target(
        "agent:builder", target, origin, agents_tab_fallback=True
    )

    assert app._link_follow_transaction is None
    assert pane.selected_entry_target() == target
    assert seen["outcome"].agents_tab_fallback is True
