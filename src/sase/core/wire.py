"""Wire records for the sase.core facade.

These types are the **stable** boundary that a future Rust backend produces and
consumes. They intentionally do not subclass or share code with the
``sase.ace.changespec.models`` Python dataclasses — the Python models can keep
evolving for the TUI, while wire records change only with a schema bump.

Phase 0A introduces the types and JSON-safe serialization. Conversion from the
existing Python ``ChangeSpec`` dataclasses lives in
:mod:`sase.core.wire_conversion`.

JSON shape conventions:

- ``None`` is preserved (becomes JSON ``null``).
- ``list`` is preserved (never replaced with ``None`` for empty sections).
- All keys are lowercase ``snake_case``.
- ``schema_version`` lives at the top of :class:`ChangeSpecWire` so a Rust
  parser can refuse to deserialize newer records.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

CHANGESPEC_WIRE_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class SourceSpanWire:
    """Inclusive 1-based line range pointing into the source file."""

    file_path: str
    start_line: int
    end_line: int


@dataclass
class SectionWire:
    """A raw section captured by line range so Python can rewrite atomically."""

    name: str
    start_line: int
    end_line: int
    raw_lines: list[str] = field(default_factory=list)


@dataclass
class CommitWire:
    """Wire form of :class:`sase.ace.changespec.models.CommitEntry`."""

    number: int
    note: str
    chat: str | None = None
    diff: str | None = None
    plan: str | None = None
    proposal_letter: str | None = None
    suffix: str | None = None
    suffix_type: str | None = None
    body: list[str] = field(default_factory=list)


@dataclass
class HookStatusLineWire:
    """Wire form of :class:`sase.ace.changespec.models.HookStatusLine`."""

    commit_entry_num: str
    timestamp: str
    status: str
    duration: str | None = None
    suffix: str | None = None
    suffix_type: str | None = None
    summary: str | None = None


@dataclass
class HookWire:
    """Wire form of :class:`sase.ace.changespec.models.HookEntry`."""

    command: str
    status_lines: list[HookStatusLineWire] = field(default_factory=list)


@dataclass
class CommentWire:
    """Wire form of :class:`sase.ace.changespec.models.CommentEntry`."""

    reviewer: str
    file_path: str
    suffix: str | None = None
    suffix_type: str | None = None


@dataclass
class MentorStatusLineWire:
    """Wire form of :class:`sase.ace.changespec.models.MentorStatusLine`."""

    profile_name: str
    mentor_name: str
    status: str
    timestamp: str | None
    duration: str | None = None
    suffix: str | None = None
    suffix_type: str | None = None


@dataclass
class MentorWire:
    """Wire form of :class:`sase.ace.changespec.models.MentorEntry`."""

    entry_id: str
    profiles: list[str] = field(default_factory=list)
    status_lines: list[MentorStatusLineWire] = field(default_factory=list)
    is_draft: bool = False


@dataclass
class TimestampWire:
    """Wire form of :class:`sase.ace.changespec.models.TimestampEntry`."""

    timestamp: str
    event_type: str
    detail: str


@dataclass
class DeltaWire:
    """Wire form of :class:`sase.ace.changespec.models.DeltaEntry`.

    ``change_type`` uses the long form ("A", "M", "D"). The on-disk glyphs
    ("+", "~", "-") are a formatting concern and stay out of the wire shape.
    """

    path: str
    change_type: str


@dataclass
class RawChangeSpecWire:
    """A raw, unparsed ChangeSpec slice — exactly the bytes between
    ``source_span.start_line`` and ``source_span.end_line`` in the source file.

    A Rust parser can be handed one of these without re-reading the file.
    """

    source_span: SourceSpanWire
    raw_text: str


@dataclass
class ChangeSpecWire:
    """The full parsed wire form of one ChangeSpec.

    Fields mirror :class:`sase.ace.changespec.models.ChangeSpec` plus the
    derived ``project_basename`` and a stable ``source_span``. Lists are
    always present (empty rather than ``None``) so JSON shape is regular.
    """

    schema_version: int
    name: str
    project_basename: str
    file_path: str
    source_span: SourceSpanWire
    status: str
    parent: str | None
    cl_or_pr: str | None
    bug: str | None
    description: str
    test_targets: list[str] = field(default_factory=list)
    kickstart: str | None = None
    commits: list[CommitWire] = field(default_factory=list)
    hooks: list[HookWire] = field(default_factory=list)
    comments: list[CommentWire] = field(default_factory=list)
    mentors: list[MentorWire] = field(default_factory=list)
    timestamps: list[TimestampWire] = field(default_factory=list)
    deltas: list[DeltaWire] = field(default_factory=list)


@dataclass
class ParseErrorWire:
    """Structured error a Rust parser may emit instead of a ChangeSpecWire."""

    kind: str
    message: str
    file_path: str
    line: int | None = None
    column: int | None = None


def to_json_dict(record: Any) -> Any:
    """Project a wire record (or list of them) to a JSON-safe ``dict``/``list``.

    Falls through unchanged for primitives so callers can pass arbitrary
    nested structures. Uses :func:`dataclasses.asdict` under the hood, which
    recurses into nested wire dataclasses.
    """
    if isinstance(record, list):
        return [to_json_dict(item) for item in record]
    if isinstance(record, tuple):
        return [to_json_dict(item) for item in record]
    if isinstance(record, dict):
        return {k: to_json_dict(v) for k, v in record.items()}
    if hasattr(record, "__dataclass_fields__"):
        return asdict(record)
    return record
