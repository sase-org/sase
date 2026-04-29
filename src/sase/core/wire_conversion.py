"""Convert existing Python ``sase.ace.changespec`` dataclasses to wire records.

These helpers are the only place the Python models touch the wire shape. Going
the other direction (wire -> Python) is Phase 1 work, after a Rust parser
exists.
"""

from __future__ import annotations

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
