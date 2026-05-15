"""Read normalized tool-call artifacts for TUI display.

Tool-call data is read from SASE-owned per-run artifacts. For Claude these are
written hook-first by the SASE ``PreToolUse``/``PostToolUse`` collector
(schema v3) when SASE manages the agent workspace; the existing stream-json
parser (schema v1/v2) remains as a fallback when hooks aren't installed and
for back-compat with older artifact runs. When both sources have produced
records for the same ``tool_use_id``, hook records win — they carry richer
fields (``cwd``/``transcript_path``/``permission_mode`` and durations).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sase.ace.tui.models.agent import Agent

TOOL_CALLS_FILENAME = "tool_calls.jsonl"
SUPPORTED_SCHEMA_VERSIONS = frozenset({1, 2, 3})
KNOWN_STATUSES = frozenset({"success", "failure", "interrupted", "subagent", "pending"})


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


def read_tool_calls_for_agent(agent: Agent) -> list[ToolCallEntry] | None:
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

    artifact_dirs = discover_related_tool_artifact_dirs(agent, artifacts_dir)
    paths = [path / TOOL_CALLS_FILENAME for path in artifact_dirs]
    existing_paths = [path for path in paths if path.is_file()]
    if not existing_paths:
        return None

    entries: list[ToolCallEntry] = []
    file_order = 0
    for artifact_dir in artifact_dirs:
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

    The current directory is always first. Siblings are included only when
    their ``agent_meta.json`` or ``done.json`` explicitly points at the same
    parent or retry-chain root timestamp.
    """
    current = Path(artifacts_dir).expanduser()
    result: list[Path] = [current]
    root_ids = _agent_root_ids(agent, current)
    if not root_ids:
        return result

    parent = current.parent
    try:
        siblings = sorted(parent.iterdir(), key=lambda path: path.name)
    except OSError:
        return result

    seen = {current.resolve(strict=False)}
    for sibling in siblings:
        if sibling == current or not sibling.is_dir():
            continue
        resolved = sibling.resolve(strict=False)
        if resolved in seen:
            continue
        if _artifact_dir_matches_roots(sibling, root_ids):
            result.append(sibling)
            seen.add(resolved)
    return result


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
    if isinstance(raw_status, str) and raw_status in KNOWN_STATUSES:
        return raw_status

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
    """Drop stream-derived rows when a hook record exists for the same call.

    Hook records (``source == "hook"``, schema v3) carry richer fields than
    stream-derived rows for the same ``tool_use_id``: the canonical
    ``cwd``/``transcript_path``/``permission_mode`` strings, an exact
    ``duration_ms`` for ``PostToolUse``, and Claude's authoritative status
    derivation. When both sources are present for the same logical tool call,
    keep only the hook entries so the timeline is not double-counted.
    """
    hook_ids = {
        entry.tool_use_id
        for entry in entries
        if entry.source == "hook" and entry.tool_use_id
    }
    if not hook_ids:
        return entries
    return [
        entry
        for entry in entries
        if entry.tool_use_id not in hook_ids or entry.source == "hook"
    ]


def _collapse_tool_use_pairs(
    entries: list[ToolCallEntry],
) -> list[ToolCallEntry]:
    """Merge ``ToolUse`` + ``ToolResult`` pairs with matching ``tool_use_id``.

    Orphan ``ToolUse`` rows (no result yet) are kept with status ``pending``.
    Other event types (``PostToolUse``, ``SubagentStart``, etc.) pass through
    unchanged. Schema-v1 records are returned as-is for back-compat.
    """
    starts_by_id: dict[str, int] = {}
    merged: list[ToolCallEntry | None] = list(entries)

    for index, entry in enumerate(entries):
        if entry.event == "ToolUse" and entry.tool_use_id:
            starts_by_id[entry.tool_use_id] = index
            continue
        if entry.event == "ToolResult" and entry.tool_use_id:
            start_index = starts_by_id.pop(entry.tool_use_id, None)
            if start_index is None:
                continue
            start_entry = merged[start_index]
            if start_entry is None:
                continue
            merged[start_index] = _merge_use_and_result(start_entry, entry)
            merged[index] = None

    return [entry for entry in merged if entry is not None]


def _merge_use_and_result(start: ToolCallEntry, end: ToolCallEntry) -> ToolCallEntry:
    """Combine a ``ToolUse`` start entry with its matching ``ToolResult`` end."""
    response_summary: Mapping[str, Any] = end.tool_response_summary
    return ToolCallEntry(
        recorded_at=start.recorded_at,
        runtime=start.runtime,
        event="ToolUse",
        status=end.status if end.status in KNOWN_STATUSES else start.status,
        tool_name=start.tool_name,
        tool_use_id=start.tool_use_id,
        duration_ms=start.duration_ms or end.duration_ms,
        tool_input_summary=start.tool_input_summary,
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


def _agent_root_ids(agent: Agent, current: Path) -> set[str]:
    root_ids: set[str] = set()
    for value in (
        getattr(agent, "retry_chain_root_timestamp", None),
        getattr(agent, "parent_timestamp", None),
        current.name,
    ):
        if isinstance(value, str) and value:
            root_ids.add(value)

    current_meta = _combined_artifact_metadata(current)
    for key in (
        "retry_chain_root_timestamp",
        "retry_of_timestamp",
        "parent_timestamp",
    ):
        value = current_meta.get(key)
        if isinstance(value, str) and value:
            root_ids.add(value)
    return root_ids


def _artifact_dir_matches_roots(path: Path, root_ids: set[str]) -> bool:
    if path.name in root_ids:
        return True
    metadata = _combined_artifact_metadata(path)
    for key in (
        "retry_chain_root_timestamp",
        "retry_of_timestamp",
        "parent_timestamp",
    ):
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
