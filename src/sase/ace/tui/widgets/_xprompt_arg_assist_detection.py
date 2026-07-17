"""Cursor detection helpers for xprompt argument assist."""

from __future__ import annotations

import re
from typing import Literal

from sase.xprompt._parsing import (
    XPromptReference,
    XPromptReferenceArgKind,
    iter_xprompt_references,
)

from ._xprompt_arg_assist_inputs import required_inputs
from ._xprompt_arg_assist_models import (
    ActiveXPromptArgHint,
    XPromptArgCompletionContext,
    XPromptAssistEntry,
    XPromptInputHint,
)

_REFERENCE_BASE_RE = re.compile(
    r"(?P<marker>#!|#)"
    r"(?P<name>[a-zA-Z_][a-zA-Z0-9_]*(?:/[a-zA-Z_][a-zA-Z0-9_]*)*)"
    r"(?P<hitl>!!|\?\?)?"
)
_NAMED_ARG_CURSOR_RE = re.compile(
    r"(?:^|,)\s*(?P<name>[a-zA-Z_][a-zA-Z0-9_]*)\s*=\s*[^,]*$"
)


def detect_xprompt_arg_hint_at_cursor(
    text: str,
    cursor_offset: int,
    entries: list[XPromptAssistEntry],
) -> ActiveXPromptArgHint | None:
    """Resolve a typed xprompt argument hint at *cursor_offset*.

    Detection is intentionally narrow and only recognizes incomplete argument
    positions where the prompt bar can offer lightweight assistance without
    pretending to parse full xprompt semantics.
    """
    if not text or cursor_offset < 0 or cursor_offset > len(text):
        return None

    entry_by_name = _entry_by_name(entries)
    for ref in iter_xprompt_references(text):
        if ref.start >= cursor_offset:
            continue
        if ref.arg_kind is XPromptReferenceArgKind.PLUS:
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
        active_index = _active_input_index_for_suffix(suffix, entry)
        if active_index is None:
            continue

        mode: Literal["colon", "paren"]
        mode = "paren" if suffix.startswith("(") else "colon"
        return ActiveXPromptArgHint(
            entry=entry,
            reference_start=ref.start,
            reference_end=cursor_offset,
            reference_text=text[ref.start : cursor_offset],
            trigger_mode=mode,
            active_input_index=active_index,
        )
    return None


def accepted_xprompt_arg_hint(
    text: str,
    reference_start: int,
    reference_end: int,
    entries: list[XPromptAssistEntry],
) -> ActiveXPromptArgHint | None:
    """Resolve a post-accept hint for an inserted xprompt reference."""
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
    return ActiveXPromptArgHint(
        entry=entry,
        reference_start=reference_start,
        reference_end=reference_end,
        reference_text=reference_text,
    )


