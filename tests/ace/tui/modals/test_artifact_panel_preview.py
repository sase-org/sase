"""Graph preview and detail preview tests for the artifact panel modal."""

from __future__ import annotations

import threading
from typing import Any

import pytest
from rich.console import RenderableType
from textual.widgets import Input, OptionList, Static

from sase.ace.tui.modals.artifact_panel_modal import ArtifactPanelModal
from sase.core.artifact_wire import (
    ArtifactDetailPagedWire,
    ArtifactDetailWire,
    ArtifactNodeWire,
    ArtifactPageRequestWire,
    ArtifactQueryWire,
)
from tests.ace.tui.modals._artifact_panel_modal_helpers import (
    _LargeFakeArtifactGraph,
    _ModalTestApp,
    _node,
    _paged_detail,
)


@pytest.mark.asyncio
async def test_graph_preview_and_export_are_bounded_and_explicit() -> None:
    graph = _LargeFakeArtifactGraph()
    modal = ArtifactPanelModal(
        artifact_id="agent:current",
        show_paged_func=graph.show_paged,
        graph_func=graph.graph,
        export_func=graph.export,
    )
    app = _ModalTestApp()

    async with app.run_test() as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()
        await pilot.pause()
        modal.action_next_option()
        modal.action_prev_option()
        await pilot.pause()
        assert graph.graph_calls == []
        assert graph.export_calls == []

        modal.action_preview_graph()
        modal.action_export_graph()

    assert [(call.root_id, call.limit) for call in graph.graph_calls] == [
        ("agent:current", 100)
    ]
    assert [(call.root_id, call.limit, fmt) for call, fmt in graph.export_calls] == [
        ("agent:current", 100, "mermaid")
    ]
    assert graph.show_calls == []


@pytest.mark.asyncio
async def test_filter_updates_do_not_rerender_file_preview() -> None:
    render_calls: list[str] = []

    def render_detail(detail: ArtifactDetailWire) -> RenderableType:
        assert detail.node is not None
        render_calls.append(detail.node.id)
        return f"preview for {detail.node.id}"

    graph = _LargeFakeArtifactGraph()
    modal = ArtifactPanelModal(
        artifact_id="agent:current",
        show_paged_func=graph.show_paged,
        detail_renderer=render_detail,
    )
    app = _ModalTestApp()

    async with app.run_test() as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()
        await pilot.pause()
        await pilot.pause()
        assert render_calls == ["agent:current"]

        filter_input = modal.query_one("#artifact-panel-filter", Input)
        filter_input.value = "File 12"
        await pilot.pause()

    assert render_calls == ["agent:current"]
    assert [artifact_id for artifact_id, _ in graph.show_paged_calls] == [
        "agent:current"
    ]
    assert graph.show_calls == []


@pytest.mark.asyncio
async def test_late_load_result_is_ignored_after_rapid_navigation() -> None:
    beta_started = threading.Event()
    release_beta = threading.Event()
    show_calls: list[str] = []

    def fake_paged_show(
        index_path: str | Any,
        artifact_id: str,
        request: ArtifactPageRequestWire | None = None,
    ) -> ArtifactDetailPagedWire:
        del index_path, request
        show_calls.append(artifact_id)
        if artifact_id == "agent:beta":
            beta_started.set()
            release_beta.wait(timeout=2)
        children = []
        if artifact_id == "agent:alpha":
            children = [
                _node("agent:beta", "agent", "Beta agent"),
                _node("agent:gamma", "agent", "Gamma agent"),
            ]
        return _paged_detail(artifact_id, kind="agent", children=children)

    modal = ArtifactPanelModal(
        artifact_id="agent:alpha",
        index_path="/tmp/fake.sqlite",
        show_paged_func=fake_paged_show,
    )
    app = _ModalTestApp()

    async with app.run_test() as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()
        await pilot.pause()

        modal._navigate_to("agent:beta")
        for _ in range(20):
            await pilot.pause()
            if beta_started.is_set():
                break
        assert beta_started.is_set()

        modal._navigate_to("agent:gamma")
        for _ in range(20):
            await pilot.pause()
            if "agent:gamma" in show_calls:
                break
        release_beta.set()
        for _ in range(20):
            await pilot.pause()
            if modal._detail is not None and modal._detail.node is not None:
                if modal._detail.node.id == "agent:gamma":
                    break

    assert show_calls[:3] == ["agent:alpha", "agent:beta", "agent:gamma"]
    assert modal._state.current_id == "agent:gamma"
    assert modal._detail is not None
    assert modal._detail.node is not None
    assert modal._detail.node.id == "agent:gamma"


