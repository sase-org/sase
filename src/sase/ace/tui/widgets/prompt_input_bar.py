"""Prompt input bar widget for agent workflow in the ace TUI."""

from pathlib import Path
from typing import Any

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
    SnippetRequested as _SnippetRequested,
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
from sase.ace.tui.widgets.frontmatter_panel import FrontmatterPanel
from sase.ace.tui.widgets.prompt_stack import PromptStackState
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea
from sase.ace.tui.widgets._todo_highlight import (
    todo_annotation_count,
    todo_theme_colors,
)
from sase.xprompt.models import InputArg

__all__ = ["PromptInputBar", "StashedPromptPane"]


class PromptInputBar(
    PromptInputBarFrontmatterMixin,
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
        self._soft_completion_visible = False
        self._title_mode_suffix = ""
        # Monotonic per-rebuild id namespace so a fresh stack mounted while the
        # previous panes are still being detached never collides on widget ids.
        self._generation = 0
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
        if self._mode == "prompt" and len(self._stack) > 1:
            title = f"{title} · {len(self._stack)} agents"
        if self._mode == "prompt" and self._stack.binding is not None:
            try:
                self._sync_state_from_widgets()
            except Exception:
                pass
            binding = self._stack.binding
            path = binding.path
            home = str(Path.home())
            if path.startswith(home + "/"):
                path = "~" + path[len(home) :]
            title = f"{title} · {binding.name} · {path}"
            if self._stack.is_dirty:
                title = f"{title} [bold #D0A215]●[/]"
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
            item.item_id: todo_annotation_count(item.text) for item in self._stack.items
        }

    def _sync_todo_counts_from_mounted_panes(self) -> None:
        """Aggregate each mounted pane's cached annotation count."""
        counts: dict[str, int] = {}
        for item in self._stack.items:
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
            (item for item in self._stack.items if self._pane_id(item) == text_area.id),
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

        ``<enter>`` opens the submit chooser, so a multi-pane stack swaps the
        ``[Esc] normal`` hint for ``[Esc] nav`` and adds ``[^S] stash`` plus
        ``[^G Enter] this`` hints for active-pane actions.  ``Esc`` still drops
        into NORMAL mode for the normal ``g`` prefix; INSERT mode reaches the
        same prompt-local actions through the ``Ctrl+G`` prefix.
        """
        if self._mode == "prompt" and len(self._stack) > 1:
            return (
                "[Enter] submit…  [Esc] nav  [^C] cancel  [^S] stash  [^G Enter] this"
            )
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
        if self._mode == "prompt" and len(self._stack) > 1:
            return "[g<enter>] launch  [gj/gk] pane  [gJ/gK] move  [^S/gs] stash"
        if self._mode == "prompt":
            return "[Esc] clear  [i] insert  [g<enter>] send  [^S] stash  [^C] cancel"
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
        text_area._warm_current_xprompt_assist_entries()
        text_area._warm_vcs_project_completion_catalog()
        text_area._warm_history_word_completion_cache()
        text_area._warm_common_placeholder_cache()
        text_area._on_prompt_completion_context_changed()
        self._apply_active_classes()
        self.auto_show_frontmatter_panel()
        self._schedule_height_update()

    def _app_theme_changed(self) -> None:
        """Recompose theme-derived title chrome after an app theme switch."""
        if self.is_mounted:
            self._refresh_title(self._title_mode_suffix)
