"""Collapsed-clan reveal coverage for Agents-tab jump entry points."""

from __future__ import annotations

from typing import Any

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.actions.agents._notification_navigation import (
    navigate_to_agent_tab,
    navigate_to_named_agent,
)
from sase.ace.tui.models._agent_tree import agent_fold_key
from sase.ace.tui.models.fold_state import FoldLevel
from tests.ace.tui.visual._ace_png_snapshot_startup import (
    patch_startup_loaders,
    wait_for_startup,
)

from ._agent_jump_clan_helpers import (
    CLAN_NAME,
    PROJECT_CL_NAME,
    ClanJumpHarness,
    collapsed_clan,
    make_realistic_agent,
    realistic_collapsed_clan,
)


def _clan_key(container: Any) -> str:
    clan_key = agent_fold_key(container)
    assert clan_key is not None
    return clan_key


def _assert_revealed(app: ClanJumpHarness, container: Any, target: Any) -> None:
    assert app._agents[app.current_idx].identity == target.identity
    assert app._fold_manager.get(_clan_key(container)) is not FoldLevel.COLLAPSED


def test_named_agent_reveals_collapsed_clan_member_by_artifact_dir() -> None:
    app, container, target, _sibling = realistic_collapsed_clan()
    assert all(agent.identity != target.identity for agent in app._agents)

    assert (
        navigate_to_named_agent(
            app,
            target.agent_name,
            artifact_dir=target.artifacts_dir,
        )
        is True
    )
    _assert_revealed(app, container, target)
    other_key = agent_fold_key(container)
    assert other_key is not None
    assert app._fold_manager.get(other_key) is not FoldLevel.COLLAPSED


def test_named_agent_falls_back_to_name_and_monitor_id() -> None:
    app, container, target, _sibling = realistic_collapsed_clan()
    assert navigate_to_named_agent(app, target.agent_name, artifact_dir=None) is True
    _assert_revealed(app, container, target)

    app, container, target, _sibling = realistic_collapsed_clan()
    assert (
        navigate_to_named_agent(app, target.agent_name, artifact_dir="/no-such-dir")
        is True
    )
    _assert_revealed(app, container, target)

    app, container, target, _sibling = realistic_collapsed_clan()
    target.monitor_id = "mon-xyz"
    assert navigate_to_named_agent(app, "mon-xyz") is True
    _assert_revealed(app, container, target)


def test_named_agent_artifact_dir_beats_visible_name_match() -> None:
    app, container, target, sibling = realistic_collapsed_clan(
        with_sibling=True, duplicate_name=True
    )
    assert sibling is not None
    assert sibling.agent_name == target.agent_name
    assert sibling.artifacts_dir != target.artifacts_dir
    assert app._agents[app.current_idx].identity == sibling.identity

    assert (
        navigate_to_named_agent(
            app,
            target.agent_name,
            artifact_dir=target.artifacts_dir,
        )
        is True
    )
    _assert_revealed(app, container, target)


def test_named_agent_does_not_select_project_cl_name_sibling() -> None:
    app, container, target, sibling = realistic_collapsed_clan(with_sibling=True)
    assert sibling is not None
    assert sibling.cl_name == target.cl_name == PROJECT_CL_NAME
    assert sibling.agent_name != target.agent_name
    assert app._agents[app.current_idx].identity == sibling.identity

    assert (
        navigate_to_named_agent(
            app,
            target.agent_name,
            artifact_dir=target.artifacts_dir,
        )
        is True
    )
    _assert_revealed(app, container, target)


def test_named_agent_unknown_name_warns() -> None:
    app, _container, _target, _sibling = realistic_collapsed_clan()
    assert navigate_to_named_agent(app, "ghost") is False
    assert app.notifications == ["Agent 'ghost' not found"]


def test_runners_raw_suffix_selects_hidden_clan_member() -> None:
    app, container, target, sibling = realistic_collapsed_clan(with_sibling=True)
    assert sibling is not None
    assert sibling.cl_name == target.cl_name
    assert app._agents[app.current_idx].identity == sibling.identity

    assert (
        navigate_to_agent_tab(
            app,
            target.cl_name,
            pid=None,
            raw_suffix=target.raw_suffix,
        )
        is True
    )
    _assert_revealed(app, container, target)


