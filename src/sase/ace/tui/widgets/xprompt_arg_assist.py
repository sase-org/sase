"""Pure xprompt argument assist models and render helpers for the TUI."""

from __future__ import annotations

from ._xprompt_arg_assist_catalog import (
    build_xprompt_assist_entries,
    merge_local_xprompt_entries,
    xprompt_assist_entry_from_local_xprompt,
    xprompt_assist_entry_from_workflow,
)
from ._xprompt_arg_assist_detection import (
    accepted_xprompt_arg_hint,
    detect_xprompt_arg_completion_at_cursor,
    detect_xprompt_arg_hint_at_cursor,
)
from ._xprompt_arg_assist_inputs import (
    append_input_args,
    append_input_hints,
    has_no_required_inputs,
    has_only_optional_inputs,
    input_hint_from_input_arg,
    input_label,
    required_inputs,
    visible_inputs,
)
from ._xprompt_arg_assist_models import (
    ActiveXPromptArgHint,
    PendingXPromptCompletionSpacer,
    XPromptArgCompletionContext,
    XPromptAssistEntry,
    XPromptInputHint,
)
from ._xprompt_arg_assist_skeletons import (
    colon_args_skeleton,
    named_args_skeleton,
    xprompt_completion_skeleton,
    xprompt_completion_suffix_skeleton,
)

__all__ = [
    "ActiveXPromptArgHint",
    "PendingXPromptCompletionSpacer",
    "XPromptArgCompletionContext",
    "XPromptAssistEntry",
    "XPromptInputHint",
    "accepted_xprompt_arg_hint",
    "append_input_args",
    "append_input_hints",
    "build_xprompt_assist_entries",
    "colon_args_skeleton",
    "detect_xprompt_arg_completion_at_cursor",
    "detect_xprompt_arg_hint_at_cursor",
    "has_no_required_inputs",
    "has_only_optional_inputs",
    "input_hint_from_input_arg",
    "input_label",
    "merge_local_xprompt_entries",
    "named_args_skeleton",
    "required_inputs",
    "visible_inputs",
    "xprompt_assist_entry_from_local_xprompt",
    "xprompt_assist_entry_from_workflow",
    "xprompt_completion_skeleton",
    "xprompt_completion_suffix_skeleton",
]
