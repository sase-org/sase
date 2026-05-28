"""Renderers for deterministic episodic-memory episodes."""

from __future__ import annotations

from pathlib import Path
import shutil
import textwrap
from typing import Any

from sase.core.episode_wire import (
    EpisodeEventWire,
    EpisodeLessonWire,
    EpisodeSourceRefWire,
    EpisodeWire,
)
from sase.memory.episodes.views import (
    EpisodeGraphEdgeMode,
    build_agent_evidence_pack_view,
    build_graph_view,
    build_overview_view,
    build_sources_view,
    build_timeline_view,
)

_SECTION_KINDS = {
    "Goal": {"goal"},
    "Decisions And Feedback": {"decision", "feedback", "question_answer"},
    "Work Performed": {"artifact", "implementation", "memory_context"},
    "Outcome": {"failure", "open_question", "retry", "verification"},
}


def render_lesson_markdown(episode: EpisodeWire) -> str:
    """Render a deterministic human-facing lesson document from an episode."""

    lines: list[str] = [f"# {episode.title}", ""]
    if episode.summary:
        lines.extend(["## Summary", "", episode.summary, ""])

    for section, kinds in _SECTION_KINDS.items():
        lessons = _lessons_for_kinds(episode.lessons, kinds)
        if not lessons:
            continue
        lines.extend([f"## {section}", ""])
        lines.extend(_render_lessons(lessons))
        lines.append("")

    if episode.events:
        lines.extend(["## Timeline", ""])
        for event in sorted(
            episode.events,
            key=lambda item: (item.timestamp is None, item.timestamp or "", item.id),
        ):
            lines.append(_render_event(event))
        lines.append("")

    if episode.lessons:
        lines.extend(["## Lessons", ""])
        lines.extend(_render_lessons(sorted(episode.lessons, key=lambda item: item.id)))
        lines.append("")

    lines.extend(["## Sources", ""])
    for source in sorted(
        episode.sources, key=lambda item: (item.kind, item.path, item.id)
    ):
        lines.append(_render_source(source))
    lines.append("")
    return "\n".join(lines)


def render_overview_text(episode: EpisodeWire, *, width: int | None = None) -> str:
    """Render the compact v2 overview view."""

    view = build_overview_view(episode)
    lines = [
        f"# {view.title}",
        "",
        f"Episode: {view.episode_id}",
        f"Project: {view.project}",
        f"Status: {view.status}",
        f"Importance: {view.importance_band} ({view.importance_score})",
        f"Time span: {view.time_span}",
    ]
    if view.component_key:
        component_kind = view.component_root_kind or "component"
        lines.append(f"Component: {component_kind} {view.component_key}")
    lines.append("")
    lines.extend(_paragraph("Summary", view.summary, width=width))
    lines.extend(
        _kv_section(
            "Participants",
            {
                "Agents": _join_or_dash(view.agents),
                "Chats": _join_or_dash(view.chats),
                "Sources": str(view.source_count),
                "Events": str(view.event_count),
                "Strong edges": str(view.strong_edge_count),
            },
            width=width,
        )
    )
    if view.importance_factors:
        lines.extend(["## Importance Factors", ""])
        for factor in view.importance_factors:
            label = str(factor["label"])
            suffix = f" ({factor['score']})" if factor["score"] else ""
            lines.extend(_bullet(f"{label}{suffix}", width=width))
        lines.append("")
    if view.weak_metadata:
        lines.extend(
            _metadata_section("Weak Metadata", view.weak_metadata, width=width)
        )
    if view.warnings:
        lines.extend(["## Warnings", ""])
        for warning in view.warnings:
            lines.extend(_bullet(warning, width=width))
        lines.append("")
    lines.extend(["## Next Commands", ""])
    for command in view.next_commands:
        lines.extend(_bullet(command, width=width))
    lines.append("")
    return "\n".join(lines)


