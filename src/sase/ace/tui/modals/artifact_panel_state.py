"""Navigation state and row modeling for the artifact panel modal."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from sase.core.artifact_wire.constants import ARTIFACT_FILE_TYPE_METADATA_KEY
from sase.core.artifact_wire import (
    ArtifactDetailPagedWire,
    ArtifactDetailWire,
    ArtifactGroupSummaryWire,
    ArtifactLinkWire,
    ArtifactNodeWire,
    ArtifactRelationPageWire,
)


ARTIFACT_PANEL_GROUP_PAGE_SIZE = 10
ARTIFACT_PANEL_SHOW_MORE_ACTION = "show_more"


@dataclass(frozen=True)
class ArtifactPanelRow:
    """One row rendered in the artifact panel navigation list."""

    id: str
    label: str
    artifact_id: str | None = None
    artifact_kind: str | None = None
    file_type: str | None = None
    edge_direction: str | None = None
    link_type: str | None = None
    title: str = ""
    subtitle: str = ""
    updated_label: str = ""
    group_key: str | None = None
    page_action: str | None = None
    row_type: str = "artifact"
    group: str | None = None
    status_label: str = ""
    selectable: bool = True


@dataclass
class _ArtifactPanelRows:
    rows: list[ArtifactPanelRow]
    total_selectable: int
    truncated: bool = False


@dataclass(frozen=True)
class _ArtifactPanelRelationPageKey:
    """Stable key for one loaded relationship page in the modal."""

    group_key: str
    relation: str
    link_type: str | None = None


@dataclass
class ArtifactPanelPagedModel:
    """Paged artifact detail plus a legacy projection for current renderers."""

    paged_detail: ArtifactDetailPagedWire
    detail: ArtifactDetailWire
    relation_pages: dict[_ArtifactPanelRelationPageKey, ArtifactRelationPageWire] = (
        field(default_factory=dict)
    )
    group_offsets: dict[_ArtifactPanelRelationPageKey, int] = field(
        default_factory=dict
    )
    group_totals: dict[_ArtifactPanelRelationPageKey, int] = field(default_factory=dict)


@dataclass
class ArtifactPanelNavigationState:
    current_id: str
    back_stack: list[str] = field(default_factory=list)
    forward_stack: list[str] = field(default_factory=list)
    selected_row_id: str | None = None
    filter_text: str = ""
    detail: ArtifactDetailWire | None = None
    paged_model: ArtifactPanelPagedModel | None = None

    def navigate_to(self, artifact_id: str) -> bool:
        """Move to *artifact_id*, returning whether a fresh load is needed."""
        if artifact_id == self.current_id:
            return False
        self.back_stack.append(self.current_id)
        self.current_id = artifact_id
        self.forward_stack.clear()
        self.selected_row_id = None
        self.detail = None
        self.paged_model = None
        return True

    def back(self) -> str | None:
        if not self.back_stack:
            return None
        previous = self.back_stack.pop()
        self.forward_stack.append(self.current_id)
        self.current_id = previous
        self.selected_row_id = None
        self.detail = None
        self.paged_model = None
        return previous

    def forward(self) -> str | None:
        if not self.forward_stack:
            return None
        next_id = self.forward_stack.pop()
        self.back_stack.append(self.current_id)
        self.current_id = next_id
        self.selected_row_id = None
        self.detail = None
        self.paged_model = None
        return next_id

    def set_filter(self, filter_text: str) -> None:
        self.filter_text = filter_text.strip()
        self.selected_row_id = None

    def set_detail(self, detail: ArtifactDetailWire) -> None:
        self.detail = detail

    def set_paged_model(self, model: ArtifactPanelPagedModel) -> None:
        self.paged_model = model
        self.detail = model.detail


def paged_model_from_paged_detail(
    paged_detail: ArtifactDetailPagedWire,
) -> ArtifactPanelPagedModel:
    """Build modal-local paged state from the backend paged detail contract."""
    relation_pages: dict[_ArtifactPanelRelationPageKey, ArtifactRelationPageWire] = {}
    group_offsets: dict[_ArtifactPanelRelationPageKey, int] = {}
    group_totals: dict[_ArtifactPanelRelationPageKey, int] = {}

    def add_page(page: ArtifactRelationPageWire | None) -> None:
        if page is None:
            return
        key = _relation_page_key(page.summary)
        relation_pages[key] = page
        group_offsets[key] = page.summary.loaded_count
        group_totals[key] = page.summary.total_count

    add_page(paged_detail.children_page)
    for page in paged_detail.outbound_pages:
        add_page(page)
    for page in paged_detail.inbound_pages:
        add_page(page)

    return ArtifactPanelPagedModel(
        paged_detail=paged_detail,
        detail=_legacy_detail_from_paged_detail(paged_detail),
        relation_pages=relation_pages,
        group_offsets=group_offsets,
        group_totals=group_totals,
    )


def merge_relation_page_into_model(
    model: ArtifactPanelPagedModel,
    page_detail: ArtifactDetailPagedWire,
) -> ArtifactPanelPagedModel:
    """Return *model* with the requested relationship page merged in."""
    pages = _relation_pages_from_detail(page_detail)
    requested_pages = [page for page in pages if page.summary.loaded_count > 0]
    if not requested_pages:
        return model

    relation_pages = dict(model.relation_pages)
    group_offsets = dict(model.group_offsets)
    group_totals = dict(model.group_totals)

    for page in requested_pages:
        key = _relation_page_key(page.summary)
        existing = relation_pages.get(key)
        if existing is None:
            merged_page = page
        elif page.summary.direction == "children":
            merged_nodes = _dedupe_nodes([*existing.nodes, *page.nodes])
            merged_page = _replace_page(page, nodes=merged_nodes)
        else:
            merged_links = _dedupe_links([*existing.links, *page.links])
            merged_page = _replace_page(page, links=merged_links)
        relation_pages[key] = merged_page
        group_offsets[key] = _page_loaded_count(merged_page)
        group_totals[key] = page.summary.total_count

    paged_detail = _paged_detail_from_relation_pages(
        model.paged_detail,
        relation_pages,
    )
    return ArtifactPanelPagedModel(
        paged_detail=paged_detail,
        detail=_legacy_detail_from_paged_detail(paged_detail),
        relation_pages=relation_pages,
        group_offsets=group_offsets,
        group_totals=group_totals,
    )


def page_request_for_group(
    model: ArtifactPanelPagedModel,
    *,
    group_key: str,
    limit: int = ARTIFACT_PANEL_GROUP_PAGE_SIZE,
) -> tuple[str, str | None, int, int] | None:
    """Return relation/link_type/offset/limit for the next page in *group_key*."""
    for key, offset in model.group_offsets.items():
        if key.group_key == group_key:
            return key.relation, key.link_type, offset, limit
    return None


def paged_model_from_legacy_detail(
    detail: ArtifactDetailWire,
) -> ArtifactPanelPagedModel:
    """Adapt legacy injected detail into the paged modal model temporarily."""
    children_page = _legacy_relation_page(
        group_key="children",
        direction="children",
        nodes=detail.children,
    )
    outbound_pages = [
        _legacy_relation_page(
            group_key=f"outbound:{link_type}",
            direction="outbound",
            link_type=link_type,
            links=links,
        )
        for link_type, links in _group_links(detail.outbound_links).items()
    ]
    inbound_pages = [
        _legacy_relation_page(
            group_key=f"inbound:{link_type}",
            direction="inbound",
            link_type=link_type,
            links=links,
        )
        for link_type, links in _group_links(detail.inbound_links).items()
    ]
    return paged_model_from_paged_detail(
        ArtifactDetailPagedWire(
            schema_version=detail.schema_version,
            node=detail.node,
            payloads=detail.payloads,
            path_to_root=detail.path_to_root,
            diagnostics=detail.diagnostics,
            children_page=children_page,
            outbound_pages=outbound_pages,
            inbound_pages=inbound_pages,
        )
    )


def _legacy_detail_from_paged_detail(
    paged_detail: ArtifactDetailPagedWire,
) -> ArtifactDetailWire:
    """Project paged detail into the legacy shape used by detail renderers."""
    children = (
        list(paged_detail.children_page.nodes)
        if paged_detail.children_page is not None
        else []
    )
    outbound_links: list[ArtifactLinkWire] = []
    for page in paged_detail.outbound_pages:
        outbound_links.extend(page.links)
    inbound_links: list[ArtifactLinkWire] = []
    for page in paged_detail.inbound_pages:
        inbound_links.extend(page.links)
    return ArtifactDetailWire(
        schema_version=paged_detail.schema_version,
        node=paged_detail.node,
        payloads=list(paged_detail.payloads),
        outbound_links=outbound_links,
        inbound_links=inbound_links,
        children=children,
        path_to_root=list(paged_detail.path_to_root),
        diagnostics=list(paged_detail.diagnostics),
    )


def build_artifact_panel_rows(
    detail: ArtifactDetailWire,
    *,
    paged_model: ArtifactPanelPagedModel | None = None,
    filter_text: str = "",
) -> _ArtifactPanelRows:
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

    return _ArtifactPanelRows(
        rows=rows,
        total_selectable=selectable_count,
        truncated=False,
    )


def parent_id_from_detail(detail: ArtifactDetailWire, current_id: str) -> str | None:
    """Return the nearest breadcrumb parent for *current_id*."""
    candidates = [node.id for node in detail.path_to_root if node.id != current_id]
    if not candidates:
        return None
    return candidates[-1]


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


def _relation_page_key(
    summary: ArtifactGroupSummaryWire,
) -> _ArtifactPanelRelationPageKey:
    return _ArtifactPanelRelationPageKey(
        group_key=summary.group_key,
        relation=summary.direction,
        link_type=summary.link_type,
    )


def _relation_pages_from_detail(
    paged_detail: ArtifactDetailPagedWire,
) -> list[ArtifactRelationPageWire]:
    pages: list[ArtifactRelationPageWire] = []
    if paged_detail.children_page is not None:
        pages.append(paged_detail.children_page)
    pages.extend(paged_detail.outbound_pages)
    pages.extend(paged_detail.inbound_pages)
    return pages


def _paged_detail_from_relation_pages(
    base: ArtifactDetailPagedWire,
    relation_pages: dict[_ArtifactPanelRelationPageKey, ArtifactRelationPageWire],
) -> ArtifactDetailPagedWire:
    children_page = None
    outbound_pages: list[ArtifactRelationPageWire] = []
    inbound_pages: list[ArtifactRelationPageWire] = []
    for key, page in relation_pages.items():
        if key.relation == "children":
            children_page = page
        elif key.relation == "outbound":
            outbound_pages.append(page)
        elif key.relation == "inbound":
            inbound_pages.append(page)
    outbound_pages.sort(key=lambda page: page.summary.link_type or "")
    inbound_pages.sort(key=lambda page: page.summary.link_type or "")
    return ArtifactDetailPagedWire(
        schema_version=base.schema_version,
        node=base.node,
        payloads=list(base.payloads),
        path_to_root=list(base.path_to_root),
        diagnostics=list(base.diagnostics),
        children_page=children_page,
        outbound_pages=outbound_pages,
        inbound_pages=inbound_pages,
        type_counts=list(base.type_counts),
    )


def _replace_page(
    page: ArtifactRelationPageWire,
    *,
    nodes: list[ArtifactNodeWire] | None = None,
    links: list[ArtifactLinkWire] | None = None,
) -> ArtifactRelationPageWire:
    loaded_count = len(nodes) if nodes is not None else len(links or [])
    return ArtifactRelationPageWire(
        summary=ArtifactGroupSummaryWire(
            group_key=page.summary.group_key,
            direction=page.summary.direction,
            link_type=page.summary.link_type,
            total_count=page.summary.total_count,
            loaded_count=loaded_count,
        ),
        nodes=list(nodes or []),
        links=list(links or []),
    )


def _page_loaded_count(page: ArtifactRelationPageWire) -> int:
    return len(page.nodes) if page.summary.direction == "children" else len(page.links)


def _dedupe_nodes(nodes: list[ArtifactNodeWire]) -> list[ArtifactNodeWire]:
    seen: set[str] = set()
    deduped: list[ArtifactNodeWire] = []
    for node in nodes:
        if node.id in seen:
            continue
        seen.add(node.id)
        deduped.append(node)
    return deduped


def _dedupe_links(links: list[ArtifactLinkWire]) -> list[ArtifactLinkWire]:
    seen: set[str] = set()
    deduped: list[ArtifactLinkWire] = []
    for link in links:
        if link.id in seen:
            continue
        seen.add(link.id)
        deduped.append(link)
    return deduped


def _legacy_relation_page(
    *,
    group_key: str,
    direction: str,
    link_type: str | None = None,
    nodes: list[ArtifactNodeWire] | None = None,
    links: list[ArtifactLinkWire] | None = None,
) -> ArtifactRelationPageWire:
    loaded_nodes = list(nodes or [])
    loaded_links = list(links or [])
    loaded_count = len(loaded_nodes) if loaded_nodes else len(loaded_links)
    return ArtifactRelationPageWire(
        summary=ArtifactGroupSummaryWire(
            group_key=group_key,
            direction=direction,
            link_type=link_type,
            total_count=loaded_count,
            loaded_count=loaded_count,
        ),
        nodes=loaded_nodes,
        links=loaded_links,
    )


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
