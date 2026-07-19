"""Tests for the agent neighbor chooser modal."""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.widgets import OptionList

from sase.ace.tui.modals.agent_neighbor_modal import (
    AgentNeighborChoice,
    AgentNeighborModal,
    _agent_neighbor_option_text,
    _agent_neighbor_selector_keys,
)


class _TestApp(App[object | None]):
    ENABLE_COMMAND_PALETTE = False

    def compose(self) -> ComposeResult:
        yield from ()


def _choices(count: int = 3) -> list[AgentNeighborChoice]:
    return [
        AgentNeighborChoice(
            agent_name=f"foo.agent{index}",
            display_name="demo",
            status="RUNNING" if index == 0 else "DONE",
            panel_label="@review" if index == 1 else "(untagged)",
            time_hint="4m",
            group="neighbor",
            hood="foo",
            global_idx=index + 10,
        )
        for index in range(count)
    ]


async def test_agent_neighbor_modal_enter_selects_highlighted_row() -> None:
    choices = _choices()
    result: object | None = None

    async with _TestApp().run_test() as pilot:

        def on_dismiss(value: object | None) -> None:
            nonlocal result
            result = value

        modal = AgentNeighborModal("foo", choices)
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        option_list = modal.query_one("#agent-neighbor-list", OptionList)
        option_list.highlighted = 2
        await pilot.press("enter")
        await pilot.pause()

    assert result == 1


async def test_agent_neighbor_modal_letter_quick_selects_row() -> None:
    choices = _choices()
    result: object | None = None

    async with _TestApp().run_test() as pilot:

        def on_dismiss(value: object | None) -> None:
            nonlocal result
            result = value

        modal = AgentNeighborModal("foo", choices)
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        await pilot.press("b")
        await pilot.pause()

    assert result == 1


async def test_agent_neighbor_modal_j_k_move_highlight() -> None:
    async with _TestApp().run_test() as pilot:
        modal = AgentNeighborModal("foo", _choices())
        pilot.app.push_screen(modal)
        await pilot.pause()

        option_list = modal.query_one("#agent-neighbor-list", OptionList)
        assert option_list.highlighted == 1

        await pilot.press("j")
        await pilot.pause()
        assert option_list.highlighted == 2

        await pilot.press("k")
        await pilot.pause()
        assert option_list.highlighted == 1


async def test_agent_neighbor_modal_escape_and_q_cancel() -> None:
    for key in ("escape", "q"):
        result: object | None = "sentinel"
        async with _TestApp().run_test() as pilot:

            def on_dismiss(value: object | None) -> None:
                nonlocal result
                result = value

            modal = AgentNeighborModal("foo", _choices(1))
            pilot.app.push_screen(modal, callback=on_dismiss)
            await pilot.pause()

            await pilot.press(key)
            await pilot.pause()

        assert result is None


def test_agent_neighbor_modal_selector_keys_skip_navigation_keys() -> None:
    keys = _agent_neighbor_selector_keys(26)

    assert "j" not in keys
    assert "k" not in keys
    assert "q" not in keys
    assert keys[:3] == ["a", "b", "c"]


def test_agent_neighbor_modal_option_text_includes_row_metadata() -> None:
    plain = _agent_neighbor_option_text("a", _choices(2)[1]).plain

    assert "a" in plain
    assert "foo.agent1" in plain
    assert "DONE" in plain
    assert "@review" in plain
    assert "4m" in plain


def test_agent_neighbor_modal_option_text_tags_dismissed_rows() -> None:
    choice = AgentNeighborChoice(
        agent_name="foo.dismissed",
        display_name="demo",
        status="DONE",
        panel_label="@review",
        dismissed=True,
        group="descendant",
    )

    plain = _agent_neighbor_option_text("a", choice).plain

    assert "foo.dismissed" in plain
    assert "dismissed" in plain


