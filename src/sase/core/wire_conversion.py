"""Convert Python Patch dataclasses to core wire records.

These helpers are the only place the Python models touch the wire shape. Phase
1D adds the inverse direction — building legacy :class:`ChangeSpecWire` instances
from the plain dict shape returned by the Rust ``sase_core_rs`` PyO3 binding —
in legacy :func:`changespec_wire_from_dict`.
"""

from __future__ import annotations

from typing import Any

from sase.ace.patch.models import (
    CommentEntry,
    DeltaEntry,
    HookEntry,
    HookStatusLine,
    MentorEntry,
    MentorStatusLine,
    Patch,
    Stitch,
    TimestampEntry,
    normalize_pr_origin,
)
from sase.core.wire import (
    CHANGESPEC_WIRE_SCHEMA_VERSION,  # legacy wire schema
    PATCH_WIRE_SCHEMA_VERSION,
    ChangeSpecWire,  # legacy wire type
    CommentWire,
    CommitWire,
    DeltaWire,
    HookStatusLineWire,
    HookWire,
    MentorStatusLineWire,
    MentorWire,
    PatchHookStatusLineWire,
    PatchHookWire,
    PatchMentorWire,
    PatchWire,
    SourceSpanWire,
    SUPPORTED_CHANGESPEC_WIRE_SCHEMA_VERSIONS,  # legacy wire schema
    SUPPORTED_PATCH_WIRE_SCHEMA_VERSIONS,
    StitchWire,
    TimestampWire,
)

# DELTAS on-disk glyph -> long-form change_type stored in the wire record.
# Mirrors the docstring on :class:`sase.ace.patch.models.DeltaEntry`.
_DELTA_GLYPH_TO_CODE = {
    "+": "A",
    "~": "M",
    "-": "D",
}


