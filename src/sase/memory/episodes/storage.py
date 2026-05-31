"""Atomic project episode storage."""

from __future__ import annotations

from dataclasses import dataclass, replace
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
    episode_wire_from_dict,
    episode_wire_to_json_dict,
)
from sase.memory.episodes.identity import (
    EPISODE_IDENTITY_SCHEMA_VERSION,
    EpisodeAliasIndexRow,
    EpisodeMemberIndexRow,
    episode_member_keys,
    member_kind_from_key,
    merge_episode_alias_rows,
    merge_episode_member_rows,
    read_episode_alias_rows_unlocked,
    read_episode_member_rows_unlocked,
    resolve_alias_episode_id,
    write_episode_alias_rows_unlocked,
    write_episode_member_rows_unlocked,
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

    index_path = episode_index_path(episode.project, projects_root=projects_root)
    with locked_file(episode_index_lock_path(index_path), fcntl.LOCK_EX):
        return write_project_episode_unlocked(
            episode,
            lesson_markdown=lesson_markdown,
            projects_root=projects_root,
        )


def write_project_episode_unlocked(
    episode: EpisodeWire,
    *,
    lesson_markdown: str | None = None,
    projects_root: Path | str | None = None,
) -> EpisodeWriteResult:
    """Persist an episode while the caller holds the project episode lock."""

    if not episode.project.strip():
        raise ValueError("episode project must not be empty")
    if not episode.episode_id.strip():
        raise ValueError("episode id must not be empty")

    episodes_dir = project_episodes_dir(episode.project, projects_root=projects_root)
    index_path = episode_index_path(episode.project, projects_root=projects_root)
    episodes_dir.mkdir(parents=True, exist_ok=True)
    _gc_corrupt_episode_temp_dirs_unlocked(episodes_dir)
    existing_member_rows = read_episode_member_rows_unlocked(episodes_dir)
    existing_alias_rows = read_episode_alias_rows_unlocked(episodes_dir)
    canonical_episode_id, alias_rows_to_add = _resolve_episode_write_identity(
        episode,
        episodes_dir=episodes_dir,
        member_rows=existing_member_rows,
        alias_rows=existing_alias_rows,
    )
    stored_episode = (
        episode
        if canonical_episode_id == episode.episode_id
        else replace(episode, episode_id=canonical_episode_id)
    )
    target_dir = episodes_dir / stored_episode.episode_id
    payloads = _episode_file_payloads(
        stored_episode,
        lesson_markdown=lesson_markdown,
    )
    content_sha256 = _episode_content_sha256(payloads)
    index_row = _build_episode_index_row(
        stored_episode,
        lesson_path=(
            target_dir / EPISODE_LESSON_FILE_NAME
            if _episode_writes_lesson(stored_episode)
            else None
        ),
        content_sha256=content_sha256,
    )
    temp_dir = Path(
        tempfile.mkdtemp(
            prefix=f".{stored_episode.episode_id}.tmp.",
            dir=episodes_dir,
        )
    )
    try:
        for file_name, content in payloads.items():
            _write_text_and_fsync(temp_dir / file_name, content)
        files_changed = _replace_changed_files(target_dir, temp_dir, payloads)
        index_changed = upsert_episode_index_row_unlocked(index_path, index_row)
        member_rows_to_add = _member_rows_for_episode(stored_episode)
        members_changed = _write_identity_members_if_needed(
            episodes_dir,
            existing_member_rows,
            member_rows_to_add,
        )
        aliases_changed = _write_identity_aliases_if_needed(
            episodes_dir,
            existing_alias_rows,
            alias_rows_to_add,
        )
        _fsync_dir(target_dir)
        _fsync_dir(episodes_dir)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    return EpisodeWriteResult(
        episode_id=stored_episode.episode_id,
        project=stored_episode.project,
        episode_dir=target_dir,
        episode_json_path=target_dir / EPISODE_JSON_FILE_NAME,
        lesson_path=target_dir / EPISODE_LESSON_FILE_NAME,
        sources_path=target_dir / EPISODE_SOURCES_FILE_NAME,
        index_path=index_path,
        index_row=index_row,
        changed=files_changed or index_changed or members_changed or aliases_changed,
    )


def _resolve_episode_write_identity(
    episode: EpisodeWire,
    *,
    episodes_dir: Path,
    member_rows: list[EpisodeMemberIndexRow],
    alias_rows: list[EpisodeAliasIndexRow],
) -> tuple[str, list[EpisodeAliasIndexRow]]:
    member_keys = set(episode_member_keys(episode))
    desired_id = resolve_alias_episode_id(episode.episode_id, alias_rows)
    existing_ids = sorted(
        {
            resolve_alias_episode_id(row.canonical_episode_id, alias_rows)
            for row in member_rows
            if row.member_key in member_keys
        }
    )
    if _is_v2_component_episode(episode):
        existing_ids = sorted(
            {
                *existing_ids,
                *_stored_path_dependent_v2_episode_ids_for_member_keys(
                    episodes_dir,
                    member_keys,
                    alias_rows,
                ),
            }
        )
    canonical_id = _choose_canonical_episode_id(
        episode,
        desired_id=desired_id,
        existing_ids=existing_ids,
        episodes_dir=episodes_dir,
    )
    aliases = _alias_rows_for_identity_resolution(
        episode,
        canonical_id=canonical_id,
        desired_id=desired_id,
        existing_ids=existing_ids,
        episodes_dir=episodes_dir,
    )
    return canonical_id, aliases


def _choose_canonical_episode_id(
    episode: EpisodeWire,
    *,
    desired_id: str,
    existing_ids: list[str],
    episodes_dir: Path,
) -> str:
    if not existing_ids:
        return desired_id
    if desired_id in existing_ids:
        return desired_id
    if _is_v2_component_episode(episode) and all(
        _stored_episode_can_yield_to_logical_v2(episodes_dir, episode_id)
        for episode_id in existing_ids
    ):
        return desired_id
    if len(existing_ids) == 1:
        existing_id = existing_ids[0]
        if _is_v2_component_episode(episode) and _stored_episode_is_legacy(
            episodes_dir,
            existing_id,
        ):
            return desired_id
        return existing_id
    return sorted(
        existing_ids,
        key=lambda episode_id: _canonical_priority(
            episode_id,
            episodes_dir=episodes_dir,
        ),
    )[0]


def _canonical_priority(
    episode_id: str,
    *,
    episodes_dir: Path,
) -> tuple[str, str, str]:
    stored = _load_stored_episode_or_none(episodes_dir, episode_id)
    if stored is None:
        return ("", "", episode_id)
    root_time = (
        stored.metadata.get("component_root_timestamp")
        or _first_event_timestamp(stored)
        or ""
    )
    return (root_time, stored.component_key or "", episode_id)


def _alias_rows_for_identity_resolution(
    episode: EpisodeWire,
    *,
    canonical_id: str,
    desired_id: str,
    existing_ids: list[str],
    episodes_dir: Path,
) -> list[EpisodeAliasIndexRow]:
    aliases: dict[str, EpisodeAliasIndexRow] = {}
    if episode.episode_id != canonical_id:
        aliases[episode.episode_id] = EpisodeAliasIndexRow(
            schema_version=EPISODE_IDENTITY_SCHEMA_VERSION,
            project=episode.project,
            alias_episode_id=episode.episode_id,
            canonical_episode_id=canonical_id,
            reason="existing_member",
        )
    if desired_id != canonical_id:
        aliases[desired_id] = EpisodeAliasIndexRow(
            schema_version=EPISODE_IDENTITY_SCHEMA_VERSION,
            project=episode.project,
            alias_episode_id=desired_id,
            canonical_episode_id=canonical_id,
            reason="existing_member",
        )
    for existing_id in existing_ids:
        if existing_id == canonical_id:
            continue
        reason = _alias_reason_for_existing_episode(episodes_dir, existing_id)
        aliases[existing_id] = EpisodeAliasIndexRow(
            schema_version=EPISODE_IDENTITY_SCHEMA_VERSION,
            project=episode.project,
            alias_episode_id=existing_id,
            canonical_episode_id=canonical_id,
            reason=reason,
        )
    return sorted(aliases.values(), key=lambda row: row.alias_episode_id)


def _member_rows_for_episode(episode: EpisodeWire) -> list[EpisodeMemberIndexRow]:
    return [
        EpisodeMemberIndexRow(
            schema_version=EPISODE_IDENTITY_SCHEMA_VERSION,
            project=episode.project,
            member_key=member_key,
            member_kind=member_kind_from_key(member_key),
            canonical_episode_id=episode.episode_id,
        )
        for member_key in episode_member_keys(episode)
    ]


def _write_identity_members_if_needed(
    episodes_dir: Path,
    existing_rows: list[EpisodeMemberIndexRow],
    rows_to_add: list[EpisodeMemberIndexRow],
) -> bool:
    if not rows_to_add and not (episodes_dir / "members.jsonl").exists():
        return False
    return write_episode_member_rows_unlocked(
        episodes_dir,
        merge_episode_member_rows(existing_rows, rows_to_add),
    )


def _write_identity_aliases_if_needed(
    episodes_dir: Path,
    existing_rows: list[EpisodeAliasIndexRow],
    rows_to_add: list[EpisodeAliasIndexRow],
) -> bool:
    if not rows_to_add and not (episodes_dir / "aliases.jsonl").exists():
        return False
    return write_episode_alias_rows_unlocked(
        episodes_dir,
        merge_episode_alias_rows(existing_rows, rows_to_add),
    )


def _is_v2_component_episode(episode: EpisodeWire) -> bool:
    return bool(episode.component_key) and not _is_legacy_episode(episode)


def _stored_path_dependent_v2_episode_ids_for_member_keys(
    episodes_dir: Path,
    member_keys: set[str],
    alias_rows: list[EpisodeAliasIndexRow],
) -> list[str]:
    if not member_keys or not episodes_dir.is_dir():
        return []
    episode_ids: set[str] = set()
    for child in sorted(episodes_dir.iterdir(), key=lambda path: path.name):
        if not child.is_dir():
            continue
        stored = _load_stored_episode_or_none(episodes_dir, child.name)
        if stored is None or not _is_path_dependent_v2_component_episode(stored):
            continue
        if not (set(episode_member_keys(stored)) & member_keys):
            continue
        episode_ids.add(resolve_alias_episode_id(stored.episode_id, alias_rows))
    return sorted(episode_ids)


def _stored_episode_can_yield_to_logical_v2(
    episodes_dir: Path,
    episode_id: str,
) -> bool:
    return _stored_episode_is_legacy(
        episodes_dir,
        episode_id,
    ) or _stored_episode_is_path_dependent_v2_component(episodes_dir, episode_id)


def _alias_reason_for_existing_episode(episodes_dir: Path, episode_id: str) -> str:
    if _stored_episode_is_legacy(episodes_dir, episode_id):
        return "v1_migration"
    if _stored_episode_is_path_dependent_v2_component(episodes_dir, episode_id):
        return "component_key_migration"
    return "late_bridge"


def _stored_episode_is_path_dependent_v2_component(
    episodes_dir: Path,
    episode_id: str,
) -> bool:
    stored = _load_stored_episode_or_none(episodes_dir, episode_id)
    return stored is not None and _is_path_dependent_v2_component_episode(stored)


def _is_path_dependent_v2_component_episode(episode: EpisodeWire) -> bool:
    return _is_v2_component_episode(episode) and _component_key_is_path_dependent_v2(
        episode.component_key
    )


def _component_key_is_path_dependent_v2(component_key: str) -> bool:
    if component_key.startswith("component/chat/"):
        return Path(component_key.removeprefix("component/chat/")).is_absolute()
    if not component_key.startswith("component/artifact/"):
        return False
    parts = component_key.split("/")
    if len(parts) < 5:
        return False
    return Path("/".join(parts[4:])).is_absolute()


def _episode_writes_lesson(episode: EpisodeWire) -> bool:
    return not _is_v2_component_episode(episode)


def _stored_episode_is_legacy(episodes_dir: Path, episode_id: str) -> bool:
    stored = _load_stored_episode_or_none(episodes_dir, episode_id)
    return stored is not None and _is_legacy_episode(stored)


def _is_legacy_episode(episode: EpisodeWire) -> bool:
    return episode.schema_version < EPISODE_WIRE_SCHEMA_VERSION or (
        episode.status == "legacy"
    )


def _load_stored_episode_or_none(
    episodes_dir: Path,
    episode_id: str,
) -> EpisodeWire | None:
    try:
        data = json.loads(
            (episodes_dir / episode_id / EPISODE_JSON_FILE_NAME).read_text(
                encoding="utf-8"
            )
        )
        return episode_wire_from_dict(data)
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None


def _first_event_timestamp(episode: EpisodeWire) -> str | None:
    timestamps = sorted(
        {event.timestamp for event in episode.events if event.timestamp}
    )
    return timestamps[0] if timestamps else None


def _build_episode_index_row(
    episode: EpisodeWire,
    *,
    lesson_path: Path | None,
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
        lesson_path=(
            str(lesson_path.resolve(strict=False)) if lesson_path is not None else ""
        ),
        legacy_lesson_path=(
            str(lesson_path.resolve(strict=False))
            if lesson_path is not None
            and (
                episode.schema_version < EPISODE_WIRE_SCHEMA_VERSION
                or episode.status == "legacy"
            )
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
    payloads = {
        EPISODE_JSON_FILE_NAME: _ensure_trailing_newline(episode_json),
        EPISODE_SOURCES_FILE_NAME: _render_sources_jsonl(episode),
    }
    if _episode_writes_lesson(episode):
        lesson = (
            lesson_markdown
            if lesson_markdown is not None
            else (_render_minimal_lesson_markdown(episode))
        )
        payloads[EPISODE_LESSON_FILE_NAME] = _ensure_trailing_newline(lesson)
    return payloads


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
    for stale_name in (EPISODE_LESSON_FILE_NAME,):
        if stale_name in payloads:
            continue
        stale_path = target_dir / stale_name
        if stale_path.exists():
            stale_path.unlink()
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
    "write_project_episode_unlocked",
]
