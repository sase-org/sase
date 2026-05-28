"""Atomic project episode storage."""

from __future__ import annotations

from dataclasses import dataclass
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile

from sase.core.episode_facade import canonical_episode_json
from sase.core.episode_wire import (
    EPISODE_WIRE_SCHEMA_VERSION,
    EpisodeStorageIndexRowWire,
    EpisodeWire,
    episode_wire_to_json_dict,
)
from sase.memory.episodes.index import (
    episode_index_lock_path,
    episode_index_path,
    project_episodes_dir,
    upsert_episode_index_row_unlocked,
)
from sase.memory.episodes.source_refs import sort_source_refs
from sase.memory.locks import locked_file

EPISODE_JSON_FILE_NAME = "episode.json"
EPISODE_LESSON_FILE_NAME = "lesson.md"
EPISODE_SOURCES_FILE_NAME = "sources.jsonl"


@dataclass(frozen=True)
class EpisodeWriteResult:
    """Result from a project episode write."""

    episode_id: str
    project: str
    episode_dir: Path
    episode_json_path: Path
    lesson_path: Path
    sources_path: Path
    index_path: Path
    index_row: EpisodeStorageIndexRowWire
    changed: bool


def write_project_episode(
    episode: EpisodeWire,
    *,
    lesson_markdown: str | None = None,
    projects_root: Path | str | None = None,
) -> EpisodeWriteResult:
    """Persist an episode and update its project index.

    ``episode.json`` remains canonical. ``lesson.md``, ``sources.jsonl``, and
    ``index.jsonl`` are deterministic projections that can be rebuilt.
    """

    if not episode.project.strip():
        raise ValueError("episode project must not be empty")
    if not episode.episode_id.strip():
        raise ValueError("episode id must not be empty")

    episodes_dir = project_episodes_dir(episode.project, projects_root=projects_root)
    index_path = episode_index_path(episode.project, projects_root=projects_root)
    target_dir = episodes_dir / episode.episode_id
    payloads = _episode_file_payloads(episode, lesson_markdown=lesson_markdown)
    content_sha256 = _episode_content_sha256(payloads)
    index_row = _build_episode_index_row(
        episode,
        lesson_path=target_dir / EPISODE_LESSON_FILE_NAME,
        content_sha256=content_sha256,
    )

    with locked_file(episode_index_lock_path(index_path), fcntl.LOCK_EX):
        episodes_dir.mkdir(parents=True, exist_ok=True)
        _gc_corrupt_episode_temp_dirs_unlocked(episodes_dir)
        temp_dir = Path(
            tempfile.mkdtemp(
                prefix=f".{episode.episode_id}.tmp.",
                dir=episodes_dir,
            )
        )
        try:
            for file_name, content in payloads.items():
                _write_text_and_fsync(temp_dir / file_name, content)
            files_changed = _replace_changed_files(target_dir, temp_dir, payloads)
            index_changed = upsert_episode_index_row_unlocked(index_path, index_row)
            _fsync_dir(target_dir)
            _fsync_dir(episodes_dir)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    return EpisodeWriteResult(
        episode_id=episode.episode_id,
        project=episode.project,
        episode_dir=target_dir,
        episode_json_path=target_dir / EPISODE_JSON_FILE_NAME,
        lesson_path=target_dir / EPISODE_LESSON_FILE_NAME,
        sources_path=target_dir / EPISODE_SOURCES_FILE_NAME,
        index_path=index_path,
        index_row=index_row,
        changed=files_changed or index_changed,
    )


def _build_episode_index_row(
    episode: EpisodeWire,
    *,
    lesson_path: Path,
    content_sha256: str,
) -> EpisodeStorageIndexRowWire:
    """Build the deterministic index row for a stored episode."""

    event_timestamps = sorted(
        {event.timestamp for event in episode.events if event.timestamp}
    )
    return EpisodeStorageIndexRowWire(
        schema_version=EPISODE_WIRE_SCHEMA_VERSION,
        episode_id=episode.episode_id,
        project=episode.project,
        title=episode.title,
        component_key=_component_key(episode),
        status=episode.status or "active",
        summary_excerpt=_summary_excerpt(episode.summary),
        root_agent_names=_root_agent_names(episode),
        changespec_name=_changespec_name(episode),
        bead_ids=_bead_ids(episode),
        outcome=_outcome(episode),
        first_event_at=event_timestamps[0] if event_timestamps else None,
        last_event_at=event_timestamps[-1] if event_timestamps else None,
        importance_score=episode.importance_score,
        importance_band=episode.importance_band or "unknown",
        source_count=len(episode.sources),
        chat_count=_chat_count(episode),
        agent_count=_agent_count(episode),
        lesson_path=str(lesson_path.resolve(strict=False)),
        legacy_lesson_path=(
            str(lesson_path.resolve(strict=False))
            if episode.schema_version < EPISODE_WIRE_SCHEMA_VERSION
            or episode.status == "legacy"
            else None
        ),
        content_sha256=content_sha256,
    )


def _episode_content_sha256(payloads: dict[str, str]) -> str:
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


