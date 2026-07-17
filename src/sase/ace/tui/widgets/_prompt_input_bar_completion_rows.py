"""Rich row rendering helpers for the prompt input completion panel."""

from __future__ import annotations

from rich.text import Text

from sase.ace.tui.agent_completion import (
    AgentCompletionCandidate,
    neutral_vcs_workflow,
    status_style,
)
from sase.ace.tui.widgets.directive_completion import (
    DirectiveArgCompletionMetadata,
    DirectiveCompletionMetadata,
)
from sase.ace.tui.widgets.file_completion import CompletionCandidate
from sase.ace.tui.widgets.jinja_completion import JinjaCompletionMetadata
from sase.ace.tui.widgets.vcs_repo_completion import VcsRepoCompletionPlaceholder
from sase.ace.tui.widgets.xprompt_arg_assist import (
    XPromptAssistEntry,
    append_input_hints,
)
from sase.project_display_names import project_display_name_for
from sase.workspace_provider import VcsNamespaceEntry, VcsRepoEntry
from sase.xprompt.vcs_project_completion import VcsProjectEntry


def vcs_project_label_width(candidate: CompletionCandidate) -> int:
    """Visible width for the badge + primary label in a VCS completion row."""
    entry = (
        candidate.metadata if isinstance(candidate.metadata, VcsProjectEntry) else None
    )
    if entry is None:
        return len(candidate.display)
    badge_width = 5 if entry.kind == "changespec" else 4
    return badge_width + len(entry.name)


def vcs_repo_label_width(candidate: CompletionCandidate) -> int:
    """Visible width for the primary label in a repo completion row."""
    entry = candidate.metadata if isinstance(candidate.metadata, VcsRepoEntry) else None
    if entry is None:
        return len(candidate.display)
    return len(entry.name)


def vcs_ref_label_width(candidate: CompletionCandidate) -> int:
    """Visible width for the badge + primary label in a VCS ref row."""
    metadata = candidate.metadata
    if isinstance(metadata, VcsProjectEntry):
        badge_width = 5 if metadata.kind == "changespec" else 4
        return badge_width + len(metadata.name)
    if isinstance(metadata, VcsNamespaceEntry):
        badge_width = len(f"[{metadata.kind_label.upper()}] ")
        return badge_width + len(metadata.name.rstrip("/") + "/")
    return len(candidate.display)


def is_agent_completion_candidate(candidate: CompletionCandidate) -> bool:
    return isinstance(candidate.metadata, AgentCompletionCandidate)


def append_xprompt_completion_row(
    content: Text,
    candidate: CompletionCandidate,
    is_selected: bool,
) -> None:
    """Append one xprompt completion row using assist metadata when present."""
    content.append(
        candidate.display,
        style="bold green" if is_selected else "green",
    )
    entry = (
        candidate.metadata
        if isinstance(candidate.metadata, XPromptAssistEntry)
        else None
    )
    if entry is None:
        return

    kind = "skill" if entry.is_skill else entry.kind
    content.append(f"  {kind}", style="dim")
    if entry.description:
        content.append(f"  {entry.description}", style="dim")
    append_input_hints(content, entry.inputs)


def append_directive_completion_row(
    content: Text,
    candidate: CompletionCandidate,
    is_selected: bool,
) -> None:
    """Append one prompt directive completion row."""
    content.append(
        candidate.display,
        style="bold magenta" if is_selected else "magenta",
    )
    metadata = (
        candidate.metadata
        if isinstance(candidate.metadata, DirectiveCompletionMetadata)
        else None
    )
    if metadata is None:
        return

    details: list[str] = []
    if metadata.argument_hint:
        details.append(metadata.argument_hint)
    if metadata.aliases:
        details.append("alias " + ", ".join(f"%{alias}" for alias in metadata.aliases))
    if metadata.description:
        details.append(metadata.description)
    if details:
        content.append(f"  {'  '.join(details)}", style="dim")


