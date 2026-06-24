"""Completion panel behavior for PromptInputBar."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.text import Text
from textual.widgets import Static

from sase.ace.tui.widgets.directive_completion import (
    DirectiveArgCompletionMetadata,
    DirectiveCompletionMetadata,
)
from sase.ace.tui.widgets.file_completion import MAX_VISIBLE, CompletionCandidate
from sase.ace.tui.widgets.jinja_completion import JinjaCompletionMetadata
from sase.ace.tui.widgets.prompt_completion import PromptSoftCompletion
from sase.ace.tui.widgets.vcs_project_completion import VCS_PROJECT_COMPLETION_KIND
from sase.ace.tui.widgets.xprompt_arg_assist import (
    ActiveXPromptArgHint,
    XPromptAssistEntry,
    append_input_hints,
)
from sase.xprompt.vcs_project_completion import VcsProjectEntry

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


def _reserved_panel_rows(
    line_count: int,
    max_height: int = _COMPLETION_PANEL_MAX_HEIGHT,
) -> int:
    """Rows occupied by the completion panel, clamped to its CSS max-height."""
    border_box = min(line_count + _PANEL_BORDER_ROWS, max_height)
    return border_box + _PANEL_MARGIN_ROWS


def _vcs_project_label_width(candidate: CompletionCandidate) -> int:
    """Visible width for the badge + primary label in a VCS completion row."""
    entry = (
        candidate.metadata if isinstance(candidate.metadata, VcsProjectEntry) else None
    )
    if entry is None:
        return len(candidate.display)
    badge_width = 5 if entry.kind == "changespec" else 4
    return badge_width + len(entry.name)


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

    def show_file_completions(
        self,
        token: str,
        rows: list[CompletionCandidate],
        selected_index: int,
        scroll_offset: int = 0,
        completion_kind: str = "file",
    ) -> None:
        """Show the path/xprompt completion panel with Rich styling.

        Args:
            token: Current token being completed.
            rows: Completion entries.
            selected_index: Highlighted row index.
            scroll_offset: First visible entry index for scrolling.
            completion_kind: "file" for path completion, "xprompt" for xprompt.
        """
        panel = self.query_one("#prompt-completion", Static)
        total = len(rows)
        visible = rows[scroll_offset : scroll_offset + MAX_VISIBLE]

        is_xprompt = completion_kind == "xprompt"
        is_directive = completion_kind == "directive"
        is_directive_arg = completion_kind == "directive_arg"
        is_history = completion_kind == "file_history"
        is_arg_completion = completion_kind in ("xprompt_arg_name", "xprompt_arg_value")
        is_jinja = completion_kind == "jinja"
        is_vcs_project = completion_kind == VCS_PROJECT_COMPLETION_KIND
        vcs_project_label_width = (
            max(
                (_vcs_project_label_width(candidate) for candidate in visible),
                default=0,
            )
            if is_vcs_project
            else 0
        )
        panel.remove_class("jinja-diagnostics")
        panel.remove_class("jinja-error")
        panel.remove_class("jinja-warning")
        content = Text()
        for i, candidate in enumerate(visible):
            actual_idx = scroll_offset + i
            is_selected = actual_idx == selected_index

            if is_selected:
                content.append("\u25b8 ", style="bold")
            else:
                content.append("  ")

            if is_xprompt:
                self._append_xprompt_completion_row(content, candidate, is_selected)
            elif is_directive:
                self._append_directive_completion_row(content, candidate, is_selected)
            elif is_directive_arg:
                self._append_directive_arg_completion_row(
                    content,
                    candidate,
                    is_selected,
                )
            elif is_vcs_project:
                self._append_vcs_project_completion_row(
                    content,
                    candidate,
                    is_selected,
                    vcs_project_label_width,
                )
            elif is_arg_completion:
                content.append(
                    candidate.display,
                    style="bold yellow" if is_selected else "yellow",
                )
            elif is_jinja:
                self._append_jinja_completion_row(content, candidate, is_selected)
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

        # Border title: "xprompts" for xprompt completion, "recent files"
        # for file-history completion, directory for file.
        if is_xprompt:
            panel.border_title = "xprompts"
        elif is_directive:
            panel.border_title = "directives"
        elif is_directive_arg:
            panel.border_title = "directive values"
        elif is_vcs_project:
            panel.border_title = "projects & PRs"
        elif completion_kind == "xprompt_arg_name":
            panel.border_title = "xprompt arg names"
        elif completion_kind == "xprompt_arg_value":
            panel.border_title = "xprompt arg values"
        elif completion_kind == "xprompt_arg_path":
            panel.border_title = "xprompt path"
        elif is_jinja:
            panel.border_title = "jinja"
        elif is_history:
            panel.border_title = "recent files"
        elif "/" in token:
            panel.border_title = token[: token.rindex("/") + 1]
        else:
            panel.border_title = token

        if is_history:
            panel.border_subtitle = "[^L] accept  [^D] delete"
        else:
            panel.border_subtitle = ""

        panel.update(content)
        panel.remove_class("hidden")
        self._completion_visible = True
        self._completion_panel_kind = "completion"
        line_count = len(content.plain.splitlines()) if content.plain else 0
        self._completion_line_count = _reserved_panel_rows(line_count)
        self._update_height()

    def _append_xprompt_completion_row(
        self,
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

    def _append_directive_completion_row(
        self,
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
            details.append(
                "alias " + ", ".join(f"%{alias}" for alias in metadata.aliases)
            )
        if metadata.description:
            details.append(metadata.description)
        if details:
            content.append(f"  {'  '.join(details)}", style="dim")

    def _append_directive_arg_completion_row(
        self,
        content: Text,
        candidate: CompletionCandidate,
        is_selected: bool,
    ) -> None:
        """Append one prompt directive argument completion row."""
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

    def _append_vcs_project_completion_row(
        self,
        content: Text,
        candidate: CompletionCandidate,
        is_selected: bool,
        label_width: int = 0,
    ) -> None:
        """Append one ``#+`` project/PR completion row.

        Project and ChangeSpec rows use the same badges as the ProjectSelect
        modal. The empty-catalog placeholder (no :class:`VcsProjectEntry`
        metadata) renders as a single dim row.
        """
        entry = (
            candidate.metadata
            if isinstance(candidate.metadata, VcsProjectEntry)
            else None
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
                content.append(f"  · {entry.project}", style="dim")
        else:
            content.append(f"  {entry.provider_display}", style="dim")
            if entry.description:
                content.append(f"  {entry.description}", style="dim")

    def _append_jinja_completion_row(
        self,
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

    def hide_file_completions(self) -> None:
        """Hide the path completion panel."""
        panel = self.query_one("#prompt-completion", Static)
        was_jinja = self._completion_panel_kind == "jinja"
        panel.update("")
        panel.border_title = ""
        panel.border_subtitle = ""
        panel.remove_class("jinja-diagnostics")
        panel.remove_class("jinja-error")
        panel.remove_class("jinja-warning")
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
        panel = self.query_one("#prompt-completion", Static)
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
        panel.remove_class("jinja-diagnostics")
        panel.remove_class("jinja-error")
        panel.remove_class("jinja-warning")
        panel.remove_class("hidden")
        self._completion_visible = True
        self._completion_panel_kind = "xprompt_arg_hint"
        line_count = len(content.plain.splitlines()) if content.plain else 0
        self._completion_line_count = _reserved_panel_rows(line_count)
        self._update_height()

    def show_jinja_diagnostics(self, diagnostics: object) -> None:
        """Show Jinja2 diagnostics if no higher-priority panel is active."""
        if self._completion_visible and self._completion_panel_kind != "jinja":
            return
        self.hide_soft_completion()
        panel = self.query_one("#prompt-completion", Static)
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
        line_count = len(content.plain.splitlines()) if content.plain else 0
        self._completion_line_count = _reserved_panel_rows(
            line_count,
            _JINJA_PANEL_MAX_HEIGHT,
        )
        self._update_height()

    def hide_jinja_diagnostics(self) -> None:
        """Hide the diagnostics panel when it is showing Jinja2 content."""
        if self._completion_panel_kind != "jinja":
            return
        self.hide_file_completions()
