"""Shared public helpers for prompt catalog tests."""

from __future__ import annotations

from sase.ace.tui.widgets.macro_arg_assist import MacroAssistEntry


def entry(name: str) -> MacroAssistEntry:
    return MacroAssistEntry(
        name=name,
        insertion=f"#{name}",
        reference_prefix="#",
        kind="xprompt",
        input_signature=None,
        inputs=(),
        content_preview=None,
    )
