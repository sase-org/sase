"""Prompt input bar widget for agent workflow in the ace TUI."""

from __future__ import annotations

from pathlib import Path
import time
from typing import Any

from rich.cells import cell_len
from rich.markup import escape
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Static

from sase.ace.tui.widgets._prompt_input_bar_actions import (
    PromptInputBarActionsMixin,
)
from sase.ace.tui.widgets._prompt_input_bar_completion import (
    PromptInputBarCompletionMixin,
)
from sase.ace.tui.widgets._prompt_input_bar_frontmatter import (
    InlineExpansionTransaction,
    PromptInputBarFrontmatterMixin,
)
from sase.ace.tui.widgets._prompt_input_bar_g_prefix_hints import (
    PromptInputBarGPrefixHintsMixin,
)
from sase.ace.tui.widgets._prompt_input_bar_messages import (
    AllEditorRequested as _AllEditorRequested,
    Cancelled as _Cancelled,
    EditorRequested as _EditorRequested,
    HistoryRequested as _HistoryRequested,
    RestoreRequested as _RestoreRequested,
    SaveAsXpromptRequested as _SaveAsXpromptRequested,
    SnippetPaneSaveRequested as _SnippetPaneSaveRequested,
    SnippetRequested as _SnippetRequested,
    SnippetTargetRequested as _SnippetTargetRequested,
    Stashed as _Stashed,
    Submitted as _Submitted,
    UpdatePinnedRequested as _UpdatePinnedRequested,
    WorkflowEditorRequested as _WorkflowEditorRequested,
    WriteXpromptRequested as _WriteXpromptRequested,
)
from sase.ace.tui.widgets._prompt_input_bar_stack_actions import (
    PromptInputBarStackActionsMixin,
    StashedPromptPane,
)
from sase.ace.tui.widgets._prompt_input_bar_stack_rendering import (
    PromptInputBarStackRenderingMixin,
)
from sase.ace.tui.widgets._prompt_input_bar_search import (
    PromptInputBarSearchMixin,
)
from sase.ace.tui.widgets._prompt_input_bar_snippet_pane import (
    PromptInputBarSnippetPaneMixin,
)
from sase.ace.tui.widgets._prompt_input_bar_stack_models import PromptFocusRestore
from sase.ace.tui.widgets.frontmatter_panel import FrontmatterPanel
from sase.ace.tui.widgets.prompt_stack import (
    PromptStackState,
    XPromptReadonlyTarget,
)
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea
from sase.ace.tui.widgets._todo_highlight import (
    todo_annotation_count,
    todo_theme_colors,
)
from sase.xprompt.models import InputArg

__all__ = ["PromptInputBar", "StashedPromptPane"]

_TARGET_STALE_CHECK_INTERVAL_SECONDS = 3.0


def _take_cells(value: str, width: int, *, from_right: bool = False) -> str:
    """Return a prefix/suffix of *value* that fits in *width* terminal cells."""
    if width <= 0:
        return ""
    chars = reversed(value) if from_right else iter(value)
    used = 0
    taken: list[str] = []
    for char in chars:
        char_width = max(cell_len(char), 0)
        if used + char_width > width:
            break
        taken.append(char)
        used += char_width
    if from_right:
        taken.reverse()
    return "".join(taken)