def test_agent_neighbor_modal_title_summarizes_neighbors() -> None:
    modal = AgentNeighborModal("foo.bar", _choices(2))

    title = modal._title_text()

    assert title == "Neighbors of foo.bar  [2 neighbors]"


def test_agent_neighbor_modal_title_singularizes_one_neighbor() -> None:
    modal = AgentNeighborModal("foo", _choices(1))

    assert modal._title_text() == "Neighbors of foo  [1 neighbor]"


def test_agent_neighbor_modal_title_summarizes_two_groups() -> None:
    choices = [
        AgentNeighborChoice(
            agent_name="foo.child",
            display_name="child",
            status="DONE",
            panel_label="@api",
            group="descendant",
        ),
        *_choices(2),
    ]
    modal = AgentNeighborModal("foo", choices)

    assert modal._title_text() == "Neighbors of foo  [1 descendant - 2 neighbors]"


def test_agent_neighbor_modal_title_summarizes_ancestors_first() -> None:
    choices = [
        AgentNeighborChoice(
            agent_name="foo",
            display_name="parent",
            status="DONE",
            panel_label="@api",
            group="ancestor",
        ),
        AgentNeighborChoice(
            agent_name="foo.bar.child",
            display_name="child",
            status="RUNNING",
            panel_label="@api",
            group="descendant",
        ),
        *_choices(1),
    ]
    modal = AgentNeighborModal("foo.bar", choices)

    assert modal._title_text() == (
        "Neighbors of foo.bar  [1 ancestor - 1 descendant - 1 neighbor]"
    )


async def test_agent_neighbor_modal_headers_are_non_selectable() -> None:
    choices = [
        AgentNeighborChoice(
            agent_name="foo",
            display_name="parent",
            status="DONE",
            panel_label="@api",
            group="ancestor",
        ),
        AgentNeighborChoice(
            agent_name="foo.child",
            display_name="child",
            status="DONE",
            panel_label="@api",
            group="descendant",
        ),
        *_choices(1),
    ]

    async with _TestApp().run_test() as pilot:
        modal = AgentNeighborModal("foo", choices)
        pilot.app.push_screen(modal)
        await pilot.pause()

        option_list = modal.query_one("#agent-neighbor-list", OptionList)
        first = option_list.get_option_at_index(0)
        second_header = option_list.get_option_at_index(2)
        third_header = option_list.get_option_at_index(4)

    assert first.disabled is True
    assert "Ancestors (1)" in first.prompt.plain
    assert second_header.disabled is True
    assert "Descendants (1)" in second_header.prompt.plain
    assert third_header.disabled is True
    assert "Neighbors - foo hood (1)" in third_header.prompt.plain


def test_agent_neighbor_modal_sections_neighbors_when_hood_changes() -> None:
    choices = [
        AgentNeighborChoice(
            agent_name="A.B.duplicate",
            display_name="duplicate",
            status="DONE",
            panel_label="@api",
            group="neighbor",
            hood="A.B.C",
        ),
        AgentNeighborChoice(
            agent_name="A.B.nephew",
            display_name="nephew",
            status="RUNNING",
            panel_label="@api",
            group="neighbor",
            hood="A.B",
        ),
        AgentNeighborChoice(
            agent_name="A.B.sibling-subtree",
            display_name="sibling-subtree",
            status="RUNNING",
            panel_label="@api",
            group="neighbor",
            hood="A.B",
        ),
        AgentNeighborChoice(
            agent_name="A.cousin",
            display_name="cousin",
            status="DONE",
            panel_label="@review",
            group="neighbor",
            hood="A",
        ),
    ]
    modal = AgentNeighborModal("A.B.C", choices)

    headers = [
        option.prompt.plain for option in modal._create_options() if option.disabled
    ]

    assert headers == [
        "-- Neighbors - A.B.C hood (1) --------------------",
        "-- Neighbors - A.B hood (2) --------------------",
        "-- Neighbors - A hood (1) --------------------",
    ]
