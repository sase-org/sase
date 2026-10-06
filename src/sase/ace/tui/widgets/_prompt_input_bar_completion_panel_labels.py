"""Border title and subtitle text for the prompt completion panel.

Implementations live in domain-specific modules. This module preserves the
original import surface for the completion panel and focused label tests.
"""

from sase.ace.tui.widgets._prompt_input_bar_completion_panel_labels_detail import (
    agent_completion_subtitle,
    finalizer_completion_subtitle,
    jinja_completion_subtitle,
    macro_arg_name_completion_subtitle,
    model_completion_subtitle,
)
from sase.ace.tui.widgets._prompt_input_bar_completion_panel_labels_subtitles import (
    artifact_ref_completion_subtitle,
    completion_delete_subtitle,
    history_word_completion_subtitle,
    placeholder_completion_subtitle,
    prompt_word_completion_subtitle,
)
from sase.ace.tui.widgets._prompt_input_bar_completion_panel_labels_titles import (
    completion_panel_title,
)

__all__ = [
    "agent_completion_subtitle",
    "artifact_ref_completion_subtitle",
    "completion_delete_subtitle",
    "completion_panel_title",
    "finalizer_completion_subtitle",
    "history_word_completion_subtitle",
    "jinja_completion_subtitle",
    "macro_arg_name_completion_subtitle",
    "model_completion_subtitle",
    "placeholder_completion_subtitle",
    "prompt_word_completion_subtitle",
]
