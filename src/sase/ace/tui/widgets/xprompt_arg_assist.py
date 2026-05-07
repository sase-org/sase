"""Pure xprompt argument assist models and render helpers for the TUI."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from rich.text import Text

from sase.xprompt.catalog import build_structured_xprompts_catalog
from sase.xprompt.models import UNSET, InputArg

_INPUT_INDENT = "\n     "
_REQUIRED_INPUT_STYLE = "#D7AF87"
_OPTIONAL_INPUT_STYLE = "dim #D7AF87"
_DEFAULT_STYLE = "dim #888888"


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


def _input_name_style(input_hint: XPromptInputHint) -> str:
    return _REQUIRED_INPUT_STYLE if input_hint.required else _OPTIONAL_INPUT_STYLE


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
