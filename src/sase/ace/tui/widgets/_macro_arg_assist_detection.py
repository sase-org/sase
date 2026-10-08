"""Cursor detection helpers for macro argument assist."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Literal

from sase.macro._parsing import (
    MacroReference,
    MacroReferenceArgKind,
    iter_macro_references,
)
from sase.macro._literal_zones import literal_zone_ranges

from ._macro_arg_assist_inputs import required_inputs
from ._macro_arg_assist_models import (
    ActiveMacroArgHint,
    MacroArgCompletionContext,
    MacroAssistEntry,
    MacroInputHint,
)

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


def _decode_span_value(raw: str) -> str:
    """Decode a span value for repeatable-exclusion comparison."""
    text = raw.strip()
    if len(text) >= 2 and text[0] in "\"'" and text[0] == text[-1]:
        return text[1:-1]
    return text


@dataclass(frozen=True, slots=True)
class _StructuralCall:
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


def _load_argument_spans(text: str) -> Sequence[Mapping[str, object]] | None:
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


def _structural_call_for(
    text: str,
    spans: Sequence[Mapping[str, object]] | None,
    base_end_py: int,
    cursor_py: int,
    call_name: str,
) -> _StructuralCall | None:
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
    return _StructuralCall(
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


def _structural_clauses(call: _StructuralCall) -> list[tuple[int, int]]:
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


def _structural_active_index(call: _StructuralCall, cursor_py: int) -> int:
    """Return the clause holding the cursor (clauses are contiguous)."""
    for index, (_start, end) in enumerate(_structural_clauses(call)):
        if cursor_py <= end:
            return index
    return len(_structural_clauses(call)) - 1


def _structural_is_closed(call: _StructuralCall, cursor_py: int) -> bool:
    """Return whether a real ``)`` closes the call before the cursor."""
    return call.close_py is not None and cursor_py > call.close_py


def _structural_clause_has_assign(call: _StructuralCall, start: int, end: int) -> bool:
    """Return whether the range holds a top-level ``=`` (never a quoted one)."""
    return any(
        assign_start < end and assign_end > start
        for assign_start, assign_end in call.assigns_py
    )


def _structural_clause_key(call: _StructuralCall, start: int, end: int) -> str | None:
    """Return the argument key named in the range, if any."""
    for key_start, key_end, name in call.keys_py:
        if key_start < end and key_end > start and name:
            return name
    return None


def _structural_selected_values(
    text: str, call: _StructuralCall, active_index: int
) -> frozenset[str]:
    """Decode every positional value outside the active clause."""
    values: set[str] = set()
    for index, (start, end) in enumerate(_structural_clauses(call)):
        if index == active_index:
            continue
        if _structural_clause_has_assign(call, start, end):
            continue
        value = _decode_span_value(text[start:end])
        if value:
            values.add(value)
    return frozenset(values)


def _structural_used_names(call: _StructuralCall, active_index: int) -> frozenset[str]:
    """Collect argument keys named in clauses before the active one."""
    clauses = _structural_clauses(call)
    names: set[str] = set()
    for index in range(active_index):
        start, end = clauses[index]
        for key_start, key_end, name in call.keys_py:
            if key_start < end and key_end > start and name:
                names.add(name)
    return frozenset(names)


def _rust_span_bounds_for_cursor(
    text: str,
    ref_start_py: int,
    ref_end_py: int,
    cursor_py: int,
    call_name: str,
    spans: Sequence[Mapping[str, object]] | None = None,
) -> tuple[int, int, frozenset[str]] | None:
    """Resolve whole-value span and selected values via Rust parser spans.

    Returns Python ``(value_start, value_end, selected)`` or ``None`` when
    the spans cannot express this call. Byte spans are converted to Python
    offsets only here. Pass ``spans`` to reuse one parse across a detection.
    """
    if spans is None:
        spans = _load_argument_spans(text)
    base_end_py = _reference_base_end(text, ref_start_py, cursor_py)
    if base_end_py is None:
        return None
    call = _structural_call_for(text, spans, base_end_py, cursor_py, call_name)
    if call is None:
        return None
    matched: tuple[int, int] | None = None
    for start, end in call.values_py:
        if start <= cursor_py <= end:
            matched = (start, end)
            break
    decoded = [
        (start, end, _decode_span_value(text[start:end]))
        for start, end in call.values_py
    ]
    if matched is not None:
        selected = frozenset(
            value
            for start, end, value in decoded
            if not (start == matched[0] and end == matched[1]) and value
        )
        return matched[0], matched[1], selected
    # Empty value gap: cursor sits where no value span exists (e.g. ``env=``).
    # Treat it as an empty replacement at the cursor and select every other
    # decoded value in the call for repeatable exclusion.
    selected_all = frozenset(value for _start, _end, value in decoded if value)
    return cursor_py, cursor_py, selected_all


_REFERENCE_BASE_RE = re.compile(
    r"(?P<marker>#!|#)"
    r"(?P<name>[a-zA-Z_][a-zA-Z0-9_]*(?:/[a-zA-Z_][a-zA-Z0-9_]*)*)"
    r"(?P<hitl>!!|\?\?)?"
)


def detect_macro_arg_hint_at_cursor(
    text: str,
    cursor_offset: int,
    entries: list[MacroAssistEntry],
) -> ActiveMacroArgHint | None:
    """Resolve a typed macro argument hint at *cursor_offset*.

    Detection is intentionally narrow and only recognizes incomplete argument
    positions where the prompt bar can offer lightweight assistance without
    pretending to parse full macro semantics.
    """
    if not text or cursor_offset < 0 or cursor_offset > len(text):
        return None

    spans = _load_argument_spans(text)
    entry_by_name = _entry_by_name(entries)
    for ref in iter_macro_references(text):
        if ref.start >= cursor_offset:
            continue
        if ref.arg_kind is MacroReferenceArgKind.PLUS:
            continue

        base_end = _reference_base_end(text, ref.start, cursor_offset)
        if base_end is None:
            continue
        if not (base_end <= cursor_offset):
            continue
        if ref.end > cursor_offset and not _cursor_is_inside_reference_args(
            text, ref, base_end, cursor_offset
        ):
            continue

        entry = entry_by_name.get(ref.name)
        if entry is None or not required_inputs(entry):
            continue

        suffix = text[base_end:cursor_offset]
        call = _structural_call_for(text, spans, base_end, cursor_offset, entry.name)
        active_index = _active_input_index_for_suffix(
            suffix, entry, text, cursor_offset, call
        )
        if active_index is None:
            continue

        mode: Literal["colon", "paren"]
        mode = "paren" if suffix.startswith("(") else "colon"
        return ActiveMacroArgHint(
            entry=entry,
            reference_start=ref.start,
            reference_end=cursor_offset,
            reference_text=text[ref.start : cursor_offset],
            trigger_mode=mode,
            active_input_index=active_index,
        )
    return None


def accepted_macro_arg_hint(
    text: str,
    reference_start: int,
    reference_end: int,
    entries: list[MacroAssistEntry],
) -> ActiveMacroArgHint | None:
    """Resolve a post-accept hint for an inserted macro reference."""
    if (
        reference_start < 0
        or reference_end > len(text)
        or reference_start >= reference_end
    ):
        return None

    reference_text = text[reference_start:reference_end]
    entry_by_insertion = {entry.insertion: entry for entry in entries}
    entry = entry_by_insertion.get(reference_text)
    if entry is None or not required_inputs(entry):
        return None
    return ActiveMacroArgHint(
        entry=entry,
        reference_start=reference_start,
        reference_end=reference_end,
        reference_text=reference_text,
    )


def detect_macro_arg_completion_at_cursor(
    text: str,
    cursor_offset: int,
    entries: list[MacroAssistEntry],
) -> MacroArgCompletionContext | None:
    """Resolve a Ctrl+T completion target inside macro arguments."""
    if not text or cursor_offset < 0 or cursor_offset > len(text):
        return None
    literal_ranges = literal_zone_ranges(text)
    spans = _load_argument_spans(text)

    entry_by_name = _entry_by_name(entries)
    for ref in iter_macro_references(text):
        if ref.start >= cursor_offset:
            continue
        if any(start <= ref.start < end for start, end in literal_ranges):
            continue
        if ref.arg_kind is MacroReferenceArgKind.PLUS:
            continue
        # Double-colon shorthand consumes free-form text through the rest of its
        # parsed span. A nested ``#...`` inside that body is free text, not an
        # argument position, so hard-stop the scan when the cursor sits inside
        # or at the end of the span (``#ask:: after #fork:`` must not open the
        # fork-agent menu).
        if (
            ref.arg_kind is MacroReferenceArgKind.DOUBLE_COLON_SHORTHAND
            and ref.start < cursor_offset <= ref.end
        ):
            return None

        base_end = _reference_base_end(text, ref.start, cursor_offset)
        if base_end is None or base_end > cursor_offset:
            continue
        if ref.end > cursor_offset and not _cursor_is_inside_reference_args(
            text, ref, base_end, cursor_offset
        ):
            continue

        entry = entry_by_name.get(ref.name)
        if entry is None or not entry.inputs:
            continue

        suffix = text[base_end:cursor_offset]
        call = _structural_call_for(text, spans, base_end, cursor_offset, entry.name)
        if suffix.startswith(":"):
            ctx = _colon_completion_context(
                entry,
                text,
                base_end,
                cursor_offset,
                ref.end,
                suffix,
                call,
            )
        elif suffix.startswith("("):
            ctx = _paren_completion_context(
                entry,
                text,
                base_end,
                cursor_offset,
                ref.end,
                suffix,
                call,
            )
        else:
            continue
        # An earlier reference whose colon/paren suffix overshoots into later
        # text (e.g. ``#gh:sase`` in ``#gh:sase #fork:``) yields ``None`` here;
        # keep scanning so a real later reference at the cursor still resolves.
        if ctx is not None:
            return _with_rust_span_bounds(text, ref, cursor_offset, ctx, spans)
    return None


def _with_rust_span_bounds(
    text: str,
    ref: MacroReference,
    cursor_offset: int,
    ctx: MacroArgCompletionContext,
    spans: Sequence[Mapping[str, object]] | None = None,
) -> MacroArgCompletionContext:
    """Override value bounds with Rust parser spans for choice menus."""
    if ctx.completion_kind == "macro_arg_model":
        return _with_model_effort_span(text, cursor_offset, ctx)
    if ctx.completion_kind != "macro_arg_value" or ctx.active_input is None:
        return ctx
    # Only choice-backed inputs use structural spans; other value kinds keep
    # the existing raw boundaries.
    if not (ctx.active_input.choices or ctx.active_input.type in ("bool", "enum")):
        return ctx
    bounds = _rust_span_bounds_for_cursor(
        text, ref.start, ref.end, cursor_offset, ctx.entry.name, spans=spans
    )
    if bounds is None:
        return ctx
    value_start, value_end, selected = bounds
    # Clamp to the cursor: a span that ends before the cursor (e.g. a closed
    # value with trailing whitespace) must not move the replacement backwards.
    if value_start > cursor_offset or value_end < cursor_offset:
        return ctx
    token = text[value_start:cursor_offset]
    merged_selected = frozenset(set(ctx.selected_values) | set(selected))
    # For repeatable inputs the element under the cursor stays eligible even
    # when its decoded value also appears elsewhere in the call.
    if ctx.active_input.repeatable:
        current_decoded = _decode_span_value(text[value_start:value_end])
        if current_decoded:
            merged_selected = frozenset(
                value for value in merged_selected if value != current_decoded
            )
    return MacroArgCompletionContext(
        entry=ctx.entry,
        completion_kind=ctx.completion_kind,
        value_start=value_start,
        value_end=value_end,
        token=token,
        active_input=ctx.active_input,
        used_arg_names=ctx.used_arg_names,
        selected_values=merged_selected,
        replacement=text[value_start:value_end],
    )


def _with_model_effort_span(
    text: str,
    cursor_offset: int,
    ctx: MacroArgCompletionContext,
) -> MacroArgCompletionContext:
    """Route the suffix after a model's ``@`` to the shared effort menu."""
    at = ctx.token.rfind("@")
    if at < 0 or (ctx.token.startswith("@") and ctx.token.count("@") == 1):
        return ctx
    start = ctx.value_start + at + 1
    return replace(
        ctx,
        value_start=start,
        token=text[start:cursor_offset],
        replacement=text[start : ctx.value_end],
        model_effort=True,
    )