def append_directive_arg_completion_row(
    content: Text,
    candidate: CompletionCandidate,
    is_selected: bool,
) -> None:
    """Append one prompt directive argument completion row."""
    if is_agent_completion_candidate(candidate):
        append_agent_completion_row(content, candidate, is_selected)
        return

    content.append(
        candidate.display,
        style="bold magenta" if is_selected else "magenta",
    )
    metadata = (
        candidate.metadata
        if isinstance(candidate.metadata, DirectiveArgCompletionMetadata)
        else None
    )
    if metadata is not None and metadata.description:
        content.append(f"  {metadata.description}", style="dim")


def append_agent_completion_row(
    content: Text,
    candidate: CompletionCandidate,
    is_selected: bool,
) -> None:
    """Append one visible-agent completion row."""
    metadata = (
        candidate.metadata
        if isinstance(candidate.metadata, AgentCompletionCandidate)
        else None
    )
    if metadata is None:
        content.append(candidate.display, style="bold" if is_selected else "")
        return

    workflow = metadata.vcs_workflow or neutral_vcs_workflow()
    name = _truncate_cell(metadata.name, 26)
    badge = _truncate_cell(workflow.display, 14)
    snippet = _truncate_cell(metadata.prompt_snippet or metadata.label, 64)

    content.append("● ", style=status_style(metadata.status))
    content.append(f"{name:<26}", style="bold")
    content.append("  ")
    content.append(f"{badge:<14}", style=workflow.style)
    if snippet:
        content.append("  ")
        content.append(snippet, style="dim")


def append_vcs_project_completion_row(
    content: Text,
    candidate: CompletionCandidate,
    is_selected: bool,
    label_width: int = 0,
) -> None:
    """Append one ``#+`` project/PR completion row.

    Project and ChangeSpec rows use the same badges as the ProjectSelect modal.
    The empty-catalog placeholder (no :class:`VcsProjectEntry` metadata) renders
    as a single dim row.
    """
    entry = (
        candidate.metadata if isinstance(candidate.metadata, VcsProjectEntry) else None
    )
    if entry is None:
        content.append(candidate.display, style="dim italic")
        return

    if entry.kind == "changespec":
        badge = "[PR] "
        badge_style = "bold #00D7AF"
        name_style = "bold #00D7AF" if is_selected else "#00D7AF"
    else:
        badge = "[P] "
        badge_style = "bold #87D7FF"
        name_style = "bold #87D7FF" if is_selected else "#87D7FF"

    content.append(badge, style=badge_style)
    content.append(entry.name, style=name_style)
    padding = max(0, label_width - (len(badge) + len(entry.name)))
    if padding:
        content.append(" " * padding)

    content.append(f"  {entry.display_tag}", style="dim green")
    if entry.kind == "changespec":
        if entry.status:
            content.append(f"  {entry.status}", style="dim")
        if entry.project:
            content.append(
                f"  · {project_display_name_for(entry.project)}",
                style="dim",
            )
    else:
        content.append(f"  {entry.provider_display}", style="dim")
        if entry.description:
            content.append(f"  {entry.description}", style="dim")


def append_vcs_repo_completion_row(
    content: Text,
    candidate: CompletionCandidate,
    is_selected: bool,
    label_width: int = 0,
) -> None:
    """Append one repository completion row or placeholder state."""
    entry = candidate.metadata if isinstance(candidate.metadata, VcsRepoEntry) else None
    if entry is None:
        placeholder = (
            candidate.metadata
            if isinstance(candidate.metadata, VcsRepoCompletionPlaceholder)
            else None
        )
        style = "dim italic"
        if placeholder is not None and placeholder.kind == "error":
            style = "bold red" if is_selected else "red"
        content.append(candidate.display, style=style)
        return

    name_style = "bold #87D7FF" if is_selected else "#87D7FF"
    content.append(entry.name, style=name_style)
    padding = max(0, label_width - len(entry.name))
    if padding:
        content.append(" " * padding)

    badges: list[tuple[str, str]] = []
    if entry.visibility.casefold() == "private":
        badges.append(("[private]", "bold #D7AF5F"))
    if entry.is_fork:
        badges.append(("[fork]", "bold #00D7AF"))
    if entry.is_archived:
        badges.append(("[archived]", "bold #808080"))
    for label, style in badges:
        content.append("  ")
        content.append(label, style=style)

    if entry.description:
        content.append(f"  {_truncate_cell(entry.description, 72)}", style="dim")


