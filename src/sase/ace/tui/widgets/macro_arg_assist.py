"""Pure macro argument assist models and render helpers for the TUI."""

from __future__ import annotations

from ._macro_arg_assist_catalog import (
    build_macro_assist_entries,
    merge_local_macro_entries,
    macro_assist_entry_from_local_macro,
    macro_assist_entry_from_workflow,
)
from ._macro_arg_assist_detection import (
    accepted_macro_arg_hint,
    detect_macro_arg_completion_at_cursor,
    detect_macro_arg_hint_at_cursor,
)
from ._macro_arg_assist_inputs import (
    append_input_args,
    append_input_hints,
    has_no_required_inputs,
    has_only_optional_inputs,
    input_default_style,
    input_default_suffix,
    input_hint_from_input_arg,
    input_label,
    input_name_style,
    required_inputs,
    visible_inputs,
)
from ._macro_arg_assist_models import (
    ActiveMacroArgHint,
    PendingMacroCompletionSpacer,
    MacroArgNameMetadata,
    MacroArgCompletionContext,
    MacroAssistEntry,
    MacroInputHint,
)
from ._macro_arg_assist_skeletons import (
    colon_args_skeleton,
    named_args_skeleton,
    macro_completion_skeleton,
    macro_completion_suffix_skeleton,
)

__all__ = [
    "ActiveMacroArgHint",
    "PendingMacroCompletionSpacer",
    "MacroArgNameMetadata",
    "MacroArgCompletionContext",
    "MacroAssistEntry",
    "MacroInputHint",
    "accepted_macro_arg_hint",
    "append_input_args",
    "append_input_hints",
    "build_macro_assist_entries",
    "colon_args_skeleton",
    "detect_macro_arg_completion_at_cursor",
    "detect_macro_arg_hint_at_cursor",
    "has_no_required_inputs",
    "has_only_optional_inputs",
    "input_default_style",
    "input_default_suffix",
    "input_hint_from_input_arg",
    "input_label",
    "input_name_style",
    "merge_local_macro_entries",
    "named_args_skeleton",
    "required_inputs",
    "visible_inputs",
    "macro_assist_entry_from_local_macro",
    "macro_assist_entry_from_workflow",
    "macro_completion_skeleton",
    "macro_completion_suffix_skeleton",
]