def _entry_by_name(
    entries: list[MacroAssistEntry],
) -> dict[str, MacroAssistEntry]:
    return {entry.name: entry for entry in entries}


def _reference_base_end(
    text: str,
    reference_start: int,
    cursor_offset: int,
) -> int | None:
    match = _REFERENCE_BASE_RE.match(text[reference_start:cursor_offset])
    if match is None:
        return None
    return reference_start + match.end()


def _cursor_is_inside_open_paren(text: str, ref: MacroReference) -> bool:
    return ref.end <= len(text) and text[ref.end - 1 : ref.end] == "("


def _cursor_is_inside_reference_args(
    text: str,
    ref: MacroReference,
    base_end: int,
    cursor_offset: int,
) -> bool:
    if _cursor_is_inside_open_paren(text, ref):
        return True
    if text[base_end : base_end + 1] == "(":
        return cursor_offset <= ref.end
    if ref.arg_kind is MacroReferenceArgKind.DOUBLE_COLON_SHORTHAND:
        return False
    return text[base_end : base_end + 1] == ":" and cursor_offset <= ref.end


def _active_input_index_for_suffix(
    suffix: str,
    entry: MacroAssistEntry,
    text: str,
    cursor_py: int,
    call: _StructuralCall | None,
) -> int | None:
    if suffix == ":":
        return 0
    if suffix.startswith(":"):
        return _colon_active_input_index(suffix, entry, cursor_py, call)
    if suffix == "(":
        return 0
    if suffix.startswith("("):
        return _paren_active_input_index(suffix, entry, text, cursor_py, call)
    return None