def _middle_elide_cells(value: str, width: int) -> str:
    """Fit *value* in *width* cells, preserving the path tail."""
    if width <= 0:
        return ""
    if cell_len(value) <= width:
        return value
    if width == 1:
        return "…"
    left_width = max(1, (width - 1) // 2)
    right_width = max(0, width - 1 - left_width)
    suffix = _take_cells(value, right_width, from_right=True)
    return f"{_take_cells(value, left_width)}…{suffix}"


class PromptInputBar(
    PromptInputBarFrontmatterMixin,
    PromptInputBarSnippetPaneMixin,
    PromptInputBarStackActionsMixin,
    PromptInputBarGPrefixHintsMixin,
    PromptInputBarSearchMixin,
    PromptInputBarActionsMixin,
    PromptInputBarCompletionMixin,
    PromptInputBarStackRenderingMixin,
    Static,
):
    """Prompt input bar for agent workflow, positioned at bottom of screen."""

    Submitted = _Submitted
    Cancelled = _Cancelled
    Stashed = _Stashed
    RestoreRequested = _RestoreRequested
    UpdatePinnedRequested = _UpdatePinnedRequested
    SaveAsXpromptRequested = _SaveAsXpromptRequested
    EditorRequested = _EditorRequested
    AllEditorRequested = _AllEditorRequested
    HistoryRequested = _HistoryRequested
    SnippetRequested = _SnippetRequested
    SnippetTargetRequested = _SnippetTargetRequested
    SnippetPaneSaveRequested = _SnippetPaneSaveRequested
    WorkflowEditorRequested = _WorkflowEditorRequested
    WriteXpromptRequested = _WriteXpromptRequested

    BINDINGS = []  # type: ignore[assignment]

    def __init__(
        self,
        initial_value: str = "",
        mode: str = "prompt",
        *,
        initial_panes: list[str] | None = None,
        initial_xprompt_markdown: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._initial_value = initial_value
        self._mode = mode
        self._completion_visible = False
        self._completion_line_count = 0
        self._completion_panel_kind: str | None = None
        self._g_prefix_hints_visible = False
        self._g_prefix_hints_line_count = 0
        self._g_prefix_hints_signature: tuple[
            str, tuple[tuple[str, tuple[str, ...], str], ...]
        ] = ("", ())
        self._search_command_visible = False
        self._search_command_line_count = 0
        self._mode_subtitle = "[Enter] send  [Esc] normal  [^C] cancel"
        self._subtitle_base = self._mode_subtitle
        self._soft_completion_visible = False
        self._title_mode_suffix = ""
        self._readonly_xprompt_target: XPromptReadonlyTarget | None = None
        self._xprompt_source_stale = False
        self._xprompt_stale_check_in_flight = False
        self._xprompt_stale_checked_mono = 0.0
        self._xprompt_target_generation = 0
        # Monotonic per-rebuild id namespace so a fresh stack mounted while the
        # previous panes are still being detached never collides on widget ids.
        self._generation = 0
        self._snippet_focus_restore: PromptFocusRestore | None = None
        self._placeholder = ""
        # ``#@`` + ``Ctrl+I`` inline expansions that auto-staged xprompt inputs,
        # coupled to the body splice so NORMAL-mode ``u`` / ``Ctrl+R`` unstage /
        # restage them. ``_auto_staged_inputs`` maps a currently auto-owned input
        # name to its persisted declaration (to detect later user edits).
        self._inline_expansion_txns: list[InlineExpansionTransaction] = []
        self._auto_staged_inputs: dict[str, InputArg] = {}
        if initial_panes is not None:
            # Explicit pane seeding: one verbatim pane per entry, never split on
            # an embedded ``---`` or lifted frontmatter. Used by bulk
            # kill-and-edit so each killed agent maps to exactly one pane.
            self._stack = PromptStackState.from_panes(initial_panes)
        elif initial_xprompt_markdown is not None:
            # Editor-file semantics: lift leading xprompt frontmatter into the
            # shared stack frontmatter and split real ``---`` body separators
            # into one pane per agent segment. Used when a ` @`-review-marker
            # editor return remounts the bar for review (frontmatter auto-shows
            # on mount). Compared with ``initial_value`` history-load semantics,
            # this path also normalizes a lone body pane through the canonical
            # splitter instead of keeping the body text verbatim.
            self._stack = PromptStackState.from_text(initial_xprompt_markdown)
        else:
            self._stack = self._state_from_text(initial_value)
        self._frontmatter_return_index = self._stack.selected_index
        self._todo_counts_by_item_id: dict[str, int] = {}
        self._sync_todo_counts_from_stack()

    @property
    def _base_title(self) -> str:
        """Return the base border title based on mode."""
        if self._mode == "feedback":
            return "Plan Feedback"
        if self._mode == "approve_prompt":
            return "Coder Prompt"
        return "Prompt"

    def _refresh_title(self, mode_suffix: str = "") -> None:
        """Refresh the border title, including stack count in prompt stacks."""
        self._title_mode_suffix = mode_suffix
        title = self._base_title
        if self._mode == "prompt" and self._stack.agent_count > 1:
            title = f"{title} · {self._stack.agent_count} agents"
        if self._mode == "prompt" and (
            self._stack.binding is not None or self._readonly_xprompt_target is not None
        ):
            try:
                self._sync_state_from_widgets()
            except Exception:
                pass
            target = self._target_title_payload()
            if target is not None:
                title = self._format_target_title(title, target)
                self._refresh_target_classes()
        if mode_suffix:
            # Border titles parse Rich markup; escape literal mode brackets.
            mode_suffix = mode_suffix.replace("[", "\\[")
            title = f"{title} {mode_suffix}"
        todo_chip = self._todo_chip_markup()
        if todo_chip:
            title = f"{title}  {todo_chip}"
        chip = self._active_jinja_chip_markup()
        if chip:
            title = f"{title}  {chip}"
        self.border_title = title

    def _target_title_payload(self) -> tuple[str, str | None, str] | None:
        """Return ``(reference, path, state)`` for the target title chrome."""
        readonly = self._readonly_xprompt_target
        if readonly is not None:
            return readonly.reference, readonly.path, "readonly"
        binding = self._stack.binding
        if binding is None:
            return None
        if self._xprompt_source_stale:
            state = "stale"
        elif self._stack.is_dirty:
            state = "dirty"
        else:
            state = "clean"
        return binding.reference, binding.write_path, state

    def _format_target_title(
        self,
        prefix: str,
        target: tuple[str, str | None, str],
    ) -> str:
        reference, path, state = target
        state_plain = {
            "clean": "✓",
            "dirty": "●",
            "readonly": "🔒 read-only",
            "stale": "⚠ changed on disk",
        }[state]
        path_markup = ""
        if path:
            width = self._target_path_width(prefix, reference, state_plain)
            path_markup = f" · [dim]{escape(self._target_display_path(path, width))}[/]"
        return (
            f"{prefix} · {self._target_reference_chip_markup(reference)}"
            f"{path_markup} · {self._target_state_marker_markup(state)}"
        )

    def _target_reference_chip_markup(self, reference: str) -> str:
        theme = self._current_theme()
        foreground = self._theme_color(theme, "background", "black")
        background = self._theme_color(theme, "secondary", "cyan")
        return f"[bold {foreground} on {background}] ✎ {escape(reference)} [/]"

    def _target_state_marker_markup(self, state: str) -> str:
        theme = self._current_theme()
        if state == "clean":
            return "[dim]✓[/]"
        if state == "dirty":
            return f"[bold {self._theme_color(theme, 'warning', 'yellow')}]●[/]"
        if state == "readonly":
            muted = self._theme_color(theme, "foreground", "white")
            return f"[dim {muted}]🔒 read-only[/]"
        warning = self._theme_color(theme, "warning", "yellow")
        return f"[bold {warning}]⚠ changed on disk[/]"

    def _target_path_width(
        self,
        prefix: str,
        reference: str,
        state_plain: str,
    ) -> int:
        try:
            total_width = int(self.size.width)
        except Exception:
            total_width = 0
        if total_width <= 0:
            total_width = 88
        reserved = (
            cell_len(prefix)
            + cell_len(f" · ✎ {reference} ")
            + cell_len(f" · {state_plain}")
            + 10
        )
        return max(12, min(56, total_width - reserved))

    @staticmethod
    def _target_display_path(path: str, width: int) -> str:
        home = str(Path.home())
        collapsed = path
        if path == home:
            collapsed = "~"
        elif path.startswith(home + "/"):
            collapsed = "~" + path[len(home) :]
        return _middle_elide_cells(" ".join(collapsed.splitlines()), width)

    def _current_theme(self) -> object | None:
        try:
            return self.app.current_theme
        except Exception:
            return None

    @staticmethod
    def _theme_color(theme: object | None, attr: str, fallback: str) -> str:
        if theme is not None:
            color = getattr(theme, attr, None)
            if color:
                return str(color)
        return fallback

    def _target_hint_reference(self) -> str | None:
        readonly = self._readonly_xprompt_target
        if readonly is not None:
            return readonly.reference
        binding = self._stack.binding
        return binding.reference if binding is not None else None

    def _target_save_hint(self) -> str:
        reference = self._target_hint_reference()
        if reference is None:
            return ""
        verb = "save as" if self._readonly_xprompt_target is not None else "save"
        return f"  [^G w] {verb} {_middle_elide_cells(reference, 24)}"

    def mark_readonly_xprompt_target(self, target: XPromptReadonlyTarget) -> None:
        """Show a persistent read-only source state without binding writes."""
        self._stack.unbind()
        self._readonly_xprompt_target = target
        self._xprompt_source_stale = False
        self._xprompt_target_generation += 1
        self._refresh_target_classes()
        self._refresh_title()
        self._refresh_prompt_mode_subtitle()
        self.refresh_frontmatter_panel_from_stack()

    def _mark_xprompt_source_fresh(self) -> None:
        """Clear the display-only stale flag after a successful write/reload."""
        self._xprompt_source_stale = False
        self._xprompt_target_generation += 1
        self._refresh_target_classes()

    def _schedule_xprompt_stale_check(self, *, force: bool = False) -> None:
        """Schedule one stat-only source staleness check in a worker thread."""
        binding = self._stack.binding
        if binding is None or self._readonly_xprompt_target is not None:
            return
        if not self.is_mounted:
            return
        now = time.monotonic()
        if (
            not force
            and self._xprompt_stale_checked_mono > 0.0
            and now - self._xprompt_stale_checked_mono
            < _TARGET_STALE_CHECK_INTERVAL_SECONDS
        ):
            return
        if self._xprompt_stale_check_in_flight:
            return
        generation = self._xprompt_target_generation
        write_path = binding.write_path
        fingerprint = binding.loaded_fingerprint
        self._xprompt_stale_check_in_flight = True

        def _check() -> None:
            stale = not fingerprint.matches_stat(write_path)
            completed = time.monotonic()
            try:
                self.app.call_from_thread(
                    self._complete_xprompt_stale_check,
                    generation,
                    write_path,
                    stale,
                    completed,
                )
            except Exception:
                self._xprompt_stale_check_in_flight = False

        try:
            self.run_worker(
                _check,
                name="xprompt-target-stale-check",
                thread=True,
                exclusive=True,
                group="xprompt-target-stale-check",
            )
        except Exception:
            self._xprompt_stale_check_in_flight = False

    def _complete_xprompt_stale_check(
        self,
        generation: int,
        write_path: str,
        stale: bool,
        completed_mono: float,
    ) -> None:
        """Apply a worker staleness result if it still matches this target."""
        self._xprompt_stale_check_in_flight = False
        self._xprompt_stale_checked_mono = completed_mono
        binding = self._stack.binding
        if binding is None:
            return
        if (
            generation != self._xprompt_target_generation
            or binding.write_path != write_path
        ):
            return
        if self._xprompt_source_stale == stale:
            return
        self._xprompt_source_stale = stale
        self._refresh_target_classes()
        self._refresh_title(self._title_mode_suffix)

    def _refresh_prompt_mode_subtitle(self) -> None:
        """Refresh the visible prompt subtitle after target-state changes."""
        if not self.is_mounted:
            return
        try:
            mode = self.active_text_area()._vim_mode
        except Exception:
            mode = "insert"
        subtitle = (
            self.insert_mode_subtitle()
            if mode == "insert"
            else self.normal_mode_subtitle()
        )
        self.set_prompt_mode_subtitle(subtitle)

    def _todo_chip_markup(self) -> str:
        """Return the running-gold whole-stack TODO count capsule."""
        count = sum(self._todo_counts_by_item_id.values())
        if count <= 0:
            return ""
        try:
            theme = self.app.current_theme
        except Exception:
            chip_foreground, chip_background, _note_foreground = todo_theme_colors(
                None,
                dark=True,
            )
        else:
            chip_foreground, chip_background, _note_foreground = todo_theme_colors(
                theme.foreground,
                dark=theme.dark,
            )
        return f"[bold {chip_foreground.hex} on {chip_background.hex}] TODO {count} [/]"

    def _sync_todo_counts_from_stack(self) -> None:
        """Refresh count state from the in-memory stack during construction/rebuild."""
        self._todo_counts_by_item_id = {
            item.item_id: todo_annotation_count(item.text)
            for item in self._stack.agent_items
        }

    def _sync_todo_counts_from_mounted_panes(self) -> None:
        """Aggregate each mounted pane's cached annotation count."""
        counts: dict[str, int] = {}
        for item in self._stack.agent_items:
            try:
                text_area = self.query_one(f"#{self._pane_id(item)}", PromptTextArea)
            except Exception:
                counts[item.item_id] = self._todo_counts_by_item_id.get(item.item_id, 0)
                continue
            counts[item.item_id] = text_area.todo_annotation_count
        self._todo_counts_by_item_id = counts

    def _update_todo_count_for_text_area(self, text_area: object) -> None:
        """Update only the edited pane's cached stack count."""
        if not isinstance(text_area, PromptTextArea):
            return
        item = next(
            (
                item
                for item in self._stack.agent_items
                if self._pane_id(item) == text_area.id
            ),
            None,
        )
        if item is not None:
            self._todo_counts_by_item_id[item.item_id] = text_area.todo_annotation_count

    def _active_jinja_chip_markup(self) -> str:
        """Return the active pane's Jinja2 status chip markup."""
        try:
            text_area = self.active_text_area()
        except Exception:
            return ""
        chip = getattr(text_area, "_jinja_chip_markup", None)
        if not callable(chip):
            return ""
        return str(chip())

    def insert_mode_subtitle(self) -> str:
        """Return the insert-mode subtitle, advertising the stack when stacked.

        ``<enter>`` opens the submit chooser for stacked or targeted prompts.
        A multi-pane stack swaps the ``[Esc] normal`` hint for ``[Esc] nav``
        and adds ``[^S] stash`` plus ``[^G Enter] this`` hints for active-pane
        actions.  ``Esc`` still drops into NORMAL mode for the normal ``g``
        prefix; INSERT mode reaches the same prompt-local actions through the
        ``Ctrl+G`` prefix.
        """
        target_hint = self._target_save_hint()
        if self._mode == "prompt" and self._stack.agent_count > 1:
            return (
                "[Enter] submit…  [Esc] nav  [^C] cancel  [^S] stash  "
                f"[^G Enter] this{target_hint}"
            )
        if self._mode == "prompt" and self._target_hint_reference() is not None:
            return f"[Enter] submit…  [Esc] normal  [^C] cancel{target_hint}"
        return "[Enter] send  [Esc] normal  [^C] cancel"

    def normal_mode_subtitle(self) -> str:
        """Return the normal-mode subtitle, advertising the stack keys.

        In a multi-pane stack the active pane's normal-mode hints surface the
        prompt-stack selected-pane submit (``g<enter>``), pane-focus
        (``gj``/``gk``) and reorder (``gJ``/``gK``) keys, plus the ``g`` prefix
        stash-all key (``gs``) and ``<Ctrl+S>`` active-pane stash.  A single-pane
        prompt bar still advertises ``g<enter>`` and ``<Ctrl+S>``; feedback /
        approve-prompt bars keep the original normal-mode hints since they are
        not stashable.  The full ``g`` prefix, including add-pane and
        frontmatter actions, is discoverable through the hint panel.
        """
        target_hint = self._target_save_hint()
        if self._mode == "prompt" and self._stack.agent_count > 1:
            return (
                "[g<enter>] launch  [gj/gk] pane  [gJ/gK] move  "
                f"[^S/gs] stash{target_hint}"
            )
        if self._mode == "prompt":
            return (
                "[Esc] clear  [i] insert  [g<enter>] send  [^S] stash  "
                f"[^C] cancel{target_hint}"
            )
        return "[Esc] clear  [i] insert  [^C] cancel"

    def compose(self) -> ComposeResult:
        """Compose the input bar: completion / leader panels, then stack.

        The frontmatter panel sits directly above ``#prompt-stack`` (prompt mode
        only — feedback / approve-prompt bars are not multi-agent surfaces) and
        starts hidden, auto-showing on mount when the prompt already carries
        frontmatter; otherwise the user opens it with ``g=``.
        """
        self._placeholder = self._compute_placeholder()
        yield Static("", id="prompt-completion", classes="hidden")
        if self._mode == "prompt":
            yield FrontmatterPanel(
                self._stack.frontmatter,
                id="frontmatter-panel",
                classes="hidden",
            )
        yield Static("", id="prompt-g-prefix-hints", classes="hidden")
        yield Static("", id="prompt-search-command", classes="hidden")
        with Vertical(id="prompt-stack"):
            yield from self._build_pane_widgets()

    def _compute_placeholder(self) -> str:
        """Return the empty-pane placeholder text for the current mode."""
        if self._mode == "feedback":
            return "Type plan feedback...  [^G g] editor  [^J] newline"
        if self._mode == "approve_prompt":
            return "Type coder prompt...  [^G g] editor  [^J] newline"
        return (
            "Type prompt  [^K] history  [^T] complete  [^R] find  "
            "[^G g] editor  [^Y] workflow  [^J] newline"
        )

    def on_mount(self) -> None:
        """Focus the active pane on mount and position its cursor at end."""
        text_area = self.active_text_area()
        self.watch(self.app, "theme", self._app_theme_changed, init=False)
        self._sync_todo_counts_from_mounted_panes()
        text_area.focus()
        self._cursor_to_end(text_area)

        # Border title and subtitle
        self._refresh_title()
        self.set_prompt_mode_subtitle(self.insert_mode_subtitle())
        if self._mode in ("feedback", "approve_prompt"):
            self.add_class("feedback-mode")
        self._schedule_xprompt_stale_check(force=True)
        text_area._warm_current_xprompt_assist_entries()
        text_area._warm_current_artifact_ref_completion_catalog()
        text_area._warm_vcs_project_completion_catalog()
        text_area._warm_model_completion_catalog()
        text_area._warm_prompt_path_inventory()
        text_area._warm_history_word_completion_cache()
        text_area._warm_common_placeholder_cache()
        text_area._on_prompt_completion_context_changed()
        self._apply_active_classes()
        self.auto_show_frontmatter_panel()
        self._schedule_height_update()
        self.refresh_cursor_readouts()

    def _app_theme_changed(self) -> None:
        """Recompose theme-derived title chrome after an app theme switch."""
        if self.is_mounted:
            self._refresh_title(self._title_mode_suffix)
