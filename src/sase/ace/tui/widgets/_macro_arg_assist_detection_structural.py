"""Structural span grouping for macro argument assist."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

_VALUE_ROLES = frozenset(
    {"arg_value", "arg_value_string", "arg_value_number", "arg_value_bool"}
)

_STRUCTURAL_OPENERS = frozenset({":", "(", "::"})


def _py_to_byte(text: str, py_offset: int) -> int:
    """Convert a Python str offset to a UTF-8 byte offset."""
    return len(text[:py_offset].encode("utf-8"))


def _byte_to_py(text: str, byte_offset: int) -> int:
    """Convert a UTF-8 byte offset to a Python str offset (adapter boundary)."""
    encoded = text.encode("utf-8")
    return len(encoded[:byte_offset].decode("utf-8", errors="ignore"))


def decode_span_value(raw: str) -> str:
    """Decode a span value for repeatable-exclusion comparison."""
    text = raw.strip()
    if len(text) >= 2 and text[0] in "\"'" and text[0] == text[-1]:
        return text[1:-1]
    return text


@dataclass(frozen=True, slots=True)
class StructuralCall:
    """Quote-aware clause layout for one macro call at the cursor.

    All offsets are Python ``str`` offsets. Commas, closes, values, keys and
    assigns come from sase-core argument spans, so quoted ``,``/``)``/``=``
    never split clauses. ``call_end_py`` is the closing ``)`` when the call
    is closed, else the furthest position the open call reaches.
    """

    opening_end_py: int
    close_py: int | None
    commas_py: tuple[int, ...]
    values_py: tuple[tuple[int, int], ...]
    keys_py: tuple[tuple[int, int, str], ...]
    assigns_py: tuple[tuple[int, int], ...]
    call_end_py: int


def load_argument_spans(text: str) -> Sequence[Mapping[str, object]] | None:
    """Load structural argument spans through the shared core binding.

    The import stays at the use site so TUI startup never pays for it.
    Returns ``None`` when the binding is unavailable or the parse fails.
    """
    try:
        from sase.macro.highlight import macro_argument_spans_for_text
    except Exception:
        return None
    try:
        return macro_argument_spans_for_text(text)
    except Exception:
        return None


def _span_offset(span: Mapping[str, object], key: str) -> int | None:
    """Read a byte offset out of a raw argument span, if it is a real int."""
    value = span.get(key)
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


def structural_call_for(
    text: str,
    spans: Sequence[Mapping[str, object]] | None,
    base_end_py: int,
    cursor_py: int,
    call_name: str,
) -> StructuralCall | None:
    """Group core spans into quote-aware clauses for one call.

    Starts at the opening delimiter at this reference's base end and takes
    spans until the call's closing ``)`` or the next opening delimiter.
    Returns ``None`` when the spans cannot express this call, so callers
    show no menu instead of guessing from raw string splits.
    """
    if not spans:
        return None
    encoded = text.encode("utf-8")
    base_end_byte = _py_to_byte(text, base_end_py)
    cursor_byte = _py_to_byte(text, cursor_py)
    ordered = sorted(
        spans,
        key=lambda span: (
            _span_offset(span, "start") or 0,
            _span_offset(span, "end") or 0,
        ),
    )
    opening_index: int | None = None
    opening_end_byte = 0
    for index, span in enumerate(ordered):
        if span.get("call_name") != call_name:
            continue
        if str(span.get("role", "")) != "arg_delimiter":
            continue
        span_start = _span_offset(span, "start")
        span_end = _span_offset(span, "end")
        if span_start is None or span_end is None:
            continue
        if span_start != base_end_byte:
            continue
        try:
            delim = encoded[span_start:span_end].decode("utf-8")
        except Exception:
            continue
        if delim in _STRUCTURAL_OPENERS:
            opening_index = index
            opening_end_byte = span_end
            break
    if opening_index is None:
        return None
    commas: list[int] = []
    values: list[tuple[int, int]] = []
    keys: list[tuple[int, int, str]] = []
    assigns: list[tuple[int, int]] = []
    close_byte: int | None = None
    span_ends = [opening_end_byte]
    for span in ordered[opening_index + 1 :]:
        start = _span_offset(span, "start")
        end = _span_offset(span, "end")
        if start is None or end is None:
            continue
        role = str(span.get("role", ""))
        if role == "arg_delimiter":
            try:
                delim = encoded[start:end].decode("utf-8")
            except Exception:
                continue
            if delim == ")":
                close_byte = start
                break
            if delim in ("(", ":", "::"):
                break
            if delim == ",":
                commas.append(start)
            span_ends.append(end)
            continue
        if role in _VALUE_ROLES:
            values.append((start, end))
        elif role == "arg_key":
            try:
                name = encoded[start:end].decode("utf-8").strip()
            except Exception:
                continue
            keys.append((start, end, name))
        elif role == "arg_assign":
            assigns.append((start, end))
        span_ends.append(end)
    opening_end_py = _byte_to_py(text, opening_end_byte)
    if close_byte is not None:
        call_end_byte = close_byte
    else:
        call_end_byte = max([cursor_byte, *span_ends])
    return StructuralCall(
        opening_end_py=opening_end_py,
        close_py=_byte_to_py(text, close_byte) if close_byte is not None else None,
        commas_py=tuple(_byte_to_py(text, comma) for comma in commas),
        values_py=tuple(
            (_byte_to_py(text, start), _byte_to_py(text, end)) for start, end in values
        ),
        keys_py=tuple(
            (_byte_to_py(text, start), _byte_to_py(text, end), name)
            for start, end, name in keys
        ),
        assigns_py=tuple(
            (_byte_to_py(text, start), _byte_to_py(text, end)) for start, end in assigns
        ),
        call_end_py=_byte_to_py(text, call_end_byte),
    )


def structural_clauses(call: StructuralCall) -> list[tuple[int, int]]:
    """Split the call body at structural commas into absolute ranges.

    Each range covers clause content only: the separating comma (one ASCII
    character at each recorded position) and, for closed calls, the closing
    ``)`` stay outside every clause.
    """
    bounds = [
        call.opening_end_py,
        *(comma + 1 for comma in call.commas_py),
        call.call_end_py,
    ]
    clauses = []
    for index in range(len(bounds) - 1):
        end = bounds[index + 1]
        if index < len(bounds) - 2:
            end -= 1
        clauses.append((bounds[index], end))
    return clauses


def structural_active_index(call: StructuralCall, cursor_py: int) -> int:
    """Return the clause holding the cursor (clauses are contiguous)."""
    for index, (_start, end) in enumerate(structural_clauses(call)):
        if cursor_py <= end:
            return index
    return len(structural_clauses(call)) - 1


def structural_is_closed(call: StructuralCall, cursor_py: int) -> bool:
    """Return whether a real ``)`` closes the call before the cursor."""
    return call.close_py is not None and cursor_py > call.close_py


def structural_clause_has_assign(call: StructuralCall, start: int, end: int) -> bool:
    """Return whether the range holds a top-level ``=`` (never a quoted one)."""
    return any(
        assign_start < end and assign_end > start
        for assign_start, assign_end in call.assigns_py
    )


def structural_clause_key(call: StructuralCall, start: int, end: int) -> str | None:
    """Return the argument key named in the range, if any."""
    for key_start, key_end, name in call.keys_py:
        if key_start < end and key_end > start and name:
            return name
    return None


def structural_selected_values(
    text: str, call: StructuralCall, active_index: int
) -> frozenset[str]:
    """Decode every positional value outside the active clause."""
    values: set[str] = set()
    for index, (start, end) in enumerate(structural_clauses(call)):
        if index == active_index:
            continue
        if structural_clause_has_assign(call, start, end):
            continue
        value = decode_span_value(text[start:end])
        if value:
            values.add(value)
    return frozenset(values)


def structural_used_names(call: StructuralCall, active_index: int) -> frozenset[str]:
    """Collect argument keys named in clauses before the active one."""
    clauses = structural_clauses(call)
    names: set[str] = set()
    for index in range(active_index):
        start, end = clauses[index]
        for key_start, key_end, name in call.keys_py:
            if key_start < end and key_end > start and name:
                names.add(name)
    return frozenset(names)


__all__ = [
    "StructuralCall",
    "decode_span_value",
    "load_argument_spans",
    "structural_active_index",
    "structural_call_for",
    "structural_clause_has_assign",
    "structural_clause_key",
    "structural_clauses",
    "structural_is_closed",
    "structural_selected_values",
    "structural_used_names",
]
