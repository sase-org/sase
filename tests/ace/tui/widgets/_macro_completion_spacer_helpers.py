"""Shared fixtures for macro completion spacer tests."""

from __future__ import annotations

from sase.ace.tui.widgets.macro_arg_assist import MacroAssistEntry, MacroInputHint
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea


def input_hint(
    name: str,
    type_: str,
    *,
    required: bool,
    position: int = 0,
) -> MacroInputHint:
    return MacroInputHint(
        name=name,
        type=type_,
        required=required,
        default_display=None,
        position=position,
    )


def macro_entry(
    name: str,
    *,
    prefix: str = "#",
    inputs: tuple[MacroInputHint, ...] = (),
) -> MacroAssistEntry:
    return MacroAssistEntry(
        name=name,
        insertion=f"{prefix}{name}",
        reference_prefix=prefix,
        kind="macro",
        input_signature=None,
        inputs=inputs,
        content_preview=None,
    )


def seed_entries(
    ta: PromptTextArea,
    entries: list[MacroAssistEntry],
    project: str | None = None,
) -> None:
    ta._macro_arg_assist_entries_by_project[project] = entries
