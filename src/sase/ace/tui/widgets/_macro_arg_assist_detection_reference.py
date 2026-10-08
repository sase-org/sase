"""Reference and active-input helpers for macro argument assist."""

from __future__ import annotations

import re
from typing import Literal

from sase.macro._parsing import MacroReference, MacroReferenceArgKind

from ._macro_arg_assist_detection_structural import (
    StructuralCall,
    structural_active_index,
    structural_clause_has_assign,
    structural_clause_key,
    structural_clauses,
    structural_is_closed,
)
from ._macro_arg_assist_models import MacroAssistEntry, MacroInputHint

_REFERENCE_BASE_RE = re.compile(
    r"(?P<marker>#!|#)"
    r"(?P<name>[a-zA-Z_][a-zA-Z0-9_]*(?:/[a-zA-Z_][a-zA-Z0-9_]*)*)"
    r"(?P<hitl>!!|\?\?)?"
)


def entry_by_name(
    entries: list[MacroAssistEntry],
) -> dict[str, MacroAssistEntry]:
    """Map assist entries by macro name."""
    return {entry.name: entry for entry in entries}


def reference_base_end(
    text: str,
    reference_start: int,
    cursor_offset: int,
) -> int | None:
    """Return the end of the ``#name`` base before arguments, if parseable."""
    match = _REFERENCE_BASE_RE.match(text[reference_start:cursor_offset])
    if match is None:
        return None
    return reference_start + match.end()


def _cursor_is_inside_open_paren(text: str, ref: MacroReference) -> bool:
    return ref.end <= len(text) and text[ref.end - 1 : ref.end] == "("


def cursor_is_inside_reference_args(
    text: str,
    ref: MacroReference,
    base_end: int,
    cursor_offset: int,
) -> bool:
    """Return whether the cursor sits inside the reference's arguments."""
    if _cursor_is_inside_open_paren(text, ref):
        return True
    if text[base_end : base_end + 1] == "(":
        return cursor_offset <= ref.end
    if ref.arg_kind is MacroReferenceArgKind.DOUBLE_COLON_SHORTHAND:
        return False
    return text[base_end : base_end + 1] == ":" and cursor_offset <= ref.end


def completion_kind_for_input(
    input_hint: MacroInputHint,
) -> Literal[
    "macro_arg_path",
    "macro_arg_value",
    "macro_arg_agent",
    "macro_arg_model",
    "macro_arg_type_hint",
]:
    """Map an input hint to its completion menu kind."""
    if input_hint.named_type == "model" or input_hint.value_role == "model":
        return "macro_arg_model"
    if input_hint.type == "path":
        return "macro_arg_path"
    if (input_hint.value_role or "") == "agent" or input_hint.type == "agent":
        return "macro_arg_agent"
    if input_hint.choices or input_hint.type in ("bool", "enum"):
        return "macro_arg_value"
    return "macro_arg_type_hint"


def empty_structural_call(cursor_py: int) -> StructuralCall:
    """Describe an empty argument list with no spans (``#name:``/``#name(``)."""
    return StructuralCall(
        opening_end_py=cursor_py,
        close_py=None,
        commas_py=(),
        values_py=(),
        keys_py=(),
        assigns_py=(),
        call_end_py=cursor_py,
    )


def trimmed_value_end(text: str, start: int, end: int) -> int:
    """Trim trailing whitespace from a value range."""
    while end > start and text[end - 1].isspace():
        end -= 1
    return end


def colon_active_input_index(
    suffix: str,
    entry: MacroAssistEntry,
    cursor_py: int,
    call: StructuralCall | None,
) -> int | None:
    """Return the active input index for a colon suffix, if recognized."""
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


def paren_active_input_index(
    suffix: str,
    entry: MacroAssistEntry,
    text: str,
    cursor_py: int,
    call: StructuralCall | None,
) -> int | None:
    """Return the active input index for a paren suffix, if recognized."""
    body = suffix[1:]
    if not body:
        return 0
    if call is None:
        return None
    if structural_is_closed(call, cursor_py):
        return None

    clauses = structural_clauses(call)
    active = structural_active_index(call, cursor_py)
    clause_start, clause_end = clauses[active]
    if structural_clause_has_assign(call, clause_start, clause_end):
        name = structural_clause_key(call, clause_start, clause_end)
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
        if not structural_clause_has_assign(call, *clauses[index])
    )
    if positional_index < len(entry.inputs):
        candidate = entry.inputs[positional_index]
        return positional_index if candidate.repeatable else None
    if entry.inputs and entry.inputs[-1].repeatable:
        return len(entry.inputs) - 1
    return None


def active_input_index_for_suffix(
    suffix: str,
    entry: MacroAssistEntry,
    text: str,
    cursor_py: int,
    call: StructuralCall | None,
) -> int | None:
    """Dispatch a ``:``/``(`` suffix to its active-input resolver."""
    if suffix == ":":
        return 0
    if suffix.startswith(":"):
        return colon_active_input_index(suffix, entry, cursor_py, call)
    if suffix == "(":
        return 0
    if suffix.startswith("("):
        return paren_active_input_index(suffix, entry, text, cursor_py, call)
    return None


def input_by_name(
    entry: MacroAssistEntry,
    name: str,
) -> MacroInputHint | None:
    """Return the named input hint for an entry, if present."""
    for inp in entry.inputs:
        if inp.name == name:
            return inp
    return None


__all__ = [
    "active_input_index_for_suffix",
    "colon_active_input_index",
    "completion_kind_for_input",
    "cursor_is_inside_reference_args",
    "empty_structural_call",
    "entry_by_name",
    "input_by_name",
    "paren_active_input_index",
    "reference_base_end",
    "trimmed_value_end",
]
