"""Wire records for the sase.core facade.

These types are the **stable** boundary that a future Rust backend produces and
consumes. They intentionally do not subclass or share code with the
``sase.ace.patch.models`` Python dataclasses — the Python models can keep
evolving for the TUI, while wire records change only with a schema bump.

Phase 0A introduces the types and JSON-safe serialization. Conversion from the
existing Python ``Patch`` dataclasses lives in
:mod:`sase.core.wire_conversion`.

JSON shape conventions:

- ``None`` is preserved (becomes JSON ``null``).
- ``list`` is preserved (never replaced with ``None`` for empty sections).
- All keys are lowercase ``snake_case``.
- ``schema_version`` lives at the top of :class:`PatchWire` so a Rust
  parser can refuse to deserialize newer records.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from typing import Any

CHANGESPEC_WIRE_SCHEMA_VERSION = 5
SUPPORTED_CHANGESPEC_WIRE_SCHEMA_VERSIONS = frozenset(
    {2, 3, 4, CHANGESPEC_WIRE_SCHEMA_VERSION}
)
PATCH_WIRE_SCHEMA_VERSION = CHANGESPEC_WIRE_SCHEMA_VERSION
SUPPORTED_PATCH_WIRE_SCHEMA_VERSIONS = SUPPORTED_CHANGESPEC_WIRE_SCHEMA_VERSIONS


@dataclass(frozen=True)
class SourceSpanWire:
    """Inclusive 1-based line range pointing into the source file."""

    file_path: str
    start_line: int
    end_line: int


@dataclass
class StitchWire:
    """Wire form of :class:`sase.ace.patch.models.Stitch`."""

    number: int
    note: str
    chat: str | None = None
    diff: str | None = None
    plan: str | None = None
    proposal_letter: str | None = None
    suffix: str | None = None
    suffix_type: str | None = None
    body: list[str] = field(default_factory=list)


CommitWire = StitchWire


@dataclass
class PatchHookStatusLineWire:
    """Canonical wire form of a hook status line using ``stitch_id``."""

    stitch_id: str
    timestamp: str
    status: str
    duration: str | None = None
    suffix: str | None = None
    suffix_type: str | None = None
    summary: str | None = None


@dataclass
class HookStatusLineWire:
    """Legacy wire form of :class:`sase.ace.patch.models.HookStatusLine`."""

    commit_entry_num: str
    timestamp: str
    status: str
    duration: str | None = None
    suffix: str | None = None
    suffix_type: str | None = None
    summary: str | None = None


@dataclass
class PatchHookWire:
    """Canonical wire form of :class:`sase.ace.patch.models.HookEntry`."""

    command: str
    status_lines: list[PatchHookStatusLineWire] = field(default_factory=list)


@dataclass
class HookWire:
    """Legacy wire form of :class:`sase.ace.patch.models.HookEntry`."""

    command: str
    status_lines: list[HookStatusLineWire] = field(default_factory=list)


@dataclass
class CommentWire:
    """Wire form of :class:`sase.ace.patch.models.CommentEntry`."""

    reviewer: str
    file_path: str
    suffix: str | None = None
    suffix_type: str | None = None


@dataclass
class MentorStatusLineWire:
    """Wire form of :class:`sase.ace.patch.models.MentorStatusLine`."""

    profile_name: str
    mentor_name: str
    status: str
    timestamp: str | None
    duration: str | None = None
    suffix: str | None = None
    suffix_type: str | None = None


@dataclass
class PatchMentorWire:
    """Canonical wire form of :class:`sase.ace.patch.models.MentorEntry`."""

    stitch_id: str
    profiles: list[str] = field(default_factory=list)
    status_lines: list[MentorStatusLineWire] = field(default_factory=list)
    is_draft: bool = False


@dataclass
class MentorWire:
    """Legacy wire form of :class:`sase.ace.patch.models.MentorEntry`."""

    entry_id: str
    profiles: list[str] = field(default_factory=list)
    status_lines: list[MentorStatusLineWire] = field(default_factory=list)
    is_draft: bool = False


@dataclass
class TimestampWire:
    """Wire form of :class:`sase.ace.patch.models.TimestampEntry`."""

    timestamp: str
    event_type: str
    detail: str


@dataclass
class DeltaWire:
    """Wire form of :class:`sase.ace.patch.models.DeltaEntry`.

    ``change_type`` uses the long form ("A", "M", "D"). The on-disk glyphs
    ("+", "~", "-") are a formatting concern and stay out of the wire shape.
    """

    path: str
    change_type: str


@dataclass
class PatchWire:
    """The full canonical parsed wire form of one Patch.

    Lists are always present (empty rather than ``None``) so JSON shape is
    regular. Canonical history fields use ``stitches`` and ``stitch_id``.
    """

    schema_version: int
    name: str
    project_basename: str
    project_display_name: str | None
    file_path: str
    source_span: SourceSpanWire
    status: str
    parent: str | None
    pr_url: str | None
    bug: str | None
    description: str
    refs: list[str] = field(default_factory=list)
    stitches: list[StitchWire] = field(default_factory=list)
    hooks: list[PatchHookWire] = field(default_factory=list)
    comments: list[CommentWire] = field(default_factory=list)
    mentors: list[PatchMentorWire] = field(default_factory=list)
    timestamps: list[TimestampWire] = field(default_factory=list)
    deltas: list[DeltaWire] = field(default_factory=list)


@dataclass
class ChangeSpecWire:
    """The full parsed wire form of one ChangeSpec.

    Fields mirror the legacy :class:`sase.ace.patch.models.ChangeSpec` alias plus the
    derived ``project_basename`` and a stable ``source_span``. Lists are
    always present (empty rather than ``None``) so JSON shape is regular.
    """

    schema_version: int
    name: str
    project_basename: str
    project_display_name: str | None
    file_path: str
    source_span: SourceSpanWire
    status: str
    parent: str | None
    pr_url: str | None
    bug: str | None
    description: str
    refs: list[str] = field(default_factory=list)
    commits: list[CommitWire] = field(default_factory=list)
    hooks: list[HookWire] = field(default_factory=list)
    comments: list[CommentWire] = field(default_factory=list)
    mentors: list[MentorWire] = field(default_factory=list)
    timestamps: list[TimestampWire] = field(default_factory=list)
    deltas: list[DeltaWire] = field(default_factory=list)


# symvision: https://github.com/sase-org/sase-core.git
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


_DATACLASS_FIELD_NAMES: dict[type[Any], frozenset[str]] = {}


def _dataclass_field_names(cls: type[Any]) -> frozenset[str]:
    names = _DATACLASS_FIELD_NAMES.get(cls)
    if names is None:
        names = frozenset(cls.__dataclass_fields__)
        _DATACLASS_FIELD_NAMES[cls] = names
    return names


def known_field_kwargs(cls: type[Any], data: Mapping[str, Any]) -> dict[str, Any]:
    """Project *data* onto the dataclass fields of *cls*.

    Tolerant-reader guard for rehydrating wire dataclasses from dicts a
    different sase/sase-core version produced: a newer writer may add fields
    this reader does not know about yet, and splatting the raw dict raises
    ``TypeError`` from the constructor (which crashed every published TUI
    when ``sase-core-rs`` 0.3.4 added ``video_paths`` to the done-marker
    wire). Additive fields must degrade to "ignored", not crash; removed or
    renamed fields still surface through wire schema-version checks and
    defaulted attributes.
    """
    known = _dataclass_field_names(cls)
    return {key: value for key, value in data.items() if key in known}
