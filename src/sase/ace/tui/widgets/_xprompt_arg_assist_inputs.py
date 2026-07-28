"""Input hint rendering and conversion helpers for xprompt argument assist."""

from __future__ import annotations

from rich.text import Text

from sase.xprompt.models import UNSET, InputArg

from ._xprompt_arg_assist_models import XPromptAssistEntry, XPromptInputHint

_INPUT_INDENT = "\n     "
_REQUIRED_INPUT_STYLE = "#D7AF87"
_OPTIONAL_INPUT_STYLE = "dim #D7AF87"
_DEFAULT_STYLE = "dim #888888"


def visible_inputs(entry: XPromptAssistEntry) -> tuple[XPromptInputHint, ...]:
    """Return user-facing inputs for an assist entry."""
    return entry.inputs


def required_inputs(entry: XPromptAssistEntry) -> tuple[XPromptInputHint, ...]:
    """Return required user-facing inputs for an assist entry."""
    return tuple(inp for inp in entry.inputs if inp.required)


def has_no_required_inputs(entry: XPromptAssistEntry) -> bool:
    """Return True when an entry has no required user-facing inputs."""
    return not any(inp.required for inp in entry.inputs)


def has_only_optional_inputs(entry: XPromptAssistEntry) -> bool:
    """Return True when an entry has inputs and all of them are optional.

    Optional-only xprompts complete to ``#name `` (a trailing spacer) exactly
    like no-input xprompts, but only optional-only ones should let a following
    ``:`` replace that spacer -- a no-input xprompt has no arguments to
    introduce, so its trailing space must be left untouched.
    """
    return bool(entry.inputs) and has_no_required_inputs(entry)


def input_label(input_hint: XPromptInputHint) -> str:
    """Format a compact input label for non-Rich assist surfaces."""
    required_marker = "" if input_hint.required else "?"
    repeatable_marker = "…" if input_hint.repeatable else ""
    return f"{input_hint.name}{repeatable_marker}{required_marker}: {input_hint.type}"


def append_input_hints(
    text: Text,
    inputs: tuple[XPromptInputHint, ...],
    *,
    include_types: bool = True,
    active_index: int | None = None,
    include_descriptions: bool = False,
) -> None:
    """Append styled user-facing input hints to a Rich Text label."""
    for index, inp in enumerate(inputs):
        if active_index is None:
            text.append(_INPUT_INDENT)
        elif index == active_index:
            text.append("\n  ▸  ", style="bold")
        else:
            text.append(_INPUT_INDENT)
        text.append(
            _styled_input_label(inp, include_types), style=_input_name_style(inp)
        )
        if not inp.required:
            text.append(_default_suffix(inp), style=_DEFAULT_STYLE)
        if include_descriptions and inp.description:
            text.append(" - ", style=_DEFAULT_STYLE)
            text.append(inp.description, style=_DEFAULT_STYLE)


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
        repeatable=inp.repeatable,
        description=inp.description,
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


__all__ = [
    "append_input_args",
    "append_input_hints",
    "has_no_required_inputs",
    "has_only_optional_inputs",
    "input_hint_from_input_arg",
    "input_label",
    "required_inputs",
    "visible_inputs",
]
