"""Convert existing Python ``sase.ace.changespec`` dataclasses to wire records.

These helpers are the only place the Python models touch the wire shape. Phase
1D adds the inverse direction — building :class:`ChangeSpecWire` instances
from the plain dict shape returned by the Rust ``sase_core_rs`` PyO3 binding —
in :func:`changespec_wire_from_dict`.
"""

from __future__ import annotations

from typing import Any

from sase.ace.changespec.models import (
    ChangeSpec,
    CommentEntry,
    CommitEntry,
    DeltaEntry,
    HookEntry,
    HookStatusLine,
    MentorEntry,
    MentorStatusLine,
    TimestampEntry,
)
from sase.core.wire import (
    CHANGESPEC_WIRE_SCHEMA_VERSION,
    ChangeSpecWire,
    CommentWire,
    CommitWire,
    DeltaWire,
    HookStatusLineWire,
    HookWire,
    MentorStatusLineWire,
    MentorWire,
    SourceSpanWire,
    TimestampWire,
)

# DELTAS on-disk glyph -> long-form change_type stored in the wire record.
# Mirrors the docstring on :class:`sase.ace.changespec.models.DeltaEntry`.
_DELTA_GLYPH_TO_CODE = {
    "+": "A",
    "~": "M",
    "-": "D",
}


# pyvision: tests/test_core_wire.py
def commit_entry_to_wire(entry: CommitEntry) -> CommitWire:
    return CommitWire(
        number=entry.number,
        note=entry.note,
        chat=entry.chat,
        diff=entry.diff,
        plan=entry.plan,
        proposal_letter=entry.proposal_letter,
        suffix=entry.suffix,
        suffix_type=entry.suffix_type,
        body=list(entry.body) if entry.body is not None else [],
    )


# pyvision: tests/test_core_wire.py
def hook_status_line_to_wire(line: HookStatusLine) -> HookStatusLineWire:
    return HookStatusLineWire(
        commit_entry_num=line.commit_entry_num,
        timestamp=line.timestamp,
        status=line.status,
        duration=line.duration,
        suffix=line.suffix,
        suffix_type=line.suffix_type,
        summary=line.summary,
    )


# pyvision: tests/test_core_wire.py
def hook_entry_to_wire(entry: HookEntry) -> HookWire:
    status_lines = entry.status_lines or []
    return HookWire(
        command=entry.command,
        status_lines=[hook_status_line_to_wire(sl) for sl in status_lines],
    )


# pyvision: tests/test_core_wire.py
def comment_entry_to_wire(entry: CommentEntry) -> CommentWire:
    return CommentWire(
        reviewer=entry.reviewer,
        file_path=entry.file_path,
        suffix=entry.suffix,
        suffix_type=entry.suffix_type,
    )


# pyvision: tests/test_core_wire.py
def mentor_status_line_to_wire(line: MentorStatusLine) -> MentorStatusLineWire:
    return MentorStatusLineWire(
        profile_name=line.profile_name,
        mentor_name=line.mentor_name,
        status=line.status,
        timestamp=line.timestamp,
        duration=line.duration,
        suffix=line.suffix,
        suffix_type=line.suffix_type,
    )


# pyvision: tests/test_core_wire.py
def mentor_entry_to_wire(entry: MentorEntry) -> MentorWire:
    status_lines = entry.status_lines or []
    return MentorWire(
        entry_id=entry.entry_id,
        profiles=list(entry.profiles),
        status_lines=[mentor_status_line_to_wire(sl) for sl in status_lines],
        is_draft=entry.is_draft,
    )


# pyvision: tests/test_core_wire.py
def timestamp_entry_to_wire(entry: TimestampEntry) -> TimestampWire:
    return TimestampWire(
        timestamp=entry.timestamp,
        event_type=entry.event_type,
        detail=entry.detail,
    )


# pyvision: tests/test_core_wire.py
def delta_entry_to_wire(entry: DeltaEntry) -> DeltaWire:
    # ``DeltaEntry.change_type`` is already the long form ("A"/"M"/"D"); the
    # mapping is here so callers reading raw on-disk glyphs can still produce
    # a wire record via :func:`delta_glyph_to_change_type`.
    return DeltaWire(path=entry.path, change_type=entry.change_type)


# pyvision: tests/test_core_wire.py
def delta_glyph_to_change_type(glyph: str) -> str:
    """Translate an on-disk DELTAS glyph (``+``/``~``/``-``) to its long form."""
    try:
        return _DELTA_GLYPH_TO_CODE[glyph]
    except KeyError as exc:
        raise ValueError(f"Unknown DELTAS glyph: {glyph!r}") from exc