@pytest.mark.asyncio
async def test_filter_change_during_slow_render_keeps_current_preview() -> None:
    render_started = threading.Event()
    release_render = threading.Event()
    render_calls: list[str] = []

    def render_detail(detail: ArtifactDetailWire) -> RenderableType:
        assert detail.node is not None
        render_calls.append(detail.node.id)
        render_started.set()
        release_render.wait(timeout=2)
        return f"preview for {detail.node.id}"

    modal = ArtifactPanelModal(
        artifact_id="agent:current",
        index_path="/tmp/fake.sqlite",
        show_paged_func=lambda index_path, artifact_id, request=None: _paged_detail(
            artifact_id,
            kind="agent",
            children=[_node("file:needle", "file", "Needle file")],
        ),
        detail_renderer=render_detail,
    )
    app = _ModalTestApp()

    async with app.run_test() as pilot:
        pilot.app.push_screen(modal)
        for _ in range(20):
            await pilot.pause()
            if render_started.is_set():
                break
        assert render_started.is_set()

        filter_input = modal.query_one("#artifact-panel-filter", Input)
        filter_input.value = "Needle"
        await pilot.pause()
        release_render.set()
        for _ in range(20):
            await pilot.pause()
            detail_text = str(
                modal.query_one("#artifact-panel-detail", Static).render()
            )
            if "preview for agent:current" in detail_text:
                break
        detail_text = str(modal.query_one("#artifact-panel-detail", Static).render())

    assert render_calls == ["agent:current"]
    assert "preview for agent:current" in detail_text


@pytest.mark.asyncio
async def test_stale_detail_preview_worker_is_ignored_after_navigation() -> None:
    graph = _LargeFakeArtifactGraph(linked_count=4)
    alpha_started = threading.Event()
    release_alpha = threading.Event()
    render_calls: list[str] = []

    def render_detail(detail: ArtifactDetailWire) -> RenderableType:
        assert detail.node is not None
        render_calls.append(detail.node.id)
        if detail.node.id == "changespec:current":
            alpha_started.set()
            release_alpha.wait(timeout=2)
            return "stale changespec preview"
        return f"fresh preview for {detail.node.id}"

    modal = ArtifactPanelModal(
        artifact_id="changespec:current",
        show_paged_func=graph.show_paged,
        detail_renderer=render_detail,
    )
    app = _ModalTestApp()

    async with app.run_test() as pilot:
        pilot.app.push_screen(modal)
        for _ in range(20):
            await pilot.pause()
            if alpha_started.is_set():
                break
        assert alpha_started.is_set()

        option_list = modal.query_one("#artifact-panel-list", OptionList)
        for index in range(option_list.option_count):
            if option_list.get_option_at_index(index).id == "child:agent:0":
                option_list.highlighted = index
                break
        else:
            raise AssertionError("child:agent:0 row was not rendered")

        modal.action_open_selected()
        await pilot.pause()
        await pilot.pause()

        release_alpha.set()
        for _ in range(20):
            await pilot.pause()
            detail_text = str(
                modal.query_one("#artifact-panel-detail", Static).render()
            )
            if "fresh preview for agent:0" in detail_text:
                break

        detail_text = str(modal.query_one("#artifact-panel-detail", Static).render())

    assert [artifact_id for artifact_id, _ in graph.show_paged_calls] == [
        "changespec:current",
        "agent:0",
    ]
    assert graph.show_calls == []
    assert render_calls[:2] == ["changespec:current", "agent:0"]
    assert "fresh preview for agent:0" in detail_text
    assert "stale changespec preview" not in detail_text


@pytest.mark.asyncio
async def test_search_result_open_ignores_stale_detail_render_worker() -> None:
    alpha_started = threading.Event()
    release_alpha = threading.Event()
    render_calls: list[str] = []
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

    def render_detail(detail: ArtifactDetailWire) -> RenderableType:
        assert detail.node is not None
        render_calls.append(detail.node.id)
        if detail.node.id == "agent:alpha":
            alpha_started.set()
            release_alpha.wait(timeout=2)
            return "stale alpha preview"
        return f"fresh preview for {detail.node.id}"

    modal = ArtifactPanelModal(
        artifact_id="agent:alpha",
        index_path="/tmp/fake.sqlite",
        show_paged_func=fake_paged_show,
        search_func=fake_search,
        detail_renderer=render_detail,
    )
    app = _ModalTestApp()

    async with app.run_test() as pilot:
        pilot.app.push_screen(modal)
        for _ in range(20):
            await pilot.pause()
            if alpha_started.is_set():
                break
        assert alpha_started.is_set()

        search_input = modal.query_one("#artifact-panel-search", Input)
        search_input.value = "beta"
        for _ in range(10):
            await pilot.pause()
            option_list = modal.query_one("#artifact-panel-list", OptionList)
            if option_list.get_option_at_index(0).id == "group:search-results":
                break

        option_list = modal.query_one("#artifact-panel-list", OptionList)
        for index in range(option_list.option_count):
            if option_list.get_option_at_index(index).id == "search:agent:beta":
                option_list.highlighted = index
                break
        else:
            raise AssertionError("agent:beta search result was not rendered")

        modal.action_open_selected()
        release_alpha.set()
        for _ in range(20):
            await pilot.pause()
            detail_text = str(
                modal.query_one("#artifact-panel-detail", Static).render()
            )
            if "fresh preview for agent:beta" in detail_text:
                break
        detail_text = str(modal.query_one("#artifact-panel-detail", Static).render())

    assert show_calls == ["agent:alpha", "agent:beta"]
    assert render_calls[:2] == ["agent:alpha", "agent:beta"]
    assert modal._state.current_id == "agent:beta"
    assert "fresh preview for agent:beta" in detail_text
    assert "stale alpha preview" not in detail_text
