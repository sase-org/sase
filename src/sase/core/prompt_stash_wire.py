"""Wire records for the Rust prompt-stash store facade."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from sase.core.wire import known_field_kwargs

PROMPT_STASH_WIRE_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class PromptStashCursorWire:
    """Zero-based editor position for the pane active when a stash was captured.

    ``pane_index`` is bundle-local: it names the active pane among the row's
    persisted, non-empty segments, not the original prompt-stack index and not
    :attr:`PromptStashEntryWire.pane_index`.
    """

    pane_index: int
    row: int
    column: int


@dataclass(frozen=True)
class PromptStashEntryWire:
    """One stashed prompt draft row."""

    id: str
    created_at: str
    text: str
    frontmatter: str = ""
    project: str | None = None
    source: str = ""
    pane_index: int = 0
    pinned: bool = False
    cursor: PromptStashCursorWire | None = None


@dataclass(frozen=True)
class _PromptStashStoreStatsWire:
    total_lines: int = 0
    blank_lines: int = 0
    invalid_json_lines: int = 0
    invalid_record_lines: int = 0
    loaded_rows: int = 0


@dataclass(frozen=True)
class PromptStashSnapshotWire:
    schema_version: int
    entries: list[PromptStashEntryWire] = field(default_factory=list)
    stats: _PromptStashStoreStatsWire = field(
        default_factory=_PromptStashStoreStatsWire
    )


@dataclass(frozen=True)
class PromptStashPopOutcomeWire:
    schema_version: int
    removed: list[PromptStashEntryWire] = field(default_factory=list)
    snapshot: PromptStashSnapshotWire = field(
        default_factory=lambda: PromptStashSnapshotWire(
            schema_version=PROMPT_STASH_WIRE_SCHEMA_VERSION
        )
    )


def prompt_stash_wire_to_json_dict(record: Any) -> Any:
    """Project prompt-stash wire records to the dict shape expected by Rust."""
    if isinstance(record, (list, tuple)):
        return [prompt_stash_wire_to_json_dict(item) for item in record]
    if isinstance(record, dict):
        payload = {k: prompt_stash_wire_to_json_dict(v) for k, v in record.items()}
        if payload.get("cursor") is None:
            payload.pop("cursor", None)
        return payload
    if hasattr(record, "__dataclass_fields__"):
        return prompt_stash_wire_to_json_dict(asdict(record))
    return record


def _prompt_stash_cursor_from_dict(data: Any) -> PromptStashCursorWire | None:
    if not isinstance(data, dict):
        return None
    return PromptStashCursorWire(
        pane_index=int(data.get("pane_index", 0)),
        row=int(data.get("row", 0)),
        column=int(data.get("column", 0)),
    )


def _prompt_stash_entry_from_dict(data: dict[str, Any]) -> PromptStashEntryWire:
    return PromptStashEntryWire(
        id=str(data["id"]),
        created_at=str(data["created_at"]),
        text=str(data.get("text", "")),
        frontmatter=str(data.get("frontmatter", "")),
        project=None if data.get("project") is None else str(data["project"]),
        source=str(data.get("source", "")),
        pane_index=int(data.get("pane_index", 0)),
        pinned=bool(data.get("pinned", False)),
        cursor=_prompt_stash_cursor_from_dict(data.get("cursor")),
    )


def _require_schema(schema: int) -> None:
    if schema != PROMPT_STASH_WIRE_SCHEMA_VERSION:
        raise ValueError(
            f"prompt stash wire schema mismatch: got {schema}, "
            f"expected {PROMPT_STASH_WIRE_SCHEMA_VERSION}"
        )


def prompt_stash_snapshot_from_dict(
    data: dict[str, Any],
) -> PromptStashSnapshotWire:
    schema = int(data["schema_version"])
    _require_schema(schema)
    return PromptStashSnapshotWire(
        schema_version=schema,
        entries=[
            _prompt_stash_entry_from_dict(item) for item in data.get("entries") or []
        ],
        stats=_PromptStashStoreStatsWire(
            **known_field_kwargs(_PromptStashStoreStatsWire, data.get("stats") or {})
        ),
    )


def prompt_stash_pop_outcome_from_dict(
    data: dict[str, Any],
) -> PromptStashPopOutcomeWire:
    schema = int(data["schema_version"])
    _require_schema(schema)
    return PromptStashPopOutcomeWire(
        schema_version=schema,
        removed=[
            _prompt_stash_entry_from_dict(item) for item in data.get("removed") or []
        ],
        snapshot=prompt_stash_snapshot_from_dict(data["snapshot"]),
    )


__all__ = [
    "PROMPT_STASH_WIRE_SCHEMA_VERSION",
    "PromptStashCursorWire",
    "PromptStashEntryWire",
    "PromptStashPopOutcomeWire",
    "PromptStashSnapshotWire",
    "_PromptStashStoreStatsWire",
    "_prompt_stash_cursor_from_dict",
    "_prompt_stash_entry_from_dict",
    "prompt_stash_pop_outcome_from_dict",
    "prompt_stash_snapshot_from_dict",
    "prompt_stash_wire_to_json_dict",
]