def append_vcs_ref_completion_row(
    content: Text,
    candidate: CompletionCandidate,
    is_selected: bool,
    label_width: int = 0,
) -> None:
    """Append one VCS ref-root completion row or placeholder state."""
    metadata = candidate.metadata
    if isinstance(metadata, VcsProjectEntry):
        _append_vcs_ref_project_row(
            content,
            metadata,
            is_selected,
            label_width,
        )
        return
    if isinstance(metadata, VcsNamespaceEntry):
        _append_vcs_ref_namespace_row(
            content,
            metadata,
            is_selected,
            label_width,
        )
        return

    content.append(candidate.display, style="dim italic")


def append_jinja_completion_row(
    content: Text,
    candidate: CompletionCandidate,
    is_selected: bool,
) -> None:
    """Append one Jinja2 completion row."""
    metadata = (
        candidate.metadata
        if isinstance(candidate.metadata, JinjaCompletionMetadata)
        else None
    )
    kind = metadata.kind if metadata is not None else "jinja"
    style_by_kind = {
        "variable": "cyan",
        "keyword": "magenta",
        "filter": "green",
    }
    style = style_by_kind.get(kind, "white")
    if is_selected:
        style = f"bold {style}"
    content.append(candidate.display, style=style)
    content.append(f"  {kind}", style="dim")


def append_placeholder_completion_row(
    content: Text,
    candidate: CompletionCandidate,
    is_selected: bool,
) -> None:
    """Append one reusable placeholder row with a quiet bracket badge."""
    content.append("<> ", style="dim cyan")
    content.append(
        candidate.display,
        style="bold cyan" if is_selected else "cyan",
    )


def append_prompt_word_completion_row(
    content: Text,
    candidate: CompletionCandidate,
    is_selected: bool,
) -> None:
    """Append one prompt-local word without a file-type icon."""
    content.append(candidate.display, style="bold" if is_selected else "")


def _append_vcs_ref_project_row(
    content: Text,
    entry: VcsProjectEntry,
    is_selected: bool,
    label_width: int,
) -> None:
    """Append one project or ChangeSpec row in a VCS ref-root menu."""
    if entry.kind == "changespec":
        badge = "[PR] "
        badge_style = "bold #00D7AF"
        name_style = "bold #00D7AF" if is_selected else "#00D7AF"
    else:
        badge = "[P] "
        badge_style = "bold #87D7FF"
        name_style = "bold #87D7FF" if is_selected else "#87D7FF"

    content.append(badge, style=badge_style)
    content.append(entry.name, style=name_style)
    padding = max(0, label_width - (len(badge) + len(entry.name)))
    if padding:
        content.append(" " * padding)

    if entry.kind == "changespec":
        if entry.status:
            content.append(f"  {entry.status}", style="dim")
        if entry.project:
            content.append(
                f"  · {project_display_name_for(entry.project)}",
                style="dim",
            )
        return

    content.append(f"  {entry.provider_display}", style="dim")
    if entry.description:
        content.append(f"  {entry.description}", style="dim")


def _append_vcs_ref_namespace_row(
    content: Text,
    entry: VcsNamespaceEntry,
    is_selected: bool,
    label_width: int,
) -> None:
    """Append one namespace row in a VCS ref-root menu."""
    badge = f"[{entry.kind_label.upper()}] "
    label = entry.name.rstrip("/") + "/"
    badge_style = "bold #FFAF5F"
    name_style = "bold #FFAF5F" if is_selected else "#FFAF5F"

    content.append(badge, style=badge_style)
    content.append(label, style=name_style)
    padding = max(0, label_width - (len(badge) + len(label)))
    if padding:
        content.append(" " * padding)
    if entry.description:
        content.append(f"  {entry.description}", style="dim")


def _truncate_cell(value: str, width: int) -> str:
    if len(value) <= width:
        return value
    if width <= 3:
        return value[:width]
    return value[: width - 3].rstrip() + "..."
