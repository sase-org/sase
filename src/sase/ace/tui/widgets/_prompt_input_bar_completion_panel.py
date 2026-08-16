"""Completion panel state management for PromptInputBar.

Row rendering, provider classification, and border labels live in the focused
``_prompt_input_bar_completion_panel_*`` modules; this module owns the panel
widget's lifecycle, its reserved height, and the prompt bar subtitle.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.cells import cell_len
from rich.text import Text
from textual.css.query import NoMatches
from textual.widgets import Static

from sase.ace.tui.widgets._prompt_cursor_readout import (
    cursor_readout_cell_width,
    cursor_readout_position,
    format_cursor_readout,
)
from sase.ace.tui.widgets._prompt_input_bar_completion_panel_content import (
    build_completion_panel_content,
)
from sase.ace.tui.widgets._prompt_input_bar_completion_panel_kinds import (
    CompletionPanelKinds,
    at_reference_group_rule_needed,
)
from sase.ace.tui.widgets._prompt_input_bar_completion_panel_labels import (
    agent_completion_subtitle,
    artifact_ref_completion_subtitle,
    completion_delete_subtitle,
    completion_panel_title,
    model_completion_subtitle,
)
from sase.ace.tui.widgets.artifact_ref_completion import (
    ARTIFACT_REF_COMPLETION_KIND,
)
from sase.ace.tui.widgets.file_completion import (
    COMPLETION_PANEL_BORDER_ROWS,
    COMPLETION_PANEL_MAX_HEIGHT,
    CompletionCandidate,
    completion_visible_rows,
)
from sase.ace.tui.widgets.prompt_completion import PromptSoftCompletion
from sase.ace.tui.widgets.xprompt_arg_assist import (
    ActiveXPromptArgHint,
    append_input_hints,
)

if TYPE_CHECKING:
    from textual.widgets import Static as _MixinBase

    from sase.ace.tui.widgets.prompt_text_area import PromptTextArea
else:
    _MixinBase = object

# Mirror styles.tcss for #prompt-completion. The panel reserves a border-box
# height capped by max-height, plus its one-row bottom margin. The border and
# max-height mirrors live in file_completion so the row budget and the height
# reservation cannot drift apart.
_PANEL_MARGIN_ROWS = 1
_JINJA_PANEL_MAX_HEIGHT = 5

# Border corners + label padding that ``render_border_label`` reserves before
# truncating the subtitle; pinned empirically by the narrow-width widget test.
_SUBTITLE_BORDER_RESERVED_CELLS = 6
_CURSOR_READOUT_DIVIDER = "  ·  "


def _reserved_panel_rows(
    line_count: int,
    max_height: int = COMPLETION_PANEL_MAX_HEIGHT,
) -> int:
    """Rows occupied by the completion panel, clamped to its CSS max-height."""
    border_box = min(line_count + COMPLETION_PANEL_BORDER_ROWS, max_height)
    return border_box + _PANEL_MARGIN_ROWS


class PromptInputBarCompletionMixin(_MixinBase):
    """Completion panel, soft-completion subtitle, and argument hint rendering."""

    if TYPE_CHECKING:
        _completion_line_count: int
        _completion_panel_kind: str | None
        _completion_visible: bool
        _mode_subtitle: str
        _soft_completion_visible: bool
        _subtitle_base: str

        def _update_height(self) -> None: ...
        def _maybe_show_active_jinja_diagnostics(self) -> None: ...
        def active_text_area(self) -> PromptTextArea: ...

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
        group_rule: bool = False,
        group_directory: str = "",
        artifact_ref_payload_count: int = 0,
        artifact_ref_payload_total: int = 0,
        artifact_ref_truncated_payloads: int = 0,
        artifact_ref_files_suppressed: bool = False,
    ) -> None:
        """Show the shared manual-completion panel with Rich styling.

        Args:
            token: Current token being completed.
            rows: Completion entries.
            selected_index: Highlighted row index.
            scroll_offset: First visible entry index for scrolling.
            completion_kind: Named provider kind used to render rows and title.
            group_rule: True when a group rule line is drawn between groups,
                which claims one of the panel's content lines.
            group_directory: Resolved directory named by an ``@`` group rule.
        """
        panel = self._completion_panel()
        if panel is None:
            return
        total = len(rows)
        if completion_kind == ARTIFACT_REF_COMPLETION_KIND:
            group_rule = group_rule and at_reference_group_rule_needed(rows)
        row_budget = completion_visible_rows(total, group_rule=group_rule)
        visible = rows[scroll_offset : scroll_offset + row_budget]
        kinds = CompletionPanelKinds.classify(completion_kind, rows)

        # A hidden panel has no measured width on its first open. The prompt
        # bar is already laid out; subtract the panel's two border and two
        # padding columns to recover the content size used after layout.
        panel_width = panel.size.width or max(0, self.size.width - 4)
        panel_inner_width = max(0, panel_width - 2)
        _clear_jinja_panel_classes(panel)
        content = build_completion_panel_content(
            kinds,
            visible,
            total=total,
            selected_index=selected_index,
            scroll_offset=scroll_offset,
            group_rule=group_rule,
            group_directory=group_directory,
            inner_width=panel_inner_width,
        )

        panel.border_title = completion_panel_title(
            kinds,
            token,
            rows,
            group_directory,
        )

        delete_subtitle = completion_delete_subtitle(completion_kind, visible)
        if delete_subtitle:
            panel.border_subtitle = delete_subtitle
        elif kinds.artifact_ref:
            panel.border_subtitle = artifact_ref_completion_subtitle(
                visible,
                artifact_ref_payload_count,
                artifact_ref_payload_total,
                artifact_ref_truncated_payloads,
                panel_inner_width,
                artifact_ref_files_suppressed,
            )
        elif kinds.model:
            panel.border_subtitle = model_completion_subtitle(
                rows,
                selected_index,
                max(0, panel.size.width - 2),
            )
        elif kinds.directive_arg_agent or kinds.xprompt_arg_agent:
            panel.border_subtitle = agent_completion_subtitle(
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
            self._subtitle_base = subtitle
            self.border_subtitle = self._render_subtitle(subtitle)

    def show_soft_completion(self, suggestion: PromptSoftCompletion) -> None:
        """Render a soft completion in the prompt bar subtitle."""
        if self._completion_panel_kind == "jinja":
            return
        display = suggestion.display.replace("\n", " ").strip()
        if len(display) > 48:
            display = f"{display[:45]}..."
        self._soft_completion_visible = True
        base = f"[^L] accept {display}"
        self._subtitle_base = base
        self.border_subtitle = self._render_subtitle(base)

    def hide_soft_completion(self) -> None:
        """Restore the mode subtitle when no soft completion is visible."""
        if not self._soft_completion_visible:
            return
        self._soft_completion_visible = False
        self._subtitle_base = self._mode_subtitle
        self.border_subtitle = self._render_subtitle(self._mode_subtitle)

    def _render_subtitle(self, base: str) -> Text:
        """Compose *base* with the active pane's cursor readout, width-aware.

        The readout wins over *base*: when both cannot fit the bar's usable
        border-label width, ``base`` is truncated (with an ellipsis) first,
        since every hint it carries is also reachable from the ``?`` help
        modal and the ``g``-prefix hint panel; the readout has no other home.
        Builds a ``rich.text.Text`` rather than a markup string so literal
        ``[`` characters in *base* (e.g. ``"[Enter] send"``) are never parsed
        as markup.
        """
        try:
            text_area = self.active_text_area()
        except Exception:
            return Text(base, no_wrap=True)
        line, column = cursor_readout_position(text_area)
        readout = format_cursor_readout(line, column, vim_mode=text_area._vim_mode)
        readout_width = cursor_readout_cell_width(line, column)
        divider_width = cell_len(_CURSOR_READOUT_DIVIDER)
        usable = max(0, self.size.width - _SUBTITLE_BORDER_RESERVED_CELLS)

        if cell_len(base) + divider_width + readout_width <= usable:
            result = Text(base, no_wrap=True)
            result.append(_CURSOR_READOUT_DIVIDER, style="dim")
            result.append_text(readout)
            return result

        remaining = usable - divider_width - readout_width
        if remaining > 0:
            base_text = Text(base, no_wrap=True, overflow="ellipsis")
            base_text.truncate(remaining, overflow="ellipsis")
            result = Text(no_wrap=True)
            result.append_text(base_text)
            result.append(_CURSOR_READOUT_DIVIDER, style="dim")
            result.append_text(readout)
            return result

        result = Text(no_wrap=True, overflow="ellipsis")
        result.append_text(readout)
        result.truncate(usable, overflow="ellipsis")
        return result

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
