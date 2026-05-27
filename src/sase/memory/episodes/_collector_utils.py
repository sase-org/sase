"""Shared low-level helpers for episode collection."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sase.core.agent_scan_wire import AgentArtifactRecordWire
from sase.history.chat import resolve_chat_file_path
from sase.memory.episodes.source_refs import normalize_source_path


def iter_project_files(projects_root: Path) -> Iterator[Path]:
    if not projects_root.is_dir():
        return
    seen: set[str] = set()
    for pattern in ("*.sase", "*.gp", "*-archive.sase", "*-archive.gp"):
        for path in sorted(projects_root.glob(f"*/{pattern}")):
            key = normalize_source_path(path)
            if key not in seen and path.is_file():
                seen.add(key)
                yield path


def resolve_chat_selector(chat: str | Path) -> str:
    chat_text = str(chat)
    if chat_text.startswith("~") or chat_text.startswith("/") or "/" in chat_text:
        return normalize_source_path(chat_text)
    resolved = resolve_chat_file_path(chat_text)
    if resolved is not None:
        return normalize_source_path(resolved)
    if not chat_text.endswith(".md"):
        resolved_md = resolve_chat_file_path(f"{chat_text}.md")
        if resolved_md is not None:
            return normalize_source_path(resolved_md)
    return normalize_source_path(chat_text)


def timestamp_in_range(
    timestamp: str,
    *,
    since: str | None,
    until: str | None,
) -> bool:
    comparable = compact_timestamp(timestamp)
    if since is not None and comparable < _range_bound(since, end=False):
        return False
    if until is not None and comparable > _range_bound(until, end=True):
        return False
    return True


def _range_bound(value: str, *, end: bool) -> str:
    stripped = value.strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", stripped):
        suffix = "235959" if end else "000000"
        return stripped.replace("-", "") + suffix
    return compact_timestamp(stripped)


def compact_timestamp(value: str) -> str:
    stripped = value.strip()
    if re.fullmatch(r"\d{14}", stripped):
        return stripped
    if re.fullmatch(r"\d{6}_\d{6}", stripped):
        try:
            return datetime.strptime(stripped, "%y%m%d_%H%M%S").strftime("%Y%m%d%H%M%S")
        except ValueError:
            return stripped.replace("_", "")
    return stripped.replace("_", "").replace("-", "").replace(":", "").replace("T", "")


def timestamp_dir_to_iso(timestamp: str) -> str | None:
    try:
        parsed = datetime.strptime(timestamp, "%Y%m%d%H%M%S")
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC).isoformat().replace("+00:00", "Z")


def normalize_event_timestamp(timestamp: str) -> str:
    if re.fullmatch(r"\d{6}_\d{6}", timestamp):
        try:
            parsed = datetime.strptime(timestamp, "%y%m%d_%H%M%S")
        except ValueError:
            return timestamp
        return parsed.replace(tzinfo=UTC).isoformat().replace("+00:00", "Z")
    return timestamp


def epoch_to_iso(epoch_seconds: float) -> str:
    return datetime.fromtimestamp(epoch_seconds, UTC).isoformat().replace("+00:00", "Z")


def read_json_object(path: Path) -> dict[str, Any]:
    try:
        with path.open(encoding="utf-8") as handle:
            data = json.load(handle)
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def first_project_name(records: list[AgentArtifactRecordWire]) -> str | None:
    return records[0].project_name if records else None


def unique_strings(values: Iterable[str | None]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value is None or value == "" or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def str_value(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item]


def compact_metadata(values: dict[str, str | None]) -> dict[str, str]:
    return {
        key: value
        for key, value in sorted(values.items())
        if value is not None and value != ""
    }


def dedupe_records(
    records: Iterable[AgentArtifactRecordWire],
) -> list[AgentArtifactRecordWire]:
    seen: set[str] = set()
    result: list[AgentArtifactRecordWire] = []
    for record in sorted(
        records,
        key=lambda item: (
            item.project_name,
            item.workflow_dir_name,
            item.timestamp,
            item.artifact_dir,
        ),
    ):
        key = normalize_source_path(record.artifact_dir)
        if key in seen:
            continue
        seen.add(key)
        result.append(record)
    return result


def limit_records(
    records: Iterable[AgentArtifactRecordWire],
    limit: int | None,
) -> list[AgentArtifactRecordWire]:
    ordered = dedupe_records(records)
    return ordered if limit is None else ordered[:limit]


def stable_id(prefix: str, *parts: str) -> str:
    payload = json.dumps(parts, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]
    return f"{prefix}-{digest}"
