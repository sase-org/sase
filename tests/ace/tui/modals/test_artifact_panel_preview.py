"""Graph preview and detail preview tests for the artifact panel modal."""

from __future__ import annotations

import threading

import pytest
from rich.console import RenderableType
from textual.widgets import Input, OptionList, Static

from sase.ace.tui.modals.artifact_panel_modal import ArtifactPanelModal
from sase.core.artifact_wire import ArtifactDetailWire
from tests.ace.tui.modals._artifact_panel_modal_helpers import (
    _LargeFakeArtifactGraph,
    _ModalTestApp,
)


@pytest.mark.asyncio
async def test_graph_preview_and_export_are_bounded_and_explicit() -> None:
    graph = _LargeFakeArtifactGraph()
    modal = ArtifactPanelModal(
        artifact_id="agent:current",
        show_func=graph.show,
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
        show_func=graph.show,
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
    assert graph.show_calls == ["agent:current"]


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
        show_func=graph.show,
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

    assert graph.show_calls == ["changespec:current", "agent:0"]
    assert render_calls[:2] == ["changespec:current", "agent:0"]
    assert "fresh preview for agent:0" in detail_text
    assert "stale changespec preview" not in detail_text
