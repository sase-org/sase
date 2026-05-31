"""On-disk episode file projections."""

from __future__ import annotations

import hashlib
import json

from sase.core.episode_facade import canonical_episode_json
from sase.core.episode_wire import EpisodeWire, episode_wire_to_json_dict
from sase.memory.episodes._storage_files import (
    EPISODE_JSON_FILE_NAME,
    EPISODE_LESSON_FILE_NAME,
    EPISODE_SOURCES_FILE_NAME,
)
from sase.memory.episodes._storage_identity import episode_writes_lesson
from sase.memory.episodes.source_refs import sort_source_refs


def episode_file_payloads(
    episode: EpisodeWire,
    *,
    lesson_markdown: str | None,
) -> dict[str, str]:
    episode_json = canonical_episode_json(episode)
    if not episode_json.endswith("\n"):
        episode_json += "\n"
    payloads = {
        EPISODE_JSON_FILE_NAME: _ensure_trailing_newline(episode_json),
        EPISODE_SOURCES_FILE_NAME: _render_sources_jsonl(episode),
    }
    if episode_writes_lesson(episode):
        lesson = (
            lesson_markdown
            if lesson_markdown is not None
            else (_render_minimal_lesson_markdown(episode))
        )
        payloads[EPISODE_LESSON_FILE_NAME] = _ensure_trailing_newline(lesson)
    return payloads


def episode_content_sha256(payloads: dict[str, str]) -> str:
    """Hash the deterministic on-disk episode projections."""

    hasher = hashlib.sha256()
    for file_name in sorted(payloads):
        hasher.update(file_name.encode("utf-8"))
        hasher.update(b"\0")
        hasher.update(payloads[file_name].encode("utf-8"))
        hasher.update(b"\0")
    return hasher.hexdigest()


def _render_sources_jsonl(episode: EpisodeWire) -> str:
    """Render ``sources.jsonl`` from sorted episode source refs."""

    lines = [
        json.dumps(
            episode_wire_to_json_dict(source),
            sort_keys=True,
            separators=(",", ":"),
        )
        for source in sort_source_refs(list(episode.sources))
    ]
    return "".join(f"{line}\n" for line in lines)


def _render_minimal_lesson_markdown(episode: EpisodeWire) -> str:
    """Render a deterministic fallback lesson projection.

    Phase 3 owns the richer renderer. Storage accepts that rendered markdown
    when available and uses this small projection only as a safe default.
    """

    lines = [
        f"# {episode.title}",
        "",
        "## Summary",
        "",
        episode.summary,
    ]
    if episode.events:
        lines.extend(["", "## Timeline", ""])
        for event in sorted(
            episode.events, key=lambda item: (item.timestamp or "", item.id)
        ):
            prefix = f"{event.timestamp} " if event.timestamp else ""
            lines.append(
                f"- {prefix}{event.title}{_evidence_suffix(event.evidence_ids)}"
            )
    if episode.lessons:
        lines.extend(["", "## Lessons", ""])
        for lesson in sorted(episode.lessons, key=lambda item: item.id):
            lines.append(
                f"- {lesson.kind}: {lesson.text}{_evidence_suffix(lesson.evidence_ids)}"
            )
    if episode.sources:
        lines.extend(["", "## Sources", ""])
        for source in sort_source_refs(list(episode.sources)):
            status = "exists" if source.exists else "missing"
            digest = f" sha256={source.sha256}" if source.sha256 else ""
            lines.append(f"- {source.id} {source.kind} {status} {source.path}{digest}")
    return "\n".join(lines) + "\n"


def _evidence_suffix(evidence_ids: list[str]) -> str:
    if not evidence_ids:
        return ""
    return f" [{', '.join(sorted(evidence_ids))}]"


def _ensure_trailing_newline(value: str) -> str:
    return value if value.endswith("\n") else f"{value}\n"