def render_timeline_text(episode: EpisodeWire, *, width: int | None = None) -> str:
    """Render the ordered event timeline drill-down view."""

    rows = build_timeline_view(episode)
    lines = [f"# Timeline: {episode.title}", ""]
    if not rows:
        lines.append("No timeline events are recorded.")
        lines.append("")
        return "\n".join(lines)

    current_group: str | None = None
    for row in rows:
        if row.group != current_group:
            if current_group is not None:
                lines.append("")
            lines.extend([f"## {row.group}", ""])
            current_group = row.group
        text = f"{row.timestamp} [{row.kind}] {row.title}"
        if row.description:
            text += f" - {row.description}"
        if row.evidence_ids:
            text += " evidence=" + ",".join(row.evidence_ids)
        lines.extend(_bullet(text, width=width))
        if any(status.endswith(":missing") for status in row.evidence_status):
            lines.extend(
                _bullet(
                    "warning: missing evidence "
                    + ", ".join(
                        status.removesuffix(":missing")
                        for status in row.evidence_status
                        if status.endswith(":missing")
                    ),
                    width=width,
                    indent="    ",
                )
            )
    lines.append("")
    return "\n".join(lines)


def render_graph_text(
    episode: EpisodeWire,
    *,
    edge_mode: EpisodeGraphEdgeMode = "strong",
    width: int | None = None,
) -> str:
    """Render a deterministic component graph."""

    view = build_graph_view(episode, edge_mode=edge_mode)
    lines = [f"# Graph: {episode.title}", "", f"Edge mode: {view.edge_mode}", ""]
    if view.nodes:
        lines.extend(["## Nodes", ""])
        for node in view.nodes:
            label = f"{node.node_id} [{node.kind}] {node.label}"
            if node.source_id:
                label += f" source={node.source_id}"
            lines.extend(_bullet(label, width=width))
        lines.append("")
    if view.edges:
        lines.extend(["## Edges", ""])
        for edge in view.edges:
            line = (
                f"{edge.from_label} -> {edge.to_label} [{edge.kind}; {edge.strength}]"
            )
            if edge.evidence_ids:
                line += " evidence=" + ",".join(edge.evidence_ids)
            lines.extend(_bullet(line, width=width))
        lines.append("")
    else:
        lines.extend(["## Edges", "", "No graph edges are recorded.", ""])
    if view.weak_metadata:
        section_name = (
            "Weak Metadata Edges"
            if edge_mode == "all"
            else "Weak Metadata (not component edges)"
        )
        lines.extend(_metadata_section(section_name, view.weak_metadata, width=width))
    return "\n".join(lines)


def render_sources_text(episode: EpisodeWire, *, width: int | None = None) -> str:
    """Render grouped source refs with stored status and hashes."""

    view = build_sources_view(episode)
    lines = [f"# Sources: {episode.title}", ""]
    if view.warnings:
        lines.extend(["## Warnings", ""])
        for warning in view.warnings:
            lines.extend(_bullet(warning, width=width))
        lines.append("")
    if not view.groups:
        lines.append("No sources are recorded.")
        lines.append("")
        return "\n".join(lines)
    for group in view.groups:
        lines.extend([f"## {group.kind}", ""])
        for source in group.sources:
            text = (
                f"[{source.source_id}] {source.label}: {source.path} ({source.status}"
            )
            if source.size_bytes is not None:
                text += f", {source.size_bytes} bytes"
            if source.sha256:
                text += f", sha256={source.sha256}"
            text += ")"
            lines.extend(_bullet(text, width=width))
        lines.append("")
    return "\n".join(lines)


def render_agent_text(episode: EpisodeWire, *, width: int | None = None) -> str:
    """Render a bounded evidence pack for human inspection."""

    view = build_agent_evidence_pack_view(episode)
    lines = [f"# Agent Evidence Pack: {view.title}", ""]
    lines.extend(_paragraph("Framing", view.framing, width=width))
    lines.extend(_paragraph("Summary", view.summary, width=width))
    lines.extend(
        _kv_section(
            "Episode",
            {
                "ID": view.episode_id,
                "Project": view.project,
                "Status": view.status,
                "Importance": (
                    f"{view.importance['band']} ({view.importance['score']})"
                ),
                "Time span": view.time_span,
            },
            width=width,
        )
    )
    if view.warnings:
        lines.extend(["## Warnings", ""])
        for warning in view.warnings:
            lines.extend(_bullet(warning, width=width))
        lines.append("")
    if view.timeline:
        lines.extend(["## Evidence Timeline", ""])
        for event in view.timeline:
            text = f"{event['timestamp']} [{event['kind']}] {event['title']}"
            if event["evidence_ids"]:
                text += " evidence=" + ",".join(event["evidence_ids"])
            lines.extend(_bullet(text, width=width))
        lines.append("")
    if view.source_refs:
        lines.extend(["## Source Refs", ""])
        for source in view.source_refs:
            text = (
                f"[{source['id']}] {source['kind']} {source['label']} "
                f"{source['status']}: {source['path']}"
            )
            lines.extend(_bullet(text, width=width))
        lines.append("")
    if view.weak_metadata:
        lines.extend(
            _metadata_section("Weak Metadata", view.weak_metadata, width=width)
        )
    return "\n".join(lines)


