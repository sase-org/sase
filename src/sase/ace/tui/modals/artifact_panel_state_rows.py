"""Row building helpers for the artifact panel modal."""

from __future__ import annotations

from collections import defaultdict

from sase.core.artifact_wire.constants import ARTIFACT_FILE_TYPE_METADATA_KEY
from sase.core.artifact_wire import (
    ArtifactDetailWire,
    ArtifactLinkWire,
    ArtifactNodeWire,
)

from .artifact_panel_state_models import (
    ARTIFACT_PANEL_GLOBAL_SEARCH_LIMIT,
    ARTIFACT_PANEL_GROUP_PAGE_SIZE,
    ARTIFACT_PANEL_SHOW_MORE_ACTION,
    ArtifactPanelPagedModel,
    ArtifactPanelRow,
    ArtifactPanelRows,
)


def build_artifact_panel_rows(
    detail: ArtifactDetailWire,
    *,
    paged_model: ArtifactPanelPagedModel | None = None,
    filter_text: str = "",
) -> ArtifactPanelRows:
    """Build grouped, locally filtered modal rows from one detail record."""
    rows: list[ArtifactPanelRow] = []
    selectable_count = 0
    normalized_filter = filter_text.casefold().strip()

    def add_group(
        label: str,
        candidates: list[ArtifactPanelRow],
        *,
        group_key: str,
    ) -> None:
        nonlocal selectable_count
        visible = [
            row
            for row in candidates
            if not normalized_filter or normalized_filter in _row_search_text(row)
        ]
        if not visible:
            return
        loaded_count = len(visible) if normalized_filter else len(candidates)
        total_count = (
            len(candidates)
            if normalized_filter
            else _group_total_count(
                paged_model,
                group_key=group_key,
                fallback=loaded_count,
            )
        )
        group_label = _group_label(
            label, loaded_count=loaded_count, total_count=total_count
        )
        rows.append(
            ArtifactPanelRow(
                id=f"group:{group_key}",
                label=group_label,
                row_type="group",
                group=label,
                group_key=group_key,
                selectable=False,
            )
        )
        for row in visible:
            selectable_count += 1
            rows.append(row)
        if not normalized_filter and _group_has_more(
            paged_model,
            group_key=group_key,
            loaded_count=len(candidates),
        ):
            rows.append(
                _show_more_row(
                    label,
                    group_key=group_key,
                    paged_model=paged_model,
                )
            )
            selectable_count += 1

    path_rows = [
        _node_row(
            "path",
            node,
            group="Path to root",
            group_key="path",
            edge_direction="path",
        )
        for node in detail.path_to_root
    ]
    add_group("Path to root", path_rows, group_key="path")

    child_rows = [
        _node_row(
            "child",
            node,
            group="Children",
            group_key="children",
            edge_direction="children",
        )
        for node in detail.children
    ]
    add_group("Children", child_rows, group_key="children")

    for link_type, links in _group_links(detail.outbound_links).items():
        group_key = f"outbound:{link_type}"
        link_rows = [
            _link_row(
                "outbound",
                link,
                group=f"Outbound: {link_type}",
                group_key=group_key,
            )
            for link in links
        ]
        add_group(f"Outbound: {link_type}", link_rows, group_key=group_key)

    for link_type, links in _group_links(detail.inbound_links).items():
        group_key = f"inbound:{link_type}"
        link_rows = [
            _link_row(
                "inbound",
                link,
                group=f"Inbound: {link_type}",
                group_key=group_key,
            )
            for link in links
        ]
        add_group(f"Inbound: {link_type}", link_rows, group_key=group_key)

    return ArtifactPanelRows(
        rows=rows,
        total_selectable=selectable_count,
        truncated=False,
    )


def build_artifact_search_rows(
    nodes: list[ArtifactNodeWire],
    *,
    query: str,
    limit: int = ARTIFACT_PANEL_GLOBAL_SEARCH_LIMIT,
) -> ArtifactPanelRows:
    """Build modal-global search result rows."""
    rows: list[ArtifactPanelRow] = [
        ArtifactPanelRow(
            id="group:search-results",
            label=f"Search results for {query!r} ({len(nodes)})",
            row_type="group",
            group="Search results",
            group_key="search",
            selectable=False,
        )
    ]
    for node in nodes:
        rows.append(
            _node_row(
                "search",
                node,
                group="Search results",
                group_key="search",
                edge_direction="search",
            )
        )
    return ArtifactPanelRows(
        rows=rows,
        total_selectable=len(nodes),
        truncated=len(nodes) >= limit,
    )


def _node_row(
    prefix: str,
    node: ArtifactNodeWire,
    *,
    group: str,
    group_key: str,
    edge_direction: str,
) -> ArtifactPanelRow:
    file_type = _file_type_from_node(node)
    title = node.display_title or node.id
    subtitle = _compact_subtitle(node.subtitle, _status_from_metadata(node.metadata))
    return ArtifactPanelRow(
        id=f"{prefix}:{node.id}",
        label=f"{node.kind} {title}  {node.id}",
        artifact_id=node.id,
        artifact_kind=node.kind,
        file_type=file_type,
        edge_direction=edge_direction,
        title=title,
        subtitle=subtitle,
        updated_label=_compact_timestamp(node.updated_at),
        group_key=group_key,
        row_type=prefix,
        group=group,
        status_label=_status_from_metadata(node.metadata),
    )