def _completion_kind_for_input(
    input_hint: MacroInputHint,
) -> Literal[
    "macro_arg_path",
    "macro_arg_value",
    "macro_arg_agent",
    "macro_arg_model",
    "macro_arg_type_hint",
]:
    if input_hint.named_type == "model" or input_hint.value_role == "model":
        return "macro_arg_model"
    if input_hint.type == "path":
        return "macro_arg_path"
    if (input_hint.value_role or "") == "agent" or input_hint.type == "agent":
        return "macro_arg_agent"
    if input_hint.choices or input_hint.type in ("bool", "enum"):
        return "macro_arg_value"
    return "macro_arg_type_hint"


def _empty_structural_call(cursor_py: int) -> _StructuralCall:
    """Describe an empty argument list with no spans (``#name:``/``#name(``)."""
    return _StructuralCall(
        opening_end_py=cursor_py,
        close_py=None,
        commas_py=(),
        values_py=(),
        keys_py=(),
        assigns_py=(),
        call_end_py=cursor_py,
    )


def _colon_completion_context(
    entry: MacroAssistEntry,
    text: str,
    base_end: int,
    cursor_offset: int,
    reference_end: int,
    suffix: str,
    call: _StructuralCall | None,
) -> MacroArgCompletionContext | None:
    if call is None:
        # An empty argument list parses to no spans; anything else without
        # spans cannot be completed structurally.
        if suffix != ":":
            return None
        call = _empty_structural_call(cursor_offset)
    active_index = _colon_active_input_index(suffix, entry, cursor_offset, call)
    if active_index is None:
        return None

    clauses = _structural_clauses(call)
    active = _structural_active_index(call, cursor_offset)
    value_start, clause_end = clauses[active]
    if cursor_offset == value_start:
        # The cursor sits at the start of a clause with text after it
        # (``#fork:c`` with the cursor after ``:``): the active value is
        # empty. This mirrors the core completion builder.
        value_end = cursor_offset
    else:
        # A colon value ends at whitespace; text after a gap (``#fork: bar``)
        # belongs to no value. This mirrors the core completion builder.
        value_end = clause_end
        for index in range(cursor_offset, min(clause_end, len(text))):
            if text[index].isspace():
                value_end = index
                break
    token = text[value_start:cursor_offset]
    active_input = entry.inputs[active_index]
    return MacroArgCompletionContext(
        entry=entry,
        completion_kind=_completion_kind_for_input(active_input),
        value_start=value_start,
        value_end=value_end,
        token=token,
        active_input=active_input,
        selected_values=_structural_selected_values(text, call, active),
        replacement=text[value_start:value_end],
    )


