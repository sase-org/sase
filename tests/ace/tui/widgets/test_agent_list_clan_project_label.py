"""Clan-row project labels in the title slot."""

from __future__ import annotations

from datetime import datetime

from sase.ace.tui.models._agent_tree import project_clan_tree
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.widgets._agent_list_render_agent import format_agent_option
from tests.ace.tui.widgets._agent_render_cache_helpers import style_at

_GENERATION = "20261001120000"
_START = datetime(2026, 10, 1, 12, 0, 0)


def _member(
    name: str,
    suffix: str,
    *,
    project_file: str = "/projects/bob-cli/bob-cli.sase",
    project_display_name: str | None = None,
) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=name,
        project_file=project_file,
        status="RUNNING",
        start_time=_START,
        run_start_time=_START,
        raw_suffix=suffix,
        agent_name=name,
        agent_clan="research",
        agent_clan_generation=_GENERATION,
        project_display_name=project_display_name,
    )


def _container(members: list[Agent]) -> Agent:
    (container,) = [row for row in project_clan_tree(members) if row.is_clan_container]
    return container


def test_label_comes_before_status_chip_and_clan_name() -> None:
    container = _container([_member("research.one", "one")])

    (left, _, _) = format_agent_option(container, 0, is_selected=False)

    assert "bob-cli (RUNNING)" in left.plain
    label_at = left.plain.index("bob-cli")
    assert label_at < left.plain.index("(RUNNING)")
    assert left.plain.index("(RUNNING)") < left.plain.index("[R1]")
    assert left.plain.index("[R1]") < left.plain.index("research")


def test_two_projects_join_with_dim_comma() -> None:
    container = _container(
        [
            _member("research.one", "one"),
            _member(
                "research.two",
                "two",
                project_file="/projects/sase/sase.sase",
            ),
        ]
    )

    (left, _, _) = format_agent_option(container, 0, is_selected=False)

    assert "bob-cli, sase (" in left.plain
    assert style_at(left, left.plain.index("bob-cli")) == "#00D7AF"
    assert style_at(left, left.plain.index("bob-cli, sase") + len("bob-cli")) == "dim"


def test_three_projects_cap_at_two_with_overflow() -> None:
    container = _container(
        [
            _member("research.one", "one"),
            _member(
                "research.two",
                "two",
                project_file="/projects/sase/sase.sase",
            ),
            _member(
                "research.three",
                "three",
                project_file="/projects/chezmoi/chezmoi.sase",
            ),
        ]
    )

    (left, _, _) = format_agent_option(container, 0, is_selected=False)

    assert "bob-cli, chezmoi +1 (" in left.plain
    assert "sase" not in left.plain
    assert style_at(left, left.plain.index("+1")) == "dim"


def test_label_is_bold_when_selected() -> None:
    container = _container([_member("research.one", "one")])

    (plain_left, _, _) = format_agent_option(container, 0, is_selected=False)
    (selected_left, _, _) = format_agent_option(container, 0, is_selected=True)

    assert style_at(plain_left, plain_left.plain.index("bob-cli")) == "#00D7AF"
    assert (
        style_at(selected_left, selected_left.plain.index("bob-cli")) == "bold #00D7AF"
    )


def test_clan_without_projects_renders_as_before() -> None:
    container = _container(
        [_member("research.one", "one", project_file="")],
    )

    (left, _, _) = format_agent_option(container, 0, is_selected=False)

    assert left.plain.startswith("(RUNNING)")


def test_non_clan_row_ignores_clan_projects() -> None:
    member = _member("research.one", "one")
    member.agent_clan = None
    member.agent_clan_generation = None

    (left, _, _) = format_agent_option(
        member, 0, is_selected=False, clan_projects=("zzz",)
    )

    assert "zzz" not in left.plain
    assert "(RUNNING)" in left.plain
