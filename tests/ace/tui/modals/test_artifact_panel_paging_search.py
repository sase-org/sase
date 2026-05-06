"""Paging, local filtering, and global search tests for the artifact panel modal."""

from __future__ import annotations

from typing import Any

import pytest
from textual.widgets import Input, OptionList

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
async def test_paged_modal_open_does_not_render_hundreds_of_initial_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loaded_children = [_node(f"child:{idx}", "agent") for idx in range(10)]
    paged_calls: list[str] = []

    def fake_paged_show(
        index_path: str | Any,
        artifact_id: str,
        request: ArtifactPageRequestWire | None = None,
    ) -> ArtifactDetailPagedWire:
        del index_path, request
        paged_calls.append(artifact_id)
        return _paged_detail(
            artifact_id,
            kind="changespec",
            children=loaded_children,
            child_total=240,
        )

    monkeypatch.setattr(
        "sase.core.artifact_facade.artifact_show_paged",
        fake_paged_show,
    )

    modal = ArtifactPanelModal(artifact_id="alpha", index_path="/tmp/fake.sqlite")
    app = _ModalTestApp()

    async with app.run_test() as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()
        await pilot.pause()
        option_list = modal.query_one("#artifact-panel-list", OptionList)
        visible_ids = [
            option_list.get_option_at_index(index).id
            for index in range(option_list.option_count)
        ]

    assert paged_calls == ["alpha"]
    assert option_list.option_count == 12
    assert "child:child:0" in visible_ids
    assert "child:child:9" in visible_ids
    assert "show-more:children" in visible_ids


@pytest.mark.asyncio
async def test_show_more_fetches_and_merges_only_the_selected_group_page() -> None:
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
        option_list = modal.query_one("#artifact-panel-list", OptionList)
        for index in range(option_list.option_count):
            if option_list.get_option_at_index(index).id == "show-more:children":
                option_list.highlighted = index
                break
        else:
            raise AssertionError("show more row was not rendered")

        modal.action_open_selected()
        for _ in range(10):
            await pilot.pause()
            if len(paged_calls) == 2:
                break

        visible_ids = [
            option_list.get_option_at_index(index).id
            for index in range(option_list.option_count)
        ]

    assert len(paged_calls) == 2
    assert paged_calls[0] is not None
    assert paged_calls[0].offset == 0
    assert paged_calls[0].limit == 10
    assert paged_calls[1] is not None
    assert paged_calls[1].relation == "children"
    assert paged_calls[1].group_key == "children"
    assert paged_calls[1].offset == 10
    assert paged_calls[1].limit == 10
    assert "child:child:0" in visible_ids
    assert "child:child:19" in visible_ids
    assert "show-more:children" in visible_ids