def gc_corrupt_episode_temp_dirs(
    project: str,
    *,
    projects_root: Path | str | None = None,
) -> list[Path]:
    """Remove only storage temp directories from a project episode store."""

    episodes_dir = project_episodes_dir(project, projects_root=projects_root)
    index_path = episode_index_path(project, projects_root=projects_root)
    with locked_file(episode_index_lock_path(index_path), fcntl.LOCK_EX):
        return _gc_corrupt_episode_temp_dirs_unlocked(episodes_dir)


def _episode_file_payloads(
    episode: EpisodeWire,
    *,
    lesson_markdown: str | None,
) -> dict[str, str]:
    episode_json = canonical_episode_json(episode)
    if not episode_json.endswith("\n"):
        episode_json += "\n"
    lesson = (
        lesson_markdown
        if lesson_markdown is not None
        else (_render_minimal_lesson_markdown(episode))
    )
    return {
        EPISODE_JSON_FILE_NAME: _ensure_trailing_newline(episode_json),
        EPISODE_LESSON_FILE_NAME: _ensure_trailing_newline(lesson),
        EPISODE_SOURCES_FILE_NAME: _render_sources_jsonl(episode),
    }


def _replace_changed_files(
    target_dir: Path,
    temp_dir: Path,
    payloads: dict[str, str],
) -> bool:
    target_dir.mkdir(parents=True, exist_ok=True)
    changed = False
    for file_name, content in payloads.items():
        target = target_dir / file_name
        if _read_text_or_none(target) == content:
            continue
        os.replace(temp_dir / file_name, target)
        changed = True
    return changed


def _write_text_and_fsync(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())


def _gc_corrupt_episode_temp_dirs_unlocked(episodes_dir: Path) -> list[Path]:
    if not episodes_dir.exists():
        return []
    removed: list[Path] = []
    for child in sorted(episodes_dir.iterdir(), key=lambda path: path.name):
        if not child.is_dir():
            continue
        if child.name.startswith(".") and ".tmp." in child.name:
            shutil.rmtree(child)
            removed.append(child)
    return removed


def _root_agent_names(episode: EpisodeWire) -> list[str]:
    explicit = _metadata_list(episode.metadata.get("root_agent_names")) or (
        _metadata_list(episode.metadata.get("root_agents"))
    )
    if explicit:
        return explicit
    names = {
        node.label
        for node in episode.nodes
        if node.kind == "agent_run" and node.label is not None and node.label
    }
    return sorted(names)


def _component_key(episode: EpisodeWire) -> str:
    return (
        episode.component_key
        or episode.metadata.get("component_key")
        or episode.root_source_id
    )


def _summary_excerpt(summary: str) -> str:
    collapsed = " ".join(summary.split())
    if len(collapsed) <= 240:
        return collapsed
    return collapsed[:237].rstrip() + "..."


def _chat_count(episode: EpisodeWire) -> int:
    explicit = episode.metadata.get("chat_count")
    if explicit and explicit.isdigit():
        return int(explicit)
    return sum(1 for node in episode.nodes if node.kind == "chat")


def _agent_count(episode: EpisodeWire) -> int:
    explicit = episode.metadata.get("agent_count") or episode.metadata.get(
        "agent_record_count"
    )
    if explicit and explicit.isdigit():
        return int(explicit)
    return sum(1 for node in episode.nodes if node.kind == "agent_run")


def _changespec_name(episode: EpisodeWire) -> str | None:
    if episode.weak_refs.changespec_names:
        return ", ".join(sorted(set(episode.weak_refs.changespec_names)))
    explicit = episode.metadata.get("changespec_name")
    if explicit:
        return explicit
    names = {
        node.metadata.get("name") or node.label
        for node in episode.nodes
        if node.kind == "changespec"
    }
    clean = sorted({name for name in names if name})
    return ", ".join(clean) if clean else None


def _bead_ids(episode: EpisodeWire) -> list[str]:
    if episode.weak_refs.bead_ids:
        return sorted(set(episode.weak_refs.bead_ids))
    explicit = _metadata_list(episode.metadata.get("bead_ids"))
    if explicit:
        return explicit
    bead_ids = {
        node.metadata.get("id") or node.label
        for node in episode.nodes
        if node.kind == "bead"
    }
    return sorted({bead_id for bead_id in bead_ids if bead_id})


def _outcome(episode: EpisodeWire) -> str | None:
    explicit = episode.metadata.get("outcome")
    if explicit:
        return explicit
    outcomes = sorted(
        {
            node.metadata["outcome"]
            for node in episode.nodes
            if node.kind == "agent_run" and node.metadata.get("outcome")
        }
    )
    return ", ".join(outcomes) if outcomes else None


def _metadata_list(value: str | None) -> list[str]:
    if not value:
        return []
    return sorted({item.strip() for item in value.split(",") if item.strip()})


def _evidence_suffix(evidence_ids: list[str]) -> str:
    if not evidence_ids:
        return ""
    return f" [{', '.join(sorted(evidence_ids))}]"


def _ensure_trailing_newline(value: str) -> str:
    return value if value.endswith("\n") else f"{value}\n"


def _read_text_or_none(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None


def _fsync_dir(path: Path) -> None:
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


__all__ = [
    "EPISODE_JSON_FILE_NAME",
    "EPISODE_LESSON_FILE_NAME",
    "EPISODE_SOURCES_FILE_NAME",
    "EpisodeWriteResult",
    "gc_corrupt_episode_temp_dirs",
    "write_project_episode",
]
