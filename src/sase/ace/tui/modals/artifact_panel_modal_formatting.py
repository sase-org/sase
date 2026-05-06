"""Formatting helpers for the artifact panel modal."""

from __future__ import annotations

from rich.text import Text

from sase.core.artifact_wire.constants import ARTIFACT_FILE_TYPE_METADATA_KEY
from sase.core.artifact_wire import ArtifactDetailWire, ArtifactGraphWire

from .artifact_panel_state import (
    ARTIFACT_PANEL_SHOW_MORE_ACTION,
    ArtifactPanelPagedModel,
    ArtifactPanelRow,
)

_ARTIFACT_PANEL_NORMAL_HINTS = (
    "j/k: move  ': jump  enter: open  b/f: history  p/r: parent/root  "
    "/: local filter  S: global search  y: copy  e: edit  g/G: graph  q/Esc: close"
)

_ARTIFACT_BADGE_STYLES = {
    "plan": "#7DD3FC",
    "diff": "#FBBF24",
    "chat": "#A78BFA",
    "project": "#34D399",
    "prompt": "#F472B6",
    "misc": "#CBD5E1",
    "agent": "#60A5FA",
    "bead": "#FB7185",
    "changespec": "#2DD4BF",
    "cl": "#2DD4BF",
    "commit": "#F97316",
    "directory": "#94A3B8",
    "dir": "#94A3B8",
    "file": "#E2E8F0",
    "root": "#FACC15",
    "thought": "#C084FC",
}

_ARTIFACT_EDGE_STYLES = {
    "path": "#A78BFA",
    "parent": "#A78BFA",
    "children": "#22D3EE",
    "created": "#34D399",
    "worker": "#60A5FA",
    "related": "#FBBF24",
    "inbound": "#F472B6",
    "outbound": "#2DD4BF",
    "search": "#F97316",
}


def row_label(row: ArtifactPanelRow, *, hint_char: str | None = None) -> Text:
    if not row.selectable:
        text = Text(row.label)
        text.stylize(_disabled_row_style(row))
        return text
    prefix = Text()
    if hint_char is not None:
        prefix.append("[", style="dim")
        prefix.append(hint_char, style="bold #FFFF00")
        prefix.append("] ", style="dim")
    if row.page_action == ARTIFACT_PANEL_SHOW_MORE_ACTION:
        text = Text(row.label)
        text.stylize("bold cyan")
        prefix.append_text(text)
        return prefix

    badge = _semantic_badge(row.artifact_kind, row.file_type)
    badge_style = _semantic_badge_style(row.artifact_kind, row.file_type)
    text = Text()
    text.append(f"[{badge}] ", style=f"bold {badge_style}")
    text.append(row.title or row.label)
    compact_subtitle = " · ".join(
        part for part in (row.subtitle, row.updated_label) if part
    )
    if compact_subtitle:
        text.append(f"  {compact_subtitle}", style="dim")
    right_side = " · ".join(
        part for part in (row.artifact_id, row.status_label) if part
    )
    if right_side:
        text.append(f"  {right_side}", style="dim")
    if row.row_type == "path":
        text.stylize(_edge_style(row.edge_direction, row.link_type))
    elif row.row_type in {"child", "outbound", "inbound", "search"}:
        edge_label = _edge_label(row)
        if edge_label:
            text.append(
                f"  {edge_label}",
                style=f"bold {_edge_style(row.edge_direction, row.link_type)}",
            )
    if hint_char is not None:
        prefix.append_text(text)
        return prefix
    return text


def state_message(title: str, detail: str = "", *, style: str = "dim") -> Text:
    text = Text()
    text.append(title, style=f"bold {style}")
    if detail:
        text.append("\n")
        text.append(detail, style=style)
    return text


def _disabled_row_style(row: ArtifactPanelRow) -> str:
    if row.row_type == "group":
        return f"bold {_group_style(row.group_key)}"
    return "yellow"


def _group_style(group_key: str | None) -> str:
    if not group_key:
        return "cyan"
    if group_key == "path":
        return _ARTIFACT_EDGE_STYLES["path"]
    if group_key == "children":
        return _ARTIFACT_EDGE_STYLES["children"]
    if group_key.startswith("inbound"):
        return _ARTIFACT_EDGE_STYLES["inbound"]
    if group_key.startswith("outbound"):
        link_type = group_key.split(":", 1)[1] if ":" in group_key else None
        return _edge_style("outbound", link_type)
    if group_key == "search":
        return _ARTIFACT_EDGE_STYLES["search"]
    return "cyan"


def _edge_label(row: ArtifactPanelRow) -> str:
    if row.row_type == "child":
        return "children"
    if row.row_type == "search":
        return "search"
    if row.row_type in {"outbound", "inbound"}:
        return row.link_type or row.edge_direction or ""
    return row.edge_direction or ""


def _edge_style(edge_direction: str | None, link_type: str | None = None) -> str:
    if link_type and link_type in _ARTIFACT_EDGE_STYLES:
        return _ARTIFACT_EDGE_STYLES[link_type]
    if edge_direction and edge_direction in _ARTIFACT_EDGE_STYLES:
        return _ARTIFACT_EDGE_STYLES[edge_direction]
    return "cyan"


