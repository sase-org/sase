"""Row-body rendering for the prompt completion panel."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from rich.text import Text

from sase.ace.tui.agent_completion import AgentCompletionCandidate
from sase.ace.tui.models.tribe_display import named_tribe_identity_colors
from sase.ace.tui.widgets._prompt_input_bar_completion_panel_kinds import (
    CompletionPanelKinds,
)
from sase.ace.tui.widgets._prompt_input_bar_completion_rows import (
    append_agent_completion_row,
    append_artifact_ref_completion_row,
    append_at_reference_group_rule,
    append_directive_arg_completion_row,
    append_directive_completion_row,
    append_jinja_completion_row,
    append_model_completion_row,
    append_placeholder_completion_row,
    append_prompt_word_completion_row,
    append_vcs_project_completion_row,
    append_vcs_ref_completion_row,
    append_vcs_repo_completion_row,
    append_xprompt_completion_row,
    artifact_ref_kind_label_width,
    model_completion_column_widths,
    vcs_project_label_width,
    vcs_ref_label_width,
    vcs_repo_label_width,
)
from sase.ace.tui.widgets.artifact_ref_completion import (
    AtReferenceFileCompletionMetadata,
)
from sase.ace.tui.widgets.directive_completion import ModelCompletionMetadata
from sase.ace.tui.widgets.file_completion import CompletionCandidate
from sase.ace.tui.widgets.history_word_completion import (
    HistoryWordCompletionPlaceholder,
)


@dataclass(frozen=True)
class _RowLayout:
    """Per-menu column widths and palettes shared by every visible row."""

    vcs_project: int
    vcs_ref: int
    vcs_repo: int
    model: tuple[int, int]
    artifact_kind: int
    tribe_colors: dict[str, str] | None


def build_completion_panel_content(
    kinds: CompletionPanelKinds,
    visible: list[CompletionCandidate],
    *,
    total: int,
    selected_index: int,
    scroll_offset: int,
    group_rule: bool,
    group_directory: str,
    inner_width: int,
) -> Text:
    """Render the panel body for the *visible* slice of a completion menu.

    Args:
        kinds: Provider flags for the open menu.
        visible: Candidates inside the current scroll window.
        total: Number of candidates before the window was applied.
        selected_index: Highlighted index into the full candidate list.
        scroll_offset: Index of the first visible entry.
        group_rule: True when a group rule line separates the ``@`` menu's
            artifact and file groups, claiming one of the panel's lines.
        group_directory: Resolved directory named by an ``@`` group rule.
        inner_width: Content width available inside the panel border.
    """
    layout = _row_layout(kinds, visible)
    content = Text()
    group_rule_drawn = False
    for i, candidate in enumerate(visible):
        is_selected = scroll_offset + i == selected_index

        if (
            kinds.artifact_ref
            and group_rule
            and not group_rule_drawn
            and isinstance(candidate.metadata, AtReferenceFileCompletionMetadata)
        ):
            append_at_reference_group_rule(content, group_directory, inner_width)
            content.append("\n")
            group_rule_drawn = True

        if is_selected:
            content.append("▸ ", style="bold")
        else:
            content.append("  ")

        _append_candidate_row(
            content,
            candidate,
            is_selected,
            kinds=kinds,
            layout=layout,
            inner_width=inner_width,
        )

        if i < len(visible) - 1:
            content.append("\n")

    if kinds.artifact_ref and group_rule and not group_rule_drawn:
        if content:
            content.append("\n")
        append_at_reference_group_rule(content, group_directory, inner_width)

    remaining = total - (scroll_offset + len(visible))
    if remaining > 0:
        content.append(f"\n  ↓ {remaining} more…", style="dim")
    return content


def _row_layout(
    kinds: CompletionPanelKinds,
    visible: list[CompletionCandidate],
) -> _RowLayout:
    """Measure the columns every visible row of this menu must align to."""
    return _RowLayout(
        vcs_project=_max_label_width(
            visible, vcs_project_label_width, kinds.vcs_project
        ),
        vcs_ref=_max_label_width(visible, vcs_ref_label_width, kinds.vcs_ref),
        vcs_repo=_max_label_width(visible, vcs_repo_label_width, kinds.vcs_repo),
        model=model_completion_column_widths(visible) if kinds.model else (0, 0),
        artifact_kind=(
            artifact_ref_kind_label_width(visible)
            if kinds.artifact_ref or kinds.xprompt_arg_ref
            else 0
        ),
        tribe_colors=_tribe_colors(kinds, visible),
    )


def _max_label_width(
    visible: list[CompletionCandidate],
    measure: Callable[[CompletionCandidate], int],
    enabled: bool,
) -> int:
    if not enabled:
        return 0
    return max((measure(candidate) for candidate in visible), default=0)


def _tribe_colors(
    kinds: CompletionPanelKinds,
    visible: list[CompletionCandidate],
) -> dict[str, str] | None:
    if not (kinds.directive_arg_agent or kinds.xprompt_arg_agent):
        return None
    return named_tribe_identity_colors(
        {
            metadata.name.removeprefix("@")
            for candidate in visible
            if isinstance(
                (metadata := candidate.metadata),
                AgentCompletionCandidate,
            )
            and metadata.kind == "tribe"
        }
    )


def _append_candidate_row(
    content: Text,
    candidate: CompletionCandidate,
    is_selected: bool,
    *,
    kinds: CompletionPanelKinds,
    layout: _RowLayout,
    inner_width: int,
) -> None:
    """Append the provider-specific rendering of a single candidate."""
    if kinds.xprompt:
        append_xprompt_completion_row(content, candidate, is_selected)
    elif kinds.directive:
        append_directive_completion_row(content, candidate, is_selected)
    elif kinds.directive_arg:
        if isinstance(candidate.metadata, ModelCompletionMetadata):
            append_model_completion_row(
                content,
                candidate,
                is_selected,
                layout.model,
            )
        else:
            append_directive_arg_completion_row(
                content,
                candidate,
                is_selected,
                tribe_colors=layout.tribe_colors,
                model_widths=layout.model,
            )
    elif kinds.xprompt_arg_agent:
        append_agent_completion_row(
            content,
            candidate,
            is_selected,
            tribe_colors=layout.tribe_colors,
        )
    elif kinds.vcs_project:
        append_vcs_project_completion_row(
            content,
            candidate,
            is_selected,
            layout.vcs_project,
        )
    elif kinds.vcs_ref:
        append_vcs_ref_completion_row(content, candidate, is_selected, layout.vcs_ref)
    elif kinds.vcs_repo:
        append_vcs_repo_completion_row(content, candidate, is_selected, layout.vcs_repo)
    elif kinds.artifact_ref or kinds.xprompt_arg_ref:
        append_artifact_ref_completion_row(
            content,
            candidate,
            is_selected,
            layout.artifact_kind,
            inner_width,
        )
    elif kinds.arg_completion:
        content.append(
            candidate.display,
            style="bold yellow" if is_selected else "yellow",
        )
    elif kinds.jinja:
        append_jinja_completion_row(content, candidate, is_selected)
    elif kinds.placeholder:
        append_placeholder_completion_row(content, candidate, is_selected)
    elif kinds.prompt_word:
        append_prompt_word_completion_row(content, candidate, is_selected)
    elif kinds.history_word:
        if isinstance(candidate.metadata, HistoryWordCompletionPlaceholder):
            content.append(candidate.display, style="dim italic")
        else:
            append_prompt_word_completion_row(content, candidate, is_selected)
    elif candidate.is_dir:
        content.append("\U0001f4c1 ")
        content.append(candidate.display, style="bold cyan" if is_selected else "cyan")
    else:
        content.append("\U0001f4c4 ")
        content.append(candidate.display, style="bold" if is_selected else "")