def changespec_wire_from_dict(record: dict[str, Any]) -> ChangeSpecWire:
    """Rebuild a :class:`ChangeSpecWire` from the dict shape Rust emits.

    The PyO3 binding (`sase_core_rs.parse_project_bytes`) returns plain Python
    dicts whose keys mirror the JSON shape of the wire dataclasses. This
    helper rehydrates those dicts into the typed dataclass tree the rest of
    the Python code expects, so callers of :func:`parse_project_bytes` see
    the same return type whether the Python or Rust backend produced the
    record.

    Schema-version mismatches raise :class:`ValueError` rather than silently
    accepting unknown wire shapes.
    """
    schema_version = record.get("schema_version")
    if schema_version != CHANGESPEC_WIRE_SCHEMA_VERSION:
        raise ValueError(
            f"Unsupported ChangeSpecWire schema_version={schema_version!r}; "
            f"this build understands {CHANGESPEC_WIRE_SCHEMA_VERSION}."
        )

    span = record["source_span"]
    source_span = SourceSpanWire(
        file_path=span["file_path"],
        start_line=span["start_line"],
        end_line=span["end_line"],
    )

    return ChangeSpecWire(
        schema_version=schema_version,
        name=record["name"],
        project_basename=record["project_basename"],
        file_path=record["file_path"],
        source_span=source_span,
        status=record["status"],
        parent=record.get("parent"),
        cl_or_pr=record.get("cl_or_pr"),
        bug=record.get("bug"),
        description=record["description"],
        test_targets=list(record.get("test_targets") or []),
        kickstart=record.get("kickstart"),
        commits=[_commit_wire_from_dict(c) for c in record.get("commits") or []],
        hooks=[_hook_wire_from_dict(h) for h in record.get("hooks") or []],
        comments=[_comment_wire_from_dict(c) for c in record.get("comments") or []],
        mentors=[_mentor_wire_from_dict(m) for m in record.get("mentors") or []],
        timestamps=[
            _timestamp_wire_from_dict(t) for t in record.get("timestamps") or []
        ],
        deltas=[_delta_wire_from_dict(d) for d in record.get("deltas") or []],
    )


def _commit_wire_from_dict(record: dict[str, Any]) -> CommitWire:
    return CommitWire(
        number=record["number"],
        note=record["note"],
        chat=record.get("chat"),
        diff=record.get("diff"),
        plan=record.get("plan"),
        proposal_letter=record.get("proposal_letter"),
        suffix=record.get("suffix"),
        suffix_type=record.get("suffix_type"),
        body=list(record.get("body") or []),
    )


def _hook_status_line_wire_from_dict(record: dict[str, Any]) -> HookStatusLineWire:
    return HookStatusLineWire(
        commit_entry_num=record["commit_entry_num"],
        timestamp=record["timestamp"],
        status=record["status"],
        duration=record.get("duration"),
        suffix=record.get("suffix"),
        suffix_type=record.get("suffix_type"),
        summary=record.get("summary"),
    )


def _hook_wire_from_dict(record: dict[str, Any]) -> HookWire:
    return HookWire(
        command=record["command"],
        status_lines=[
            _hook_status_line_wire_from_dict(sl)
            for sl in record.get("status_lines") or []
        ],
    )


def _comment_wire_from_dict(record: dict[str, Any]) -> CommentWire:
    return CommentWire(
        reviewer=record["reviewer"],
        file_path=record["file_path"],
        suffix=record.get("suffix"),
        suffix_type=record.get("suffix_type"),
    )


def _mentor_status_line_wire_from_dict(
    record: dict[str, Any],
) -> MentorStatusLineWire:
    return MentorStatusLineWire(
        profile_name=record["profile_name"],
        mentor_name=record["mentor_name"],
        status=record["status"],
        timestamp=record["timestamp"],
        duration=record.get("duration"),
        suffix=record.get("suffix"),
        suffix_type=record.get("suffix_type"),
    )


def _mentor_wire_from_dict(record: dict[str, Any]) -> MentorWire:
    return MentorWire(
        entry_id=record["entry_id"],
        profiles=list(record.get("profiles") or []),
        status_lines=[
            _mentor_status_line_wire_from_dict(sl)
            for sl in record.get("status_lines") or []
        ],
        is_draft=bool(record.get("is_draft", False)),
    )


def _timestamp_wire_from_dict(record: dict[str, Any]) -> TimestampWire:
    return TimestampWire(
        timestamp=record["timestamp"],
        event_type=record["event_type"],
        detail=record["detail"],
    )


def _delta_wire_from_dict(record: dict[str, Any]) -> DeltaWire:
    return DeltaWire(
        path=record["path"],
        change_type=record["change_type"],
    )


def changespec_to_wire(
    cs: ChangeSpec,
    *,
    end_line: int | None = None,
) -> ChangeSpecWire:
    """Project a Python ``ChangeSpec`` into a :class:`ChangeSpecWire`.

    ``end_line`` defaults to ``cs.line_number`` because the existing Python
    parser does not track end positions. Phase 1 (Rust parser) will fill this
    in properly; tests that need a real range can pass it explicitly.
    """
    span = SourceSpanWire(
        file_path=cs.file_path,
        start_line=cs.line_number,
        end_line=end_line if end_line is not None else cs.line_number,
    )
    return ChangeSpecWire(
        schema_version=CHANGESPEC_WIRE_SCHEMA_VERSION,
        name=cs.name,
        project_basename=cs.project_basename,
        file_path=cs.file_path,
        source_span=span,
        status=cs.status,
        parent=cs.parent,
        cl_or_pr=cs.cl,
        bug=cs.bug,
        description=cs.description,
        test_targets=list(cs.test_targets) if cs.test_targets is not None else [],
        kickstart=cs.kickstart,
        commits=[commit_entry_to_wire(c) for c in (cs.commits or [])],
        hooks=[hook_entry_to_wire(h) for h in (cs.hooks or [])],
        comments=[comment_entry_to_wire(c) for c in (cs.comments or [])],
        mentors=[mentor_entry_to_wire(m) for m in (cs.mentors or [])],
        timestamps=[timestamp_entry_to_wire(t) for t in (cs.timestamps or [])],
        deltas=[delta_entry_to_wire(d) for d in (cs.deltas or [])],
    )
