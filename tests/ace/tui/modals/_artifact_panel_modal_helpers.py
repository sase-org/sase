"""Shared fixtures for artifact panel modal tests."""

from __future__ import annotations

import io
from typing import Any

from rich.console import Console, RenderableType
from textual.app import App, ComposeResult

from sase.core.artifact_wire import (
    ARTIFACT_WIRE_SCHEMA_VERSION,
    ArtifactDetailPagedWire,
    ArtifactDetailWire,
    ArtifactGraphOptionsWire,
    ArtifactGraphWire,
    ArtifactGroupSummaryWire,
    ArtifactLinkWire,
    ArtifactNodeWire,
    ArtifactRelationPageWire,
    ArtifactTypeCountWire,
)


class _ModalTestApp(App[None]):
    ENABLE_COMMAND_PALETTE = False

    def compose(self) -> ComposeResult:
        yield from ()


def _render_text(renderable: RenderableType) -> str:
    console = Console(
        file=io.StringIO(),
        record=True,
        width=140,
        color_system=None,
    )
    console.print(renderable)
    return console.export_text()


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
