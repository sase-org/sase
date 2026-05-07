"""Pure xprompt argument assist models and render helpers for the TUI."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Literal

from rich.text import Text

from sase.xprompt._parsing import (
    XPromptReference,
    XPromptReferenceArgKind,
    iter_xprompt_references,
)
from sase.xprompt.catalog import build_structured_xprompts_catalog
from sase.xprompt.models import UNSET, InputArg

_INPUT_INDENT = "\n     "
_REQUIRED_INPUT_STYLE = "#D7AF87"
_OPTIONAL_INPUT_STYLE = "dim #D7AF87"
_DEFAULT_STYLE = "dim #888888"
_REFERENCE_BASE_RE = re.compile(
    r"(?P<marker>#!|#)"
    r"(?P<name>[a-zA-Z_][a-zA-Z0-9_]*(?:/[a-zA-Z_][a-zA-Z0-9_]*)*)"
    r"(?P<hitl>!!|\?\?)?"
)
_NAMED_ARG_CURSOR_RE = re.compile(
    r"(?:^|,)\s*(?P<name>[a-zA-Z_][a-zA-Z0-9_]*)\s*=\s*[^,]*$"
)


@dataclass(frozen=True, slots=True)
class XPromptInputHint:
    """User-facing structured xprompt input metadata."""

    name: str
    type: str
    required: bool
    default_display: str | None
    position: int


@dataclass(frozen=True, slots=True)
class XPromptAssistEntry:
    """TUI-facing xprompt catalog entry used for inline assist surfaces."""

    name: str
    insertion: str
    reference_prefix: str
    kind: str
    input_signature: str | None
    inputs: tuple[XPromptInputHint, ...]
    content_preview: str | None


@dataclass(frozen=True, slots=True)
class ActiveXPromptArgHint:
    """An active argument hint resolved at a prompt cursor position."""

    entry: XPromptAssistEntry
    reference_start: int
    reference_end: int
    reference_text: str
    trigger_mode: Literal["accepted", "colon", "paren"] = "accepted"
    active_input_index: int = 0


@dataclass(frozen=True, slots=True)
class XPromptArgCompletionContext:
    """Completion target resolved inside an xprompt argument list."""

    entry: XPromptAssistEntry
    completion_kind: Literal[
        "xprompt_arg_path",
        "xprompt_arg_value",
        "xprompt_arg_name",
        "xprompt_arg_type_hint",
    ]
    value_start: int
    value_end: int
    token: str
    active_input: XPromptInputHint | None = None
    used_arg_names: frozenset[str] = frozenset()


def build_xprompt_assist_entries(
    project: str | None = None,
) -> list[XPromptAssistEntry]:
    """Build immutable TUI assist entries from the structured xprompt catalog."""
    projection = build_structured_xprompts_catalog(project=project)
    return [
        XPromptAssistEntry(
            name=entry.name,
            insertion=entry.insertion,
            reference_prefix=entry.reference_prefix,
            kind=entry.kind,
            input_signature=entry.input_signature,
            inputs=tuple(
                XPromptInputHint(
                    name=inp.name,
                    type=inp.type,
                    required=inp.required,
                    default_display=inp.default_display,
                    position=inp.position,
                )
                for inp in entry.inputs
            ),
            content_preview=entry.content_preview,
        )
        for entry in projection.entries
    ]


def visible_inputs(entry: XPromptAssistEntry) -> tuple[XPromptInputHint, ...]:
    """Return user-facing inputs for an assist entry."""
    return entry.inputs


def required_inputs(entry: XPromptAssistEntry) -> tuple[XPromptInputHint, ...]:
    """Return required user-facing inputs for an assist entry."""
    return tuple(inp for inp in entry.inputs if inp.required)


def named_args_skeleton(entry: XPromptAssistEntry) -> str:
    """Return a required-only named-argument snippet skeleton."""
    inputs = required_inputs(entry)
    if not inputs:
        return entry.insertion
    args = ", ".join(f"{inp.name}=${index}" for index, inp in enumerate(inputs, 1))
    return f"{entry.insertion}({args})$0"


def colon_args_skeleton(entry: XPromptAssistEntry) -> str:
    """Return a colon-argument snippet skeleton for the entry."""
    return f"{entry.insertion}:$0"


def input_label(input_hint: XPromptInputHint) -> str:
    """Format a compact input label for non-Rich assist surfaces."""
    required_marker = "" if input_hint.required else "?"
    return f"{input_hint.name}{required_marker}: {input_hint.type}"


def append_input_hints(
    text: Text,
    inputs: tuple[XPromptInputHint, ...],
    *,
    include_types: bool = True,
    active_index: int | None = None,
) -> None:
    """Append styled user-facing input hints to a Rich Text label."""
    for index, inp in enumerate(inputs):
        if active_index is None:
            text.append(_INPUT_INDENT)
        elif index == active_index:
            text.append("\n  \u25b8  ", style="bold")
        else:
            text.append(_INPUT_INDENT)
        text.append(
            _styled_input_label(inp, include_types), style=_input_name_style(inp)
        )
        if not inp.required:
            text.append(_default_suffix(inp), style=_DEFAULT_STYLE)


def input_hint_from_input_arg(inp: InputArg, position: int) -> XPromptInputHint | None:
    """Convert a workflow input arg to a TUI input hint, filtering step inputs."""
    if inp.is_step_input:
        return None
    required = inp.default is UNSET
    return XPromptInputHint(
        name=inp.name,
        type=inp.type.value,
        required=required,
        default_display=_default_display_from_input_arg(inp),
        position=position,
    )


def append_input_args(text: Text, inputs: list[InputArg]) -> None:
    """Append styled user-facing workflow input args to a Rich Text label."""
    hints: list[XPromptInputHint] = []
    for inp in inputs:
        hint = input_hint_from_input_arg(inp, len(hints))
        if hint is not None:
            hints.append(hint)
    append_input_hints(text, tuple(hints), include_types=False)


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
        if ref.end > cursor_offset and not _cursor_is_inside_open_paren(text, ref):
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
            return _colon_completion_context(entry, base_end, suffix)
        if suffix.startswith("("):
            return _paren_completion_context(entry, base_end, suffix)
    return None


def _input_name_style(input_hint: XPromptInputHint) -> str:
    return _REQUIRED_INPUT_STYLE if input_hint.required else _OPTIONAL_INPUT_STYLE


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
    return text[base_end : base_end + 1] == "(" and cursor_offset <= ref.end


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
) -> Literal["xprompt_arg_path", "xprompt_arg_value", "xprompt_arg_type_hint"]:
    if input_hint.type == "path":
        return "xprompt_arg_path"
    if input_hint.type == "bool":
        return "xprompt_arg_value"
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
    active_input = _input_by_name(entry, name)
    if active_input is None:
        return None

    value_leading_ws = len(value_part) - len(value_part.lstrip())
    token_start = value_start + len(name_part) + 1 + value_leading_ws
    token = value_part.lstrip()
    return XPromptArgCompletionContext(
        entry=entry,
        completion_kind=_completion_kind_for_input(active_input),
        value_start=token_start,
        value_end=value_end,
        token=token,
        active_input=active_input,
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
        return None

    name = match.group("name")
    for index, inp in enumerate(entry.inputs):
        if inp.name == name:
            return index
    return None


def _styled_input_label(input_hint: XPromptInputHint, include_types: bool) -> str:
    if include_types:
        return input_label(input_hint)
    return input_hint.name


def _default_suffix(input_hint: XPromptInputHint) -> str:
    if input_hint.default_display:
        return f"={input_hint.default_display}"
    return "?"


def _default_display_from_input_arg(inp: InputArg) -> str | None:
    default = inp.default
    if default is UNSET or default is None:
        return None
    default_text = str(default)
    if default_text == "":
        return None
    return default_text


def _input_by_name(
    entry: XPromptAssistEntry,
    name: str,
) -> XPromptInputHint | None:
    for inp in entry.inputs:
        if inp.name == name:
            return inp
    return None
