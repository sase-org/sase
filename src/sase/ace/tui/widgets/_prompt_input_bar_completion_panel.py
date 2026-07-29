"""Completion panel state management for PromptInputBar."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.text import Text
from textual.css.query import NoMatches
from textual.widgets import Static

from sase.ace.tui.agent_completion import AgentCompletionCandidate
from sase.ace.tui.models.tribe_display import named_tribe_identity_colors
from sase.ace.tui.widgets._prompt_input_bar_completion_rows import (
    append_agent_completion_row,
    append_artifact_ref_completion_row,
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
    is_agent_completion_candidate,
    model_completion_column_widths,
    vcs_project_label_width,
    vcs_ref_label_width,
    vcs_repo_label_width,
)
from sase.ace.tui.widgets.artifact_ref_completion import (
    ARTIFACT_REF_COMPLETION_KIND,
)
from sase.ace.tui.widgets.directive_completion import ModelCompletionMetadata
from sase.ace.tui.widgets.file_completion import MAX_VISIBLE, CompletionCandidate
from sase.ace.tui.widgets.history_word_completion import (
    HISTORY_WORD_COMPLETION_KIND,
    HistoryWordCompletionPlaceholder,
)
from sase.ace.tui.widgets.prompt_completion import PromptSoftCompletion
from sase.ace.tui.widgets.placeholder_completion import (
    PLACEHOLDER_COMPLETION_KIND,
    PlaceholderCompletionMetadata,
)
from sase.ace.tui.widgets.prompt_word_completion import PROMPT_WORD_COMPLETION_KIND
from sase.ace.tui.widgets.vcs_project_completion import VCS_PROJECT_COMPLETION_KIND
from sase.ace.tui.widgets.vcs_ref_completion import VCS_REF_COMPLETION_KIND
from sase.ace.tui.widgets.vcs_repo_completion import VCS_REPO_COMPLETION_KIND
from sase.ace.tui.widgets.xprompt_arg_assist import (
    ActiveXPromptArgHint,
    append_input_hints,
)

if TYPE_CHECKING:
    from textual.widgets import Static as _MixinBase
else:
    _MixinBase = object

# Mirror styles.tcss for #prompt-completion. The panel reserves a border-box
# height capped by max-height, plus its one-row bottom margin.
_PANEL_BORDER_ROWS = 2
_PANEL_MARGIN_ROWS = 1
_COMPLETION_PANEL_MAX_HEIGHT = 10
_JINJA_PANEL_MAX_HEIGHT = 5
_PLACEHOLDER_SOURCE_LEGEND = "<> prompt   ◆ saved"


def _model_completion_subtitle(
    rows: list[CompletionCandidate],
    selected_index: int,
    inner_width: int,
) -> Text:
    """Return the contextual subtitle for an enriched model menu."""
    if not 0 <= selected_index < len(rows):
        return Text()
    metadata = rows[selected_index].metadata
    if not isinstance(metadata, ModelCompletionMetadata):
        return Text()
    if metadata.kind == "model":
        subtitle = "[@] model aliases"
    elif metadata.description:
        subtitle = metadata.description
    elif metadata.alias_kind == "user":
        alias = metadata.value.lstrip("@")
        subtitle = f"set llm_provider.model_aliases.custom.{alias}.description"
    else:
        subtitle = ""
    text = Text(subtitle, no_wrap=True, overflow="ellipsis")
    if inner_width <= 0:
        return text
    text.truncate(inner_width, overflow="ellipsis")
    return text


def _reserved_panel_rows(
    line_count: int,
    max_height: int = _COMPLETION_PANEL_MAX_HEIGHT,
) -> int:
    """Rows occupied by the completion panel, clamped to its CSS max-height."""
    border_box = min(line_count + _PANEL_BORDER_ROWS, max_height)
    return border_box + _PANEL_MARGIN_ROWS


def _completion_delete_subtitle(
    completion_kind: str,
    visible: list[CompletionCandidate],
) -> str:
    """Return the delete affordance for durable completion providers."""
    delete_hint = "[^L] accept  [^D] delete"
    if completion_kind == "file_history":
        return delete_hint
    if completion_kind == HISTORY_WORD_COMPLETION_KIND:
        if visible and all(
            not isinstance(candidate.metadata, HistoryWordCompletionPlaceholder)
            for candidate in visible
        ):
            return delete_hint
        return ""
    if completion_kind == PLACEHOLDER_COMPLETION_KIND:
        legend = (
            _PLACEHOLDER_SOURCE_LEGEND
            if _visible_placeholder_sources(visible) == {"prompt", "common"}
            else ""
        )
        return f"{legend}  [^D] delete".strip()
    return ""


class PromptInputBarCompletionMixin(_MixinBase):
    """Completion panel, soft-completion subtitle, and argument hint rendering."""

    if TYPE_CHECKING:
        _completion_line_count: int
        _completion_panel_kind: str | None
        _completion_visible: bool
        _mode_subtitle: str
        _soft_completion_visible: bool

        def _update_height(self) -> None: ...
        def _maybe_show_active_jinja_diagnostics(self) -> None: ...

    def _completion_panel(self) -> Static | None:
        """Return the completion panel when it is still attached."""
        try:
            return self.query_one("#prompt-completion", Static)
        except NoMatches:
            return None

    def show_file_completions(
        self,
        token: str,
        rows: list[CompletionCandidate],
        selected_index: int,
        scroll_offset: int = 0,
        completion_kind: str = "file",
    ) -> None:
        """Show the shared manual-completion panel with Rich styling.

        Args:
            token: Current token being completed.
            rows: Completion entries.
            selected_index: Highlighted row index.
            scroll_offset: First visible entry index for scrolling.
            completion_kind: Named provider kind used to render rows and title.
        """
        panel = self._completion_panel()
        if panel is None:
            return
        total = len(rows)
        visible = rows[scroll_offset : scroll_offset + MAX_VISIBLE]

        is_xprompt = completion_kind == "xprompt"
        is_directive = completion_kind == "directive"
        is_directive_arg = completion_kind == "directive_arg"
        is_directive_arg_agent = is_directive_arg and any(
            is_agent_completion_candidate(candidate) for candidate in rows
        )
        is_model_completion = is_directive_arg and any(
            isinstance(candidate.metadata, ModelCompletionMetadata)
            for candidate in rows
        )
        is_history = completion_kind == "file_history"
        is_arg_completion = completion_kind in ("xprompt_arg_name", "xprompt_arg_value")
        is_xprompt_arg_agent = completion_kind == "xprompt_arg_agent"
        is_jinja = completion_kind == "jinja"
        is_placeholder = completion_kind == PLACEHOLDER_COMPLETION_KIND
        is_prompt_word = completion_kind == PROMPT_WORD_COMPLETION_KIND
        is_history_word = completion_kind == HISTORY_WORD_COMPLETION_KIND
        is_vcs_project = completion_kind == VCS_PROJECT_COMPLETION_KIND
        is_vcs_ref = completion_kind == VCS_REF_COMPLETION_KIND
        is_vcs_repo = completion_kind == VCS_REPO_COMPLETION_KIND
        is_artifact_ref = completion_kind == ARTIFACT_REF_COMPLETION_KIND
        tribe_colors: dict[str, str] | None = None
        if is_directive_arg_agent or is_xprompt_arg_agent:
            tribe_colors = named_tribe_identity_colors(
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
        vcs_project_width = (
            max(
                (vcs_project_label_width(candidate) for candidate in visible),
                default=0,
            )
            if is_vcs_project
            else 0
        )
        vcs_ref_width = (
            max(
                (vcs_ref_label_width(candidate) for candidate in visible),
                default=0,
            )
            if is_vcs_ref
            else 0
        )
        vcs_repo_width = (
            max(
                (vcs_repo_label_width(candidate) for candidate in visible),
                default=0,
            )
            if is_vcs_repo
            else 0
        )
        model_widths = (
            model_completion_column_widths(visible) if is_model_completion else (0, 0)
        )
        _clear_jinja_panel_classes(panel)
        content = Text()
        for i, candidate in enumerate(visible):
            actual_idx = scroll_offset + i
            is_selected = actual_idx == selected_index

            if is_selected:
                content.append("\u25b8 ", style="bold")
            else:
                content.append("  ")

            if is_xprompt:
                append_xprompt_completion_row(content, candidate, is_selected)
            elif is_directive:
                append_directive_completion_row(content, candidate, is_selected)
            elif is_directive_arg:
                if isinstance(candidate.metadata, ModelCompletionMetadata):
                    append_model_completion_row(
                        content,
                        candidate,
                        is_selected,
                        model_widths,
                    )
                else:
                    append_directive_arg_completion_row(
                        content,
                        candidate,
                        is_selected,
                        tribe_colors=tribe_colors,
                        model_widths=model_widths,
                    )
            elif is_xprompt_arg_agent:
                append_agent_completion_row(
                    content,
                    candidate,
                    is_selected,
                    tribe_colors=tribe_colors,
                )
            elif is_vcs_project:
                append_vcs_project_completion_row(
                    content,
                    candidate,
                    is_selected,
                    vcs_project_width,
                )
            elif is_vcs_ref:
                append_vcs_ref_completion_row(
                    content,
                    candidate,
                    is_selected,
                    vcs_ref_width,
                )
            elif is_vcs_repo:
                append_vcs_repo_completion_row(
                    content,
                    candidate,
                    is_selected,
                    vcs_repo_width,
                )
            elif is_artifact_ref:
                append_artifact_ref_completion_row(
                    content,
                    candidate,
                    is_selected,
                )
            elif is_arg_completion:
                content.append(
                    candidate.display,
                    style="bold yellow" if is_selected else "yellow",
                )
            elif is_jinja:
                append_jinja_completion_row(content, candidate, is_selected)
            elif is_placeholder:
                append_placeholder_completion_row(content, candidate, is_selected)
            elif is_prompt_word:
                append_prompt_word_completion_row(content, candidate, is_selected)
            elif is_history_word:
                if isinstance(
                    candidate.metadata,
                    HistoryWordCompletionPlaceholder,
                ):
                    content.append(candidate.display, style="dim italic")
                else:
                    append_prompt_word_completion_row(content, candidate, is_selected)
            elif candidate.is_dir:
                content.append("\U0001f4c1 ")
                content.append(
                    candidate.display, style="bold cyan" if is_selected else "cyan"
                )
            else:
                content.append("\U0001f4c4 ")
                content.append(candidate.display, style="bold" if is_selected else "")

            if i < len(visible) - 1:
                content.append("\n")

        remaining = total - (scroll_offset + len(visible))
        if remaining > 0:
            content.append(f"\n  \u2193 {remaining} more\u2026", style="dim")

        # Use a provider-specific title; path completion shows its directory.
        if is_xprompt:
            panel.border_title = "xprompts"
        elif is_directive:
            panel.border_title = "directives"
        elif is_directive_arg_agent:
            panel.border_title = "wait targets"
        elif is_model_completion:
            panel.border_title = (
                "model aliases" if token.startswith("@") else "%model values"
            )
        elif is_directive_arg:
            panel.border_title = "directive values"
        elif is_vcs_project:
            panel.border_title = "projects & PRs"
        elif is_vcs_ref:
            panel.border_title = token
        elif is_vcs_repo:
            panel.border_title = token
        elif is_artifact_ref:
            panel.border_title = token
        elif is_xprompt_arg_agent:
            panel.border_title = "fork targets"
        elif completion_kind == "xprompt_arg_name":
            panel.border_title = "xprompt arg names"
        elif completion_kind == "xprompt_arg_value":
            panel.border_title = "xprompt arg values"
        elif completion_kind == "xprompt_arg_path":
            panel.border_title = "xprompt path"
        elif is_jinja:
            panel.border_title = "jinja"
        elif is_placeholder:
            panel.border_title = "placeholder"
        elif is_prompt_word:
            panel.border_title = "prompt words"
        elif is_history_word:
            panel.border_title = "history words"
        elif is_history:
            panel.border_title = "recent files"
        elif "/" in token:
            panel.border_title = token[: token.rindex("/") + 1]
        else:
            panel.border_title = token

        delete_subtitle = _completion_delete_subtitle(completion_kind, visible)
        if delete_subtitle:
            panel.border_subtitle = delete_subtitle
        elif is_model_completion:
            panel.border_subtitle = _model_completion_subtitle(
                rows,
                selected_index,
                max(0, panel.size.width - 2),
            )
        else:
            panel.border_subtitle = ""

        panel.update(content)
        panel.remove_class("hidden")
        self._completion_visible = True
        self._completion_panel_kind = "completion"
        self._completion_line_count = _reserved_panel_rows(_content_line_count(content))
        self._update_height()

    def hide_file_completions(self) -> None:
        """Hide the shared manual-completion panel."""
        panel = self._completion_panel()
        if panel is None:
            return
        was_jinja = self._completion_panel_kind == "jinja"
        panel.update("")
        panel.border_title = ""
        panel.border_subtitle = ""
        _clear_jinja_panel_classes(panel)
        panel.add_class("hidden")
        self._completion_visible = False
        self._completion_panel_kind = None
        self._completion_line_count = 0
        self._update_height()
        if not was_jinja:
            self._maybe_show_active_jinja_diagnostics()

    def set_prompt_mode_subtitle(self, subtitle: str) -> None:
        """Set the prompt mode subtitle, preserving any visible soft suggestion."""
        self._mode_subtitle = subtitle
        if not self._soft_completion_visible:
            self.border_subtitle = subtitle

    def show_soft_completion(self, suggestion: PromptSoftCompletion) -> None:
        """Render a soft completion in the prompt bar subtitle."""
        if self._completion_panel_kind == "jinja":
            return
        display = suggestion.display.replace("\n", " ").strip()
        if len(display) > 48:
            display = f"{display[:45]}..."
        self._soft_completion_visible = True
        self.border_subtitle = f"[^L] accept {display}"

    def hide_soft_completion(self) -> None:
        """Restore the mode subtitle when no soft completion is visible."""
        if not self._soft_completion_visible:
            return
        self._soft_completion_visible = False
        self.border_subtitle = self._mode_subtitle

    def show_xprompt_arg_hint(self, hint: ActiveXPromptArgHint) -> None:
        """Show the post-accept xprompt argument hint panel."""
        panel = self._completion_panel()
        if panel is None:
            return
        content = Text()
        content.append(hint.reference_text, style="bold green")
        content.append(" arguments", style="dim")
        append_input_hints(
            content,
            hint.entry.inputs,
            active_index=hint.active_input_index,
            include_descriptions=True,
        )

        panel.border_title = "xprompt args"
        panel.border_subtitle = "[:] colon  [(] named args"
        panel.update(content)
        _clear_jinja_panel_classes(panel)
        panel.remove_class("hidden")
        self._completion_visible = True
        self._completion_panel_kind = "xprompt_arg_hint"
        self._completion_line_count = _reserved_panel_rows(_content_line_count(content))
        self._update_height()

    def show_jinja_diagnostics(self, diagnostics: object) -> None:
        """Show Jinja2 diagnostics if no higher-priority panel is active."""
        if self._completion_visible and self._completion_panel_kind != "jinja":
            return
        panel = self._completion_panel()
        if panel is None:
            return
        self.hide_soft_completion()
        content = Text()
        unknown = tuple(getattr(diagnostics, "unknown_variables", ()) or ())
        ok = bool(getattr(diagnostics, "ok", True))
        if not ok:
            line = getattr(diagnostics, "lineno", None) or 1
            message = getattr(diagnostics, "message", None) or "invalid template"
            content.append(f"L{line} ", style="bold red")
            content.append(str(message), style="red")
            panel.add_class("jinja-error")
            panel.remove_class("jinja-warning")
        elif unknown:
            label = "variable" if len(unknown) == 1 else "variables"
            content.append(f"unknown {label}: ", style="bold yellow")
            content.append(", ".join(unknown), style="yellow")
            panel.add_class("jinja-warning")
            panel.remove_class("jinja-error")
        else:
            self.hide_jinja_diagnostics()
            return

        panel.border_title = "jinja diagnostics"
        panel.border_subtitle = ""
        panel.update(content)
        panel.add_class("jinja-diagnostics")
        panel.remove_class("hidden")
        self._completion_visible = True
        self._completion_panel_kind = "jinja"
        self._completion_line_count = _reserved_panel_rows(
            _content_line_count(content),
            _JINJA_PANEL_MAX_HEIGHT,
        )
        self._update_height()

    def hide_jinja_diagnostics(self) -> None:
        """Hide the diagnostics panel when it is showing Jinja2 content."""
        if self._completion_panel_kind != "jinja":
            return
        self.hide_file_completions()


def _clear_jinja_panel_classes(panel: Static) -> None:
    panel.remove_class("jinja-diagnostics")
    panel.remove_class("jinja-error")
    panel.remove_class("jinja-warning")


def _content_line_count(content: Text) -> int:
    return len(content.plain.splitlines()) if content.plain else 0


def _visible_placeholder_sources(
    visible: list[CompletionCandidate],
) -> set[str]:
    sources: set[str] = set()
    for candidate in visible:
        metadata = (
            candidate.metadata
            if isinstance(candidate.metadata, PlaceholderCompletionMetadata)
            else None
        )
        sources.add(
            "common"
            if metadata is not None and metadata.source == "common"
            else "prompt"
        )
    return sources
