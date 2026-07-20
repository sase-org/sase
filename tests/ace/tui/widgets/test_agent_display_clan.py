"""Clan header and compatibility rendering in the Agents metadata panel."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from rich.text import Text

from sase.ace.tui.models._agent_tree import project_clan_tree
from sase.ace.tui.models.fold_state import FoldLevel
from sase.ace.tui.widgets.prompt_panel._agent_display_clan import (
    build_clan_detail_text,
)
from sase.ace.tui.widgets.prompt_panel._agent_display_parts import build_header_text
from sase.ace.tui.widgets.prompt_panel._agent_display_render import (
    AgentDisplayRenderMixin,
)
from tests.ace.tui.widgets._agent_display_clan_helpers import (
    make_clan_agent,
    style_at,
)


def test_clan_header_rolls_up_identity_counts_runtime_and_launch_order() -> None:
    first = make_clan_agent(
        "research.first",
        status="DONE",
        start=datetime(2026, 7, 17, 12, 0, 0),
        stop=datetime(2026, 7, 17, 12, 2, 0),
    )
    second = make_clan_agent(
        "research.second",
        status="FAILED",
        start=datetime(2026, 7, 17, 12, 1, 0),
        stop=datetime(2026, 7, 17, 12, 1, 45),
        model=None,
    )
    container = project_clan_tree([second, first])[0]
    container.clan_tribes = ("epic", "review")

    detail = build_clan_detail_text(
        container,
        now=datetime(2026, 7, 17, 12, 4, 0),
    )

    header, members = detail.plain.split("\n" + "━" * 50 + "\n", 1)
    assert header.strip() == (
        "CLAN\n"
        "Name: research\n"
        "Tribes: @epic @review\n"
        "Status: FAILED [F1 D1]\n"
        "Runtime: 2m\n"
        "Members: 2 agents\n"
        "Fold: 1/3"
    )
    members_section = members.split("\n" + "─" * 50 + "\n", 1)[0]
    assert members_section.strip() == (
        "▸ ❖ CLAN MEMBERS · 2\n"
        " 0  .first · agent · ✓ DONE · gpt-5 · 2m\n"
        " 1  .second · agent · ✗ FAILED · default · 45s"
    )
    assert "▸ ERRORS · 1\n" in detail.plain
    assert style_at(detail, detail.plain.index("CLAN")) == ("bold #D75FFF underline")
    assert style_at(detail, detail.plain.index("research")) == "#D75FFF"


def test_new_style_clan_tribe_projects_into_folded_summary_header() -> None:
    member = make_clan_agent(
        "sase-6u.land",
        status="RUNNING",
        start=datetime(2026, 7, 17, 12, 0, 0),
    )
    member.agent_clan = "sase-6u"
    member.clan_tribe = "epic"

    container = project_clan_tree([member])[0]
    detail = build_clan_detail_text(
        container,
        fold_level=FoldLevel.COLLAPSED,
    ).plain

    assert container.clan_tribes == ("epic",)
    assert "Tribes: @epic\n" in detail
    assert "Fold: 1/3\n" in detail


def test_clan_summary_renders_rich_markup_at_every_fold_level() -> None:
    member = make_clan_agent(
        "research.one",
        status="RUNNING",
        start=datetime(2026, 7, 17, 12, 0, 0),
    )
    member.clan_summary = (
        "[bold #FFD75F]RESEARCH PROMPT:[/bold #FFD75F]\n"
        "[italic]Trace the summary from launch to panel.[/italic]"
    )
    container = project_clan_tree([member])[0]

    for fold_level in (
        FoldLevel.COLLAPSED,
        FoldLevel.EXPANDED,
        FoldLevel.FULLY_EXPANDED,
    ):
        detail = build_clan_detail_text(container, fold_level=fold_level)
        plain = detail.plain

        assert (
            "Members: 1 agent\n\n"
            "RESEARCH PROMPT:\n"
            "Trace the summary from launch to panel.\n\n"
            "Fold: "
        ) in plain
        assert style_at(detail, plain.index("RESEARCH PROMPT:")) == ("bold #ffd75f")


def test_clan_summary_invalid_markup_falls_back_to_raw_text() -> None:
    member = make_clan_agent(
        "research.one",
        status="RUNNING",
        start=datetime(2026, 7, 17, 12, 0, 0),
    )
    member.clan_summary = "[bold]Research[/italic]"
    container = project_clan_tree([member])[0]

    detail = build_clan_detail_text(container).plain

    assert "Members: 1 agent\n\n[bold]Research[/italic]\n\nFold: 1/3" in detail


def test_family_header_recolors_only_real_container_name() -> None:
    family = make_clan_agent(
        "research.writer",
        status="RUNNING",
        start=datetime(2026, 7, 17, 12, 0, 0),
        family="research.writer",
    )
    family.agent_clan = None
    family.agent_family_role = "root"
    family.refresh_presented_agent_name()
    synthetic = make_clan_agent(
        "research.writer--plan",
        status="DONE",
        start=datetime(2026, 7, 17, 12, 1, 0),
        family="research.writer",
    )
    synthetic.is_synthetic_planner = True
    family.followup_agents = [synthetic]

    lone_header, _ = build_header_text(family, cheap=True)

    assert isinstance(lone_header, Text)
    assert style_at(lone_header, lone_header.plain.index("research.writer")) == (
        "#FFD700"
    )

    member = make_clan_agent(
        "research.writer--code",
        status="RUNNING",
        start=datetime(2026, 7, 17, 12, 2, 0),
        family="research.writer",
    )
    family.followup_agents.append(member)

    family_header, _ = build_header_text(family, cheap=True)

    assert isinstance(family_header, Text)
    assert (
        style_at(
            family_header,
            family_header.plain.index("research.writer"),
        )
        == "#00AFFF"
    )

    ordinary = make_clan_agent(
        "research.reader",
        status="RUNNING",
        start=datetime(2026, 7, 17, 12, 3, 0),
    )
    ordinary.agent_clan = None
    ordinary_header, _ = build_header_text(ordinary, cheap=True)

    assert isinstance(ordinary_header, Text)
    assert (
        style_at(
            ordinary_header,
            ordinary_header.plain.index("research.reader"),
        )
        == "#FFD700"
    )


def test_clan_header_uses_same_unread_aggregate_as_list_row() -> None:
    read = make_clan_agent(
        "research.read",
        status="DONE",
        start=datetime(2026, 7, 17, 12, 0, 0),
        stop=datetime(2026, 7, 17, 12, 1, 0),
    )
    unread = make_clan_agent(
        "research.unread",
        status="DONE",
        start=datetime(2026, 7, 17, 12, 1, 0),
        stop=datetime(2026, 7, 17, 12, 2, 0),
    )
    container = project_clan_tree([read, unread])[0]

    detail = build_clan_detail_text(
        container,
        unread_ids={unread.identity},
    )

    assert "Status: DONE [U1 D1]\n" in detail.plain


def test_clan_build_header_path_is_aggregate_only() -> None:
    member = make_clan_agent(
        "research.only",
        status="WAITING",
        start=datetime(2026, 7, 17, 12, 0, 0),
    )
    member.run_start_time = None
    container = project_clan_tree([member])[0]

    header, traceback = build_header_text(container, cheap=True)

    assert traceback is None
    assert header.plain.startswith("CLAN\nName: research\n")
    assert "AGENT PROMPT" not in header.plain
    assert "ChangeSpec:" not in header.plain
    assert "No prompt file found" not in header.plain


def test_non_clan_agent_has_no_members_section() -> None:
    agent = make_clan_agent(
        "research.only",
        status="RUNNING",
        start=datetime(2026, 7, 17, 12, 0, 0),
    )

    header, _ = build_header_text(agent, cheap=True)

    assert not header.plain.startswith("CLAN")
    assert "MEMBERS" not in header.plain


def test_legacy_parallel_root_keeps_compatibility_members_section() -> None:
    root = make_clan_agent(
        "legacy-root",
        status="DONE",
        start=datetime(2026, 7, 17, 12, 0, 0),
        stop=datetime(2026, 7, 17, 12, 2, 0),
    )
    root.agent_clan = None
    root.agent_family_parallel = True
    child = make_clan_agent(
        "legacy-child",
        status="DONE",
        start=datetime(2026, 7, 17, 12, 1, 0),
        stop=datetime(2026, 7, 17, 12, 2, 0),
    )
    child.agent_clan = None
    child.agent_family_parallel = True
    child.agent_family_role = "phase"
    root.runtime_children = [child]

    header, _ = build_header_text(root, cheap=True)

    assert "MEMBERS · 1\n" in header.plain
    assert "phase · legacy-child · ✓ DONE · gpt-5 · 1m0s\n" in header.plain


def test_clan_full_render_bypasses_attempt_and_artifact_paths() -> None:
    member = make_clan_agent(
        "research.only",
        status="DONE",
        start=datetime(2026, 7, 17, 12, 0, 0),
        stop=datetime(2026, 7, 17, 12, 1, 0),
    )
    container = project_clan_tree([member])[0]

    class _Harness(AgentDisplayRenderMixin):
        attempt_pinned_number = 4

        def __init__(self) -> None:
            self.content = None
            self._app = SimpleNamespace(_member_jump_maps={})

        @property
        def app(self) -> object:
            return self._app

        def update(self, content: object) -> None:
            self.content = content

        def _render_attempt_pinned(self, *_args: object) -> None:
            raise AssertionError("synthetic clans have no attempts")

    harness = _Harness()
    harness._update_display_impl(container)

    assert isinstance(harness.content, Text)
    assert harness.content.plain.startswith("CLAN\nName: research\n")
    assert harness._app._member_jump_maps[container.identity].targets[0].number == "0"
