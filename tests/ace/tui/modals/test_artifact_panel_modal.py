"""Load, header, and navigation tests for the artifact panel modal."""

from __future__ import annotations

from collections import Counter
from time import perf_counter
from typing import Any

import pytest
from rich.console import RenderableType
from textual.widgets import OptionList, Static

from sase.ace.tui.modals.artifact_panel_modal import ArtifactPanelModal
from sase.core.artifact_wire import (
    ARTIFACT_WIRE_SCHEMA_VERSION,
    ArtifactDetailPagedWire,
    ArtifactDetailWire,
    ArtifactGroupSummaryWire,
    ArtifactLinkWire,
    ArtifactPageRequestWire,
    ArtifactRelationPageWire,
    ArtifactTypeCountWire,
)
from tests.ace.tui.modals._artifact_panel_modal_helpers import (
    _LargeFakeArtifactGraph,
    _ModalTestApp,
    _node,
    _paged_detail,
    _render_text,
)


@pytest.mark.asyncio
async def test_default_modal_load_uses_paged_show_and_projects_legacy_detail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paged_calls: list[tuple[str, str, ArtifactPageRequestWire | None]] = []
    legacy_calls: list[str] = []
    child = _node("child:one", "agent", "Child one")
    link = ArtifactLinkWire(
        id="out-1",
        link_type="created",
        source_id="alpha",
        target_id="agent:one",
    )

    def fake_paged_show(
        index_path: str | Any,
        artifact_id: str,
        request: ArtifactPageRequestWire | None = None,
    ) -> ArtifactDetailPagedWire:
        paged_calls.append((str(index_path), artifact_id, request))
        return _paged_detail(
            artifact_id,
            kind="changespec",
            children=[child],
            outbound_links=[link],
            path_to_root=[_node("/", "root")],
        )

    def fake_legacy_show(index_path: str | Any, artifact_id: str) -> ArtifactDetailWire:
        del index_path
        legacy_calls.append(artifact_id)
        raise AssertionError("legacy artifact_show should not be used")

    monkeypatch.setattr(
        "sase.core.artifact_facade.artifact_show_paged",
        fake_paged_show,
    )
    monkeypatch.setattr("sase.core.artifact_facade.artifact_show", fake_legacy_show)

    modal = ArtifactPanelModal(
        artifact_id="alpha",
        index_path="/tmp/fake-artifacts.sqlite",
    )
    app = _ModalTestApp()

    async with app.run_test() as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()
        await pilot.pause()

    assert [(path, artifact_id) for path, artifact_id, _ in paged_calls] == [
        ("/tmp/fake-artifacts.sqlite", "alpha")
    ]
    assert isinstance(paged_calls[0][2], ArtifactPageRequestWire)
    assert legacy_calls == []
    assert modal._paged_model is not None
    assert modal._detail is not None
    assert [node.id for node in modal._detail.children] == ["child:one"]
    assert [link.target_id for link in modal._detail.outbound_links] == ["agent:one"]


@pytest.mark.asyncio
async def test_artifact_modal_renders_persistent_header_with_counts() -> None:
    child = _node("agent:child", "agent", "Child agent")

    def fake_paged_show(
        index_path: str | Any,
        artifact_id: str,
        request: ArtifactPageRequestWire | None = None,
    ) -> ArtifactDetailPagedWire:
        del index_path, request
        return _paged_detail(
            artifact_id,
            kind="changespec",
            title="Alpha CL",
            metadata={"status": "WIP"},
            children=[child],
            child_total=12,
            path_to_root=[_node("/", "root", "/")],
            type_counts=[ArtifactTypeCountWire("agent", 12)],
        )

    modal = ArtifactPanelModal(
        artifact_id="changespec:alpha",
        index_path="/tmp/fake.sqlite",
        show_paged_func=fake_paged_show,
    )
    app = _ModalTestApp()

    async with app.run_test() as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()
        await pilot.pause()
        primary = str(
            modal.query_one("#artifact-panel-header-primary", Static).render()
        )
        path = str(modal.query_one("#artifact-panel-header-path", Static).render())
        counts = str(modal.query_one("#artifact-panel-header-counts", Static).render())

    assert "[CL]" in primary
    assert "Alpha CL" in primary
    assert "WIP" in primary
    assert "derived" in primary
    assert "Path: / > Alpha CL" in path
    assert "children 1/12" in counts
    assert "agent 12" in counts