def agent_evidence_pack_json_dict(episode: EpisodeWire) -> dict[str, Any]:
    """Return stable machine-readable agent evidence pack data."""

    return build_agent_evidence_pack_view(episode).to_json_dict()


def _lessons_for_kinds(
    lessons: list[EpisodeLessonWire],
    kinds: set[str],
) -> list[EpisodeLessonWire]:
    return sorted(
        [lesson for lesson in lessons if lesson.kind in kinds],
        key=lambda lesson: (lesson.kind, lesson.id),
    )


def _render_lessons(lessons: list[EpisodeLessonWire]) -> list[str]:
    return [
        f"- {lesson.text}{_render_evidence(lesson.evidence_ids)}" for lesson in lessons
    ]


def _render_event(event: EpisodeEventWire) -> str:
    prefix = event.timestamp or "undated"
    description = f" - {event.description}" if event.description else ""
    return (
        f"- {prefix} {event.title}{description}{_render_evidence(event.evidence_ids)}"
    )


def _render_source(source: EpisodeSourceRefWire) -> str:
    label = source.label or Path(source.path).name or source.path
    status = "exists" if source.exists else "missing"
    details = [status]
    if source.size_bytes is not None:
        details.append(f"{source.size_bytes} bytes")
    if source.sha256:
        details.append(f"sha256={source.sha256}")
    return (
        f"- [{source.id}] {source.kind} `{label}`: `{source.path}` "
        f"({', '.join(details)})"
    )


def _render_evidence(evidence_ids: list[str]) -> str:
    if not evidence_ids:
        return ""
    return (
        " [evidence: " + ", ".join(f"`{item}`" for item in sorted(evidence_ids)) + "]"
    )


def _paragraph(title: str, text: str, *, width: int | None) -> list[str]:
    lines = [f"## {title}", ""]
    lines.extend(_wrap(text or "-", width=width))
    lines.append("")
    return lines


def _kv_section(
    title: str,
    values: dict[str, str],
    *,
    width: int | None,
) -> list[str]:
    lines = [f"## {title}", ""]
    for key, value in values.items():
        lines.extend(_bullet(f"{key}: {value}", width=width))
    lines.append("")
    return lines


def _metadata_section(
    title: str,
    metadata: dict[str, list[str]],
    *,
    width: int | None,
) -> list[str]:
    lines = [f"## {title}", ""]
    for key, values in metadata.items():
        lines.extend(_bullet(f"{key}: {', '.join(values)}", width=width))
    lines.append("")
    return lines


def _bullet(
    text: str,
    *,
    width: int | None,
    indent: str = "",
) -> list[str]:
    prefix = f"{indent}- "
    continuation = f"{indent}  "
    wrapped = _wrap(
        text,
        width=width,
        initial_indent=prefix,
        subsequent_indent=continuation,
    )
    return wrapped or [prefix.rstrip()]


def _wrap(
    text: str,
    *,
    width: int | None,
    initial_indent: str = "",
    subsequent_indent: str = "",
) -> list[str]:
    columns = _render_width(width)
    return textwrap.wrap(
        " ".join(str(text).split()),
        width=columns,
        initial_indent=initial_indent,
        subsequent_indent=subsequent_indent,
        break_long_words=False,
        break_on_hyphens=False,
    ) or [initial_indent.rstrip()]


def _render_width(width: int | None) -> int:
    if width is not None:
        return max(40, width)
    return max(40, shutil.get_terminal_size((100, 24)).columns)


def _join_or_dash(values: list[str]) -> str:
    return ", ".join(values) if values else "-"


__all__ = [
    "agent_evidence_pack_json_dict",
    "render_agent_text",
    "render_graph_text",
    "render_lesson_markdown",
    "render_overview_text",
    "render_sources_text",
    "render_timeline_text",
]