def _stitch_to_wire(entry: Stitch) -> StitchWire:
    return StitchWire(
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


_commit_entry_to_wire = _stitch_to_wire


def _hook_status_line_to_patch_wire(
    line: HookStatusLine,
) -> PatchHookStatusLineWire:
    return PatchHookStatusLineWire(
        stitch_id=line.stitch_id,
        timestamp=line.timestamp,
        status=line.status,
        duration=line.duration,
        suffix=line.suffix,
        suffix_type=line.suffix_type,
        summary=line.summary,
    )


def _hook_status_line_to_wire(line: HookStatusLine) -> HookStatusLineWire:
    return HookStatusLineWire(
        commit_entry_num=line.commit_entry_num,
        timestamp=line.timestamp,
        status=line.status,
        duration=line.duration,
        suffix=line.suffix,
        suffix_type=line.suffix_type,
        summary=line.summary,
    )


def _hook_entry_to_patch_wire(entry: HookEntry) -> PatchHookWire:
    status_lines = entry.status_lines or []
    return PatchHookWire(
        command=entry.command,
        status_lines=[_hook_status_line_to_patch_wire(sl) for sl in status_lines],
    )


def hook_entry_to_wire(entry: HookEntry) -> HookWire:
    status_lines = entry.status_lines or []
    return HookWire(
        command=entry.command,
        status_lines=[_hook_status_line_to_wire(sl) for sl in status_lines],
    )


def comment_entry_to_wire(entry: CommentEntry) -> CommentWire:
    return CommentWire(
        reviewer=entry.reviewer,
        file_path=entry.file_path,
        suffix=entry.suffix,
        suffix_type=entry.suffix_type,
    )


def _mentor_status_line_to_wire(line: MentorStatusLine) -> MentorStatusLineWire:
    return MentorStatusLineWire(
        profile_name=line.profile_name,
        mentor_name=line.mentor_name,
        status=line.status,
        timestamp=line.timestamp,
        duration=line.duration,
        suffix=line.suffix,
        suffix_type=line.suffix_type,
    )


def mentor_entry_to_wire(entry: MentorEntry) -> MentorWire:
    status_lines = entry.status_lines or []
    return MentorWire(
        entry_id=entry.entry_id,
        profiles=list(entry.profiles),
        status_lines=[_mentor_status_line_to_wire(sl) for sl in status_lines],
        is_draft=entry.is_draft,
    )


def _mentor_entry_to_patch_wire(entry: MentorEntry) -> PatchMentorWire:
    status_lines = entry.status_lines or []
    return PatchMentorWire(
        stitch_id=entry.stitch_id,
        profiles=list(entry.profiles),
        status_lines=[_mentor_status_line_to_wire(sl) for sl in status_lines],
        is_draft=entry.is_draft,
    )


def _timestamp_entry_to_wire(entry: TimestampEntry) -> TimestampWire:
    return TimestampWire(
        timestamp=entry.timestamp,
        event_type=entry.event_type,
        detail=entry.detail,
    )


def _delta_entry_to_wire(entry: DeltaEntry) -> DeltaWire:
    # ``DeltaEntry.change_type`` is already the long form ("A"/"M"/"D"); the
    # mapping is here so callers reading raw on-disk glyphs can still produce
    # a wire record via :func:`_delta_glyph_to_change_type`.
    return DeltaWire(path=entry.path, change_type=entry.change_type)


def _delta_glyph_to_change_type(glyph: str) -> str:
    """Translate an on-disk DELTAS glyph (``+``/``~``/``-``) to its long form."""
    try:
        return _DELTA_GLYPH_TO_CODE[glyph]
    except KeyError as exc:
        raise ValueError(f"Unknown DELTAS glyph: {glyph!r}") from exc


def changespec_wire_from_dict(record: dict[str, Any]) -> ChangeSpecWire:
    """Rebuild a legacy :class:`ChangeSpecWire` from the dict shape Rust emits.

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
    if (
        schema_version not in SUPPORTED_CHANGESPEC_WIRE_SCHEMA_VERSIONS
    ):  # legacy wire schema
        raise ValueError(
            f"Unsupported ChangeSpecWire schema_version={schema_version!r}; "  # legacy wire type
            f"this build understands {CHANGESPEC_WIRE_SCHEMA_VERSION}."  # legacy wire schema
        )

    span = record["source_span"]
    source_span = SourceSpanWire(
        file_path=span["file_path"],
        start_line=span["start_line"],
        end_line=span["end_line"],
    )

    return ChangeSpecWire(  # legacy wire type
        schema_version=schema_version,
        name=record["name"],
        project_basename=record["project_basename"],
        project_display_name=record.get("project_display_name"),
        file_path=record["file_path"],
        source_span=source_span,
        status=record["status"],
        parent=record.get("parent"),
        pr_url=record.get("pr_url", record.get("cl_or_pr")),
        pr_origin=normalize_pr_origin(record.get("pr_origin")),
        bug=record.get("bug"),
        description=record["description"],
        refs=list(record.get("refs") or []),
        commits=[
            _commit_wire_from_dict(c)
            for c in _list_field(record, "commits", "stitches")
        ],
        hooks=[_hook_wire_from_dict(h) for h in record.get("hooks") or []],
        comments=[_comment_wire_from_dict(c) for c in record.get("comments") or []],
        mentors=[_mentor_wire_from_dict(m) for m in record.get("mentors") or []],
        timestamps=[
            _timestamp_wire_from_dict(t) for t in record.get("timestamps") or []
        ],
        deltas=[_delta_wire_from_dict(d) for d in record.get("deltas") or []],
    )


def patch_wire_from_dict(record: dict[str, Any]) -> PatchWire:
    """Rebuild a canonical :class:`PatchWire` from Rust or JSON dict data."""
    schema_version = record.get("schema_version")
    if schema_version not in SUPPORTED_PATCH_WIRE_SCHEMA_VERSIONS:
        raise ValueError(
            f"Unsupported PatchWire schema_version={schema_version!r}; "
            f"this build understands {PATCH_WIRE_SCHEMA_VERSION}."
        )

    span = record["source_span"]
    source_span = SourceSpanWire(
        file_path=span["file_path"],
        start_line=span["start_line"],
        end_line=span["end_line"],
    )

    return PatchWire(
        schema_version=schema_version,
        name=record["name"],
        project_basename=record["project_basename"],
        project_display_name=record.get("project_display_name"),
        file_path=record["file_path"],
        source_span=source_span,
        status=record["status"],
        parent=record.get("parent"),
        pr_url=record.get("pr_url", record.get("cl_or_pr")),
        pr_origin=normalize_pr_origin(record.get("pr_origin")),
        bug=record.get("bug"),
        description=record["description"],
        refs=list(record.get("refs") or []),
        stitches=[
            _stitch_wire_from_dict(c)
            for c in _list_field(record, "stitches", "commits")
        ],
        hooks=[_patch_hook_wire_from_dict(h) for h in record.get("hooks") or []],
        comments=[_comment_wire_from_dict(c) for c in record.get("comments") or []],
        mentors=[_patch_mentor_wire_from_dict(m) for m in record.get("mentors") or []],
        timestamps=[
            _timestamp_wire_from_dict(t) for t in record.get("timestamps") or []
        ],
        deltas=[_delta_wire_from_dict(d) for d in record.get("deltas") or []],
    )


def _list_field(
    record: dict[str, Any],
    preferred: str,
    fallback: str,
) -> list[dict[str, Any]]:
    if preferred in record and fallback in record:
        preferred_value = record.get(preferred) or []
        fallback_value = record.get(fallback) or []
        if preferred_value != fallback_value:
            raise ValueError(f"Conflicting wire fields {preferred!r} and {fallback!r}")
        return list(preferred_value)
    return list(record.get(preferred, record.get(fallback)) or [])


def _string_alias_field(
    record: dict[str, Any],
    preferred: str,
    fallback: str,
) -> str:
    if preferred in record and fallback in record:
        preferred_value = record[preferred]
        fallback_value = record[fallback]
        if preferred_value != fallback_value:
            raise ValueError(f"Conflicting wire fields {preferred!r} and {fallback!r}")
        return str(preferred_value)
    if preferred in record:
        return str(record[preferred])
    if fallback in record:
        return str(record[fallback])
    raise KeyError(preferred)


def _stitch_wire_from_dict(record: dict[str, Any]) -> StitchWire:
    return StitchWire(
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


def _commit_wire_from_dict(record: dict[str, Any]) -> CommitWire:
    return _stitch_wire_from_dict(record)


def _patch_hook_status_line_wire_from_dict(
    record: dict[str, Any],
) -> PatchHookStatusLineWire:
    return PatchHookStatusLineWire(
        stitch_id=_string_alias_field(record, "stitch_id", "commit_entry_num"),
        timestamp=record["timestamp"],
        status=record["status"],
        duration=record.get("duration"),
        suffix=record.get("suffix"),
        suffix_type=record.get("suffix_type"),
        summary=record.get("summary"),
    )


def _hook_status_line_wire_from_dict(record: dict[str, Any]) -> HookStatusLineWire:
    return HookStatusLineWire(
        commit_entry_num=_string_alias_field(record, "commit_entry_num", "stitch_id"),
        timestamp=record["timestamp"],
        status=record["status"],
        duration=record.get("duration"),
        suffix=record.get("suffix"),
        suffix_type=record.get("suffix_type"),
        summary=record.get("summary"),
    )


def _patch_hook_wire_from_dict(record: dict[str, Any]) -> PatchHookWire:
    return PatchHookWire(
        command=record["command"],
        status_lines=[
            _patch_hook_status_line_wire_from_dict(sl)
            for sl in record.get("status_lines") or []
        ],
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
        entry_id=_string_alias_field(record, "entry_id", "stitch_id"),
        profiles=list(record.get("profiles") or []),
        status_lines=[
            _mentor_status_line_wire_from_dict(sl)
            for sl in record.get("status_lines") or []
        ],
        is_draft=bool(record.get("is_draft", False)),
    )


def _patch_mentor_wire_from_dict(record: dict[str, Any]) -> PatchMentorWire:
    return PatchMentorWire(
        stitch_id=_string_alias_field(record, "stitch_id", "entry_id"),
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


# Legacy Python compatibility symbol required by tools/validate_sase_core_rs.
# symvision: tools/validate_sase_core_rs
def changespec_to_wire(  # legacy Python compat symbol
    cs: Patch,
    *,
    end_line: int | None = None,
) -> ChangeSpecWire:
    """Project a Python ``Patch`` into a legacy :class:`ChangeSpecWire`.

    ``end_line`` defaults to ``cs.line_number`` because the existing Python
    parser does not track end positions. Phase 1 (Rust parser) will fill this
    in properly; tests that need a real range can pass it explicitly.
    """
    span = SourceSpanWire(
        file_path=cs.file_path,
        start_line=cs.line_number,
        end_line=end_line if end_line is not None else cs.line_number,
    )
    return ChangeSpecWire(  # legacy wire type
        schema_version=CHANGESPEC_WIRE_SCHEMA_VERSION,  # legacy wire schema
        name=cs.name,
        project_basename=cs.project_basename,
        project_display_name=cs.project_display_name,
        file_path=cs.file_path,
        source_span=span,
        status=cs.status,
        parent=cs.parent,
        pr_url=cs.pr_url,
        pr_origin=normalize_pr_origin(cs.pr_origin),
        bug=cs.bug,
        description=cs.description,
        refs=list(getattr(cs, "refs", ()) or ()),
        commits=[_commit_entry_to_wire(c) for c in (cs.commits or [])],
        hooks=[hook_entry_to_wire(h) for h in (cs.hooks or [])],
        comments=[comment_entry_to_wire(c) for c in (cs.comments or [])],
        mentors=[mentor_entry_to_wire(m) for m in (cs.mentors or [])],
        timestamps=[_timestamp_entry_to_wire(t) for t in (cs.timestamps or [])],
        deltas=[_delta_entry_to_wire(d) for d in (cs.deltas or [])],
    )


def patch_to_wire(
    patch: Patch,
    *,
    end_line: int | None = None,
) -> PatchWire:
    """Project a Python ``Patch`` into a canonical :class:`PatchWire`."""
    span = SourceSpanWire(
        file_path=patch.file_path,
        start_line=patch.line_number,
        end_line=end_line if end_line is not None else patch.line_number,
    )
    return PatchWire(
        schema_version=PATCH_WIRE_SCHEMA_VERSION,
        name=patch.name,
        project_basename=patch.project_basename,
        project_display_name=patch.project_display_name,
        file_path=patch.file_path,
        source_span=span,
        status=patch.status,
        parent=patch.parent,
        pr_url=patch.pr_url,
        pr_origin=normalize_pr_origin(patch.pr_origin),
        bug=patch.bug,
        description=patch.description,
        refs=list(getattr(patch, "refs", ()) or ()),
        stitches=[_stitch_to_wire(c) for c in (patch.stitches or [])],
        hooks=[_hook_entry_to_patch_wire(h) for h in (patch.hooks or [])],
        comments=[comment_entry_to_wire(c) for c in (patch.comments or [])],
        mentors=[_mentor_entry_to_patch_wire(m) for m in (patch.mentors or [])],
        timestamps=[_timestamp_entry_to_wire(t) for t in (patch.timestamps or [])],
        deltas=[_delta_entry_to_wire(d) for d in (patch.deltas or [])],
    )
