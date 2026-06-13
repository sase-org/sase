"""Read normalized tool-call artifacts for TUI display.

Tool-call data is read from SASE-owned per-run artifacts. New provider runs
write normalized stream-backed rows to ``tool_calls.jsonl`` as the cross-runtime
contract. Claude schema-v3 hook rows from older runs remain readable for
backward compatibility. If a historical mixed file contains both stream and
hook rows for the same ``tool_use_id``, the hook rows are kept as a legacy
de-duplication rule so old timelines do not double-count one tool call.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sase.ace.tui.models.agent import Agent

TOOL_CALLS_FILENAME = "tool_calls.jsonl"
SUPPORTED_SCHEMA_VERSIONS = frozenset({1, 2, 3})
KNOWN_STATUSES = frozenset({"success", "failure", "interrupted", "subagent", "pending"})
LINEAGE_METADATA_KEYS = (
    "parent_timestamp",
    "retry_of_timestamp",
    "retried_as_timestamp",
    "retry_chain_root_timestamp",
)
_MAX_RELATED_ARTIFACT_DIRS = 128
_MAX_RELATED_FALLBACK_SIBLINGS = 128


@dataclass(frozen=True)
class ToolCallEntry:
    """One normalized tool-call artifact record, with TUI display helpers."""

    recorded_at: str
    runtime: str
    event: str
    status: str
    tool_name: str | None = None
    tool_use_id: str | None = None
    duration_ms: int | None = None
    tool_input_summary: Mapping[str, Any] = field(default_factory=dict)
    tool_response_summary: Mapping[str, Any] = field(default_factory=dict)
    session_id: str | None = None
    transcript_path: str | None = None
    cwd: str | None = None
    permission_mode: str | None = None
    agent_id: str | None = None
    agent_type: str | None = None
    parent_tool_use_id: str | None = None
    error: str | None = None
    is_interrupt: bool = False
    source: str | None = None
    artifact_dir: str | None = None
    source_path: str | None = None
    line_number: int = 0
    _recorded_at_sort: datetime = field(
        default=datetime.max.replace(tzinfo=UTC), compare=False, repr=False
    )
    _file_order: int = field(default=0, compare=False, repr=False)

    @property
    def display_tool_name(self) -> str:
        """Return a stable label for unknown tools and subagent events."""
        if self.tool_name:
            return self.tool_name
        if self.event in {"SubagentStart", "SubagentStop"}:
            return self.event
        return self.event or "unknown"

    @property
    def compact_target(self) -> str:
        """Best-effort target summary for one-line timeline rows."""
        return _compact_tool_target(
            self.tool_name,
            self.tool_input_summary,
            self.tool_response_summary,
        )

    @property
    def detail(self) -> str:
        """Best-effort one-line detail derived from input/response summaries."""
        return _tool_call_detail(
            self.tool_name,
            self.tool_input_summary,
            self.tool_response_summary,
            error=self.error,
        )


def read_tool_calls_for_agent(
    agent: Agent,
    *,
    artifact_dirs: Sequence[Path | str] | None = None,
) -> list[ToolCallEntry] | None:
    """Return tool calls for *agent*.

    Returns ``None`` when no relevant ``tool_calls.jsonl`` exists, and ``[]``
    when one or more artifacts exist but contain no usable records.
    """
    get_artifacts_dir = getattr(agent, "get_artifacts_dir", None)
    if not callable(get_artifacts_dir):
        return None

    artifacts_dir = get_artifacts_dir()
    if not artifacts_dir:
        return None

    current = Path(artifacts_dir).expanduser()
    related_dirs = (
        discover_related_tool_artifact_dirs(agent, current)
        if artifact_dirs is None
        else _dedupe_artifact_dirs(artifact_dirs, current=current)
    )
    paths = [path / TOOL_CALLS_FILENAME for path in related_dirs]
    existing_paths = [path for path in paths if path.is_file()]
    if not existing_paths:
        return None

    entries: list[ToolCallEntry] = []
    file_order = 0
    for artifact_dir in related_dirs:
        path = artifact_dir / TOOL_CALLS_FILENAME
        if not path.is_file():
            continue
        entries.extend(_read_tool_call_file(path, artifact_dir, file_order))
        file_order += 1

    entries.sort(
        key=lambda entry: (
            entry._recorded_at_sort,
            entry._file_order,
            entry.line_number,
            entry.tool_use_id or "",
        )
    )
    entries = _prefer_hook_records(entries)
    return _collapse_tool_use_pairs(entries)


def discover_related_tool_artifact_dirs(
    agent: Agent,
    artifacts_dir: str | Path,
) -> list[Path]:
    """Discover artifact directories for one logical agent lineage.

    The current directory is always first. Index-backed discovery follows
    explicit lineage pointers in ``sase-core``. If the index is missing or
    stale, the filesystem fallback follows direct pointers and scans only a
    small bounded prefix of legacy siblings.
    """
    current = Path(artifacts_dir).expanduser()
    current_meta = _combined_artifact_metadata(current)
    root_ids = _agent_root_ids(agent, current, current_meta)

    indexed_dirs = _discover_related_tool_artifact_dirs_from_index(current, root_ids)
    if indexed_dirs:
        return _dedupe_artifact_dirs(indexed_dirs, current=current)

    direct_dirs = _discover_related_tool_artifact_dirs_direct(
        agent,
        current,
        current_meta,
    )
    scanned_dirs = _discover_related_tool_artifact_dirs_bounded_scan(
        current,
        root_ids,
    )
    return _dedupe_artifact_dirs(
        [*direct_dirs, *scanned_dirs],
        current=current,
    )


def _discover_related_tool_artifact_dirs_from_index(
    current: Path,
    root_ids: set[str],
) -> list[Path]:
    try:
        from sase.core.agent_scan_facade import (
            default_agent_artifact_index_path,
            query_related_agent_artifact_dirs,
        )
    except ImportError:
        return []

    index_path = default_agent_artifact_index_path()
    if not index_path.is_file():
        return []
    try:
        return query_related_agent_artifact_dirs(
            index_path,
            current,
            sorted(root_ids),
        )
    except (AttributeError, ImportError, OSError, RuntimeError, ValueError):
        return []


def _discover_related_tool_artifact_dirs_direct(
    agent: Agent,
    current: Path,
    current_meta: Mapping[str, Any],
) -> list[Path]:
    related: list[Path] = []
    queue: list[Path] = [current]
    queue.extend(_related_agent_artifact_dirs(agent))
    queue.extend(
        current.parent / timestamp
        for timestamp in _lineage_timestamps_for_agent(agent, current, current_meta)
    )
    seen: set[Path] = set()

    while queue and len(related) < _MAX_RELATED_ARTIFACT_DIRS:
        path = queue.pop(0).expanduser()
        if path.parent != current.parent:
            continue
        key = _path_identity(path)
        if key in seen:
            continue
        seen.add(key)
        if not path.is_dir():
            continue
        related.append(path)

        metadata = (
            current_meta
            if key == _path_identity(current)
            else (_combined_artifact_metadata(path))
        )
        queue.extend(
            path.parent / timestamp
            for timestamp in _metadata_lineage_timestamps(metadata)
        )

    return related


def _discover_related_tool_artifact_dirs_bounded_scan(
    current: Path,
    root_ids: set[str],
) -> list[Path]:
    if not root_ids:
        return []

    related: list[Path] = []
    scanned_dirs = 0
    try:
        siblings = current.parent.iterdir()
    except OSError:
        return []

    for sibling in siblings:
        if scanned_dirs >= _MAX_RELATED_FALLBACK_SIBLINGS:
            break
        if sibling == current:
            continue
        try:
            is_dir = sibling.is_dir()
        except OSError:
            continue
        if not is_dir:
            continue
        scanned_dirs += 1
        if _artifact_dir_matches_roots(sibling, root_ids):
            related.append(sibling)
    return related


def discover_related_tool_artifact_dirs_cached(
    agent: Agent,
    artifacts_dir: str | Path,
    *,
    cached_dirs: list[Path] | None = None,
    cached_parent_mtime_ns: int = 0,
) -> tuple[list[Path], int]:
    """Discover artifact directories, reusing a prior result when possible.

    Returns ``(dirs, parent_mtime_ns)``. When the parent directory's mtime
    matches ``cached_parent_mtime_ns`` and ``cached_dirs`` is non-empty, returns
    ``cached_dirs`` without re-walking the parent or re-reading sibling
    metadata. Otherwise re-runs :func:`discover_related_tool_artifact_dirs`.
    """
    current = Path(artifacts_dir).expanduser()
    parent = current.parent
    try:
        parent_mtime_ns = parent.stat().st_mtime_ns
    except OSError:
        return [current], 0

    if (
        cached_dirs
        and cached_parent_mtime_ns
        and parent_mtime_ns == cached_parent_mtime_ns
    ):
        return cached_dirs, parent_mtime_ns

    return discover_related_tool_artifact_dirs(agent, artifacts_dir), parent_mtime_ns


def derive_tool_call_status(record: Mapping[str, Any]) -> str:
    """Derive a known display status from a normalized artifact record."""
    raw_status = record.get("status")
    if isinstance(raw_status, str):
        normalized_status = raw_status.lower()
        if normalized_status in KNOWN_STATUSES:
            return normalized_status
        if normalized_status in {"failed", "error"}:
            return "failure"
        if normalized_status in {"cancelled", "canceled"}:
            return "interrupted"
        if normalized_status in {"in_progress", "running"}:
            return "pending"

    if record.get("is_interrupt") is True:
        return "interrupted"

    event = record.get("event")
    if event == "PostToolUseFailure":
        return "failure"
    if event in {"SubagentStart", "SubagentStop"}:
        return "subagent"
    if event == "ToolUse":
        return "pending"

    response = record.get("tool_response_summary")
    if isinstance(response, Mapping):
        if response.get("interrupted") is True:
            return "interrupted"
        if (
            response.get("success") is False
            or response.get("is_error") is True
            or response.get("error")
        ):
            return "failure"

    return "success"


def _prefer_hook_records(entries: list[ToolCallEntry]) -> list[ToolCallEntry]:
    """Drop stream rows when an old hook row exists for the same call.

    New artifacts should not mix Claude stream and hook collection. This rule
    is retained for historical runs created while Claude hook collection was
    enabled, where both sources could describe one logical ``tool_use_id``.
    """
    hook_ids = {
        (entry.runtime, entry.tool_use_id)
        for entry in entries
        if entry.source == "hook" and entry.tool_use_id
    }
    if not hook_ids:
        return entries
    return [
        entry
        for entry in entries
        if (entry.runtime, entry.tool_use_id) not in hook_ids or entry.source == "hook"
    ]


def _collapse_tool_use_pairs(
    entries: list[ToolCallEntry],
) -> list[ToolCallEntry]:
    """Merge ``ToolUse`` + ``ToolResult`` pairs with matching ``tool_use_id``.

    Orphan ``ToolUse`` rows (no result yet) are kept with status ``pending``.
    Other event types (``PostToolUse``, ``SubagentStart``, etc.) pass through
    unchanged. Schema-v1 records are returned as-is for back-compat.
    """
    starts_by_id: dict[tuple[str, str, str], int] = {}
    merged: list[ToolCallEntry | None] = list(entries)

    for index, entry in enumerate(entries):
        if entry.event == "ToolUse" and entry.tool_use_id:
            starts_by_id[_tool_pair_key(entry)] = index
            continue
        if entry.event == "ToolResult" and entry.tool_use_id:
            start_index = starts_by_id.pop(_tool_pair_key(entry), None)
            if start_index is None:
                continue
            start_entry = merged[start_index]
            if start_entry is None:
                continue
            merged[start_index] = _merge_use_and_result(start_entry, entry)
            merged[index] = None

    return [entry for entry in merged if entry is not None]


def _tool_pair_key(entry: ToolCallEntry) -> tuple[str, str, str]:
    """Return the scope in which a provider tool-use id is unique."""
    scope = entry.session_id or entry.artifact_dir or ""
    return entry.runtime, entry.tool_use_id or "", scope


def _merge_use_and_result(start: ToolCallEntry, end: ToolCallEntry) -> ToolCallEntry:
    """Combine a ``ToolUse`` start entry with its matching ``ToolResult`` end."""
    response_summary: Mapping[str, Any] = end.tool_response_summary
    return ToolCallEntry(
        recorded_at=start.recorded_at,
        runtime=start.runtime,
        event="ToolUse",
        status=end.status if end.status in KNOWN_STATUSES else start.status,
        tool_name=start.tool_name or end.tool_name,
        tool_use_id=start.tool_use_id,
        duration_ms=start.duration_ms or end.duration_ms,
        tool_input_summary=start.tool_input_summary or end.tool_input_summary,
        tool_response_summary=response_summary,
        session_id=start.session_id or end.session_id,
        transcript_path=start.transcript_path or end.transcript_path,
        cwd=start.cwd or end.cwd,
        permission_mode=start.permission_mode or end.permission_mode,
        agent_id=start.agent_id or end.agent_id,
        agent_type=start.agent_type or end.agent_type,
        parent_tool_use_id=start.parent_tool_use_id or end.parent_tool_use_id,
        error=start.error or end.error,
        is_interrupt=start.is_interrupt or end.is_interrupt,
        source=start.source or end.source,
        artifact_dir=start.artifact_dir,
        source_path=start.source_path,
        line_number=start.line_number,
        _recorded_at_sort=start._recorded_at_sort,
        _file_order=start._file_order,
    )


def _compact_tool_target(
    tool_name: str | None,
    tool_input_summary: Mapping[str, Any],
    tool_response_summary: Mapping[str, Any],
) -> str:
    """Return a compact target string for common tools."""
    del tool_response_summary
    for key in ("file_path", "path", "url", "query", "pattern", "description"):
        value = tool_input_summary.get(key)
        if isinstance(value, str) and value:
            return _one_line(value, 96)

    command = tool_input_summary.get("command")
    if isinstance(command, str) and command:
        return _one_line(command, 96)

    subagent_type = tool_input_summary.get("subagent_type")
    if isinstance(subagent_type, str) and subagent_type:
        return subagent_type

    if tool_name:
        return ""
    input_keys = tool_input_summary.get("input_keys")
    if isinstance(input_keys, list) and input_keys:
        return ", ".join(str(key) for key in input_keys[:4])
    return ""


def _tool_call_detail(
    tool_name: str | None,
    tool_input_summary: Mapping[str, Any],
    tool_response_summary: Mapping[str, Any],
    *,
    error: str | None = None,
) -> str:
    """Return a bounded one-line detail string for a timeline row."""
    if error:
        return _one_line(error, 140)

    response_error = tool_response_summary.get("error")
    if isinstance(response_error, str) and response_error:
        return _one_line(response_error, 140)

    parts: list[str] = []
    if tool_name == "Bash":
        exit_code = tool_response_summary.get("exit_code")
        if isinstance(exit_code, int):
            parts.append(f"exit {exit_code}")
    for key in (
        "stdout_preview",
        "stderr_preview",
        "output_preview",
        "content_preview",
        "result_preview",
        "preview",
    ):
        value = tool_response_summary.get(key)
        if isinstance(value, str) and value:
            parts.append(_one_line(value, 120))
            break

    if not parts:
        for key in ("content_length", "old_string_length", "new_string_length"):
            value = tool_input_summary.get(key)
            if isinstance(value, int):
                parts.append(f"{key}={value}")
        edits = tool_input_summary.get("edits_count")
        if isinstance(edits, int):
            parts.append(f"edits={edits}")

    if not parts:
        keys = tool_response_summary.get("response_keys")
        if isinstance(keys, list) and keys:
            parts.append("response: " + ", ".join(str(key) for key in keys[:4]))

    return " | ".join(parts)


def _read_tool_call_file(
    path: Path,
    artifact_dir: Path,
    file_order: int,
) -> list[ToolCallEntry]:
    entries: list[ToolCallEntry] = []
    try:
        with open(path, encoding="utf-8") as f:
            for line_number, line in enumerate(f, start=1):
                entry = _parse_tool_call_line(
                    line,
                    artifact_dir=artifact_dir,
                    source_path=path,
                    line_number=line_number,
                    file_order=file_order,
                )
                if entry is not None:
                    entries.append(entry)
    except OSError:
        return []
    return entries


def _parse_tool_call_line(
    line: str,
    *,
    artifact_dir: Path,
    source_path: Path,
    line_number: int,
    file_order: int,
) -> ToolCallEntry | None:
    try:
        record = json.loads(line)
    except json.JSONDecodeError:
        return None

    if not isinstance(record, Mapping):
        return None
    if record.get("schema_version") not in SUPPORTED_SCHEMA_VERSIONS:
        return None

    input_summary = _mapping_or_empty(record.get("tool_input_summary"))
    response_summary = _mapping_or_empty(record.get("tool_response_summary"))
    recorded_at = _str_or_empty(record.get("recorded_at"))
    return ToolCallEntry(
        recorded_at=recorded_at,
        runtime=_str_or_default(record.get("runtime"), "unknown"),
        event=_str_or_default(record.get("event"), "unknown"),
        status=derive_tool_call_status(record),
        tool_name=_str_or_none(record.get("tool_name")),
        tool_use_id=_str_or_none(record.get("tool_use_id")),
        duration_ms=_int_or_none(record.get("duration_ms")),
        tool_input_summary=input_summary,
        tool_response_summary=response_summary,
        session_id=_str_or_none(record.get("session_id")),
        transcript_path=_str_or_none(record.get("transcript_path")),
        cwd=_str_or_none(record.get("cwd")),
        permission_mode=_str_or_none(record.get("permission_mode")),
        agent_id=_str_or_none(record.get("agent_id")),
        agent_type=_str_or_none(record.get("agent_type")),
        parent_tool_use_id=_str_or_none(record.get("parent_tool_use_id")),
        error=_str_or_none(record.get("error")),
        is_interrupt=record.get("is_interrupt") is True,
        source=_str_or_none(record.get("source")),
        artifact_dir=str(artifact_dir),
        source_path=str(source_path),
        line_number=line_number,
        _recorded_at_sort=_parse_recorded_at(recorded_at),
        _file_order=file_order,
    )


def _dedupe_artifact_dirs(
    artifact_dirs: Iterable[Path | str],
    *,
    current: Path,
) -> list[Path]:
    seen: set[Path] = set()
    result: list[Path] = []
    for raw_path in (current, *artifact_dirs):
        path = Path(raw_path).expanduser()
        key = _path_identity(path)
        if key in seen:
            continue
        seen.add(key)
        result.append(path)
    if not result:
        return [current]
    head = result[0]
    tail = sorted(result[1:], key=lambda path: path.name)
    return [head, *tail]


def _path_identity(path: Path) -> Path:
    try:
        return path.resolve(strict=False)
    except OSError:
        return path.absolute()


def _related_agent_artifact_dirs(agent: Agent) -> list[Path]:
    related: list[Path] = []
    queue: list[Any] = [
        *list(getattr(agent, "followup_agents", []) or []),
        *list(getattr(agent, "retry_chain_siblings", []) or []),
    ]
    seen: set[int] = set()
    while queue and len(related) < _MAX_RELATED_ARTIFACT_DIRS:
        candidate = queue.pop(0)
        identity = id(candidate)
        if identity in seen:
            continue
        seen.add(identity)
        get_artifacts_dir = getattr(candidate, "get_artifacts_dir", None)
        if callable(get_artifacts_dir):
            artifacts_dir = get_artifacts_dir()
            if isinstance(artifacts_dir, (str, Path)) and artifacts_dir:
                related.append(Path(artifacts_dir).expanduser())
        queue.extend(getattr(candidate, "followup_agents", []) or [])
        queue.extend(getattr(candidate, "retry_chain_siblings", []) or [])
    return related


def _lineage_timestamps_for_agent(
    agent: Agent,
    current: Path,
    current_meta: Mapping[str, Any],
) -> set[str]:
    timestamps = {
        current.name,
        *_metadata_lineage_timestamps(current_meta),
    }
    for field_name in LINEAGE_METADATA_KEYS:
        value = getattr(agent, field_name, None)
        if isinstance(value, str) and value:
            timestamps.add(value)
    return timestamps


def _metadata_lineage_timestamps(metadata: Mapping[str, Any]) -> set[str]:
    timestamps: set[str] = set()
    for key in LINEAGE_METADATA_KEYS:
        value = metadata.get(key)
        if isinstance(value, str) and value:
            timestamps.add(value)
    return timestamps


def _agent_root_ids(
    agent: Agent,
    current: Path,
    current_meta: Mapping[str, Any] | None = None,
) -> set[str]:
    root_ids: set[str] = set()
    for value in (
        getattr(agent, "retry_chain_root_timestamp", None),
        getattr(agent, "retry_of_timestamp", None),
        getattr(agent, "retried_as_timestamp", None),
        getattr(agent, "parent_timestamp", None),
        current.name,
    ):
        if isinstance(value, str) and value:
            root_ids.add(value)

    if current_meta is None:
        current_meta = _combined_artifact_metadata(current)
    for key in LINEAGE_METADATA_KEYS:
        value = current_meta.get(key)
        if isinstance(value, str) and value:
            root_ids.add(value)
    return root_ids


def _artifact_dir_matches_roots(path: Path, root_ids: set[str]) -> bool:
    if path.name in root_ids:
        return True
    metadata = _combined_artifact_metadata(path)
    for key in LINEAGE_METADATA_KEYS:
        value = metadata.get(key)
        if isinstance(value, str) and value in root_ids:
            return True
    return False


def _combined_artifact_metadata(path: Path) -> dict[str, Any]:
    data: dict[str, Any] = {}
    for filename in ("agent_meta.json", "done.json"):
        loaded = _read_json_object(path / filename)
        if loaded:
            data.update(loaded)
    return data


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return dict(data) if isinstance(data, Mapping) else {}


def _mapping_or_empty(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _parse_recorded_at(value: str) -> datetime:
    if not value:
        return datetime.max.replace(tzinfo=UTC)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return datetime.max.replace(tzinfo=UTC)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _str_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _str_or_empty(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _str_or_default(value: Any, default: str) -> str:
    return value if isinstance(value, str) and value else default


def _int_or_none(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return None


def _one_line(value: str, limit: int) -> str:
    text = " ".join(value.replace("\r\n", "\n").replace("\r", "\n").splitlines())
    if len(text) <= limit:
        return text
    return text[:limit] + f"...[{len(text) - limit} more]"
