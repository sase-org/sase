"""Agents-tab `l` jumps to a clan's lone running member."""

from __future__ import annotations

from types import SimpleNamespace

from sase.ace.tui.actions.agents._folding import AgentFoldingMixin
from sase.ace.tui.models._agent_tree import agent_fold_key
from sase.ace.tui.models.fold_state import FoldLevel
from tests.ace.tui._agent_jump_clan_helpers import ClanJumpHarness
from tests.ace.tui._member_jump_navigation_helpers import make_agent


class ClanLJumpHarness(AgentFoldingMixin, ClanJumpHarness):
    """Folding dispatcher over the production-shaped member-jump harness."""

    def __init__(self, complete, container) -> None:  # type: ignore[no-untyped-def]
        self._panel_focus = None
        super().__init__(complete, container)
        # Keep the container selected after the base refilter.
        self.current_idx = next(
            index
            for index, agent in enumerate(self._agents)
            if agent.identity == container.identity
        )

    def _resolve_focused_panel(self):  # type: ignore[no-untyped-def]
        return self._panel_focus


def _make_clan(
    statuses: list[str],
    *,
    harness_cls: type[ClanLJumpHarness] = ClanLJumpHarness,
) -> tuple[ClanLJumpHarness, object, list[object]]:
    members = []
    for index, status in enumerate(statuses):
        member = make_agent(f"member-{index}", clan="research")
        member.status = status
        member.status_bucket = None
        members.append(member)
    from sase.ace.tui.models._agent_tree import project_clan_tree

    complete = project_clan_tree(members)
    container = next(agent for agent in complete if agent.is_clan_container)
    app = harness_cls(complete, container)
    return app, container, members


def _clan_key(container) -> str:  # type: ignore[no-untyped-def]
    key = agent_fold_key(container)
    assert key is not None
    return key


def _selected(app):  # type: ignore[no-untyped-def]
    return app._agents[app.current_idx]


def test_collapsed_clan_with_one_running_jumps_to_member() -> None:
    app, container, _ = _make_clan(["RUNNING", "DONE", "WAITING"])
    key = _clan_key(container)
    assert app._fold_manager.get(key) is FoldLevel.COLLAPSED
    anchors_before = len(app._entry_jump_agents_anchor_stack)

    app.action_expand_or_layout()

    assert app._fold_manager.get(key) is not FoldLevel.COLLAPSED
    running = next(
        agent
        for agent in app._agents_with_children
        if not agent.is_clan_container and agent.status == "RUNNING"
    )
    assert _selected(app).identity == running.identity
    assert len(app._entry_jump_agents_anchor_stack) == anchors_before + 1
    assert app.notifications == []


def test_expanded_clan_with_one_running_selects_member_without_fold_change() -> None:
    app, container, _ = _make_clan(["RUNNING", "DONE", "WAITING"])
    key = _clan_key(container)
    app._fold_manager.expand(key)
    app._refilter_agents()
    app.current_idx = next(
        index
        for index, agent in enumerate(app._agents)
        if agent.identity == container.identity
    )
    before = dict(app._fold_manager._states)
    anchors_before = len(app._entry_jump_agents_anchor_stack)

    app.action_expand_or_layout()

    running = next(
        agent
        for agent in app._agents_with_children
        if not agent.is_clan_container and agent.status == "RUNNING"
    )
    assert _selected(app).identity == running.identity
    assert dict(app._fold_manager._states) == before
    assert len(app._entry_jump_agents_anchor_stack) == anchors_before + 1
    assert app.notifications == []


def test_two_running_collapsed_only_expands() -> None:
    app, container, _ = _make_clan(["RUNNING", "RUNNING", "DONE"])
    key = _clan_key(container)
    anchors_before = len(app._entry_jump_agents_anchor_stack)

    app.action_expand_or_layout()

    assert app._fold_manager.get(key) is not FoldLevel.COLLAPSED
    assert _selected(app).identity == container.identity
    assert len(app._entry_jump_agents_anchor_stack) == anchors_before
    assert app.notifications == []


def test_two_running_expanded_is_noop() -> None:
    app, container, _ = _make_clan(["RUNNING", "STARTING", "DONE"])
    key = _clan_key(container)
    app._fold_manager.expand(key)
    app._refilter_agents()
    app.current_idx = next(
        index
        for index, agent in enumerate(app._agents)
        if agent.identity == container.identity
    )
    before = dict(app._fold_manager._states)
    anchors_before = len(app._entry_jump_agents_anchor_stack)

    app.action_expand_or_layout()

    assert dict(app._fold_manager._states) == before
    assert _selected(app).identity == container.identity
    assert len(app._entry_jump_agents_anchor_stack) == anchors_before


