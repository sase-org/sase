"""Navigation state and row modeling for the artifact panel modal."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from sase.core.artifact_wire import (
    ArtifactDetailWire,
    ArtifactLinkWire,
    ArtifactNodeWire,
)


ARTIFACT_PANEL_ROW_LIMIT = 100


@dataclass(frozen=True)
class ArtifactPanelRow:
    """One row rendered in the artifact panel navigation list."""

    id: str
    label: str
    artifact_id: str | None = None
    row_type: str = "artifact"
    group: str | None = None
    link_type: str | None = None
    selectable: bool = True


@dataclass
class _ArtifactPanelRows:
    rows: list[ArtifactPanelRow]
    total_selectable: int
    truncated: bool = False


@dataclass
class ArtifactPanelNavigationState:
    current_id: str
    back_stack: list[str] = field(default_factory=list)
    forward_stack: list[str] = field(default_factory=list)
    selected_row_id: str | None = None
    filter_text: str = ""
    detail: ArtifactDetailWire | None = None

    def navigate_to(self, artifact_id: str) -> bool:
        """Move to *artifact_id*, returning whether a fresh load is needed."""
        if artifact_id == self.current_id:
            return False
        self.back_stack.append(self.current_id)
        self.current_id = artifact_id
        self.forward_stack.clear()
        self.selected_row_id = None
        self.detail = None
        return True

    def back(self) -> str | None:
        if not self.back_stack:
            return None
        previous = self.back_stack.pop()
        self.forward_stack.append(self.current_id)
        self.current_id = previous
        self.selected_row_id = None
        self.detail = None
        return previous

    def forward(self) -> str | None:
        if not self.forward_stack:
            return None
        next_id = self.forward_stack.pop()
        self.back_stack.append(self.current_id)
        self.current_id = next_id
        self.selected_row_id = None
        self.detail = None
        return next_id

    def set_filter(self, filter_text: str) -> None:
        self.filter_text = filter_text.strip()
        self.selected_row_id = None

    def set_detail(self, detail: ArtifactDetailWire) -> None:
        self.detail = detail


def build_artifact_panel_rows(
    detail: ArtifactDetailWire,
    *,
    filter_text: str = "",
    row_limit: int = ARTIFACT_PANEL_ROW_LIMIT,
) -> _ArtifactPanelRows:
    """Build grouped, locally filtered modal rows from one detail record."""
    rows: list[ArtifactPanelRow] = []
    selectable_count = 0
    truncated = False
    normalized_filter = filter_text.casefold().strip()

    def add_group(label: str, candidates: list[ArtifactPanelRow]) -> None:
        nonlocal selectable_count, truncated
        visible = [
            row
            for row in candidates
            if not normalized_filter or normalized_filter in _row_search_text(row)
        ]
        if not visible:
            return
        rows.append(
            ArtifactPanelRow(
                id=f"group:{label.casefold().replace(' ', '_')}",
                label=label,
                row_type="group",
                selectable=False,
            )
        )
        for row in visible:
            selectable_count += 1
            if selectable_count > row_limit:
                truncated = True
                continue
            rows.append(row)

    path_rows = [
        _node_row("path", node, group="Path to root") for node in detail.path_to_root
    ]
    add_group("Path to root", path_rows)

    child_rows = [
        _node_row("child", node, group="Children") for node in detail.children
    ]
    add_group("Children", child_rows)

    for link_type, links in _group_links(detail.outbound_links).items():
        link_rows = [
            _link_row("outbound", link, group=f"Outbound: {link_type}")
            for link in links
        ]
        add_group(f"Outbound: {link_type}", link_rows)

    for link_type, links in _group_links(detail.inbound_links).items():
        link_rows = [
            _link_row("inbound", link, group=f"Inbound: {link_type}") for link in links
        ]
        add_group(f"Inbound: {link_type}", link_rows)

    if truncated:
        rows.append(
            ArtifactPanelRow(
                id="__truncated__",
                label=(
                    f"Showing first {row_limit} linked rows. "
                    "Use a filter to narrow this artifact locally."
                ),
                row_type="notice",
                selectable=False,
            )
        )

    return _ArtifactPanelRows(
        rows=rows,
        total_selectable=selectable_count,
        truncated=truncated,
    )


def parent_id_from_detail(detail: ArtifactDetailWire, current_id: str) -> str | None:
    """Return the nearest breadcrumb parent for *current_id*."""
    candidates = [node.id for node in detail.path_to_root if node.id != current_id]
    if not candidates:
        return None
    return candidates[-1]


def _node_row(prefix: str, node: ArtifactNodeWire, *, group: str) -> ArtifactPanelRow:
    return ArtifactPanelRow(
        id=f"{prefix}:{node.id}",
        label=f"{node.kind} {node.display_title}  {node.id}",
        artifact_id=node.id,
        row_type=prefix,
        group=group,
    )


def _link_row(
    direction: str, link: ArtifactLinkWire, *, group: str
) -> ArtifactPanelRow:
    artifact_id = link.target_id if direction == "outbound" else link.source_id
    direction_label = "to" if direction == "outbound" else "from"
    other_id = link.target_id if direction == "outbound" else link.source_id
    return ArtifactPanelRow(
        id=f"{direction}:{link.id}",
        label=f"{link.link_type} {direction_label} {other_id}",
        artifact_id=artifact_id,
        row_type=direction,
        group=group,
        link_type=link.link_type,
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
            row.row_type,
            row.group,
            row.link_type,
        )
        if part
    ).casefold()
