"""Markdown renderer for deterministic episodic-memory lessons."""

from __future__ import annotations

from pathlib import Path

from sase.core.episode_wire import (
    EpisodeEventWire,
    EpisodeLessonWire,
    EpisodeSourceRefWire,
    EpisodeWire,
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


__all__ = [
    "render_lesson_markdown",
]
