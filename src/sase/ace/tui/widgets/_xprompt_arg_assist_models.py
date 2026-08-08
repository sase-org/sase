"""Data models for xprompt argument assist surfaces."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sase.xprompt.models import MemoryType


@dataclass(frozen=True, slots=True)
class XPromptInputHint:
    """User-facing structured xprompt input metadata."""

    name: str
    type: str
    required: bool
    default_display: str | None
    position: int
    repeatable: bool = False
    description: str | None = None


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
    description: str | None = None
    is_skill: bool = False
    skill_name: str | None = None
    """Provider-visible ``/`` name; ``name`` stays the ``#`` reference."""
    memory_type: MemoryType | None = None
    ref_kind: str | None = None
    ref_sidecar_role: str | None = None
    ref_path_globs: tuple[str, ...] | None = None
    ref_shadowed_sources: tuple[str, ...] = ()


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
class PendingXPromptCompletionSpacer:
    """A trailing spacer left by an xprompt completion.

    Xprompts without required inputs complete to ``#name `` with a deliberate
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
class XPromptArgCompletionContext:
    """Completion target resolved inside an xprompt argument list."""

    entry: XPromptAssistEntry
    completion_kind: Literal[
        "xprompt_arg_path",
        "xprompt_arg_value",
        "xprompt_arg_agent",
        "xprompt_arg_name",
        "xprompt_arg_ref",
        "xprompt_arg_type_hint",
    ]
    value_start: int
    value_end: int
    token: str
    active_input: XPromptInputHint | None = None
    used_arg_names: frozenset[str] = frozenset()
    selected_values: frozenset[str] = frozenset()


__all__ = [
    "ActiveXPromptArgHint",
    "PendingXPromptCompletionSpacer",
    "XPromptArgCompletionContext",
    "XPromptAssistEntry",
    "XPromptInputHint",
]