@pytest.mark.asyncio
async def test_artifact_modal_passes_paged_relationship_context_to_default_renderer() -> (
    None
):
    show_calls: list[ArtifactPageRequestWire | None] = []
    child = _node("agent:child", "agent", "Child agent")
    created_link = ArtifactLinkWire(
        id="created-1",
        link_type="created",
        source_id="changespec:alpha",
        target_id="file:plan",
        metadata={"target_title": "Plan file"},
    )
    worker_link = ArtifactLinkWire(
        id="worker-1",
        link_type="worker",
        source_id="changespec:alpha",
        target_id="agent:worker",
        metadata={"target_title": "Worker agent"},
    )
    inbound_link = ArtifactLinkWire(
        id="related-1",
        link_type="related",
        source_id="changespec:beta",
        target_id="changespec:alpha",
        metadata={"source_title": "Beta CL"},
    )

    def fake_paged_show(
        index_path: str | Any,
        artifact_id: str,
        request: ArtifactPageRequestWire | None = None,
    ) -> ArtifactDetailPagedWire:
        del index_path
        show_calls.append(request)
        assert artifact_id == "changespec:alpha"
        return ArtifactDetailPagedWire(
            schema_version=ARTIFACT_WIRE_SCHEMA_VERSION,
            node=_node(artifact_id, "changespec", "Alpha CL"),
            path_to_root=[_node("/", "root", "/")],
            children_page=ArtifactRelationPageWire(
                summary=ArtifactGroupSummaryWire(
                    group_key="children",
                    direction="children",
                    total_count=12,
                    loaded_count=1,
                ),
                nodes=[child],
            ),
            outbound_pages=[
                ArtifactRelationPageWire(
                    summary=ArtifactGroupSummaryWire(
                        group_key="outbound:created",
                        direction="outbound",
                        link_type="created",
                        total_count=7,
                        loaded_count=1,
                    ),
                    links=[created_link],
                ),
                ArtifactRelationPageWire(
                    summary=ArtifactGroupSummaryWire(
                        group_key="outbound:worker",
                        direction="outbound",
                        link_type="worker",
                        total_count=1,
                        loaded_count=1,
                    ),
                    links=[worker_link],
                ),
            ],
            inbound_pages=[
                ArtifactRelationPageWire(
                    summary=ArtifactGroupSummaryWire(
                        group_key="inbound:related",
                        direction="inbound",
                        link_type="related",
                        total_count=4,
                        loaded_count=1,
                    ),
                    links=[inbound_link],
                )
            ],
            type_counts=[ArtifactTypeCountWire("agent", 12)],
        )

    modal = ArtifactPanelModal(
        artifact_id="changespec:alpha",
        index_path="/tmp/fake.sqlite",
        show_paged_func=fake_paged_show,
    )
    app = _ModalTestApp()

    async with app.run_test() as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()
        await pilot.pause()
        await pilot.pause()
        assert modal._render_worker is not None
        assert modal._render_worker.result is not None
        detail_text = _render_text(modal._render_worker.result)

    assert len(show_calls) == 1
    assert "Context" in detail_text
    assert "Parent: /" in detail_text
    assert "Children: 1/12 - Child agent (agent:child)" in detail_text
    assert "Created: 1/7 - Plan file (file:plan)" in detail_text
    assert "Worker: 1 - Worker agent (agent:worker)" in detail_text
    assert "Related from: 1/4 - Beta CL (changespec:beta)" in detail_text
    assert "Inbound: related=1/4" in detail_text
    assert "Types: agent=12" in detail_text


