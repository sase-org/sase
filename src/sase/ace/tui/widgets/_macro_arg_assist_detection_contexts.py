"""Completion contexts and cursor detectors for macro argument assist."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Literal

from sase.macro._parsing import (
    MacroReference,
    MacroReferenceArgKind,
    iter_macro_references,
)
from sase.macro._literal_zones import literal_zone_ranges

from ._macro_arg_assist_detection_reference import (
    active_input_index_for_suffix,
    colon_active_input_index,
    completion_kind_for_input,
    cursor_is_inside_reference_args,
    empty_structural_call,
    entry_by_name,
    input_by_name,
    paren_active_input_index,
    reference_base_end,
    trimmed_value_end,
)
from ._macro_arg_assist_detection_structural import (
    StructuralCall,
    decode_span_value,
    load_argument_spans,
    structural_active_index,
    structural_call_for,
    structural_clause_has_assign,
    structural_clauses,
    structural_is_closed,
    structural_selected_values,
    structural_used_names,
)
from ._macro_arg_assist_inputs import required_inputs
from ._macro_arg_assist_models import (
    ActiveMacroArgHint,
    MacroArgCompletionContext,
    MacroAssistEntry,
)


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
        spans = load_argument_spans(text)
    base_end_py = reference_base_end(text, ref_start_py, cursor_py)
    if base_end_py is None:
        return None
    call = structural_call_for(text, spans, base_end_py, cursor_py, call_name)
    if call is None:
        return None
    matched: tuple[int, int] | None = None
    for start, end in call.values_py:
        if start <= cursor_py <= end:
            matched = (start, end)
            break
    decoded = [
        (start, end, decode_span_value(text[start:end]))
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

    spans = load_argument_spans(text)
    by_name = entry_by_name(entries)
    for ref in iter_macro_references(text):
        if ref.start >= cursor_offset:
            continue
        if ref.arg_kind is MacroReferenceArgKind.PLUS:
            continue

        base_end = reference_base_end(text, ref.start, cursor_offset)
        if base_end is None:
            continue
        if not (base_end <= cursor_offset):
            continue
        if ref.end > cursor_offset and not cursor_is_inside_reference_args(
            text, ref, base_end, cursor_offset
        ):
            continue

        entry = by_name.get(ref.name)
        if entry is None or not required_inputs(entry):
            continue

        suffix = text[base_end:cursor_offset]
        call = structural_call_for(text, spans, base_end, cursor_offset, entry.name)
        active_index = active_input_index_for_suffix(
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
    spans = load_argument_spans(text)

    by_name = entry_by_name(entries)
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

        base_end = reference_base_end(text, ref.start, cursor_offset)
        if base_end is None or base_end > cursor_offset:
            continue
        if ref.end > cursor_offset and not cursor_is_inside_reference_args(
            text, ref, base_end, cursor_offset
        ):
            continue

        entry = by_name.get(ref.name)
        if entry is None or not entry.inputs:
            continue

        suffix = text[base_end:cursor_offset]
        call = structural_call_for(text, spans, base_end, cursor_offset, entry.name)
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
        current_decoded = decode_span_value(text[value_start:value_end])
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


def _colon_completion_context(
    entry: MacroAssistEntry,
    text: str,
    base_end: int,
    cursor_offset: int,
    reference_end: int,
    suffix: str,
    call: StructuralCall | None,
) -> MacroArgCompletionContext | None:
    if call is None:
        # An empty argument list parses to no spans; anything else without
        # spans cannot be completed structurally.
        if suffix != ":":
            return None
        call = empty_structural_call(cursor_offset)
    active_index = colon_active_input_index(suffix, entry, cursor_offset, call)
    if active_index is None:
        return None

    clauses = structural_clauses(call)
    active = structural_active_index(call, cursor_offset)
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
        completion_kind=completion_kind_for_input(active_input),
        value_start=value_start,
        value_end=value_end,
        token=token,
        active_input=active_input,
        selected_values=structural_selected_values(text, call, active),
        replacement=text[value_start:value_end],
    )


def _paren_completion_context(
    entry: MacroAssistEntry,
    text: str,
    base_end: int,
    cursor_offset: int,
    reference_end: int,
    suffix: str,
    call: StructuralCall | None,
) -> MacroArgCompletionContext | None:
    if call is None:
        # An empty argument list parses to no spans; anything else without
        # spans cannot be completed structurally.
        if suffix != "(":
            return None
        call = empty_structural_call(cursor_offset)
    if structural_is_closed(call, cursor_offset):
        return None

    clauses = structural_clauses(call)
    active = structural_active_index(call, cursor_offset)
    clause_start, clause_end = clauses[active]
    clause = text[clause_start:clause_end]
    stripped_clause = clause.lstrip()
    leading_ws = len(clause) - len(stripped_clause)
    value_start = clause_start + leading_ws
    value_end = clause_end
    value_end = trimmed_value_end(text, value_start, value_end)
    token = text[value_start:cursor_offset]

    if not structural_clause_has_assign(call, clause_start, clause_end):
        if any(ch.isspace() for ch in token):
            return None
        active_index = paren_active_input_index(
            suffix, entry, text, cursor_offset, call
        )
        if active_index is not None:
            active_input = entry.inputs[active_index]
            completion_kind = completion_kind_for_input(active_input)
            if active_input.repeatable or len(entry.inputs) == 1:
                return MacroArgCompletionContext(
                    entry=entry,
                    completion_kind=completion_kind,
                    value_start=value_start,
                    value_end=value_end,
                    token=token,
                    active_input=active_input,
                    used_arg_names=structural_used_names(call, active),
                    selected_values=structural_selected_values(text, call, active),
                    replacement=text[value_start:value_end],
                )
        if len(entry.inputs) == 1:
            single_input = entry.inputs[0]
            completion_kind = completion_kind_for_input(single_input)
            if completion_kind == "macro_arg_agent":
                return MacroArgCompletionContext(
                    entry=entry,
                    completion_kind=completion_kind,
                    value_start=value_start,
                    value_end=value_end,
                    token=token,
                    active_input=single_input,
                    used_arg_names=structural_used_names(call, active),
                    selected_values=structural_selected_values(text, call, active),
                    replacement=text[value_start:value_end],
                )
        return MacroArgCompletionContext(
            entry=entry,
            completion_kind="macro_arg_name",
            value_start=value_start,
            value_end=value_end,
            token=token,
            used_arg_names=structural_used_names(call, active),
        )

    name_part, value_part = stripped_clause.split("=", 1)
    name = name_part.strip()
    named_input = input_by_name(entry, name)
    if named_input is None:
        return None

    value_leading_ws = len(value_part) - len(value_part.lstrip())
    token_start = value_start + len(name_part) + 1 + value_leading_ws
    token = text[token_start:cursor_offset]
    return MacroArgCompletionContext(
        entry=entry,
        completion_kind=completion_kind_for_input(named_input),
        value_start=token_start,
        value_end=value_end,
        token=token,
        active_input=named_input,
        used_arg_names=structural_used_names(call, active),
        replacement=text[token_start:value_end],
    )


__all__ = [
    "accepted_macro_arg_hint",
    "detect_macro_arg_completion_at_cursor",
    "detect_macro_arg_hint_at_cursor",
]
