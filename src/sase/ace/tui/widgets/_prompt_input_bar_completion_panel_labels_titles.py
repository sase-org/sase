"""Border titles for the prompt completion panel."""

from __future__ import annotations

from sase.ace.tui.widgets._prompt_input_bar_completion_panel_kinds import (
    CompletionPanelKinds,
)
from sase.ace.tui.widgets._prompt_input_bar_completion_panel_labels_shared import (
    SYNC_TITLE_STATUS,
)
from sase.ace.tui.widgets._prompt_input_bar_completion_rows import (
    at_reference_directory_display,
)
from sase.ace.tui.widgets.artifact_ref_completion import (
    AtReferenceFileCompletionMetadata,
    AtReferenceLoadingCompletionMetadata,
    ArtifactRefKindCompletionMetadata,
    ArtifactRefSyncCompletionMetadata,
)
from sase.ace.tui.widgets.directive_completion import (
    ModelCompletionMetadata,
)
from sase.ace.tui.widgets.file_completion import CompletionCandidate
from sase.ace.tui.widgets.jinja_completion import JinjaCompletionMetadata
from sase.ace.tui.widgets.macro_arg_assist import MacroArgNameMetadata
from sase.ace.tui.widgets.next_word_menu import (
    next_word_menu_context,
    next_word_menu_title,
)


def completion_panel_title(
    kinds: CompletionPanelKinds,
    token: str,
    rows: list[CompletionCandidate],
    group_directory: str,
) -> str:
    """Return the provider-specific title; path completion shows its directory."""
    if kinds.macro:
        return "macros"
    if kinds.directive:
        return "directives"
    if kinds.bead:
        return "beads"
    if kinds.finalizer:
        return "%final values"
    if kinds.directive_arg_agent:
        return "wait targets"
    if kinds.model_alias:
        return "model aliases"
    if kinds.model_explicit:
        return "explicit models"
    if kinds.model:
        if scoped_title := _model_completion_provider_scope_title(token, rows):
            return scoped_title
        return "model aliases" if token.startswith("@") else "%model values"
    if kinds.macro_arg_model:
        if kinds.macro_arg_model_effort:
            return "%model effort"
        return "model aliases" if token.startswith("@") else "%model values"
    if kinds.directive_arg:
        return "directive values"
    if kinds.vcs_project:
        return "projects & PRs"
    if kinds.vcs_ref:
        return token
    if kinds.vcs_repo:
        return token
    if kinds.artifact_ref:
        return _at_reference_panel_title(token, rows, group_directory)
    if kinds.macro_arg_agent:
        return "fork targets"
    if kinds.macro_arg_name:
        metadata = next(
            (
                candidate.metadata
                for candidate in rows
                if isinstance(candidate.metadata, MacroArgNameMetadata)
            ),
            None,
        )
        if metadata is not None:
            return f"{metadata.reference_text} args"
        return "macro arg names"
    if kinds.kind == "macro_arg_value":
        return _macro_arg_value_panel_title(rows)
    if kinds.kind == "macro_arg_path":
        return "macro path"
    if kinds.jinja:
        return _jinja_panel_title(rows)
    if kinds.placeholder:
        return "placeholder"
    if kinds.prompt_word:
        return "prompt words"
    if kinds.history_word:
        return "history words"
    if kinds.next_word:
        return next_word_menu_title(next_word_menu_context(rows))
    if kinds.history:
        return "recent files"
    if "/" in token:
        return token[: token.rindex("/") + 1]
    return token


def _jinja_panel_title(rows: list[CompletionCandidate]) -> str:
    """Return the slot-specific title for a Jinja2 menu, plus scope label."""
    slot = "variable"
    namespace: str | None = None
    scope_label: str | None = None
    for candidate in rows:
        metadata = candidate.metadata
        if isinstance(metadata, JinjaCompletionMetadata):
            slot = metadata.slot
            namespace = metadata.namespace
            scope_label = metadata.scope_label
            break
    if slot == "filter":
        title = "| filters"
    elif slot == "test":
        title = "is tests"
    elif slot == "statement":
        title = "{% statements"
    elif slot == "member":
        title = f"{namespace}. members" if namespace else "members"
    elif slot == "none":
        title = "jinja"
    else:
        title = "{{ variables"
    if scope_label:
        title = f"{title} · {scope_label}"
    return title


def _at_reference_panel_title(
    token: str,
    rows: list[CompletionCandidate],
    directory: str,
) -> str:
    """Return the adaptive title for an ``@`` Kind-stage menu."""
    sync_metadata = next(
        (
            candidate.metadata
            for candidate in rows
            if isinstance(candidate.metadata, ArtifactRefSyncCompletionMetadata)
        ),
        None,
    )
    if sync_metadata is not None:
        status = SYNC_TITLE_STATUS.get(sync_metadata.phase, sync_metadata.phase)
        return f"@ {sync_metadata.kind} · {status}"
    has_artifacts = any(
        isinstance(candidate.metadata, ArtifactRefKindCompletionMetadata)
        for candidate in rows
    )
    has_files = any(
        isinstance(candidate.metadata, AtReferenceFileCompletionMetadata)
        for candidate in rows
    )
    is_loading = any(
        isinstance(candidate.metadata, AtReferenceLoadingCompletionMetadata)
        for candidate in rows
    )
    if has_artifacts and has_files:
        return "@ reference"
    if has_artifacts:
        return "@ artifact kinds"
    if has_files or is_loading:
        return f"@ {at_reference_directory_display(directory)}"
    return token


def _macro_arg_value_panel_title(rows: list[CompletionCandidate]) -> str:
    """Return ``<input> · <named_type or enum>`` for choice menus."""
    from sase.ace.tui.widgets._file_completion_macro_args import (
        MacroArgValueMetadata,
    )

    for candidate in rows:
        metadata = candidate.metadata
        if isinstance(metadata, MacroArgValueMetadata) and metadata.input_name:
            type_label = metadata.type_label or "enum"
            return f"{metadata.input_name} · {type_label}"
    return "macro arg values"


def _model_completion_provider_scope_title(
    token: str,
    rows: list[CompletionCandidate],
) -> str:
    head, separator, _remainder = token.partition("/")
    if not separator or not head:
        return ""
    scoped_prefix = f"{head.casefold()}/"
    for candidate in rows:
        metadata = candidate.metadata
        if (
            isinstance(metadata, ModelCompletionMetadata)
            and metadata.kind == "model"
            and metadata.provider.casefold() == head.casefold()
            and metadata.value.casefold().startswith(scoped_prefix)
        ):
            return f"{metadata.provider}/ models"
    return ""