def test_zero_running_keeps_today_behavior() -> None:
    app, container, _ = _make_clan(["DONE", "WAITING", "FAILED"])
    key = _clan_key(container)

    app.action_expand_or_layout()
    assert app._fold_manager.get(key) is not FoldLevel.COLLAPSED
    assert _selected(app).identity == container.identity

    before = dict(app._fold_manager._states)
    app.action_expand_or_layout()
    assert dict(app._fold_manager._states) == before
    assert _selected(app).identity == container.identity


def test_reveal_failure_falls_back_without_toast() -> None:
    app, container, _ = _make_clan(["RUNNING", "DONE"])
    key = _clan_key(container)
    running = next(
        agent
        for agent in app._agents_with_children
        if not agent.is_clan_container and agent.status == "RUNNING"
    )
    # Simulate a search filter hiding the running member: the resolver still
    # sees it through the selected clan's runtime children, but the reveal
    # cannot find it in the complete projection.
    app._agents_with_children = [
        agent
        for agent in app._agents_with_children
        if agent.identity != running.identity
    ]

    app.action_expand_or_layout()

    assert app.notifications == []
    assert _selected(app).identity == container.identity
    assert app._fold_manager.get(key) is not FoldLevel.COLLAPSED


def test_whole_panel_focus_keeps_existing_branch() -> None:
    app, container, _ = _make_clan(["RUNNING", "DONE"])
    key = _clan_key(container)
    app._panel_focus = SimpleNamespace(collapsed=False, panel_key=None)
    anchors_before = len(app._entry_jump_agents_anchor_stack)

    app.action_expand_or_layout()

    assert _selected(app).identity == container.identity
    assert app._fold_manager.get(key) is FoldLevel.COLLAPSED
    assert len(app._entry_jump_agents_anchor_stack) == anchors_before


def test_banner_focus_keeps_existing_branch() -> None:
    app, container, _ = _make_clan(["RUNNING", "DONE"])
    key = _clan_key(container)
    app._current_group_key = ("research",)
    anchors_before = len(app._entry_jump_agents_anchor_stack)

    app.action_expand_or_layout()

    assert _selected(app).identity == container.identity
    assert len(app._entry_jump_agents_anchor_stack) == anchors_before
    # Banner expansion must not trigger the clan jump; the clan fold stays
    # collapsed when the banner branch handles the key.
    assert app._fold_manager.get(key) is FoldLevel.COLLAPSED


async def test_real_app_l_jump_to_lone_running_member(
    monkeypatch: object,
) -> None:
    from sase.ace.testing import AcePage
    from tests.ace.tui._agent_jump_clan_helpers import (
        CLAN_NAME,
        make_realistic_agent,
    )
    from tests.ace.tui.visual._ace_png_snapshot_startup import (
        patch_startup_loaders,
        wait_for_startup,
    )
    from tests.ace.tui.visual._ace_png_snapshot_waits import wait_for_visual_idle

    running = make_realistic_agent(
        f"{CLAN_NAME}.land",
        clan=CLAN_NAME,
        artifacts_dir=f"/{CLAN_NAME}.land",
    )
    running.status = "RUNNING"
    running.status_bucket = None
    done = make_realistic_agent(
        f"{CLAN_NAME}.plan",
        clan=CLAN_NAME,
        artifacts_dir=f"/{CLAN_NAME}.plan",
    )
    done.status = "DONE"
    done.status_bucket = None
    patch_startup_loaders(monkeypatch, agents=[running, done])  # type: ignore[arg-type]

    async with AcePage(initial_tab="agents") as page:
        await wait_for_startup(page)
        app = page.app
        container = next(
            agent
            for agent in app._agents_with_children
            if getattr(agent, "is_clan_container", False)
        )
        target = next(
            agent
            for agent in app._agents_with_children
            if getattr(agent, "artifacts_dir", None) == f"/{CLAN_NAME}.land"
        )
        app.current_idx = next(
            index
            for index, agent in enumerate(app._agents)
            if agent.identity == container.identity
        )
        await page.press("l")
        await wait_for_visual_idle(page)
        selected = app._agents[app.current_idx]
        assert selected.identity == target.identity
