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
    ArtifactDetailWire,
    ArtifactGraphOptionsWire,
    ArtifactGraphWire,
    ArtifactLinkWire,
    ArtifactNodeWire,
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
        self.graph_calls: list[ArtifactGraphOptionsWire] = []
        self.export_calls: list[tuple[ArtifactGraphOptionsWire, str]] = []
        self.details = self._build_details(linked_count)

    def show(self, index_path: str | Any, artifact_id: str) -> ArtifactDetailWire:
        del index_path
        self.show_calls.append(artifact_id)
        return self.details[artifact_id]

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


async def measure_modal_open(
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

    query_counts = Counter(graph.show_calls)
    errors: list[str] = []
    if query_counts != Counter({start_id: 1}):
        errors.append(f"unexpected show calls: {dict(query_counts)}")
    if graph.graph_calls:
        errors.append(f"unexpected graph calls: {len(graph.graph_calls)}")
    if graph.export_calls:
        errors.append(f"unexpected export calls: {len(graph.export_calls)}")

    return query_record(
        f"modal_open:{start_id}",
        elapsed_ms,
        fixture=fixture,
        bounded=True,
        query_count=len(graph.show_calls),
        result_count=option_count,
        errors=errors,
    )


async def run_modal_measurements(*, linked_count: int) -> list[dict[str, Any]]:
    return [
        await measure_modal_open(start_id=start_id, linked_count=linked_count)
        for start_id in ("/", "changespec:current", "agent:current")
    ]
