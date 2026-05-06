"""Performance and hardening tests for the artifact panel modal."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
import threading
from time import perf_counter
from typing import Any

import pytest
from rich.console import RenderableType
from textual.app import App, ComposeResult
from textual.widgets import Input, OptionList, Static

from sase.ace.tui.modals.artifact_panel_modal import ArtifactPanelModal, _row_label
from sase.ace.tui.modals.artifact_panel_state import (
    build_artifact_panel_rows,
    paged_model_from_paged_detail,
)
from sase.core.artifact_wire import (
    ARTIFACT_WIRE_SCHEMA_VERSION,
    ArtifactDetailPagedWire,
    ArtifactDetailWire,
    ArtifactGroupSummaryWire,
    ArtifactGraphOptionsWire,
    ArtifactGraphWire,
    ArtifactLinkWire,
    ArtifactNodeWire,
    ArtifactPageRequestWire,
    ArtifactRelationPageWire,
    ArtifactTypeCountWire,
)


class _ModalTestApp(App[None]):
    ENABLE_COMMAND_PALETTE = False

    def compose(self) -> ComposeResult:
        yield from ()


def _node(
    artifact_id: str,
    kind: str = "file",
    title: str | None = None,
    metadata: dict[str, Any] | None = None,
    subtitle: str | None = None,
    updated_at: str | None = None,
) -> ArtifactNodeWire:
    return ArtifactNodeWire(
        id=artifact_id,
        kind=kind,
        display_title=title or artifact_id,
        subtitle=subtitle,
        provenance="derived",
        metadata=metadata or {},
        updated_at=updated_at,
    )


def _detail(
    artifact_id: str,
    *,
    kind: str = "file",
    title: str | None = None,
    metadata: dict[str, Any] | None = None,
    children: list[ArtifactNodeWire] | None = None,
    outbound_links: list[ArtifactLinkWire] | None = None,
    inbound_links: list[ArtifactLinkWire] | None = None,
    path_to_root: list[ArtifactNodeWire] | None = None,
) -> ArtifactDetailWire:
    return ArtifactDetailWire(
        schema_version=ARTIFACT_WIRE_SCHEMA_VERSION,
        node=_node(artifact_id, kind, title, metadata),
        children=children or [],
        outbound_links=outbound_links or [],
        inbound_links=inbound_links or [],
        path_to_root=path_to_root or [],
    )


def _missing_detail() -> ArtifactDetailWire:
    return ArtifactDetailWire(schema_version=ARTIFACT_WIRE_SCHEMA_VERSION, node=None)


def _paged_detail(
    artifact_id: str,
    *,
    kind: str = "file",
    title: str | None = None,
    metadata: dict[str, Any] | None = None,
    children: list[ArtifactNodeWire] | None = None,
    child_total: int | None = None,
    outbound_links: list[ArtifactLinkWire] | None = None,
    inbound_links: list[ArtifactLinkWire] | None = None,
    path_to_root: list[ArtifactNodeWire] | None = None,
    type_counts: list[ArtifactTypeCountWire] | None = None,
) -> ArtifactDetailPagedWire:
    loaded_children = children or []
    loaded_outbound = outbound_links or []
    loaded_inbound = inbound_links or []
    children_page = (
        ArtifactRelationPageWire(
            summary=ArtifactGroupSummaryWire(
                group_key="children",
                direction="children",
                total_count=child_total
                if child_total is not None
                else len(loaded_children),
                loaded_count=len(loaded_children),
            ),
            nodes=loaded_children,
        )
        if loaded_children or child_total is not None
        else None
    )
    outbound_pages = [
        ArtifactRelationPageWire(
            summary=ArtifactGroupSummaryWire(
                group_key=f"outbound:{link.link_type}",
                direction="outbound",
                link_type=link.link_type,
                total_count=1,
                loaded_count=1,
            ),
            links=[link],
        )
        for link in loaded_outbound
    ]
    inbound_pages = [
        ArtifactRelationPageWire(
            summary=ArtifactGroupSummaryWire(
                group_key=f"inbound:{link.link_type}",
                direction="inbound",
                link_type=link.link_type,
                total_count=1,
                loaded_count=1,
            ),
            links=[link],
        )
        for link in loaded_inbound
    ]
    return ArtifactDetailPagedWire(
        schema_version=ARTIFACT_WIRE_SCHEMA_VERSION,
        node=_node(artifact_id, kind, title, metadata),
        children_page=children_page,
        outbound_pages=outbound_pages,
        inbound_pages=inbound_pages,
        path_to_root=path_to_root or [],
        type_counts=type_counts or [],
    )


class _LargeFakeArtifactGraph:
    """Deterministic large graph fixture that avoids Rust and user state."""

    def __init__(self, *, linked_count: int = 240) -> None:
        self.show_calls: list[str] = []
        self.graph_calls: list[ArtifactGraphOptionsWire] = []
        self.export_calls: list[tuple[ArtifactGraphOptionsWire, str]] = []
        self.details = self._build_details(linked_count)

    def show(self, index_path: str | Any, artifact_id: str) -> ArtifactDetailWire:
        del index_path
        self.show_calls.append(artifact_id)
        return self.details[artifact_id]

    def graph(
        self, index_path: str | Any, options: ArtifactGraphOptionsWire
    ) -> ArtifactGraphWire:
        del index_path
        self.graph_calls.append(options)
        root_id = options.root_id or "/"
        nodes = [self.details[root_id].node, *self.details[root_id].children]
        limit = options.limit or len(nodes)
        return ArtifactGraphWire(
            schema_version=ARTIFACT_WIRE_SCHEMA_VERSION,
            root_id=root_id,
            nodes=[node for node in nodes if node is not None][:limit],
            node_count=len(nodes),
            link_count=len(self.details[root_id].outbound_links)
            + len(self.details[root_id].inbound_links),
            truncated=len(nodes) > limit,
        )

    def export(
        self,
        index_path: str | Any,
        options: ArtifactGraphOptionsWire,
        output_format: str,
    ) -> str:
        del index_path
        self.export_calls.append((options, output_format))
        return "flowchart TD\n  root --> child\n"

    def _build_details(self, linked_count: int) -> dict[str, ArtifactDetailWire]:
        root_children = [
            _node(f"changespec:{idx}", "changespec", f"ChangeSpec {idx}")
            for idx in range(linked_count)
        ]
        changespec_children = [
            _node(f"agent:{idx}", "agent", f"Agent {idx}")
            for idx in range(linked_count)
        ]
        agent_children = [
            _node(
                f"file:{idx}",
                "file",
                f"File {idx}",
                {"path": f"/tmp/nonexistent-artifact-{idx}.txt"},
            )
            for idx in range(linked_count)
        ]
        details = {
            "/": _detail("/", kind="root", children=root_children),
            "changespec:current": _detail(
                "changespec:current",
                kind="changespec",
                metadata={"name": "feature/current", "status": "WIP"},
                children=changespec_children,
                outbound_links=[
                    ArtifactLinkWire(
                        id=f"cs-created-{idx}",
                        link_type="created",
                        source_id="changespec:current",
                        target_id=f"agent:{idx}",
                    )
                    for idx in range(linked_count)
                ],
                inbound_links=[
                    ArtifactLinkWire(
                        id=f"cs-related-{idx}",
                        link_type="related",
                        source_id=f"project:{idx}",
                        target_id="changespec:current",
                    )
                    for idx in range(linked_count)
                ],
                path_to_root=[_node("/", "root")],
            ),
            "agent:current": _detail(
                "agent:current",
                kind="agent",
                metadata={"status": "DONE", "provider": "codex"},
                children=agent_children,
                path_to_root=[_node("/", "root"), _node("changespec:current")],
            ),
        }
        for nodes in (root_children, changespec_children, agent_children):
            for node in nodes:
                details[node.id] = _detail(node.id, kind=node.kind)
        return details


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
    assert option_list.option_count == 11
    assert "child:child:0" in visible_ids
    assert "child:child:9" in visible_ids


def test_rich_row_model_includes_semantic_fields_and_group_counts() -> None:
    child = _node(
        "file:/tmp/plan.md",
        "file",
        "plan.md",
        {"artifact_type": "plan", "status": "fresh"},
        subtitle="Epic plan",
        updated_at="2026-05-06T02:45:00Z",
    )
    paged = _paged_detail(
        "changespec:alpha",
        kind="changespec",
        children=[child],
        child_total=12,
    )

    model = paged_model_from_paged_detail(paged)
    rows = build_artifact_panel_rows(model.detail, paged_model=model).rows

    assert rows[0].label == "Children (1/12)"
    assert rows[0].selectable is False
    assert rows[1].artifact_id == "file:/tmp/plan.md"
    assert rows[1].artifact_kind == "file"
    assert rows[1].file_type == "plan"
    assert rows[1].edge_direction == "children"
    assert rows[1].title == "plan.md"
    assert rows[1].subtitle == "Epic plan · fresh"
    assert rows[1].updated_label == "2026-05-06"
    assert rows[1].group_key == "children"

    rendered = str(_row_label(rows[1]))
    assert "[PLAN]" in rendered
    assert "plan.md" in rendered
    assert "file:/tmp/plan.md" in rendered


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


@pytest.mark.parametrize("start_id", ["/", "changespec:current", "agent:current"])
@pytest.mark.asyncio
async def test_large_graph_open_smoke_documents_latency_and_query_counts(
    start_id: str, capsys: pytest.CaptureFixture[str]
) -> None:
    graph = _LargeFakeArtifactGraph()
    modal = ArtifactPanelModal(artifact_id=start_id, show_func=graph.show)
    app = _ModalTestApp()

    start = perf_counter()
    async with app.run_test() as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()
        await pilot.pause()
        option_list = modal.query_one("#artifact-panel-list", OptionList)
        assert option_list.option_count > 100
    elapsed_ms = (perf_counter() - start) * 1000

    query_counts = Counter(graph.show_calls)
    print(
        "artifact_panel_large_open "
        f"start={start_id} latency_ms={elapsed_ms:.2f} "
        f"show_calls={len(graph.show_calls)} "
        f"graph_calls={len(graph.graph_calls)} export_calls={len(graph.export_calls)}"
    )
    captured = capsys.readouterr()

    assert query_counts == Counter({start_id: 1})
    assert graph.graph_calls == []
    assert graph.export_calls == []
    assert f"start={start_id}" in captured.out
    assert "show_calls=1 graph_calls=0 export_calls=0" in captured.out


@pytest.mark.asyncio
async def test_row_navigation_does_not_requery_and_open_selected_queries_once() -> None:
    graph = _LargeFakeArtifactGraph()
    modal = ArtifactPanelModal(artifact_id="changespec:current", show_func=graph.show)
    app = _ModalTestApp()

    async with app.run_test() as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()
        await pilot.pause()

        modal.action_next_option()
        modal.action_next_option()
        modal.action_prev_option()
        await pilot.pause()
        assert graph.show_calls == ["changespec:current"]

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

    assert graph.show_calls == ["changespec:current", "agent:0"]


@pytest.mark.asyncio
async def test_missing_start_artifact_rebuilds_context_and_retries_once(
    tmp_path: Path,
) -> None:
    show_calls: list[str] = []
    refresh_calls: list[tuple[str, str, str | None, str | None]] = []
    context_path = tmp_path / "project.gp"

    def fake_show(index_path: str | Any, artifact_id: str) -> ArtifactDetailWire:
        show_calls.append(artifact_id)
        if len(show_calls) == 1:
            return _missing_detail()
        return _detail(artifact_id, kind="changespec")

    def fake_refresh(
        index_path: str | Any,
        artifact_id: str,
        ctx_path: str | Any | None,
        artifact_dir: str | Any | None,
    ) -> None:
        refresh_calls.append(
            (
                str(index_path),
                artifact_id,
                str(ctx_path) if ctx_path is not None else None,
                str(artifact_dir) if artifact_dir is not None else None,
            )
        )

    modal = ArtifactPanelModal(
        artifact_id="changespec:current",
        index_path="/tmp/artifacts.sqlite",
        show_func=fake_show,
        refresh_missing_func=fake_refresh,
        context_path=context_path,
    )
    app = _ModalTestApp()

    async with app.run_test() as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()
        await pilot.pause()

    assert show_calls == ["changespec:current", "changespec:current"]
    assert refresh_calls == [
        (
            "/tmp/artifacts.sqlite",
            "changespec:current",
            str(context_path),
            None,
        )
    ]
    assert modal._detail is not None
    assert modal._detail.node is not None


@pytest.mark.asyncio
async def test_missing_start_artifact_does_not_refresh_more_than_once(
    tmp_path: Path,
) -> None:
    show_calls: list[str] = []
    refresh_calls: list[str] = []

    def fake_show(index_path: str | Any, artifact_id: str) -> ArtifactDetailWire:
        del index_path
        show_calls.append(artifact_id)
        return _missing_detail()

    def fake_refresh(
        index_path: str | Any,
        artifact_id: str,
        ctx_path: str | Any | None,
        artifact_dir: str | Any | None,
    ) -> None:
        del index_path, ctx_path, artifact_dir
        refresh_calls.append(artifact_id)

    modal = ArtifactPanelModal(
        artifact_id="changespec:missing",
        show_func=fake_show,
        refresh_missing_func=fake_refresh,
        context_path=tmp_path / "project.gp",
    )
    app = _ModalTestApp()

    async with app.run_test() as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()
        await pilot.pause()
        modal.action_root()
        await pilot.pause()
        await pilot.pause()
        modal._navigate_to("changespec:missing")
        await pilot.pause()
        await pilot.pause()

    assert show_calls == [
        "changespec:missing",
        "changespec:missing",
        "/",
        "/",
        "changespec:missing",
    ]
    assert refresh_calls == ["changespec:missing", "/"]


@pytest.mark.asyncio
async def test_artifact_load_error_renders_error_without_broad_queries() -> None:
    show_calls: list[str] = []
    graph_calls: list[ArtifactGraphOptionsWire] = []
    export_calls: list[tuple[ArtifactGraphOptionsWire, str]] = []

    def fake_show(index_path: str | Any, artifact_id: str) -> ArtifactDetailWire:
        del index_path
        show_calls.append(artifact_id)
        raise RuntimeError("synthetic artifact backend failure")

    def fake_graph(
        index_path: str | Any, options: ArtifactGraphOptionsWire
    ) -> ArtifactGraphWire:
        del index_path
        graph_calls.append(options)
        return ArtifactGraphWire(schema_version=ARTIFACT_WIRE_SCHEMA_VERSION)

    def fake_export(
        index_path: str | Any,
        options: ArtifactGraphOptionsWire,
        output_format: str,
    ) -> str:
        del index_path
        export_calls.append((options, output_format))
        return ""

    modal = ArtifactPanelModal(
        artifact_id="broken",
        show_func=fake_show,
        graph_func=fake_graph,
        export_func=fake_export,
    )
    app = _ModalTestApp()

    async with app.run_test() as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()
        await pilot.pause()
        modal.action_next_option()
        modal.action_prev_option()
        await pilot.pause()
        detail_text = str(modal.query_one("#artifact-panel-detail", Static).render())

    assert show_calls == ["broken"]
    assert graph_calls == []
    assert export_calls == []
    assert "Artifact load failed" in detail_text
    assert "synthetic artifact backend failure" in detail_text


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
