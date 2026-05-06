"""Fake TUI modal measurements for the artifact graph benchmark."""

from __future__ import annotations

import time
from collections import Counter
from typing import Any

from textual.app import App, ComposeResult
from textual.widgets import OptionList

from sase.ace.tui.modals.artifact_panel_modal import ArtifactPanelModal
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
)

from .records import query_record


class _ModalBenchApp(App[None]):
    ENABLE_COMMAND_PALETTE = False

    def compose(self) -> ComposeResult:
        yield from ()


class _LargeFakeArtifactGraph:
    """Deterministic large graph fixture that avoids Rust and user state."""

    def __init__(self, *, linked_count: int) -> None:
        self.show_calls: list[str] = []
        self.show_paged_calls: list[tuple[str, ArtifactPageRequestWire]] = []
        self.graph_calls: list[ArtifactGraphOptionsWire] = []
        self.export_calls: list[tuple[ArtifactGraphOptionsWire, str]] = []
        self.details = self._build_details(linked_count)

    def show(self, index_path: str | Any, artifact_id: str) -> ArtifactDetailWire:
        del index_path
        self.show_calls.append(artifact_id)
        return self.details[artifact_id]

    def show_paged(
        self,
        index_path: str | Any,
        artifact_id: str,
        request: ArtifactPageRequestWire | None = None,
    ) -> ArtifactDetailPagedWire:
        del index_path
        request = request or ArtifactPageRequestWire()
        self.show_paged_calls.append((artifact_id, request))
        detail = self.details.get(artifact_id)
        if detail is None:
            return _missing_paged_detail()
        return _paged_detail_from_detail(detail, request)

    def graph(
        self,
        index_path: str | Any,
        options: ArtifactGraphOptionsWire,
    ) -> ArtifactGraphWire:
        del index_path
        self.graph_calls.append(options)
        root_id = options.root_id or "/"
        detail = self.details[root_id]
        nodes = [detail.node, *detail.children]
        limit = options.limit or len(nodes)
        return ArtifactGraphWire(
            schema_version=ARTIFACT_WIRE_SCHEMA_VERSION,
            root_id=root_id,
            nodes=[node for node in nodes if node is not None][:limit],
            node_count=len(nodes),
            link_count=len(detail.outbound_links) + len(detail.inbound_links),
            truncated=len(nodes) > limit,
            limit=limit,
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


def _node(
    artifact_id: str,
    kind: str = "file",
    title: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> ArtifactNodeWire:
    return ArtifactNodeWire(
        id=artifact_id,
        kind=kind,
        display_title=title or artifact_id,
        provenance="derived",
        metadata=metadata or {},
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


def _missing_paged_detail() -> ArtifactDetailPagedWire:
    return ArtifactDetailPagedWire(
        schema_version=ARTIFACT_WIRE_SCHEMA_VERSION,
        node=None,
    )


def _relation_page(
    *,
    group_key: str,
    direction: str,
    total_count: int,
    nodes: list[ArtifactNodeWire] | None = None,
    links: list[ArtifactLinkWire] | None = None,
    link_type: str | None = None,
) -> ArtifactRelationPageWire:
    loaded_nodes = nodes or []
    loaded_links = links or []
    return ArtifactRelationPageWire(
        summary=ArtifactGroupSummaryWire(
            group_key=group_key,
            direction=direction,
            link_type=link_type,
            total_count=total_count,
            loaded_count=(
                len(loaded_nodes) if direction == "children" else len(loaded_links)
            ),
        ),
        nodes=loaded_nodes,
        links=loaded_links,
    )


def _slice_page[T](items: list[T], request: ArtifactPageRequestWire) -> list[T]:
    offset = request.offset
    limit = request.limit
    return items[offset : offset + limit]


def _paged_detail_from_detail(
    detail: ArtifactDetailWire,
    request: ArtifactPageRequestWire,
) -> ArtifactDetailPagedWire:
    relation = request.relation
    link_type = request.link_type
    children_page = None
    outbound_pages: list[ArtifactRelationPageWire] = []
    inbound_pages: list[ArtifactRelationPageWire] = []

    if relation in (None, "children"):
        children_page = _relation_page(
            group_key="children",
            direction="children",
            total_count=len(detail.children),
            nodes=_slice_page(detail.children, request),
        )

    if relation in (None, "outbound"):
        for current_link_type, links in _group_links(detail.outbound_links).items():
            if link_type is not None and current_link_type != link_type:
                continue
            outbound_pages.append(
                _relation_page(
                    group_key=f"outbound:{current_link_type}",
                    direction="outbound",
                    link_type=current_link_type,
                    total_count=len(links),
                    links=_slice_page(links, request),
                )
            )

    if relation in (None, "inbound"):
        for current_link_type, links in _group_links(detail.inbound_links).items():
            if link_type is not None and current_link_type != link_type:
                continue
            inbound_pages.append(
                _relation_page(
                    group_key=f"inbound:{current_link_type}",
                    direction="inbound",
                    link_type=current_link_type,
                    total_count=len(links),
                    links=_slice_page(links, request),
                )
            )

    return ArtifactDetailPagedWire(
        schema_version=ARTIFACT_WIRE_SCHEMA_VERSION,
        node=detail.node,
        payloads=detail.payloads,
        path_to_root=detail.path_to_root,
        diagnostics=detail.diagnostics,
        children_page=children_page,
        outbound_pages=outbound_pages,
        inbound_pages=inbound_pages,
    )


def _group_links(links: list[ArtifactLinkWire]) -> dict[str, list[ArtifactLinkWire]]:
    grouped: dict[str, list[ArtifactLinkWire]] = {}
    for link in links:
        grouped.setdefault(link.link_type, []).append(link)
    return dict(sorted(grouped.items()))


async def measure_modal_open(
    *,
    start_id: str,
    linked_count: int,
) -> dict[str, Any]:
    fixture = {"linked_rows": linked_count}
    graph = _LargeFakeArtifactGraph(linked_count=linked_count)
    modal = ArtifactPanelModal(artifact_id=start_id, show_paged_func=graph.show_paged)
    app = _ModalBenchApp()

    start = time.perf_counter()
    async with app.run_test() as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()
        await pilot.pause()
        option_count = modal.query_one("#artifact-panel-list", OptionList).option_count
    elapsed_ms = (time.perf_counter() - start) * 1000.0

    query_counts = Counter(artifact_id for artifact_id, _ in graph.show_paged_calls)
    errors: list[str] = []
    if query_counts != Counter({start_id: 1}):
        errors.append(f"unexpected paged show calls: {dict(query_counts)}")
    if graph.show_calls:
        errors.append(f"unexpected legacy show calls: {len(graph.show_calls)}")
    if graph.graph_calls:
        errors.append(f"unexpected graph calls: {len(graph.graph_calls)}")
    if graph.export_calls:
        errors.append(f"unexpected export calls: {len(graph.export_calls)}")
    if option_count > 40:
        errors.append(f"initial modal open loaded too many rows: {option_count}")

    return query_record(
        f"modal_open:paged:{start_id}",
        elapsed_ms,
        fixture=fixture,
        bounded=True,
        query_count=len(graph.show_paged_calls),
        result_count=option_count,
        errors=errors,
        query_counts={
            "artifact_show_paged": len(graph.show_paged_calls),
            "artifact_show": len(graph.show_calls),
            "artifact_graph": len(graph.graph_calls),
            "artifact_export": len(graph.export_calls),
        },
    )


async def measure_modal_open_missing_artifact(*, linked_count: int) -> dict[str, Any]:
    fixture = {"linked_rows": linked_count, "targeted_refreshes": 1}
    graph = _LargeFakeArtifactGraph(linked_count=linked_count)
    start_id = "changespec:current"
    refresh_calls: list[str] = []

    def fake_show_paged(
        index_path: str | Any,
        artifact_id: str,
        request: ArtifactPageRequestWire | None = None,
    ) -> ArtifactDetailPagedWire:
        if not graph.show_paged_calls:
            request = request or ArtifactPageRequestWire()
            graph.show_paged_calls.append((artifact_id, request))
            return _missing_paged_detail()
        return graph.show_paged(index_path, artifact_id, request)

    def fake_refresh(
        index_path: str | Any,
        artifact_id: str,
        context_path: str | Any | None,
        artifact_dir: str | Any | None,
    ) -> None:
        del index_path, context_path, artifact_dir
        refresh_calls.append(artifact_id)

    modal = ArtifactPanelModal(
        artifact_id=start_id,
        index_path="/tmp/sase-artifact-perf.sqlite",
        show_paged_func=fake_show_paged,
        refresh_missing_func=fake_refresh,
        context_path="/tmp/sase-artifact-perf.gp",
    )
    app = _ModalBenchApp()

    start = time.perf_counter()
    async with app.run_test() as pilot:
        pilot.app.push_screen(modal)
        for _ in range(4):
            await pilot.pause()
        option_count = modal.query_one("#artifact-panel-list", OptionList).option_count
    elapsed_ms = (time.perf_counter() - start) * 1000.0

    errors: list[str] = []
    if [artifact_id for artifact_id, _ in graph.show_paged_calls] != [
        start_id,
        start_id,
    ]:
        errors.append(f"unexpected paged retry calls: {graph.show_paged_calls!r}")
    if refresh_calls != [start_id]:
        errors.append(f"unexpected targeted refresh calls: {refresh_calls!r}")
    if graph.show_calls:
        errors.append(f"unexpected legacy show calls: {len(graph.show_calls)}")
    if option_count > 40:
        errors.append(f"missing-artifact retry loaded too many rows: {option_count}")

    return query_record(
        f"modal_open:missing_artifact_targeted_refresh:{start_id}",
        elapsed_ms,
        fixture=fixture,
        bounded=True,
        query_count=len(graph.show_paged_calls),
        result_count=option_count,
        errors=errors,
        query_counts={
            "artifact_show_paged": len(graph.show_paged_calls),
            "artifact_show": len(graph.show_calls),
        },
        mutation_counts={
            "calls": len(refresh_calls),
            "targeted_refreshes": len(refresh_calls),
        },
    )


async def measure_modal_open_legacy_compat(
    *,
    start_id: str,
    linked_count: int,
) -> dict[str, Any]:
    fixture = {"linked_rows": linked_count}
    graph = _LargeFakeArtifactGraph(linked_count=linked_count)
    modal = ArtifactPanelModal(artifact_id=start_id, show_func=graph.show)
    app = _ModalBenchApp()

    start = time.perf_counter()
    async with app.run_test() as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()
        await pilot.pause()
        option_count = modal.query_one("#artifact-panel-list", OptionList).option_count
    elapsed_ms = (time.perf_counter() - start) * 1000.0

    errors: list[str] = []
    if Counter(graph.show_calls) != Counter({start_id: 1}):
        errors.append(f"unexpected legacy show calls: {graph.show_calls!r}")
    if graph.show_paged_calls:
        errors.append(f"unexpected paged show calls: {graph.show_paged_calls!r}")

    return query_record(
        f"modal_open_legacy_compat:{start_id}",
        elapsed_ms,
        fixture=fixture,
        bounded=False,
        query_count=len(graph.show_calls),
        result_count=option_count,
        errors=errors,
        query_counts={
            "artifact_show": len(graph.show_calls),
            "artifact_show_paged": len(graph.show_paged_calls),
        },
    )


async def run_modal_measurements(*, linked_count: int) -> list[dict[str, Any]]:
    records = [
        await measure_modal_open(start_id=start_id, linked_count=linked_count)
        for start_id in ("/", "changespec:current", "agent:current")
    ]
    records.append(await measure_modal_open_missing_artifact(linked_count=linked_count))
    records.append(
        await measure_modal_open_legacy_compat(
            start_id="/",
            linked_count=linked_count,
        )
    )
    return records
