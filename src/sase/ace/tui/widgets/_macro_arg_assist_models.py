"""Data models for macro argument assist surfaces."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sase.macro.models import InputChoice, MemoryType


@dataclass(frozen=True, slots=True)
class MacroInputHint:
    """User-facing structured macro input metadata."""

    name: str
    type: str
    required: bool
    default_display: str | None
    position: int
    repeatable: bool = False
    description: str | None = None
    choices: tuple[InputChoice, ...] = ()
    named_type: str | None = None
    value_role: str | None = None


@dataclass(frozen=True, slots=True)
class MacroArgNameMetadata:
    """Metadata for a selectable keyword-argument name row."""

    reference_text: str
    input_hint: MacroInputHint


@dataclass(frozen=True, slots=True)
class MacroAssistEntry:
    """TUI-facing macro catalog entry used for inline assist surfaces."""

    name: str
    insertion: str
    reference_prefix: str
    kind: str
    input_signature: str | None
    inputs: tuple[MacroInputHint, ...]
    content_preview: str | None
    description: str | None = None
    is_skill: bool = False
    skill_name: str | None = None
    """Provider-visible ``/`` name; ``name`` stays the ``#`` reference."""
    memory_type: MemoryType | None = None


@dataclass(frozen=True, slots=True)
class ActiveMacroArgHint:
    """An active argument hint resolved at a prompt cursor position."""

    entry: MacroAssistEntry
    reference_start: int
    reference_end: int
    reference_text: str
    trigger_mode: Literal["accepted", "colon", "paren"] = "accepted"
    active_input_index: int = 0


@dataclass(frozen=True, slots=True)
class PendingMacroCompletionSpacer:
    """A trailing spacer left by a macro completion.

    Macros without required inputs complete to ``#name `` with a deliberate
    trailing space. This records the inserted spacer so the next typed
    punctuation can replace it in place. The recorded identity lets the edit
    layer confirm the cursor still sits immediately after the spacer and the
    reference text is unchanged before consuming the punctuation.
    """

    spacer_offset: int
    reference_start: int
    reference_text: str
    has_optional_inputs: bool


@dataclass(frozen=True, slots=True)
class MacroArgCompletionContext:
    """Completion target resolved inside a macro argument list."""

    entry: MacroAssistEntry
    completion_kind: Literal[
        "macro_arg_path",
        "macro_arg_value",
        "macro_arg_agent",
        "macro_arg_model",
        "macro_arg_name",
        "macro_arg_type_hint",
    ]
    value_start: int
    value_end: int
    token: str
    active_input: MacroInputHint | None = None
    model_effort: bool = False
    used_arg_names: frozenset[str] = frozenset()
    selected_values: frozenset[str] = frozenset()
    replacement: str = ""


__all__ = [
    "ActiveMacroArgHint",
    "PendingMacroCompletionSpacer",
    "MacroArgNameMetadata",
    "MacroArgCompletionContext",
    "MacroAssistEntry",
    "MacroInputHint",
]
