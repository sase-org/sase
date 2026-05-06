"""Paged artifact detail state helpers for the artifact panel modal."""

from __future__ import annotations

from collections import defaultdict

from sase.core.artifact_wire import (
    ArtifactDetailPagedWire,
    ArtifactDetailWire,
    ArtifactGroupSummaryWire,
    ArtifactLinkWire,
    ArtifactNodeWire,
    ArtifactRelationPageWire,
)

from .artifact_panel_state_models import (
    ARTIFACT_PANEL_GROUP_PAGE_SIZE,
    ArtifactPanelPagedModel,
    ArtifactPanelRelationPageKey,
)


def paged_model_from_paged_detail(
    paged_detail: ArtifactDetailPagedWire,
) -> ArtifactPanelPagedModel:
    """Build modal-local paged state from the backend paged detail contract."""
    relation_pages: dict[ArtifactPanelRelationPageKey, ArtifactRelationPageWire] = {}
    group_offsets: dict[ArtifactPanelRelationPageKey, int] = {}
    group_totals: dict[ArtifactPanelRelationPageKey, int] = {}

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


def parent_id_from_detail(detail: ArtifactDetailWire, current_id: str) -> str | None:
    """Return the nearest breadcrumb parent for *current_id*."""
    candidates = [node.id for node in detail.path_to_root if node.id != current_id]
    if not candidates:
        return None
    return candidates[-1]


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


def _group_links(links: list[ArtifactLinkWire]) -> dict[str, list[ArtifactLinkWire]]:
    grouped: dict[str, list[ArtifactLinkWire]] = defaultdict(list)
    for link in links:
        grouped[link.link_type].append(link)
    return dict(sorted(grouped.items()))


def _relation_page_key(
    summary: ArtifactGroupSummaryWire,
) -> ArtifactPanelRelationPageKey:
    return ArtifactPanelRelationPageKey(
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
    relation_pages: dict[ArtifactPanelRelationPageKey, ArtifactRelationPageWire],
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