def header_loading_primary(artifact_id: str) -> Text:
    text = Text()
    text.append("[ARTIFACT] ", style=f"bold {_ARTIFACT_BADGE_STYLES['file']}")
    text.append(artifact_id)
    return text


def header_primary(node: object) -> Text:
    kind = str(getattr(node, "kind", "") or "")
    metadata = getattr(node, "metadata", {}) or {}
    file_type = metadata.get(ARTIFACT_FILE_TYPE_METADATA_KEY)
    badge = _semantic_badge(kind, str(file_type) if file_type else None)
    badge_style = _semantic_badge_style(kind, str(file_type) if file_type else None)
    title = str(getattr(node, "display_title", "") or getattr(node, "id", ""))
    provenance = str(getattr(node, "provenance", "") or "")
    source = _join_compact(
        [
            str(getattr(node, "source_kind", "") or ""),
            str(getattr(node, "source_id", "") or ""),
        ],
        separator=":",
    )
    markers = [
        str(metadata.get("status") or metadata.get("state") or ""),
        provenance,
        source,
    ]
    text = Text()
    text.append(f"[{badge}] ", style=f"bold {badge_style}")
    text.append(title or str(getattr(node, "id", "")), style="bold")
    marker_text = _join_compact(markers)
    if marker_text:
        text.append(f"  {marker_text}", style="dim")
    return text


def header_breadcrumb(detail: ArtifactDetailWire) -> Text:
    parts = [node.display_title or node.id for node in detail.path_to_root]
    if detail.node is not None:
        current = detail.node.display_title or detail.node.id
        if not parts or parts[-1] != current:
            parts.append(current)
    text = Text()
    text.append("Path: ", style="dim")
    text.append(_compressed_breadcrumb(parts))
    return text


def header_counts(paged_model: ArtifactPanelPagedModel | None) -> Text:
    if paged_model is None:
        return Text("")

    paged = paged_model.paged_detail
    chunks: list[str] = []
    if paged.children_page is not None:
        chunks.append(f"children {_summary_count(paged.children_page.summary)}")
    outbound_total = sum(page.summary.total_count for page in paged.outbound_pages)
    inbound_total = sum(page.summary.total_count for page in paged.inbound_pages)
    if outbound_total:
        chunks.append(f"outbound {outbound_total}")
    if inbound_total:
        chunks.append(f"inbound {inbound_total}")
    chunks.extend(
        f"{_semantic_badge(type_count.artifact_type, type_count.artifact_type).lower()} {type_count.total_count}"
        for type_count in paged.type_counts[:6]
    )
    text = Text()
    text.append("Counts: ", style="dim")
    text.append("  ".join(chunks) if chunks else "none", style="dim")
    return text


def _summary_count(summary: object) -> str:
    loaded = int(getattr(summary, "loaded_count", 0) or 0)
    total = int(getattr(summary, "total_count", 0) or 0)
    if total > loaded:
        return f"{loaded}/{total}"
    return str(total or loaded)


def _semantic_badge(kind: str | None, file_type: str | None = None) -> str:
    if file_type:
        return {
            "plan": "PLAN",
            "diff": "DIFF",
            "chat": "CHAT",
            "project": "PROJECT",
            "prompt": "PROMPT",
            "misc": "MISC",
        }.get(file_type, file_type.upper())
    return {
        "agent": "AGENT",
        "bead": "BEAD",
        "changespec": "CL",
        "cl": "CL",
        "commit": "COMMIT",
        "directory": "DIR",
        "dir": "DIR",
        "file": "FILE",
        "project": "PROJECT",
        "root": "ROOT",
        "thought": "THOUGHT",
    }.get(kind or "", (kind or "artifact").upper())


def _semantic_badge_style(kind: str | None, file_type: str | None = None) -> str:
    if file_type:
        return _ARTIFACT_BADGE_STYLES.get(file_type, _ARTIFACT_BADGE_STYLES["file"])
    return _ARTIFACT_BADGE_STYLES.get(kind or "", _ARTIFACT_BADGE_STYLES["file"])


def _compressed_breadcrumb(parts: list[str]) -> str:
    cleaned = [part for part in parts if part]
    if len(cleaned) <= 4:
        return " > ".join(cleaned)
    return " > ".join([cleaned[0], "...", *cleaned[-3:]])


def _join_compact(parts: list[str], *, separator: str = " · ") -> str:
    return separator.join(part for part in parts if part)


def graph_preview_text(graph: ArtifactGraphWire) -> Text:
    text = Text()
    text.append("Graph preview\n", style="bold")
    text.append("Root: ", style="bold")
    text.append(f"{graph.root_id or ''}\n")
    text.append("Nodes: ", style="bold")
    text.append(f"{graph.node_count or len(graph.nodes)}\n")
    text.append("Links: ", style="bold")
    text.append(f"{graph.link_count or len(graph.links)}\n")
    text.append("Truncated: ", style="bold")
    text.append(f"{graph.truncated}\n")
    for node in graph.nodes[:10]:
        text.append(f"- {node.kind} {node.display_title}  {node.id}\n")
    return text
