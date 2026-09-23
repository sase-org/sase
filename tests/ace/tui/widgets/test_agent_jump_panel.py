"""Mounted jump-panel behavior for the Agents tab sticky jump footer."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import VerticalScroll

from sase.ace.tui._app_action_availability import check_app_action
from sase.ace.tui.actions.navigation._member_jump import MemberJumpNavigationMixin
from sase.ace.tui.models._agent_tree import project_clan_tree
from sase.ace.tui.models.agent_tribe_summary import AgentPanelFocus
from sase.ace.tui.models.fold_state import FoldLevel
from sase.ace.tui.widgets._agent_detail_panels import DetailLayoutMode
from sase.ace.tui.widgets.agent_detail import AgentDetail
from sase.ace.tui.widgets.agent_jump_panel import AgentJumpPanel
from sase.ace.tui.widgets.prompt_panel import AgentPromptPanel
from sase.ace.tui.widgets.prompt_panel._member_roster import (
    MemberJumpMap,
    MemberJumpNumbering,
    MemberRosterEntry,
    append_member_roster,
)
from sase.ace.tui.widgets.renderable_text import renderable_to_text
from tests.ace.tui._member_jump_navigation_helpers import (
    JumpHarness,
    make_agent as make_nav_agent,
    make_family as make_nav_family,
)
from tests.ace.tui.widgets._agent_display_clan_helpers import make_clan_agent
from tests.ace.tui.widgets._agent_display_family_helpers import make_family
from tests.ace.tui.widgets._agent_display_helpers import make_agent
from tests.ace.tui.widgets._agent_display_tribe_helpers import make_tribe_snapshot
from tests.ace.tui.widgets._prompt_panel_section_navigation_helpers import (
    _MetadataNavigationApp,
    section,
)


def _solo() -> Any:
    return make_agent(agent_name="solo")


class _DetailApp(App[None]):
    def compose(self) -> ComposeResult:
        yield AgentDetail(id="agent-detail-panel")


async def _show_agent(detail: AgentDetail, agent: Any, pilot: Any) -> None:
    detail.update_display_immediate(agent)
    await pilot.pause()


def _jump_panel(detail: AgentDetail) -> AgentJumpPanel:
    return detail.query_one("#agent-jump-panel", AgentJumpPanel)


def _jump_text(panel: AgentJumpPanel) -> str:
    content = panel.query_one("#agent-jump-content")
    return renderable_to_text(getattr(content, "content", None)) or ""


def _labeled_map(
    container: Any,
    labels: list[str],
    *,
    roles: list[str] | None = None,
    title: str = "ROSTER",
    accent: str = "#00D7AF",
) -> MemberJumpMap:
    """Build a labeled jump map over synthetic roster entries."""
    entries = tuple(
        MemberRosterEntry(
            identity=(container.identity[0], label, None),
            presented_name=label,
            label=label,
            kind="agent",
            status="RUNNING",
            model="m",
            duration="1m",
            is_dismissed=(role == "dismissed"),
            target_role=role if role != "member" else None,  # type: ignore[arg-type]
        )
        for label, role in zip(labels, roles or ["member"] * len(labels), strict=True)
    )
    return append_member_roster(
        Text(),
        container_identity=container.identity,
        entries=entries,
        title=title,
        accent=accent,
        panel_level=FoldLevel.COLLAPSED,
        numbering=MemberJumpNumbering(total=len(entries)),
    )


async def test_empty_state_hides_jump_panel() -> None:
    app = _DetailApp()
    async with app.run_test(size=(80, 24)) as pilot:
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        await _show_agent(detail, _solo(), pilot)
        detail.show_empty()
        await pilot.pause()
        panel = _jump_panel(detail)
        assert panel.has_class("hidden")
        assert not panel.has_targets
        assert detail.jump_panel_toggle_available() is False


async def test_plain_node_hides_jump_panel() -> None:
    app = _DetailApp()
    async with app.run_test(size=(80, 24)) as pilot:
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        await _show_agent(detail, _solo(), pilot)
        panel = _jump_panel(detail)
        assert panel.has_class("hidden")
        assert not panel.has_targets
        assert detail.jump_panel_toggle_available() is False


async def test_all_unnumbered_document_hides_jump_panel() -> None:
    app = _DetailApp()
    async with app.run_test(size=(80, 24)) as pilot:
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        await _show_agent(detail, _solo(), pilot)
        panel = _jump_panel(detail)
        solo = _solo()
        entries = (
            MemberRosterEntry(
                identity=(solo.identity[0], "spent", None),
                presented_name="spent",
                label="spent",
                kind="agent",
                status="RUNNING",
                model="m",
                duration="1m",
            ),
        )
        spent_map = append_member_roster(
            Text(),
            container_identity=solo.identity,
            entries=entries,
            title="NEIGHBORS",
            accent="#00D7AF",
            panel_level=FoldLevel.COLLAPSED,
            numbering=MemberJumpNumbering(total=1, capacity=0),
        )
        assert spent_map.targets == ()
        assert len(spent_map.sections) == 1
        detail._on_member_jump_map(spent_map)  # noqa: SLF001
        await pilot.pause()
        assert panel.has_class("hidden")
        assert detail.jump_panel_toggle_available() is False


async def test_family_container_shows_collapsed_panel(tmp_path: Path) -> None:
    root, _child = make_family(tmp_path)
    app = _DetailApp()
    async with app.run_test(size=(80, 24)) as pilot:
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        await _show_agent(detail, root, pilot)
        panel = _jump_panel(detail)
        assert not panel.has_class("hidden")
        assert panel.has_targets
        assert not panel.is_expanded
        assert detail.jump_panel_toggle_available() is True
        assert "JUMP" in str(panel.border_title)
        assert "FAMILY SHELLS" in str(panel.border_title)
        assert "more" in str(panel.border_subtitle)
        assert len(_jump_text(panel).splitlines()) <= 2


async def test_clan_selection_shows_jump_panel() -> None:
    member = make_clan_agent(
        "clan-test", status="RUNNING", start=datetime(2024, 1, 1), stop=None
    )
    container = project_clan_tree([member])[0]
    assert container.is_clan_container
    app = _DetailApp()
    async with app.run_test(size=(80, 24)) as pilot:
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        await _show_agent(detail, container, pilot)
        panel = _jump_panel(detail)
        assert not panel.has_class("hidden")
        assert panel.has_targets
        assert "CLAN MEMBERS" in str(panel.border_title)
        assert detail.jump_panel_toggle_available() is True


async def test_tribe_panel_shows_jump_panel() -> None:
    app = _DetailApp()
    async with app.run_test(size=(80, 24)) as pilot:
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        detail.show_tribe_summary(make_tribe_snapshot())
        await pilot.pause()
        panel = _jump_panel(detail)
        assert not panel.has_class("hidden")
        assert panel.has_targets
        assert "TRIBE MEMBERS" in str(panel.border_title)


async def test_toggle_expands_to_every_target_and_back(tmp_path: Path) -> None:
    root, _child = make_family(tmp_path)
    app = _DetailApp()
    async with app.run_test(size=(80, 24)) as pilot:
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        await _show_agent(detail, root, pilot)
        panel = _jump_panel(detail)

        assert detail.toggle_jump_panel_expanded() is True
        await pilot.pause()
        assert panel.is_expanded
        assert "less" in str(panel.border_subtitle)
        body = _jump_text(panel)
        assert "--plan" in body and "--code" in body

        assert detail.toggle_jump_panel_expanded() is False
        await pilot.pause()
        assert not panel.is_expanded
        assert "more" in str(panel.border_subtitle)


async def test_expanded_state_persists_across_selection(tmp_path: Path) -> None:
    root, _child = make_family(tmp_path)
    app = _DetailApp()
    async with app.run_test(size=(80, 24)) as pilot:
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        await _show_agent(detail, root, pilot)
        assert detail.toggle_jump_panel_expanded() is True

        await _show_agent(detail, _solo(), pilot)
        await _show_agent(detail, root, pilot)
        panel = _jump_panel(detail)
        assert panel.is_expanded
        assert "less" in str(panel.border_subtitle)


async def test_panel_sits_below_secondary_scroll_in_every_layout(
    tmp_path: Path,
) -> None:
    root, _child = make_family(tmp_path)
    app = _DetailApp()
    async with app.run_test(size=(80, 24)) as pilot:
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        await _show_agent(detail, root, pilot)
        panel = _jump_panel(detail)
        detail._has_file_content = True  # noqa: SLF001
        detail._has_llm_calls_content = True  # noqa: SLF001
        for layout in (
            DetailLayoutMode.METADATA_ONLY,
            DetailLayoutMode.METADATA_LARGER,
            DetailLayoutMode.EQUAL,
            DetailLayoutMode.SECONDARY_LARGER,
            DetailLayoutMode.SECONDARY_ONLY,
        ):
            detail.set_detail_layout(layout)
            await pilot.pause()
            assert not panel.has_class("hidden")
            file_scroll = detail.query_one("#agent-file-scroll", VerticalScroll)
            llm_scroll = detail.query_one("#agent-llm-calls-scroll", VerticalScroll)
            assert panel.region.y >= file_scroll.region.bottom
            assert panel.region.y >= llm_scroll.region.bottom
            assert panel.region.bottom <= detail.region.bottom


async def test_search_overlay_keeps_jump_panel_visible(tmp_path: Path) -> None:
    root, _child = make_family(tmp_path)
    app = _DetailApp()
    async with app.run_test(size=(80, 24)) as pilot:
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        await _show_agent(detail, root, pilot)
        prompt_scroll = detail.query_one("#agent-prompt-scroll", VerticalScroll)
        search_scroll = detail.query_one("#agent-search-scroll", VerticalScroll)
        detail._show_active_metadata_scroll(search_scroll)  # noqa: SLF001
        panel = _jump_panel(detail)
        assert not panel.has_class("hidden")
        assert detail.jump_panel_toggle_available() is True
        detail._show_active_metadata_scroll(prompt_scroll)  # noqa: SLF001
        assert not panel.has_class("hidden")


async def test_identity_change_resets_panel_scroll(tmp_path: Path) -> None:
    root, _child = make_family(tmp_path)
    app = _DetailApp()
    async with app.run_test(size=(80, 12)) as pilot:
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        await _show_agent(detail, root, pilot)
        detail._on_member_jump_map(  # noqa: SLF001
            _labeled_map(_solo(), [f"target-{index:02d}" for index in range(12)])
        )
        assert detail.toggle_jump_panel_expanded() is True
        await pilot.pause()
        panel = _jump_panel(detail)
        assert panel.max_scroll_y > 0
        panel.scroll_y = panel.max_scroll_y
        await pilot.pause()
        assert panel.scroll_y > 0

        await _show_agent(detail, _solo(), pilot)
        assert panel.scroll_y == 0


async def test_hint_document_hides_panel_and_back(tmp_path: Path) -> None:
    root, _child = make_family(tmp_path)
    app = _DetailApp()
    async with app.run_test(size=(80, 24)) as pilot:
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        await _show_agent(detail, root, pilot)
        panel = _jump_panel(detail)
        assert not panel.has_class("hidden")

        detail.update_display_with_hints(root)
        await pilot.pause()
        assert panel.has_class("hidden")
        assert detail.jump_panel_toggle_available() is False

        await _show_agent(detail, root, pilot)
        assert not panel.has_class("hidden")
        assert detail.jump_panel_toggle_available() is True


async def test_bottom_pinned_body_stays_pinned_across_jump_toggle() -> None:
    app = _MetadataNavigationApp()
    async with app.run_test(size=(50, 16)) as pilot:
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        prompt = detail.query_one("#agent-prompt-panel", AgentPromptPanel)
        scroll = app.query_one("#agent-prompt-scroll", VerticalScroll)
        body = section("ONE", "one\n" * 30)
        prompt.prepare_section_document("pin-document")
        prompt.update(body)
        await pilot.pause()
        await pilot.press("G")
        await pilot.pause()
        assert prompt.is_pinned_to_bottom
        detail._on_member_jump_map(_labeled_map(_solo(), ["aa", "bb"]))  # noqa: SLF001
        await pilot.pause()
        detail.toggle_jump_panel_expanded()
        await pilot.pause()
        assert prompt.is_pinned_to_bottom
        assert int(scroll.scroll_y) == prompt.bottom_scroll_target(scroll)


async def test_two_digit_prefix_narrows_and_restores() -> None:
    app = _DetailApp()
    async with app.run_test(size=(80, 24)) as pilot:
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        await _show_agent(detail, _solo(), pilot)
        jump_map = _labeled_map(_solo(), [f"target-{index:02d}" for index in range(12)])
        assert jump_map.targets[0].number == "00"
        detail._on_member_jump_map(jump_map)  # noqa: SLF001
        await pilot.pause()
        panel = _jump_panel(detail)
        assert not panel.has_class("hidden")
        assert len(_jump_text(panel).splitlines()) <= 2

        detail.set_jump_panel_prefix("1")
        await pilot.pause()
        assert "1▁" in str(panel.border_title)
        assert str(panel.border_subtitle) == "esc cancel"
        narrowed = _jump_text(panel)
        assert "target-10" in narrowed and "target-11" in narrowed
        assert "target-00" not in narrowed

        detail.set_jump_panel_prefix(None)
        await pilot.pause()
        assert "ROSTER" in str(panel.border_title)
        assert "00–11" in str(panel.border_title)
        assert "more" in str(panel.border_subtitle)
        assert "target-00" in _jump_text(panel)


async def test_neighbors_map_shows_dismissed_revive_cells() -> None:
    app = _DetailApp()
    async with app.run_test(size=(80, 24)) as pilot:
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        await _show_agent(detail, _solo(), pilot)
        jump_map = _labeled_map(
            _solo(),
            ["lane.peer", "lane.old"],
            roles=["neighbor", "dismissed"],
            title="NEIGHBORS",
            accent="#00D7AF",
        )
        detail._on_member_jump_map(jump_map)  # noqa: SLF001
        await pilot.pause()
        panel = _jump_panel(detail)
        assert not panel.has_class("hidden")
        assert "NEIGHBORS" in str(panel.border_title)
        collapsed = _jump_text(panel)
        assert "lane.peer" in collapsed
        assert "⊘" in collapsed
        assert detail.toggle_jump_panel_expanded() is True
        await pilot.pause()
        assert "revive" in _jump_text(panel)


async def test_narrow_prefix_without_targets_shows_empty_line() -> None:
    app = _DetailApp()
    async with app.run_test(size=(80, 24)) as pilot:
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        await _show_agent(detail, _solo(), pilot)
        detail._on_member_jump_map(_labeled_map(_solo(), ["aa", "bb"]))  # noqa: SLF001
        await pilot.pause()
        detail.set_jump_panel_prefix("9")
        await pilot.pause()
        assert "no targets start with 9" in _jump_text(_jump_panel(detail))


async def test_unbound_toggle_key_omits_subtitle() -> None:
    app = _DetailApp()
    async with app.run_test(size=(80, 24)) as pilot:
        detail = app.query_one("#agent-detail-panel", AgentDetail)
        await _show_agent(detail, _solo(), pilot)
        panel = _jump_panel(detail)
        detail._on_member_jump_map(_labeled_map(_solo(), ["aa"]))  # noqa: SLF001
        await pilot.pause()
        assert "more" in str(panel.border_subtitle)

        app._keymap_registry = SimpleNamespace(  # noqa: SLF001
            app=SimpleNamespace(toggle_agent_jump_panel="")
        )
        panel._last_digest = None  # noqa: SLF001
        detail._on_member_jump_map(_labeled_map(_solo(), ["aa"]))  # noqa: SLF001
        await pilot.pause()
        assert str(panel.border_subtitle) == ""


def _fallback(_action: str, _parameters: tuple[object, ...]) -> bool:
    return True


class _FakeAgentsApp:
    current_tab = "agents"
    _screen_stack = ("screen",)

    def __init__(self, *, prompt_active: bool, detail: Any) -> None:
        self._prompt_active = prompt_active
        self._detail = detail

    def _prompt_input_active(self) -> bool:
        return self._prompt_active

    def query_one(self, _selector: str, _type: Any = None) -> Any:
        return self._detail


class _FakeDetail:
    def __init__(self, *, available: bool) -> None:
        self._available = available

    def jump_panel_toggle_available(self) -> bool:
        return self._available


def test_toggle_unavailable_while_prompt_input_owns_keys_or_hidden() -> None:
    available = _FakeAgentsApp(prompt_active=False, detail=_FakeDetail(available=True))
    assert check_app_action(available, "toggle_agent_jump_panel", (), _fallback) is True
    busy = _FakeAgentsApp(prompt_active=True, detail=_FakeDetail(available=True))
    assert check_app_action(busy, "toggle_agent_jump_panel", (), _fallback) is False
    hidden = _FakeAgentsApp(prompt_active=False, detail=_FakeDetail(available=False))
    assert check_app_action(hidden, "toggle_agent_jump_panel", (), _fallback) is False


class _RecordingDetail:
    def __init__(self, prefixes: list[str | None]) -> None:
        self._prefixes = prefixes

    def set_jump_panel_prefix(self, prefix: str | None) -> None:
        self._prefixes.append(prefix)


class _PrefixNavStub(MemberJumpNavigationMixin):
    """Minimal host for the pending-digit jump-panel hooks."""

    current_tab = "agents"

    def __init__(self) -> None:
        self._member_jump_pending_digit: str | None = None
        self._member_jump_pending_container_identity: Any = None
        self.prefixes: list[str | None] = []
        self.footer_digits: list[str] = []
        self.footer_refreshes = 0

    def query_one(self, selector: str, _type: Any = None) -> Any:
        if selector == "#agent-detail-panel":
            return _RecordingDetail(self.prefixes)
        return SimpleNamespace(
            update_member_jump_bindings=lambda *args, **_kwargs: (
                self.footer_digits.append(args[0])
            )
        )

    def _refresh_agent_footer_bindings_only(self) -> None:
        self.footer_refreshes += 1


def test_first_digit_hook_narrows_and_cancel_restores() -> None:
    stub = _PrefixNavStub()
    stub._update_member_jump_footer("1")
    assert stub.prefixes == ["1"]

    stub._member_jump_pending_digit = "1"
    assert stub._cancel_member_jump_pending() is True
    assert stub.prefixes == ["1", None]
    assert stub.footer_refreshes == 1

    stub._member_jump_pending_digit = "2"
    stub._update_member_jump_footer("2")
    assert stub._cancel_member_jump_pending(refresh_footer=False) is True
    assert stub.prefixes == ["1", None, "2", None]
    assert stub.footer_refreshes == 1

    assert stub._cancel_member_jump_pending() is False
    assert stub.prefixes == ["1", None, "2", None]


def _press_each_number(
    app: JumpHarness, container: Any, jump_map: MemberJumpMap
) -> None:
    """Press every panel number through the real key path and check landing."""
    from sase.ace.tui.widgets._agent_jump_legend import JumpLegendRenderable

    rendered = renderable_to_text(JumpLegendRenderable(jump_map, mode="expanded"))
    assert rendered
    for target in jump_map.targets:
        assert target.number in rendered
        assert target.label in rendered
        app.current_idx = next(
            index
            for index, agent in enumerate(app._agents)
            if agent.identity == container.identity
        )
        assert app._handle_member_jump_key(target.number) is True
        landed = app._agents[app.current_idx].identity
        assert landed == target.member_identity, (target.number, landed)
    assert app.notifications == []


def test_panel_numbers_land_through_real_jump_path() -> None:
    complete, root, child = make_nav_family(in_clan=False)
    app = JumpHarness(complete, root)
    entries = (
        MemberRosterEntry(
            identity=child.identity,
            presented_name="alpha--code",
            label="--code",
            kind="agent",
            status="DONE",
            model="m",
            duration="1m",
        ),
    )
    jump_map = append_member_roster(
        Text(),
        container_identity=root.identity,
        entries=entries,
        title="FAMILY SHELLS",
        accent="#00AFFF",
        panel_level=FoldLevel.COLLAPSED,
        numbering=MemberJumpNumbering(total=len(entries)),
    )
    app._member_jump_maps[root.identity] = jump_map
    _press_each_number(app, root, jump_map)


def test_panel_neighbor_number_lands() -> None:
    container = make_nav_agent("foo.plan")
    neighbor = make_nav_agent("foo.code")
    app = JumpHarness([container, neighbor], container)
    app._neighbor_targets[container.identity] = {neighbor.identity}
    entries = (
        MemberRosterEntry(
            identity=neighbor.identity,
            presented_name="foo.code",
            label="foo.code",
            kind="agent",
            status="RUNNING",
            model="m",
            duration="1m",
            target_role="neighbor",
        ),
    )
    jump_map = append_member_roster(
        Text(),
        container_identity=container.identity,
        entries=entries,
        title="NEIGHBORS",
        accent="#00D7AF",
        panel_level=FoldLevel.COLLAPSED,
        numbering=MemberJumpNumbering(total=len(entries)),
    )
    app._member_jump_maps[container.identity] = jump_map
    _press_each_number(app, container, jump_map)


def test_panel_dismissed_number_revives() -> None:
    from sase.ace.tui.widgets._agent_jump_legend import JumpLegendRenderable

    container = make_nav_agent("foo")
    dismissed = make_nav_agent("foo.scratch")
    app = JumpHarness([container], container)
    app._dismissed_agent_objects = [dismissed]
    app._dismissed_agents = {dismissed.identity}
    entries = (
        MemberRosterEntry(
            identity=dismissed.identity,
            presented_name="foo.scratch",
            label="foo.scratch",
            kind="agent",
            status="QUESTION",
            model="m",
            duration="1m",
            is_dismissed=True,
            target_role="dismissed",
        ),
    )
    jump_map = append_member_roster(
        Text(),
        container_identity=container.identity,
        entries=entries,
        title="NEIGHBORS",
        accent="#00D7AF",
        panel_level=FoldLevel.COLLAPSED,
        numbering=MemberJumpNumbering(total=len(entries)),
    )
    app._member_jump_maps[container.identity] = jump_map

    rendered = renderable_to_text(JumpLegendRenderable(jump_map, mode="expanded"))
    assert rendered and "revive" in rendered

    assert app._handle_member_jump_key("0") is True
    assert app.revived_agents == [dismissed]
    assert app._agents[app.current_idx].identity == container.identity
    assert app.notifications == []


def test_panel_clan_and_tribe_numbers_land() -> None:
    members = [
        make_clan_agent(
            "research.first",
            status="DONE",
            start=datetime(2026, 7, 17, 12, 0, 0),
            stop=datetime(2026, 7, 17, 12, 2, 0),
        ),
        make_clan_agent(
            "research.second",
            status="FAILED",
            start=datetime(2026, 7, 17, 12, 1, 0),
            stop=datetime(2026, 7, 17, 12, 1, 45),
        ),
    ]
    projected = project_clan_tree(members)
    container = next(agent for agent in projected if agent.is_clan_container)
    app = JumpHarness([*projected], container)
    entries = tuple(
        MemberRosterEntry(
            identity=member.identity,
            presented_name=member.agent_name or "member",
            label=f"member-{index}",
            kind="agent",
            status="DONE",
            model="m",
            duration="1m",
        )
        for index, member in enumerate(container.runtime_children)
    )
    jump_map = append_member_roster(
        Text(),
        container_identity=container.identity,
        entries=entries,
        title="CLAN MEMBERS",
        accent="#D75FFF",
        panel_level=FoldLevel.COLLAPSED,
        numbering=MemberJumpNumbering(total=len(entries)),
    )
    app._member_jump_maps[container.identity] = jump_map
    _press_each_number(app, container, jump_map)

    tribe_members = [
        make_nav_agent(f"t.member{index}", tribe="t") for index in range(3)
    ]
    tribe_app = JumpHarness(tribe_members, tribe_members[0])
    focus = AgentPanelFocus(
        panel_key=tribe_app._panel_group.focused_key, collapsed=False
    )

    def _focused_panel() -> AgentPanelFocus:
        return focus

    tribe_app._resolve_focused_panel = _focused_panel  # noqa: SLF001
    tribe_entries = tuple(
        MemberRosterEntry(
            identity=member.identity,
            presented_name=member.agent_name or "member",
            label=f"t-label-{index}",
            kind="agent",
            status="RUNNING",
            model="m",
            duration="1m",
        )
        for index, member in enumerate(tribe_members)
    )
    tribe_map = append_member_roster(
        Text(),
        container_identity=focus.container_identity,
        entries=tribe_entries,
        title="TRIBE MEMBERS",
        accent="#AF87D7",
        panel_level=FoldLevel.COLLAPSED,
        numbering=MemberJumpNumbering(total=len(tribe_entries)),
    )
    tribe_app._member_jump_maps[focus.container_identity] = tribe_map
    from sase.ace.tui.widgets._agent_jump_legend import JumpLegendRenderable

    rendered = renderable_to_text(JumpLegendRenderable(tribe_map, mode="expanded"))
    assert rendered
    for target in tribe_map.targets:
        assert target.number in rendered
        assert app.notifications == []
        assert tribe_app._handle_member_jump_key(target.number) is True
        assert (
            tribe_app._agents[tribe_app.current_idx].identity == target.member_identity
        )
    assert tribe_app.notifications == []
