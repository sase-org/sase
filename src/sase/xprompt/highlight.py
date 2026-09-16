"""Frontend-agnostic xprompt syntax highlight spans."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import heapq
from typing import TYPE_CHECKING, Literal, cast

from sase.artifact_refs import scan_artifact_refs

from . import alt_inspect, jinja_inspect, xprompt_inspect
from ._fenced_blocks import fenced_block_details
from ._literal_zones import inline_literal_ranges
from .placeholder_completion import PlaceholderPosition, placeholder_spans

if TYPE_CHECKING:
    from .xprompt_inspect import XPromptSpan

MAX_HIGHLIGHT_BYTES = 80_000
MAX_HIGHLIGHT_LINES = 1_200

XPromptHighlightRole = Literal[
    "xprompt.invocation",
    "xprompt.invocation_arg",
    "xprompt.directive",
    "xprompt.directive_arg",
    "xprompt.arg_delimiter",
    "xprompt.arg_key",
    "xprompt.arg_assign",
    "xprompt.arg_value",
    "xprompt.arg_value_string",
    "xprompt.arg_value_number",
    "xprompt.arg_value_bool",
    "xprompt.separator",
    "xprompt.skill",
    "jinja.delimiter",
    "jinja.statement",
    "jinja.variable",
    "jinja.comment",
    "jinja.filter",
    "jinja.keyword",
    "jinja.operator",
    "alt.delimiter",
    "alt.separator",
    "alt.branch_name",
    "alt.error",
    "placeholder",
    "artifact_ref",
    "code.fence",
    "code.inline",
]

XPromptArgumentSpanValidity = Literal[
    "ok",
    "unknown_key",
    "type_mismatch",
    "duplicate_key",
    "unresolvable",
]

XPromptArgumentSource = Literal["xprompt", "directive"]


@dataclass(frozen=True, slots=True)
class HighlightSpan:
    """A half-open character range carrying one semantic highlight role."""

    start: int
    end: int
    role: XPromptHighlightRole
    validity: XPromptArgumentSpanValidity = "ok"
    source: XPromptArgumentSource | None = None


@dataclass(frozen=True, slots=True)
class _Candidate:
    candidate_id: int
    start: int
    end: int
    role: XPromptHighlightRole
    validity: XPromptArgumentSpanValidity
    source: XPromptArgumentSource | None


# Lower numbers win. Keeping every role explicit makes precedence additions
# deliberate and gives same-family overlaps a deterministic result.
_ROLE_PRECEDENCE: dict[XPromptHighlightRole, int] = {
    "code.fence": 0,
    "code.inline": 1,
    "xprompt.invocation": 10,
    "xprompt.directive": 11,
    "xprompt.separator": 12,
    "xprompt.skill": 13,
    "xprompt.arg_key": 20,
    "xprompt.arg_assign": 21,
    "xprompt.arg_delimiter": 22,
    "alt.delimiter": 30,
    "alt.separator": 31,
    "alt.branch_name": 32,
    "alt.error": 33,
    "jinja.delimiter": 40,
    "jinja.statement": 41,
    "jinja.variable": 42,
    "jinja.comment": 43,
    "jinja.filter": 44,
    "jinja.keyword": 45,
    "jinja.operator": 46,
    "placeholder": 50,
    "artifact_ref": 60,
    "xprompt.arg_value_string": 70,
    "xprompt.arg_value_number": 71,
    "xprompt.arg_value_bool": 72,
    "xprompt.arg_value": 73,
    "xprompt.invocation_arg": 90,
    "xprompt.directive_arg": 91,
}

_ARGUMENT_ROLE_BY_CORE_ROLE: dict[str, XPromptHighlightRole] = {
    "arg_delimiter": "xprompt.arg_delimiter",
    "arg_key": "xprompt.arg_key",
    "arg_assign": "xprompt.arg_assign",
    "arg_value": "xprompt.arg_value",
    "arg_value_string": "xprompt.arg_value_string",
    "arg_value_number": "xprompt.arg_value_number",
    "arg_value_bool": "xprompt.arg_value_bool",
}

_VALIDITIES: frozenset[str] = frozenset(
    {"ok", "unknown_key", "type_mismatch", "duplicate_key", "unresolvable"}
)

_SOURCES: frozenset[str] = frozenset({"xprompt", "directive"})
_MISSING_BINDING = object()
_xprompt_argument_spans_binding: Callable[..., object] | object | None = None


def _get_xprompt_argument_spans_binding() -> Callable[..., object] | None:
    global _xprompt_argument_spans_binding

    if _xprompt_argument_spans_binding is _MISSING_BINDING:
        return None
    if _xprompt_argument_spans_binding is None:
        try:
            from sase.core.rust import require_rust_binding

            _xprompt_argument_spans_binding = require_rust_binding(
                "xprompt_argument_spans"
            )
        except Exception:
            _xprompt_argument_spans_binding = _MISSING_BINDING
            return None
    return cast(Callable[..., object], _xprompt_argument_spans_binding)


def highlight_spans(
    text: str,
    *,
    known_skills: frozenset[str] = frozenset(),
    include_artifact_refs: bool = True,
    xprompt_arg_assist_entries: Sequence[object] | None = None,
) -> list[HighlightSpan]:
    """Return a flat, ordered, non-overlapping role partition of *text*."""
    if (
        len(text.encode("utf-8")) > MAX_HIGHLIGHT_BYTES
        or text.count("\n") > MAX_HIGHLIGHT_LINES
    ):
        return []

    collected: list[HighlightSpan] = []

    try:
        xprompt_tokens: list[XPromptSpan] = xprompt_inspect.tokenize(
            text,
            known_skills=known_skills,
        )
    except Exception:
        xprompt_tokens = []
    collected.extend(
        HighlightSpan(
            span.start,
            span.end,
            cast(XPromptHighlightRole, f"xprompt.{span.kind}"),
        )
        for span in xprompt_tokens
    )

    collected.extend(
        _xprompt_argument_highlight_spans(
            text,
            xprompt_arg_assist_entries=xprompt_arg_assist_entries,
        )
    )

    try:
        jinja_tokens = jinja_inspect.tokenize(text)
    except Exception:
        jinja_tokens = []
    collected.extend(
        HighlightSpan(
            span.start,
            span.end,
            cast(XPromptHighlightRole, f"jinja.{span.kind}"),
        )
        for span in jinja_tokens
    )

    try:
        alt_tokens = alt_inspect.tokenize(text)
    except Exception:
        alt_tokens = []
    collected.extend(
        HighlightSpan(
            span.start,
            span.end,
            cast(XPromptHighlightRole, f"alt.{span.kind}"),
        )
        for span in alt_tokens
    )

    try:
        placeholders = placeholder_spans(text)
    except Exception:
        placeholders = ()
    for span in placeholders:
        if not span.raw:
            continue
        start = _position_to_offset(text, span.range.start)
        end = _position_to_offset(text, span.range.end)
        if start is not None and end is not None:
            collected.append(HighlightSpan(start, end, "placeholder"))

    if include_artifact_refs:
        try:
            artifact_candidates = scan_artifact_refs(text)
        except Exception:
            artifact_candidates = ()
        byte_offsets = _byte_to_character_offsets(text)
        for candidate in artifact_candidates:
            start = byte_offsets.get(candidate.candidate_span.start)
            end = byte_offsets.get(candidate.candidate_span.end)
            if start is not None and end is not None:
                collected.append(HighlightSpan(start, end, "artifact_ref"))

    try:
        fenced_blocks = fenced_block_details(text)
    except Exception:
        fenced_blocks = []
    collected.extend(
        HighlightSpan(block.block_range[0], block.block_range[1], "code.fence")
        for block in fenced_blocks
    )

    try:
        inline_ranges = inline_literal_ranges(text)
    except Exception:
        inline_ranges = []
    collected.extend(
        HighlightSpan(start, end, "code.inline") for start, end in inline_ranges
    )

    return _flatten_spans(collected, text_length=len(text))


def _flatten_spans(
    spans: list[HighlightSpan],
    *,
    text_length: int,
) -> list[HighlightSpan]:
    candidates: list[_Candidate] = []
    for candidate_id, span in enumerate(spans):
        start = max(0, min(span.start, text_length))
        end = max(0, min(span.end, text_length))
        if end <= start:
            continue
        candidates.append(
            _Candidate(
                candidate_id,
                start,
                end,
                span.role,
                span.validity,
                span.source,
            )
        )
    if not candidates:
        return []

    starts: dict[int, list[_Candidate]] = {}
    ends: dict[int, list[int]] = {}
    for candidate in candidates:
        starts.setdefault(candidate.start, []).append(candidate)
        ends.setdefault(candidate.end, []).append(candidate.candidate_id)
    boundaries = sorted({*starts, *ends})
    by_id = {candidate.candidate_id: candidate for candidate in candidates}
    active: set[int] = set()
    heap: list[tuple[int, int]] = []
    pieces: list[tuple[_Candidate, int, int]] = []
    for start, end in zip(boundaries, boundaries[1:], strict=False):
        active.difference_update(ends.get(start, ()))
        for candidate in starts.get(start, ()):
            active.add(candidate.candidate_id)
            heapq.heappush(
                heap,
                (_ROLE_PRECEDENCE[candidate.role], candidate.candidate_id),
            )
        while heap and heap[0][1] not in active:
            heapq.heappop(heap)
        if not heap:
            continue
        winner = by_id[heap[0][1]]
        if pieces and pieces[-1][0].candidate_id == winner.candidate_id:
            pieces[-1] = (winner, pieces[-1][1], end)
        else:
            pieces.append((winner, start, end))

    return [
        HighlightSpan(
            start=start,
            end=end,
            role=candidate.role,
            validity=candidate.validity,
            source=candidate.source,
        )
        for candidate, start, end in pieces
    ]


def _xprompt_argument_highlight_spans(
    text: str,
    *,
    xprompt_arg_assist_entries: Sequence[object] | None,
) -> list[HighlightSpan]:
    binding = _get_xprompt_argument_spans_binding()
    if binding is None:
        return []

    try:
        if xprompt_arg_assist_entries is None:
            raw_spans = binding(text)
        else:
            raw_spans = binding(
                text,
                _xprompt_arg_assist_entries_to_wire(xprompt_arg_assist_entries),
            )
    except Exception:
        return []
    if not isinstance(raw_spans, Sequence):
        return []

    byte_offsets = _byte_to_character_offsets(text)
    spans: list[HighlightSpan] = []
    for raw_span in raw_spans:
        if not isinstance(raw_span, Mapping):
            continue
        role = _ARGUMENT_ROLE_BY_CORE_ROLE.get(str(raw_span.get("role", "")))
        if role is None:
            continue
        start = _int_value(raw_span.get("start"))
        end = _int_value(raw_span.get("end"))
        if start is None or end is None:
            continue
        start_char = byte_offsets.get(start)
        end_char = byte_offsets.get(end)
        if start_char is None or end_char is None:
            continue
        spans.append(
            HighlightSpan(
                start_char,
                end_char,
                role,
                validity=_validity_value(raw_span.get("validity")),
                source=_source_value(raw_span.get("source")),
            )
        )
    return spans


def _xprompt_arg_assist_entries_to_wire(
    entries: Sequence[object],
) -> list[dict[str, object]]:
    return [_xprompt_arg_assist_entry_to_wire(entry) for entry in entries]


def _xprompt_arg_assist_entry_to_wire(entry: object) -> dict[str, object]:
    name = str(_field(entry, "name", ""))
    return {
        "name": name,
        "display_label": _field(entry, "display_label", name),
        "insertion": _field(entry, "insertion", name),
        "reference_prefix": _field(entry, "reference_prefix", "#"),
        "kind": _field(entry, "kind", None),
        "source_bucket": _field(entry, "source_bucket", ""),
        "project": _field(entry, "project", None),
        "tags": list(cast(Sequence[object], _field(entry, "tags", ()) or ())),
        "input_signature": _field(entry, "input_signature", None),
        "inputs": [
            _xprompt_input_hint_to_wire(input_hint)
            for input_hint in cast(Sequence[object], _field(entry, "inputs", ()) or ())
        ],
        "content_preview": _field(entry, "content_preview", None),
        "description": _field(entry, "description", None),
        "source_path_display": _field(entry, "source_path_display", None),
        "definition_path": _field(entry, "definition_path", None),
        "definition_range": _field(entry, "definition_range", None),
        "is_skill": bool(_field(entry, "is_skill", False)),
        "skill_name": _field(entry, "skill_name", None),
        "memory_type": _field(entry, "memory_type", None),
    }


def _xprompt_input_hint_to_wire(input_hint: object) -> dict[str, object]:
    return {
        "name": _field(input_hint, "name", ""),
        "type": _field(input_hint, "type", ""),
        "description": _field(input_hint, "description", None),
        "required": bool(_field(input_hint, "required", False)),
        "default_display": _field(input_hint, "default_display", None),
        "position": _position_value(_field(input_hint, "position", 0)),
        "repeatable": bool(_field(input_hint, "repeatable", False)),
    }


def _field(value: object, name: str, default: object) -> object:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _int_value(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


def _position_value(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return 0
    return 0


def _validity_value(value: object) -> XPromptArgumentSpanValidity:
    if isinstance(value, str) and value in _VALIDITIES:
        return cast(XPromptArgumentSpanValidity, value)
    return "ok"


def _source_value(value: object) -> XPromptArgumentSource | None:
    if isinstance(value, str) and value in _SOURCES:
        return cast(XPromptArgumentSource, value)
    return None


def _position_to_offset(text: str, position: PlaceholderPosition) -> int | None:
    """Convert a zero-based LSP UTF-16 position to a character offset."""
    if position.line < 0 or position.character < 0:
        return None
    line_start = 0
    for _ in range(position.line):
        newline = text.find("\n", line_start)
        if newline == -1:
            return None
        line_start = newline + 1

    newline = text.find("\n", line_start)
    line_end = len(text) if newline == -1 else newline
    utf16_offset = 0
    for offset in range(line_start, line_end):
        if utf16_offset == position.character:
            return offset
        utf16_offset += 2 if ord(text[offset]) > 0xFFFF else 1
        if utf16_offset > position.character:
            return None
    return line_end if utf16_offset == position.character else None


def _byte_to_character_offsets(text: str) -> dict[int, int]:
    offsets = {0: 0}
    byte_offset = 0
    for character_offset, char in enumerate(text, start=1):
        byte_offset += len(char.encode("utf-8"))
        offsets[byte_offset] = character_offset
    return offsets


__all__ = [
    "MAX_HIGHLIGHT_BYTES",
    "MAX_HIGHLIGHT_LINES",
    "HighlightSpan",
    "XPromptArgumentSource",
    "XPromptArgumentSpanValidity",
    "XPromptHighlightRole",
    "highlight_spans",
]