def _paren_completion_context(
    entry: MacroAssistEntry,
    text: str,
    base_end: int,
    cursor_offset: int,
    reference_end: int,
    suffix: str,
    call: _StructuralCall | None,
) -> MacroArgCompletionContext | None:
    if call is None:
        # An empty argument list parses to no spans; anything else without
        # spans cannot be completed structurally.
        if suffix != "(":
            return None
        call = _empty_structural_call(cursor_offset)
    if _structural_is_closed(call, cursor_offset):
        return None

    clauses = _structural_clauses(call)
    active = _structural_active_index(call, cursor_offset)
    clause_start, clause_end = clauses[active]
    clause = text[clause_start:clause_end]
    stripped_clause = clause.lstrip()
    leading_ws = len(clause) - len(stripped_clause)
    value_start = clause_start + leading_ws
    value_end = clause_end
    value_end = _trimmed_value_end(text, value_start, value_end)
    token = text[value_start:cursor_offset]

    if not _structural_clause_has_assign(call, clause_start, clause_end):
        if any(ch.isspace() for ch in token):
            return None
        active_index = _paren_active_input_index(
            suffix, entry, text, cursor_offset, call
        )
        if active_index is not None:
            active_input = entry.inputs[active_index]
            completion_kind = _completion_kind_for_input(active_input)
            if active_input.repeatable or len(entry.inputs) == 1:
                return MacroArgCompletionContext(
                    entry=entry,
                    completion_kind=completion_kind,
                    value_start=value_start,
                    value_end=value_end,
                    token=token,
                    active_input=active_input,
                    used_arg_names=_structural_used_names(call, active),
                    selected_values=_structural_selected_values(text, call, active),
                    replacement=text[value_start:value_end],
                )
        if len(entry.inputs) == 1:
            single_input = entry.inputs[0]
            completion_kind = _completion_kind_for_input(single_input)
            if completion_kind == "macro_arg_agent":
                return MacroArgCompletionContext(
                    entry=entry,
                    completion_kind=completion_kind,
                    value_start=value_start,
                    value_end=value_end,
                    token=token,
                    active_input=single_input,
                    used_arg_names=_structural_used_names(call, active),
                    selected_values=_structural_selected_values(text, call, active),
                    replacement=text[value_start:value_end],
                )
        return MacroArgCompletionContext(
            entry=entry,
            completion_kind="macro_arg_name",
            value_start=value_start,
            value_end=value_end,
            token=token,
            used_arg_names=_structural_used_names(call, active),
        )

    name_part, value_part = stripped_clause.split("=", 1)
    name = name_part.strip()
    named_input = _input_by_name(entry, name)
    if named_input is None:
        return None

    value_leading_ws = len(value_part) - len(value_part.lstrip())
    token_start = value_start + len(name_part) + 1 + value_leading_ws
    token = text[token_start:cursor_offset]
    return MacroArgCompletionContext(
        entry=entry,
        completion_kind=_completion_kind_for_input(named_input),
        value_start=token_start,
        value_end=value_end,
        token=token,
        active_input=named_input,
        used_arg_names=_structural_used_names(call, active),
        replacement=text[token_start:value_end],
    )


