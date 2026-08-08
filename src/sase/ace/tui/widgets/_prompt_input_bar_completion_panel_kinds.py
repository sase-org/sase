"""Provider-kind classification for the prompt completion panel.

The panel renders one of many named completion providers, and both its row
body and its border labels branch on the same set of predicates. Classifying
once keeps those two renderers from drifting apart.
"""

from __future__ import annotations

from dataclasses import dataclass

from sase.ace.tui.widgets._prompt_input_bar_completion_rows import (
    is_agent_completion_candidate,
)
from sase.ace.tui.widgets.artifact_ref_completion import (
    ARTIFACT_REF_COMPLETION_KIND,
    AtReferenceFileCompletionMetadata,
    ArtifactRefKindCompletionMetadata,
)
from sase.ace.tui.widgets.directive_completion import ModelCompletionMetadata
from sase.ace.tui.widgets.file_completion import CompletionCandidate
from sase.ace.tui.widgets.history_word_completion import (
    HISTORY_WORD_COMPLETION_KIND,
)
from sase.ace.tui.widgets.placeholder_completion import (
    PLACEHOLDER_COMPLETION_KIND,
)
from sase.ace.tui.widgets.prompt_word_completion import PROMPT_WORD_COMPLETION_KIND
from sase.ace.tui.widgets.vcs_project_completion import VCS_PROJECT_COMPLETION_KIND
from sase.ace.tui.widgets.vcs_ref_completion import VCS_REF_COMPLETION_KIND
from sase.ace.tui.widgets.vcs_repo_completion import VCS_REPO_COMPLETION_KIND


@dataclass(frozen=True)
class CompletionPanelKinds:
    """Which named provider an open completion panel is rendering."""

    kind: str
    xprompt: bool
    directive: bool
    directive_arg: bool
    directive_arg_agent: bool
    model: bool
    history: bool
    arg_completion: bool
    xprompt_arg_agent: bool
    jinja: bool
    placeholder: bool
    prompt_word: bool
    history_word: bool
    vcs_project: bool
    vcs_ref: bool
    vcs_repo: bool
    artifact_ref: bool
    xprompt_arg_ref: bool

    @classmethod
    def classify(
        cls,
        completion_kind: str,
        rows: list[CompletionCandidate],
    ) -> CompletionPanelKinds:
        """Return the provider flags for *completion_kind* over *rows*."""
        is_directive_arg = completion_kind == "directive_arg"
        return cls(
            kind=completion_kind,
            xprompt=completion_kind == "xprompt",
            directive=completion_kind == "directive",
            directive_arg=is_directive_arg,
            directive_arg_agent=is_directive_arg
            and any(is_agent_completion_candidate(candidate) for candidate in rows),
            model=is_directive_arg
            and any(
                isinstance(candidate.metadata, ModelCompletionMetadata)
                for candidate in rows
            ),
            history=completion_kind == "file_history",
            arg_completion=completion_kind in ("xprompt_arg_name", "xprompt_arg_value"),
            xprompt_arg_agent=completion_kind == "xprompt_arg_agent",
            jinja=completion_kind == "jinja",
            placeholder=completion_kind == PLACEHOLDER_COMPLETION_KIND,
            prompt_word=completion_kind == PROMPT_WORD_COMPLETION_KIND,
            history_word=completion_kind == HISTORY_WORD_COMPLETION_KIND,
            vcs_project=completion_kind == VCS_PROJECT_COMPLETION_KIND,
            vcs_ref=completion_kind == VCS_REF_COMPLETION_KIND,
            vcs_repo=completion_kind == VCS_REPO_COMPLETION_KIND,
            artifact_ref=completion_kind == ARTIFACT_REF_COMPLETION_KIND,
            xprompt_arg_ref=completion_kind == "xprompt_arg_ref",
        )


def at_reference_group_rule_needed(rows: list[CompletionCandidate]) -> bool:
    """Return whether *rows* contain both Kind-stage menu groups."""
    has_artifacts = any(
        isinstance(candidate.metadata, ArtifactRefKindCompletionMetadata)
        for candidate in rows
    )
    has_files = any(
        isinstance(candidate.metadata, AtReferenceFileCompletionMetadata)
        for candidate in rows
    )
    return has_artifacts and has_files