@pytest.mark.asyncio
async def test_artifact_modal_keeps_one_argument_custom_detail_renderer_compatible() -> (
    None
):
    renderer_calls: list[str] = []

    def custom_renderer(detail: ArtifactDetailWire) -> RenderableType:
        assert detail.node is not None
        renderer_calls.append(detail.node.id)
        return f"custom render for {detail.node.id}"

    modal = ArtifactPanelModal(
        artifact_id="alpha",
        index_path="/tmp/fake.sqlite",
        show_paged_func=lambda index_path, artifact_id, request=None: _paged_detail(
            artifact_id,
            kind="changespec",
            children=[_node("child:one", "agent")],
            child_total=12,
        ),
        detail_renderer=custom_renderer,
    )
    app = _ModalTestApp()

    async with app.run_test() as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()
        await pilot.pause()
        detail_text = str(modal.query_one("#artifact-panel-detail", Static).render())

    assert renderer_calls == ["alpha"]
    assert "custom render for alpha" in detail_text


@pytest.mark.parametrize("start_id", ["/", "changespec:current", "agent:current"])
@pytest.mark.asyncio
async def test_large_graph_paged_open_smoke_documents_latency_and_query_counts(
    start_id: str, capsys: pytest.CaptureFixture[str]
) -> None:
    graph = _LargeFakeArtifactGraph()
    modal = ArtifactPanelModal(artifact_id=start_id, show_paged_func=graph.show_paged)
    app = _ModalTestApp()

    start = perf_counter()
    async with app.run_test() as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()
        await pilot.pause()
        option_list = modal.query_one("#artifact-panel-list", OptionList)
        assert 1 <= option_list.option_count <= 40
    elapsed_ms = (perf_counter() - start) * 1000

    query_counts = Counter(artifact_id for artifact_id, _ in graph.show_paged_calls)
    print(
        "artifact_panel_large_paged_open "
        f"start={start_id} latency_ms={elapsed_ms:.2f} "
        f"show_paged_calls={len(graph.show_paged_calls)} "
        f"show_calls={len(graph.show_calls)} "
        f"graph_calls={len(graph.graph_calls)} export_calls={len(graph.export_calls)}"
    )
    captured = capsys.readouterr()

    assert query_counts == Counter({start_id: 1})
    assert graph.show_paged_calls[0][1].limit == 10
    assert graph.show_calls == []
    assert graph.graph_calls == []
    assert graph.export_calls == []
    assert f"start={start_id}" in captured.out
    assert "show_paged_calls=1 show_calls=0 graph_calls=0 export_calls=0" in (
        captured.out
    )


@pytest.mark.asyncio
async def test_paged_row_navigation_does_not_requery_or_call_broad_graph(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = _LargeFakeArtifactGraph()
    broad_calls: list[str] = []

    def fail_broad_call(*args: Any, **kwargs: Any) -> None:
        del args, kwargs
        broad_calls.append("called")
        raise AssertionError("hot row navigation must not call broad artifact APIs")

    for name in ("artifact_rebuild", "artifact_list", "artifact_summary"):
        monkeypatch.setattr(f"sase.core.artifact_facade.{name}", fail_broad_call)

    modal = ArtifactPanelModal(
        artifact_id="changespec:current",
        show_paged_func=graph.show_paged,
    )
    app = _ModalTestApp()

    async with app.run_test() as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()
        await pilot.pause()

        modal.action_next_option()
        modal.action_next_option()
        modal.action_prev_option()
        await pilot.pause()
        assert [call[0] for call in graph.show_paged_calls] == ["changespec:current"]

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

    assert [call[0] for call in graph.show_paged_calls] == [
        "changespec:current",
        "agent:0",
    ]
    assert graph.show_calls == []
    assert graph.graph_calls == []
    assert graph.export_calls == []
    assert broad_calls == []


@pytest.mark.asyncio
async def test_legacy_show_func_compatibility_remains_single_detail_call() -> None:
    graph = _LargeFakeArtifactGraph(linked_count=8)
    modal = ArtifactPanelModal(
        artifact_id="changespec:current",
        show_func=graph.show,
    )
    app = _ModalTestApp()

    async with app.run_test() as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()
        await pilot.pause()
        option_list = modal.query_one("#artifact-panel-list", OptionList)
        assert option_list.option_count > 8

    assert graph.show_calls == ["changespec:current"]
    assert graph.show_paged_calls == []