def _link_row(
    direction: str, link: ArtifactLinkWire, *, group: str, group_key: str
) -> ArtifactPanelRow:
    artifact_id = link.target_id if direction == "outbound" else link.source_id
    direction_label = "to" if direction == "outbound" else "from"
    other_id = link.target_id if direction == "outbound" else link.source_id
    metadata_prefix = "target" if direction == "outbound" else "source"
    title = _metadata_str(link.metadata, f"{metadata_prefix}_title") or other_id
    subtitle = _compact_subtitle(
        f"{link.link_type} {direction_label}",
        _status_from_metadata(link.metadata),
    )
    return ArtifactPanelRow(
        id=f"{direction}:{link.id}",
        label=f"{link.link_type} {direction_label} {other_id}",
        artifact_id=artifact_id,
        artifact_kind=(
            _metadata_str(link.metadata, f"{metadata_prefix}_kind")
            or _artifact_kind_from_id(artifact_id)
        ),
        file_type=_metadata_str(link.metadata, f"{metadata_prefix}_file_type"),
        edge_direction=direction,
        row_type=direction,
        group=group,
        group_key=group_key,
        link_type=link.link_type,
        title=title,
        subtitle=subtitle,
        updated_label=_compact_timestamp(link.updated_at),
        status_label=_status_from_metadata(link.metadata),
    )


def _group_links(links: list[ArtifactLinkWire]) -> dict[str, list[ArtifactLinkWire]]:
    grouped: dict[str, list[ArtifactLinkWire]] = defaultdict(list)
    for link in links:
        grouped[link.link_type].append(link)
    return dict(sorted(grouped.items()))


def _row_search_text(row: ArtifactPanelRow) -> str:
    return " ".join(
        part
        for part in (
            row.label,
            row.artifact_id,
            row.artifact_kind,
            row.file_type,
            row.edge_direction,
            row.title,
            row.subtitle,
            row.updated_label,
            row.row_type,
            row.group,
            row.group_key,
            row.link_type,
            row.status_label,
        )
        if part
    ).casefold()


def _group_total_count(
    paged_model: ArtifactPanelPagedModel | None,
    *,
    group_key: str,
    fallback: int,
) -> int:
    if paged_model is None:
        return fallback
    for key, total in paged_model.group_totals.items():
        if key.group_key == group_key:
            return total
    return fallback


def _group_loaded_count(
    paged_model: ArtifactPanelPagedModel | None,
    *,
    group_key: str,
    fallback: int,
) -> int:
    if paged_model is None:
        return fallback
    for key, offset in paged_model.group_offsets.items():
        if key.group_key == group_key:
            return offset
    return fallback


def _group_has_more(
    paged_model: ArtifactPanelPagedModel | None,
    *,
    group_key: str,
    loaded_count: int,
) -> bool:
    loaded = _group_loaded_count(
        paged_model,
        group_key=group_key,
        fallback=loaded_count,
    )
    total = _group_total_count(
        paged_model,
        group_key=group_key,
        fallback=loaded_count,
    )
    return loaded < total


def _show_more_row(
    label: str,
    *,
    group_key: str,
    paged_model: ArtifactPanelPagedModel | None,
) -> ArtifactPanelRow:
    loaded = _group_loaded_count(paged_model, group_key=group_key, fallback=0)
    total = _group_total_count(paged_model, group_key=group_key, fallback=loaded)
    remaining = max(total - loaded, 0)
    next_count = min(ARTIFACT_PANEL_GROUP_PAGE_SIZE, remaining)
    return ArtifactPanelRow(
        id=f"show-more:{group_key}",
        label=f"Show {next_count} more {label.lower()} ({loaded}/{total})",
        group_key=group_key,
        page_action=ARTIFACT_PANEL_SHOW_MORE_ACTION,
        row_type="show_more",
        group=label,
        selectable=True,
    )


def _group_label(label: str, *, loaded_count: int, total_count: int) -> str:
    if total_count > loaded_count:
        return f"{label} ({loaded_count}/{total_count})"
    return f"{label} ({loaded_count})"


def _file_type_from_node(node: ArtifactNodeWire) -> str | None:
    value = node.metadata.get(ARTIFACT_FILE_TYPE_METADATA_KEY)
    return str(value) if value else None


def _metadata_str(metadata: dict[str, object], key: str) -> str | None:
    value = metadata.get(key)
    return str(value) if value else None


def _status_from_metadata(metadata: dict[str, object]) -> str:
    for key in ("status", "state"):
        value = metadata.get(key)
        if value:
            return str(value)
    return ""


def _compact_subtitle(*parts: str | None) -> str:
    return " · ".join(part for part in parts if part)


def _compact_timestamp(value: str | None) -> str:
    if not value:
        return ""
    if "T" in value:
        return value.split("T", 1)[0]
    return value[:10]


def _artifact_kind_from_id(artifact_id: str) -> str | None:
    if artifact_id == "/":
        return "root"
    prefix = artifact_id.split(":", 1)[0]
    return {
        "agent": "agent",
        "bead": "bead",
        "changespec": "changespec",
        "cl": "changespec",
        "commit": "commit",
        "dir": "directory",
        "directory": "directory",
        "file": "file",
        "project": "project",
        "prompt": "file",
        "thought": "thought",
    }.get(prefix)