@pytest.mark.asyncio
async def test_local_filter_uses_loaded_rows_without_fetching_more_pages() -> None:
    paged_calls: list[ArtifactPageRequestWire | None] = []
    loaded_children = [
        _node(f"child:{idx}", "agent", f"Child {idx}") for idx in range(10)
    ]

    def fake_paged_show(
        index_path: str | Any,
        artifact_id: str,
        request: ArtifactPageRequestWire | None = None,
    ) -> ArtifactDetailPagedWire:
        del index_path
        paged_calls.append(request)
        return _paged_detail(
            artifact_id,
            kind="changespec",
            children=loaded_children,
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
        for _ in range(10):
            await pilot.pause()
            if paged_calls:
                break

        filter_input = modal.query_one("#artifact-panel-filter", Input)
        filter_input.value = "Child 9"
        await pilot.pause()
        option_list = modal.query_one("#artifact-panel-list", OptionList)
        filtered_ids = [
            option_list.get_option_at_index(index).id
            for index in range(option_list.option_count)
        ]

        filter_input.value = ""
        await pilot.pause()
        restored_ids = [
            option_list.get_option_at_index(index).id
            for index in range(option_list.option_count)
        ]

    assert len(paged_calls) == 1
    assert filtered_ids == ["group:children", "child:child:9"]
    assert "show-more:children" in restored_ids


@pytest.mark.asyncio
async def test_local_filter_never_calls_global_artifact_search() -> None:
    search_calls: list[ArtifactQueryWire] = []

    def fake_search(
        index_path: str | Any,
        query: ArtifactQueryWire,
    ) -> list[ArtifactNodeWire]:
        del index_path
        search_calls.append(query)
        raise AssertionError("local filter must not run global artifact search")

    modal = ArtifactPanelModal(
        artifact_id="alpha",
        index_path="/tmp/fake.sqlite",
        show_paged_func=lambda index_path, artifact_id, request=None: _paged_detail(
            artifact_id,
            kind="changespec",
            children=[_node("child:needle", "agent", "Needle child")],
            child_total=20,
        ),
        search_func=fake_search,
    )
    app = _ModalTestApp()

    async with app.run_test() as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()
        await pilot.pause()

        filter_input = modal.query_one("#artifact-panel-filter", Input)
        filter_input.value = "needle"
        await pilot.pause()

    assert search_calls == []


@pytest.mark.asyncio
async def test_global_search_uses_bounded_query_and_navigates_with_history() -> None:
    show_calls: list[str] = []
    search_calls: list[ArtifactQueryWire] = []

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
        del index_path
        search_calls.append(query)
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

        modal.action_focus_global_search()
        search_input = modal.query_one("#artifact-panel-search", Input)
        search_input.value = "beta"
        for _ in range(10):
            await pilot.pause()
            if search_calls:
                break

        option_list = modal.query_one("#artifact-panel-list", OptionList)
        for index in range(option_list.option_count):
            if option_list.get_option_at_index(index).id == "search:agent:beta":
                option_list.highlighted = index
                break
        else:
            raise AssertionError("global search result row was not rendered")

        modal.action_open_selected()
        for _ in range(10):
            await pilot.pause()
            if show_calls == ["agent:alpha", "agent:beta"]:
                break

    assert len(search_calls) == 1
    assert search_calls[0].text == "beta"
    assert search_calls[0].limit == 25
    assert search_calls[0].offset == 0
    assert show_calls == ["agent:alpha", "agent:beta"]
    assert modal._state.current_id == "agent:beta"
    assert modal._state.back_stack == ["agent:alpha"]
    assert modal._search_text == ""


@pytest.mark.asyncio
async def test_global_search_empty_and_error_states_are_recoverable() -> None:
    search_calls: list[str | None] = []

    def fake_search(
        index_path: str | Any,
        query: ArtifactQueryWire,
    ) -> list[ArtifactNodeWire]:
        del index_path
        search_calls.append(query.text)
        if query.text == "boom":
            raise RuntimeError("synthetic search failure")
        return []

    modal = ArtifactPanelModal(
        artifact_id="alpha",
        index_path="/tmp/fake.sqlite",
        show_paged_func=lambda index_path, artifact_id, request=None: _paged_detail(
            artifact_id,
            kind="changespec",
        ),
        search_func=fake_search,
    )
    app = _ModalTestApp()

    async with app.run_test() as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()
        await pilot.pause()

        search_input = modal.query_one("#artifact-panel-search", Input)
        search_input.value = "boom"
        for _ in range(10):
            await pilot.pause()
            option_list = modal.query_one("#artifact-panel-list", OptionList)
            detail = str(option_list.get_option_at_index(0).prompt)
            if "Search failed" in detail:
                break
        option_list = modal.query_one("#artifact-panel-list", OptionList)
        error_text = str(option_list.get_option_at_index(0).prompt)

        search_input.value = "missing"
        for _ in range(10):
            await pilot.pause()
            option_list = modal.query_one("#artifact-panel-list", OptionList)
            detail = str(option_list.get_option_at_index(0).prompt)
            if "No global results" in detail:
                break
        option_list = modal.query_one("#artifact-panel-list", OptionList)
        empty_text = str(option_list.get_option_at_index(0).prompt)

    assert search_calls == ["boom", "missing"]
    assert "Search failed: synthetic search failure" in error_text
    assert "No global results for 'missing'" in empty_text
