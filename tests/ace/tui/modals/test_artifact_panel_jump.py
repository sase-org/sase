"""Jump hint tests for the artifact panel modal."""

from __future__ import annotations

from typing import Any

import pytest
from textual.widgets import Input, OptionList, Static

from sase.ace.tui.modals.artifact_panel_modal import ArtifactPanelModal
from sase.core.artifact_wire import (
    ArtifactDetailPagedWire,
    ArtifactNodeWire,
    ArtifactPageRequestWire,
    ArtifactQueryWire,
)
from tests.ace.tui.modals._artifact_panel_modal_helpers import (
    _ModalTestApp,
    _node,
    _paged_detail,
)


@pytest.mark.asyncio
async def test_artifact_jump_hint_highlights_relationship_then_enter_opens() -> None:
    show_calls: list[str] = []
    children = [_node(f"child:{idx}", "agent", f"Child {idx}") for idx in range(3)]

    def fake_paged_show(
        index_path: str | Any,
        artifact_id: str,
        request: ArtifactPageRequestWire | None = None,
    ) -> ArtifactDetailPagedWire:
        del index_path, request
        show_calls.append(artifact_id)
        return _paged_detail(
            artifact_id,
            kind="changespec",
            children=children if artifact_id == "alpha" else [],
        )

    modal = ArtifactPanelModal(
        artifact_id="alpha",
        index_path="/tmp/fake.sqlite",
        show_paged_func=fake_paged_show,
    )
    app = _ModalTestApp()

    async with app.run_test() as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()
        await pilot.pause()

        await pilot.press("apostrophe")
        await pilot.pause()
        option_list = modal.query_one("#artifact-panel-list", OptionList)
        assert "[2]" in str(option_list.get_option_at_index(2).prompt)

        await pilot.press("2")
        await pilot.pause()

        assert show_calls == ["alpha"]
        assert option_list.get_option_at_index(option_list.highlighted).id == (
            "child:child:1"
        )

        await pilot.press("enter")
        for _ in range(10):
            await pilot.pause()
            if show_calls == ["alpha", "child:1"]:
                break

    assert show_calls == ["alpha", "child:1"]
    assert modal._state.current_id == "child:1"


@pytest.mark.asyncio
async def test_artifact_jump_hint_covers_show_more_without_activating() -> None:
    paged_calls: list[ArtifactPageRequestWire | None] = []

    def fake_paged_show(
        index_path: str | Any,
        artifact_id: str,
        request: ArtifactPageRequestWire | None = None,
    ) -> ArtifactDetailPagedWire:
        del index_path
        paged_calls.append(request)
        offset = request.offset if request is not None else 0
        children = [
            _node(f"child:{idx}", "agent") for idx in range(offset, offset + 10)
        ]
        return _paged_detail(
            artifact_id,
            kind="changespec",
            children=children,
            child_total=25,
        )

    modal = ArtifactPanelModal(
        artifact_id="alpha",
        index_path="/tmp/fake.sqlite",
        show_paged_func=fake_paged_show,
    )
    app = _ModalTestApp()

    async with app.run_test() as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()
        await pilot.pause()

        await pilot.press("apostrophe")
        await pilot.pause()
        option_list = modal.query_one("#artifact-panel-list", OptionList)
        show_more_index = next(
            index
            for index in range(option_list.option_count)
            if option_list.get_option_at_index(index).id == "show-more:children"
        )
        assert "[a]" in str(option_list.get_option_at_index(show_more_index).prompt)

        await pilot.press("a")
        await pilot.pause()

        assert len(paged_calls) == 1
        assert option_list.get_option_at_index(option_list.highlighted).id == (
            "show-more:children"
        )

        await pilot.press("enter")
        for _ in range(10):
            await pilot.pause()
            if len(paged_calls) == 2:
                break

    assert len(paged_calls) == 2
    assert paged_calls[1] is not None
    assert paged_calls[1].group_key == "children"
    assert paged_calls[1].offset == 10


@pytest.mark.asyncio
async def test_artifact_jump_hint_covers_search_results_and_escape_cancels() -> None:
    show_calls: list[str] = []

    def fake_paged_show(
        index_path: str | Any,
        artifact_id: str,
        request: ArtifactPageRequestWire | None = None,
    ) -> ArtifactDetailPagedWire:
        del index_path, request
        show_calls.append(artifact_id)
        return _paged_detail(artifact_id, kind="agent", title=f"Detail {artifact_id}")

    def fake_search(
        index_path: str | Any,
        query: ArtifactQueryWire,
    ) -> list[ArtifactNodeWire]:
        del index_path, query
        return [_node("agent:beta", "agent", "Beta agent")]

    modal = ArtifactPanelModal(
        artifact_id="agent:alpha",
        index_path="/tmp/fake.sqlite",
        show_paged_func=fake_paged_show,
        search_func=fake_search,
    )
    app = _ModalTestApp()

    async with app.run_test() as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()
        await pilot.pause()

        search_input = modal.query_one("#artifact-panel-search", Input)
        search_input.value = "beta"
        for _ in range(10):
            await pilot.pause()
            option_list = modal.query_one("#artifact-panel-list", OptionList)
            if option_list.get_option_at_index(0).id == "group:search-results":
                break

        await pilot.press("apostrophe")
        await pilot.pause()
        option_list = modal.query_one("#artifact-panel-list", OptionList)
        assert "[1]" in str(option_list.get_option_at_index(1).prompt)

        await pilot.press("escape")
        await pilot.pause()
        assert pilot.app.screen is modal
        assert modal._entry_jump_mode_active is False
        assert "': jump" in str(
            modal.query_one("#artifact-panel-hints", Static).render()
        )

        await pilot.press("apostrophe")
        await pilot.press("1")
        await pilot.pause()

        assert show_calls == ["agent:alpha"]
        assert option_list.get_option_at_index(option_list.highlighted).id == (
            "search:agent:beta"
        )

        await pilot.press("enter")
        for _ in range(10):
            await pilot.pause()
            if show_calls == ["agent:alpha", "agent:beta"]:
                break

    assert show_calls == ["agent:alpha", "agent:beta"]
    assert modal._state.current_id == "agent:beta"


@pytest.mark.asyncio
async def test_artifact_jump_repeated_apostrophe_toggles_previous_row() -> None:
    children = [_node(f"child:{idx}", "agent", f"Child {idx}") for idx in range(3)]
    modal = ArtifactPanelModal(
        artifact_id="alpha",
        index_path="/tmp/fake.sqlite",
        show_paged_func=lambda index_path, artifact_id, request=None: _paged_detail(
            artifact_id,
            kind="changespec",
            children=children,
        ),
    )
    app = _ModalTestApp()

    async with app.run_test() as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()
        await pilot.pause()
        option_list = modal.query_one("#artifact-panel-list", OptionList)
        assert option_list.get_option_at_index(option_list.highlighted).id == (
            "child:child:0"
        )

        await pilot.press("apostrophe")
        await pilot.press("2")
        await pilot.pause()
        assert option_list.get_option_at_index(option_list.highlighted).id == (
            "child:child:1"
        )

        await pilot.press("apostrophe")
        await pilot.press("apostrophe")
        await pilot.pause()
        assert option_list.get_option_at_index(option_list.highlighted).id == (
            "child:child:0"
        )
