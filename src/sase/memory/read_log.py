"""Foundation helpers for auditable ``sase memory read`` access."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import fcntl
import json
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from sase.agent.identity import (
    AgentIdentity,
    AgentIdentityError,
    AgentIdentitySource,
    agent_name_from_meta,
    discover_agent_identity,
    resolve_audit_identity,
)
from sase.agent.identity import (
    require_agent_identity as _require_agent_identity,
)
from sase.core.paths import sase_projects_dir
from sase.content_layout import LayoutCollisionError
from sase.main.init_memory.config import project_memory_name
from sase.memory.locks import locked_file
from sase.memory.notes import MemoryNote, parse_memory_note_text
from sase.memory.paths import (
    CANONICAL_MEMORY_RELATIVE_ROOT,
    LEGACY_MEMORY_RELATIVE_ROOT,
    canonical_memory_reference,
    memory_read_root,
)
from sase.project_aliases import resolve_project_alias_ref

READ_LOG_SCHEMA_VERSION = 2

MemoryReadKind = Literal["note", "web", "strand"]


class MemoryReadError(ValueError):
    """Base class for memory-read validation errors."""


class MemoryReadPathError(MemoryReadError):
    """Raised when a memory-relative read path is not allowed."""


@dataclass(frozen=True)
class ValidatedMemoryPath:
    """A memory file path that has passed read-path validation."""

    memory_root: Path
    allowed_root: Path
    canonical_path: str
    path: Path
    resolved_path: Path
    note: MemoryNote
    content_root: Path


@dataclass(frozen=True)
class FrontmatterStripResult:
    body: str
    stripped: bool


@dataclass(frozen=True)
class MemoryReadContent:
    path: ValidatedMemoryPath
    raw_text: str
    body: str
    byte_count: int
    frontmatter_stripped: bool


@dataclass(frozen=True)
class MemoryReadEvent:
    """One audited ``sase memory read`` event.

    ``canonical_path``/``resolved_path``/``byte_count``/``frontmatter_stripped``
    keep their pre-web meaning exactly for a single-note read: every consumer
    written before webs existed (the ACE memory-reads loader, ``memory log``)
    keeps working unchanged. ``kind``/``selectors``/``resolved_targets``/
    ``included_targets``/``depth``/``scope_origin`` generalize the event to
    also describe a web or strand batch; for a single-note read they default
    to the note-only values below. For a batch, ``canonical_path`` and
    ``resolved_path`` fall back to the first resolved target so old
    consumers still show something reasonable rather than an empty field.
    """

    schema_version: int
    id: str
    timestamp: str
    project: str
    cwd: str
    canonical_path: str
    resolved_path: str
    agent_name: str
    agent_source: str
    artifacts_dir: str | None
    reason: str
    byte_count: int
    frontmatter_stripped: bool
    kind: MemoryReadKind = "note"
    selectors: tuple[str, ...] = ()
    resolved_targets: tuple[str, ...] = ()
    included_targets: tuple[str, ...] = ()
    depth: int | None = None
    scope_origin: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class MemoryReadPathSummary:
    canonical_path: str
    read_count: int
    distinct_agent_count: int
    last_read_at: str
    last_agent: str
    last_reason: str


@dataclass(frozen=True)
class MemoryReadAgentSummary:
    agent_name: str
    read_count: int
    distinct_path_count: int
    last_read_at: str
    last_path: str
    last_reason: str


def validate_memory_read_path(
    memory_relative_path: str | Path,
    *,
    project_root: Path | None = None,
    home_root: Path | None = None,
) -> ValidatedMemoryPath:
    """Validate and canonicalize a path relative to an allowed memory root."""
    raw_path = Path(memory_relative_path)
    if raw_path.is_absolute():
        raise MemoryReadPathError("memory read path must be relative to sase/memory/")

    parts = _normalize_memory_read_parts(raw_path)
    if not parts or parts == (".",):
        raise MemoryReadPathError("memory read path is required")
    if any(part in {"", ".", ".."} for part in parts):
        raise MemoryReadPathError("memory read path must not contain traversal")
    if Path(*parts).suffix != ".md":
        raise MemoryReadPathError("memory read path must point to a .md file")
    if not _is_flat_note_path(parts):
        raise MemoryReadPathError("memory read path must be a flat .md note name")

    for content_root, memory_root in _memory_read_roots(project_root, home_root):
        path = _validate_memory_read_candidate(
            content_root=content_root,
            memory_root=memory_root,
            parts=parts,
            raw_path=raw_path,
        )
        if path is not None:
            return path

    raise MemoryReadPathError(f"memory file does not exist: {raw_path.as_posix()}")


def _normalize_memory_read_parts(raw_path: Path) -> tuple[str, ...]:
    parts = raw_path.parts
    for prefix in (
        CANONICAL_MEMORY_RELATIVE_ROOT.parts,
        LEGACY_MEMORY_RELATIVE_ROOT.parts,
    ):
        if parts[: len(prefix)] == prefix:
            return parts[len(prefix) :]
    return parts


def _is_flat_note_path(parts: tuple[str, ...]) -> bool:
    return len(parts) == 1


def _memory_read_roots(
    project_root: Path | None,
    home_root: Path | None,
) -> tuple[tuple[Path, Path], ...]:
    root = (project_root or Path.cwd()).resolve(strict=False)
    content_roots = [root]

    if home_root is not None:
        resolved_home_root = home_root.expanduser().resolve(strict=False)
        if resolved_home_root != root:
            content_roots.append(resolved_home_root)

    roots: list[tuple[Path, Path]] = []
    for content_root in content_roots:
        try:
            selected = memory_read_root(
                content_root,
                label=f"memory for {content_root}",
            )
        except LayoutCollisionError as exc:
            raise MemoryReadPathError(str(exc)) from exc
        if selected is not None:
            roots.append((content_root, selected))
    return tuple(roots)


def _validate_memory_read_candidate(
    *,
    content_root: Path,
    memory_root: Path,
    parts: tuple[str, ...],
    raw_path: Path,
) -> ValidatedMemoryPath | None:
    allowed_root = memory_root.resolve(strict=False)
    candidate = memory_root.joinpath(*parts)

    try:
        resolved = candidate.resolve(strict=True)
    except FileNotFoundError as exc:
        if _has_broken_symlink_component(candidate, memory_root):
            raise MemoryReadPathError(
                f"memory file cannot be resolved: {raw_path.as_posix()}"
            ) from exc
        return None
    except OSError as exc:
        raise MemoryReadPathError(
            f"memory file cannot be resolved: {raw_path.as_posix()}"
        ) from exc

    if not candidate.is_file():
        raise MemoryReadPathError(f"memory path is not a file: {raw_path.as_posix()}")
    if not _is_relative_to(resolved, allowed_root):
        raise MemoryReadPathError(
            "memory file resolves outside the allowed sase/memory/ directory"
        )

    note = _read_validated_memory_note(
        memory_root=memory_root,
        path=candidate,
        raw_path=raw_path,
    )
    if note.is_web_descriptor:
        slug = Path(note.relative_path).stem
        raise MemoryReadPathError(
            f"{note.relative_path} is an always-loaded memory web descriptor; "
            f"read its strands with `sase memory read {slug}:<keyword>`"
        )
    if note.type == "core":
        raise MemoryReadPathError(
            f"{note.relative_path} is always-loaded context and cannot be read with this command"
        )
    if note.type != "reference":
        raise MemoryReadPathError(
            f"memory file is not a reference memory note: {note.relative_path}"
        )

    canonical_path = Path(*parts).as_posix()
    return ValidatedMemoryPath(
        memory_root=memory_root,
        allowed_root=allowed_root,
        canonical_path=canonical_path,
        path=candidate,
        resolved_path=resolved,
        note=note,
        content_root=content_root,
    )


def _read_validated_memory_note(
    *,
    memory_root: Path,
    path: Path,
    raw_path: Path,
) -> MemoryNote:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise MemoryReadPathError(
            f"memory file does not exist: {raw_path.as_posix()}"
        ) from exc
    relative = path.relative_to(memory_root)
    note = parse_memory_note_text(
        text,
        CANONICAL_MEMORY_RELATIVE_ROOT / relative,
    )
    return MemoryNote(
        path=note.path,
        type=note.type,
        parent=canonical_memory_reference(note.parent).as_posix(),
        description=note.description,
        body=note.body,
        frontmatter=note.frontmatter,
        type_source=note.type_source,
        parent_source=note.parent_source,
        source_path=None,
        priority=note.priority,
        priority_source=note.priority_source,
    )


def _has_broken_symlink_component(path: Path, root: Path) -> bool:
    current = root
    components = [current]
    for part in path.relative_to(root).parts:
        current = current / part
        components.append(current)

    for component in components:
        if not component.is_symlink():
            continue
        try:
            component.resolve(strict=True)
        except (FileNotFoundError, OSError, RuntimeError):
            return True
    return False


def read_memory_content(path: ValidatedMemoryPath) -> MemoryReadContent:
    """Read a validated memory file and strip leading YAML frontmatter."""
    raw_text = path.resolved_path.read_text(encoding="utf-8")
    stripped = strip_leading_frontmatter(raw_text)
    return MemoryReadContent(
        path=path,
        raw_text=raw_text,
        body=stripped.body,
        byte_count=len(raw_text.encode("utf-8")),
        frontmatter_stripped=stripped.stripped,
    )


def strip_leading_frontmatter(text: str) -> FrontmatterStripResult:
    """Remove one leading ``---`` frontmatter block, preserving body text."""
    lines = text.splitlines(keepends=True)
    if not lines or not _is_frontmatter_delimiter(lines[0]):
        return FrontmatterStripResult(body=text, stripped=False)

    for index, line in enumerate(lines[1:], start=1):
        if _is_frontmatter_delimiter(line):
            body_lines = lines[index + 1 :]
            if body_lines and not body_lines[0].strip():
                body_lines = body_lines[1:]
            return FrontmatterStripResult(
                body="".join(body_lines),
                stripped=True,
            )
    return FrontmatterStripResult(body=text, stripped=False)


def require_agent_identity(env: Mapping[str, str] | None = None) -> AgentIdentity:
    """Return the current agent identity or raise a clear auditability error."""
    return _require_agent_identity(env, purpose="memory reads")


def normalize_read_reason(reason: str) -> str:
    """Normalize and validate a read reason for audit logging."""
    normalized = reason.strip()
    if not normalized:
        raise MemoryReadError("memory read reason must not be empty")
    return normalized


def build_memory_read_event(
    content: MemoryReadContent,
    *,
    reason: str,
    agent: AgentIdentity,
    project: str | None = None,
    cwd: Path | None = None,
    now: datetime | None = None,
    read_id: str | None = None,
) -> MemoryReadEvent:
    """Build a structured log event for a validated memory read."""
    cwd_path = (cwd or Path.cwd()).resolve(strict=False)
    project_name = project or project_memory_name(cwd_path)
    timestamp = _event_timestamp(now or datetime.now(tz=UTC))
    return MemoryReadEvent(
        schema_version=READ_LOG_SCHEMA_VERSION,
        id=read_id or uuid4().hex[:12],
        timestamp=timestamp,
        project=project_name,
        cwd=str(cwd_path),
        canonical_path=content.path.canonical_path,
        resolved_path=str(content.path.resolved_path),
        agent_name=agent.name,
        agent_source=agent.source,
        artifacts_dir=agent.artifacts_dir,
        reason=normalize_read_reason(reason),
        byte_count=content.byte_count,
        frontmatter_stripped=content.frontmatter_stripped,
        kind="note",
        selectors=(content.path.canonical_path,),
        resolved_targets=(content.path.canonical_path,),
    )


def build_memory_read_batch_event(
    *,
    kind: MemoryReadKind,
    selectors: Sequence[str],
    resolved_targets: Sequence[str],
    byte_count: int,
    frontmatter_stripped: bool,
    reason: str,
    agent: AgentIdentity,
    included_targets: Sequence[str] = (),
    depth: int | None = None,
    scope_origin: Mapping[str, str] | Sequence[tuple[str, str]] = (),
    project: str | None = None,
    cwd: Path | None = None,
    now: datetime | None = None,
    read_id: str | None = None,
) -> MemoryReadEvent:
    """Build a structured log event for a resolved selector batch.

    Used for any read that is not a single note: a bare web, a strand
    selector, or a batch mixing more than one selector. ``canonical_path``
    falls back to the first resolved target for pre-web consumers;
    ``resolved_path`` has no single meaningful filesystem path for a batch,
    so it is left empty.
    """
    cwd_path = (cwd or Path.cwd()).resolve(strict=False)
    project_name = project or project_memory_name(cwd_path)
    timestamp = _event_timestamp(now or datetime.now(tz=UTC))
    resolved_list = tuple(resolved_targets)
    primary = resolved_list[0] if resolved_list else ""
    scope_pairs = (
        tuple(scope_origin.items())
        if isinstance(scope_origin, Mapping)
        else tuple(scope_origin)
    )
    return MemoryReadEvent(
        schema_version=READ_LOG_SCHEMA_VERSION,
        id=read_id or uuid4().hex[:12],
        timestamp=timestamp,
        project=project_name,
        cwd=str(cwd_path),
        canonical_path=primary,
        resolved_path="",
        agent_name=agent.name,
        agent_source=agent.source,
        artifacts_dir=agent.artifacts_dir,
        reason=normalize_read_reason(reason),
        byte_count=byte_count,
        frontmatter_stripped=frontmatter_stripped,
        kind=kind,
        selectors=tuple(selectors),
        resolved_targets=resolved_list,
        included_targets=tuple(included_targets),
        depth=depth,
        scope_origin=scope_pairs,
    )


def memory_read_log_path(
    project: str | None = None, *, cwd: Path | None = None
) -> Path:
    """Return the project-scoped memory-read JSONL path under ``~/.sase``."""
    project_name = resolve_project_alias_ref(
        project or project_memory_name(cwd or Path.cwd())
    )
    return sase_projects_dir() / project_name / "memory_reads.jsonl"


def append_memory_read_event(
    event: MemoryReadEvent,
    *,
    log_path: Path | None = None,
) -> None:
    """Append one memory-read event under an exclusive file lock."""
    path = log_path or memory_read_log_path(event.project)
    path.parent.mkdir(parents=True, exist_ok=True)
    with locked_file(path.with_suffix(".lock"), fcntl.LOCK_EX):
        with path.open("a", encoding="utf-8") as output_file:
            json.dump(asdict(event), output_file, sort_keys=True)
            output_file.write("\n")
            output_file.flush()


def read_memory_read_events(
    *,
    project: str | None = None,
    log_path: Path | None = None,
) -> tuple[MemoryReadEvent, ...]:
    """Read memory-read events, skipping malformed JSONL rows."""
    path = log_path or memory_read_log_path(project)
    with locked_file(path.with_suffix(".lock"), fcntl.LOCK_SH):
        if not path.exists():
            return ()
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return ()

    events: list[MemoryReadEvent] = []
    for line in lines:
        if not line.strip():
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict):
            continue
        event = _event_from_mapping(data)
        if event is not None:
            events.append(event)
    return tuple(events)


def filter_memory_read_events(
    events: Iterable[MemoryReadEvent],
    *,
    canonical_path: str | None = None,
    agent_name: str | None = None,
) -> tuple[MemoryReadEvent, ...]:
    """Filter read events by canonical memory path/web/strand target and/or agent.

    ``canonical_path`` matches either the legacy single-path field or
    membership in ``resolved_targets``, so ``--path glossary:stitch`` finds a
    strand read the same way ``--path foo.md`` finds a note read.
    """
    path_filter = canonical_path.strip() if canonical_path else None
    agent_filter = agent_name.strip() if agent_name else None
    return tuple(
        event
        for event in events
        if (
            path_filter is None
            or event.canonical_path == path_filter
            or path_filter in event.resolved_targets
        )
        and (agent_filter is None or event.agent_name == agent_filter)
    )


def summarize_memory_reads_by_path(
    events: Iterable[MemoryReadEvent],
) -> tuple[MemoryReadPathSummary, ...]:
    """Aggregate read counts and latest-read context by canonical memory path."""
    grouped: dict[str, list[MemoryReadEvent]] = {}
    for event in events:
        grouped.setdefault(event.canonical_path, []).append(event)

    summaries = [
        MemoryReadPathSummary(
            canonical_path=path,
            read_count=len(path_events),
            distinct_agent_count=len({event.agent_name for event in path_events}),
            last_read_at=_latest_event(path_events).timestamp,
            last_agent=_latest_event(path_events).agent_name,
            last_reason=_latest_event(path_events).reason,
        )
        for path, path_events in grouped.items()
    ]
    return tuple(sorted(summaries, key=lambda summary: summary.canonical_path))


def summarize_memory_reads_by_agent(
    events: Iterable[MemoryReadEvent],
) -> tuple[MemoryReadAgentSummary, ...]:
    """Aggregate read counts and latest-read context by agent name."""
    grouped: dict[str, list[MemoryReadEvent]] = {}
    for event in events:
        grouped.setdefault(event.agent_name, []).append(event)

    summaries = [
        MemoryReadAgentSummary(
            agent_name=agent_name,
            read_count=len(agent_events),
            distinct_path_count=len({event.canonical_path for event in agent_events}),
            last_read_at=_latest_event(agent_events).timestamp,
            last_path=_latest_event(agent_events).canonical_path,
            last_reason=_latest_event(agent_events).reason,
        )
        for agent_name, agent_events in grouped.items()
    ]
    return tuple(sorted(summaries, key=lambda summary: summary.agent_name))


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _is_frontmatter_delimiter(line: str) -> bool:
    return line.strip() == "---"


def _event_timestamp(now: datetime) -> str:
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    return now.astimezone(UTC).isoformat()


_VALID_SCHEMA_VERSIONS = frozenset({1, 2})
_VALID_KINDS = frozenset({"note", "web", "strand"})


def _event_from_mapping(data: Mapping[str, Any]) -> MemoryReadEvent | None:
    """Parse one JSONL row, accepting both the v1 and v2 event shapes.

    v1 rows (pre-web, ``schema_version: 1``) never had ``kind``/
    ``selectors``/etc.; they are upgraded in place to the note-only defaults
    so every reader can treat the log as one uniform sequence.
    """
    schema_version = data.get("schema_version")
    if schema_version not in _VALID_SCHEMA_VERSIONS:
        return None
    required_strings = (
        "id",
        "timestamp",
        "project",
        "cwd",
        "canonical_path",
        "resolved_path",
        "agent_name",
        "agent_source",
        "reason",
    )
    for key in required_strings:
        if not isinstance(data.get(key), str):
            return None
    if not isinstance(data.get("byte_count"), int):
        return None
    if not isinstance(data.get("frontmatter_stripped"), bool):
        return None
    artifacts_dir = data.get("artifacts_dir")
    if artifacts_dir is not None and not isinstance(artifacts_dir, str):
        return None

    kind = data.get("kind", "note")
    if kind not in _VALID_KINDS:
        return None
    canonical_path = data["canonical_path"]
    selectors = _string_tuple(data.get("selectors"), default=(canonical_path,))
    resolved_targets = _string_tuple(
        data.get("resolved_targets"), default=(canonical_path,)
    )
    included_targets = _string_tuple(data.get("included_targets"), default=())
    if selectors is None or resolved_targets is None or included_targets is None:
        return None
    depth = data.get("depth")
    if depth is not None and not isinstance(depth, int):
        return None
    scope_origin = _scope_origin_tuple(data.get("scope_origin"))
    if scope_origin is None:
        return None

    return MemoryReadEvent(
        schema_version=schema_version,
        id=data["id"],
        timestamp=data["timestamp"],
        project=data["project"],
        cwd=data["cwd"],
        canonical_path=canonical_path,
        resolved_path=data["resolved_path"],
        agent_name=data["agent_name"],
        agent_source=data["agent_source"],
        artifacts_dir=artifacts_dir,
        reason=data["reason"],
        byte_count=data["byte_count"],
        frontmatter_stripped=data["frontmatter_stripped"],
        kind=kind,
        selectors=selectors,
        resolved_targets=resolved_targets,
        included_targets=included_targets,
        depth=depth,
        scope_origin=scope_origin,
    )


def _string_tuple(value: Any, *, default: tuple[str, ...]) -> tuple[str, ...] | None:
    if value is None:
        return default
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        return None
    return tuple(value)


def _scope_origin_tuple(value: Any) -> tuple[tuple[str, str], ...] | None:
    if value is None:
        return ()
    if not isinstance(value, list):
        return None
    pairs: list[tuple[str, str]] = []
    for item in value:
        if (
            not isinstance(item, list)
            or len(item) != 2
            or not all(isinstance(part, str) for part in item)
        ):
            return None
        pairs.append((item[0], item[1]))
    return tuple(pairs)


def _latest_event(events: list[MemoryReadEvent]) -> MemoryReadEvent:
    return max(events, key=lambda event: event.timestamp)