def test_select_file_agent_reveals_collapsed_clan_member() -> None:
    from sase.ace.tui.actions.artifacts_files import ArtifactsFilesActionsMixin

    class _App(ArtifactsFilesActionsMixin, ClanJumpHarness):
        pass

    app, container, target = collapsed_clan(harness_cls=_App)
    assert all(agent.identity != target.identity for agent in app._agents)
    assert app._select_file_agent(target.identity, target.raw_suffix) is True
    _assert_revealed(app, container, target)


def test_restore_agents_link_trail_hop_reveals_collapsed_clan_member() -> None:
    from sase.ace.tui.actions._link_follow_types import LinkTrailHop
    from sase.ace.tui.actions.link_trail import LinkTrailMixin
    from sase.core.artifact_entry_target import ArtifactEntryTarget

    class _App(LinkTrailMixin, ClanJumpHarness):
        pass

    app, container, target = collapsed_clan(harness_cls=_App)
    hop = LinkTrailHop(
        tab="agents",
        pane_key=None,
        origin=ArtifactEntryTarget("agents", (target.agent_name,)),
        query_source=None,
    )
    assert app._restore_agents_link_trail_hop(hop) is True
    _assert_revealed(app, container, target)


def test_reveal_loaded_agent_reveals_collapsed_clan_member() -> None:
    from sase.ace.tui.actions._link_follow_targets import LinkFollowTargetsMixin

    class _App(LinkFollowTargetsMixin, ClanJumpHarness):
        pass

    app, container, target = collapsed_clan(harness_cls=_App)
    assert app._reveal_loaded_agent(target) is True
    _assert_revealed(app, container, target)


def test_reveal_last_launch_target_reveals_collapsed_clan_member() -> None:
    from sase.ace.tui.actions.agent_workflow._kill_last_launch import (
        KillAndEditLastLaunchMixin,
    )

    class _App(KillAndEditLastLaunchMixin, ClanJumpHarness):
        pass

    app, container, target = collapsed_clan(harness_cls=_App)
    app._reveal_last_launch_target(target.identity)
    _assert_revealed(app, container, target)


def test_open_tool_run_reveals_collapsed_clan_member(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.ace.tui.actions.agents import _notification_handlers as handlers
    from sase.notifications import Notification

    app, container, target = collapsed_clan()
    monkeypatch.setattr(
        handlers, "_resolve_visible_tool_run_node", lambda _app, _rid: target
    )
    notification = Notification(
        id="n-open",
        timestamp="2026-09-27T12:00:00+00:00",
        sender="tool-run",
        action="OpenToolRun",
        action_data={"run_id": "r" * 32},
    )
    assert handlers.handle_open_tool_run(app, notification) is True
    _assert_revealed(app, container, target)


def test_reveal_tool_run_block_reveals_collapsed_clan_member() -> None:
    from sase.ace.tui.tool_runs.reveal import reveal_tool_run_block

    app, container, target = collapsed_clan()
    assert reveal_tool_run_block(app, "a" * 32, agent=target.agent_name) is True
    _assert_revealed(app, container, target)


async def test_real_app_named_agent_jump_expands_collapsed_clan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.ace.tui.models._agent_tree import agent_fold_key as fold_key_of

    first = make_realistic_agent(
        f"{CLAN_NAME}.land",
        clan=CLAN_NAME,
        artifacts_dir=f"/{CLAN_NAME}.land",
    )
    second = make_realistic_agent(
        f"{CLAN_NAME}.plan",
        clan=CLAN_NAME,
        artifacts_dir=f"/{CLAN_NAME}.plan",
    )
    patch_startup_loaders(monkeypatch, agents=[first, second])

    async with AcePage(initial_tab="agents") as page:
        await wait_for_startup(page)
        app = page.app
        target = next(
            agent
            for agent in app._agents_with_children
            if getattr(agent, "raw_suffix", None) == second.raw_suffix
        )
        container = next(
            agent
            for agent in app._agents_with_children
            if getattr(agent, "is_clan_container", False)
        )
        fold_key = fold_key_of(container)
        assert fold_key is not None
        app._fold_manager.collapse(fold_key)
        app._refilter_agents()
        assert all(agent.identity != target.identity for agent in app._agents)

        app._save_current_tab_position()
        app._switch_to_tab("artifacts")

        assert (
            navigate_to_named_agent(
                app,
                target.agent_name,
                artifact_dir=target.artifacts_dir,
            )
            is True
        )
        await page.pause()

        assert app.current_tab == "agents"
        selected = app._agents[app.current_idx]
        assert selected.identity == target.identity
        assert app._fold_manager.get(fold_key) is not FoldLevel.COLLAPSED