def detect_xprompt_arg_completion_at_cursor(
    text: str,
    cursor_offset: int,
    entries: list[XPromptAssistEntry],
) -> XPromptArgCompletionContext | None:
    """Resolve a Ctrl+T completion target inside xprompt arguments."""
    if not text or cursor_offset < 0 or cursor_offset > len(text):
        return None

    entry_by_name = _entry_by_name(entries)
    for ref in iter_xprompt_references(text):
        if ref.start >= cursor_offset:
            continue
        if ref.arg_kind is XPromptReferenceArgKind.PLUS:
            continue
        # Double-colon shorthand consumes free-form text through the rest of its
        # parsed span. A nested ``#...`` inside that body is free text, not an
        # argument position, so hard-stop the scan when the cursor sits inside
        # or at the end of the span (``#ask:: after #fork:`` must not open the
        # fork-agent menu).
        if (
            ref.arg_kind is XPromptReferenceArgKind.DOUBLE_COLON_SHORTHAND
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
        if suffix.startswith(":"):
            ctx = _colon_completion_context(entry, base_end, suffix)
        elif suffix.startswith("("):
            ctx = _paren_completion_context(entry, base_end, suffix)
        else:
            continue
        # An earlier reference whose colon/paren suffix overshoots into later
        # text (e.g. ``#gh:sase`` in ``#gh:sase #fork:``) yields ``None`` here;
        # keep scanning so a real later reference at the cursor still resolves.
        if ctx is not None:
            return ctx
    return None


def _entry_by_name(
    entries: list[XPromptAssistEntry],
) -> dict[str, XPromptAssistEntry]:
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


def _cursor_is_inside_open_paren(text: str, ref: XPromptReference) -> bool:
    return ref.end <= len(text) and text[ref.end - 1 : ref.end] == "("


def _cursor_is_inside_reference_args(
    text: str,
    ref: XPromptReference,
    base_end: int,
    cursor_offset: int,
) -> bool:
    if _cursor_is_inside_open_paren(text, ref):
        return True
    if text[base_end : base_end + 1] == "(":
        return cursor_offset <= ref.end
    if ref.arg_kind is XPromptReferenceArgKind.DOUBLE_COLON_SHORTHAND:
        return False
    return text[base_end : base_end + 1] == ":" and cursor_offset <= ref.end


def _active_input_index_for_suffix(
    suffix: str,
    entry: XPromptAssistEntry,
) -> int | None:
    if suffix == ":":
        return 0
    if suffix.startswith(":"):
        return _colon_active_input_index(suffix, entry)
    if suffix == "(":
        return 0
    if suffix.startswith("("):
        return _paren_active_input_index(suffix, entry)
    return None


def _completion_kind_for_input(
    input_hint: XPromptInputHint,
) -> Literal[
    "xprompt_arg_path",
    "xprompt_arg_value",
    "xprompt_arg_agent",
    "xprompt_arg_type_hint",
]:
    if input_hint.type == "path":
        return "xprompt_arg_path"
    if input_hint.type == "bool":
        return "xprompt_arg_value"
    if input_hint.type == "agent":
        return "xprompt_arg_agent"
    return "xprompt_arg_type_hint"


def _colon_completion_context(
    entry: XPromptAssistEntry,
    base_end: int,
    suffix: str,
) -> XPromptArgCompletionContext | None:
    active_index = _colon_active_input_index(suffix, entry)
    if active_index is None:
        return None

    body = suffix[1:]
    value_start = base_end + 1
    if "," in body:
        last_comma = body.rfind(",")
        value_start += last_comma + 1
    value_end = base_end + len(suffix)
    token = suffix[value_start - base_end :]
    active_input = entry.inputs[active_index]
    return XPromptArgCompletionContext(
        entry=entry,
        completion_kind=_completion_kind_for_input(active_input),
        value_start=value_start,
        value_end=value_end,
        token=token,
        active_input=active_input,
    )


def _paren_completion_context(
    entry: XPromptAssistEntry,
    base_end: int,
    suffix: str,
) -> XPromptArgCompletionContext | None:
    body = suffix[1:]
    if ")" in body:
        return None

    clause_start = body.rfind(",") + 1
    clause = body[clause_start:]
    stripped_clause = clause.lstrip()
    leading_ws = len(clause) - len(stripped_clause)
    value_start = base_end + 1 + clause_start + leading_ws
    value_end = base_end + len(suffix)

    if "=" not in stripped_clause:
        if any(ch.isspace() for ch in stripped_clause):
            return None
        if len(entry.inputs) == 1:
            single_input = entry.inputs[0]
            completion_kind = _completion_kind_for_input(single_input)
            if completion_kind == "xprompt_arg_agent":
                return XPromptArgCompletionContext(
                    entry=entry,
                    completion_kind=completion_kind,
                    value_start=value_start,
                    value_end=value_end,
                    token=stripped_clause,
                    active_input=single_input,
                    used_arg_names=_used_named_arg_names(body[:clause_start]),
                )
        return XPromptArgCompletionContext(
            entry=entry,
            completion_kind="xprompt_arg_name",
            value_start=value_start,
            value_end=value_end,
            token=stripped_clause,
            used_arg_names=_used_named_arg_names(body[:clause_start]),
        )

    name_part, value_part = stripped_clause.split("=", 1)
    name = name_part.strip()
    named_input = _input_by_name(entry, name)
    if named_input is None:
        return None

    value_leading_ws = len(value_part) - len(value_part.lstrip())
    token_start = value_start + len(name_part) + 1 + value_leading_ws
    token = value_part.lstrip()
    return XPromptArgCompletionContext(
        entry=entry,
        completion_kind=_completion_kind_for_input(named_input),
        value_start=token_start,
        value_end=value_end,
        token=token,
        active_input=named_input,
        used_arg_names=_used_named_arg_names(body[:clause_start]),
    )


def _used_named_arg_names(body_prefix: str) -> frozenset[str]:
    names: set[str] = set()
    for clause in body_prefix.split(","):
        if "=" not in clause:
            continue
        name = clause.split("=", 1)[0].strip()
        if name:
            names.add(name)
    return frozenset(names)


def _colon_active_input_index(
    suffix: str,
    entry: XPromptAssistEntry,
) -> int | None:
    value = suffix[1:]
    if any(ch.isspace() for ch in value):
        return None
    if "+" in value or "(" in value or ")" in value:
        return None
    return min(value.count(","), len(entry.inputs) - 1)


def _paren_active_input_index(
    suffix: str,
    entry: XPromptAssistEntry,
) -> int | None:
    body = suffix[1:]
    if ")" in body:
        return None
    if not body:
        return 0

    match = _NAMED_ARG_CURSOR_RE.search(body)
    if match is None:
        clauses = body.split(",")
        if "=" in clauses[-1] or any(ch.isspace() for ch in clauses[-1].strip()):
            return None
        positional_index = sum(1 for clause in clauses[:-1] if "=" not in clause)
        if positional_index < len(entry.inputs):
            candidate = entry.inputs[positional_index]
            return positional_index if candidate.repeatable else None
        if entry.inputs and entry.inputs[-1].repeatable:
            return len(entry.inputs) - 1
        return None

    name = match.group("name")
    for index, inp in enumerate(entry.inputs):
        if inp.name == name:
            return index
    return None


def _input_by_name(
    entry: XPromptAssistEntry,
    name: str,
) -> XPromptInputHint | None:
    for inp in entry.inputs:
        if inp.name == name:
            return inp
    return None


__all__ = [
    "accepted_xprompt_arg_hint",
    "detect_xprompt_arg_completion_at_cursor",
    "detect_xprompt_arg_hint_at_cursor",
]
