"""Rich row rendering helpers for the prompt input completion panel.

Implementations live in domain-specific modules. This module preserves the
original import surface for the completion panel and focused rendering tests.
"""

from sase.ace.tui.widgets._prompt_input_bar_completion_rows_agents import (
    append_agent_completion_row,
    is_agent_completion_candidate,
)
from sase.ace.tui.widgets._prompt_input_bar_completion_rows_artifacts import (
    append_artifact_ref_completion_row,
    append_at_reference_group_rule,
    artifact_ref_kind_label_width,
    at_reference_directory_display,
)
from sase.ace.tui.widgets._prompt_input_bar_completion_rows_directives import (
    append_directive_arg_completion_row,
    append_directive_completion_row,
    append_model_completion_row,
    model_completion_column_widths,
)
from sase.ace.tui.widgets._prompt_input_bar_completion_rows_simple import (
    append_jinja_completion_row,
    append_placeholder_completion_row,
    append_prompt_word_completion_row,
    append_xprompt_completion_row,
)
from sase.ace.tui.widgets._prompt_input_bar_completion_rows_vcs import (
    append_vcs_project_completion_row,
    append_vcs_ref_completion_row,
    append_vcs_repo_completion_row,
    vcs_project_label_width,
    vcs_ref_label_width,
    vcs_repo_label_width,
)

__all__ = [
    "append_agent_completion_row",
    "append_artifact_ref_completion_row",
    "append_at_reference_group_rule",
    "append_directive_arg_completion_row",
    "append_directive_completion_row",
    "append_jinja_completion_row",
    "append_model_completion_row",
    "append_placeholder_completion_row",
    "append_prompt_word_completion_row",
    "append_vcs_project_completion_row",
    "append_vcs_ref_completion_row",
    "append_vcs_repo_completion_row",
    "append_xprompt_completion_row",
    "artifact_ref_kind_label_width",
    "at_reference_directory_display",
    "is_agent_completion_candidate",
    "model_completion_column_widths",
    "vcs_project_label_width",
    "vcs_ref_label_width",
    "vcs_repo_label_width",
]