def _trimmed_value_end(text: str, start: int, end: int) -> int:
    while end > start and text[end - 1].isspace():
        end -= 1
    return end


def _colon_active_input_index(
    suffix: str,
    entry: MacroAssistEntry,
    cursor_py: int,
    call: _StructuralCall | None,
) -> int | None:
    value = suffix[1:]
    if any(ch.isspace() for ch in value):
        return None
    if "+" in value or "(" in value or ")" in value:
        return None
    if call is None:
        return None
    # Structural commas respect quotes and text blocks; a quoted comma is
    # one value, not a separator.
    count = sum(1 for comma in call.commas_py if comma < cursor_py)
    return min(count, len(entry.inputs) - 1)


def _paren_active_input_index(
    suffix: str,
    entry: MacroAssistEntry,
    text: str,
    cursor_py: int,
    call: _StructuralCall | None,
) -> int | None:
    body = suffix[1:]
    if not body:
        return 0
    if call is None:
        return None
    if _structural_is_closed(call, cursor_py):
        return None

    clauses = _structural_clauses(call)
    active = _structural_active_index(call, cursor_py)
    clause_start, clause_end = clauses[active]
    if _structural_clause_has_assign(call, clause_start, clause_end):
        name = _structural_clause_key(call, clause_start, clause_end)
        if name is None:
            return None
        for index, inp in enumerate(entry.inputs):
            if inp.name == name:
                return index
        return None

    if any(ch.isspace() for ch in text[clause_start:clause_end].strip()):
        return None
    positional_index = sum(
        1
        for index in range(active)
        if not _structural_clause_has_assign(call, *clauses[index])
    )
    if positional_index < len(entry.inputs):
        candidate = entry.inputs[positional_index]
        return positional_index if candidate.repeatable else None
    if entry.inputs and entry.inputs[-1].repeatable:
        return len(entry.inputs) - 1
    return None


def _input_by_name(
    entry: MacroAssistEntry,
    name: str,
) -> MacroInputHint | None:
    for inp in entry.inputs:
        if inp.name == name:
            return inp
    return None


__all__ = [
    "accepted_macro_arg_hint",
    "detect_macro_arg_completion_at_cursor",
    "detect_macro_arg_hint_at_cursor",
]
