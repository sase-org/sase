"""Prompt input bar widget for agent workflow in the ace TUI."""

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
    PromptInputBarFrontmatterMixin,
)
from sase.ace.tui.widgets._prompt_input_bar_messages import (
    Cancelled as _Cancelled,
    EditorRequested as _EditorRequested,
    HistoryRequested as _HistoryRequested,
    RestoreRequested as _RestoreRequested,
    SnippetRequested as _SnippetRequested,
    Stashed as _Stashed,
    Submitted as _Submitted,
    WorkflowEditorRequested as _WorkflowEditorRequested,
)
from sase.ace.tui.widgets._prompt_input_bar_stack_actions import (
    PromptInputBarStackActionsMixin,
    StashedPromptPane,
)
from sase.ace.tui.widgets._prompt_input_bar_stack_rendering import (
    PromptInputBarStackRenderingMixin,
)
from sase.ace.tui.widgets.frontmatter_panel import FrontmatterPanel
from sase.ace.tui.widgets.prompt_stack import PromptStackState

__all__ = ["PromptInputBar", "StashedPromptPane"]


class PromptInputBar(
    PromptInputBarFrontmatterMixin,
    PromptInputBarStackActionsMixin,
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
    EditorRequested = _EditorRequested
    HistoryRequested = _HistoryRequested
    SnippetRequested = _SnippetRequested
    WorkflowEditorRequested = _WorkflowEditorRequested

    BINDINGS = []  # type: ignore[assignment]

    def __init__(
        self,
        initial_value: str = "",
        mode: str = "prompt",
        *,
        initial_panes: list[str] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._initial_value = initial_value
        self._mode = mode
        self._completion_visible = False
        self._completion_line_count = 0
        self._completion_panel_kind: str | None = None
        self._mode_subtitle = "[Enter] send  [Esc] normal  [^C] cancel"
        self._soft_completion_visible = False
        self._title_mode_suffix = ""
        # Monotonic per-rebuild id namespace so a fresh stack mounted while the
        # previous panes are still being detached never collides on widget ids.
        self._generation = 0
        self._placeholder = ""
        # Guards against piling up deferred live-split passes while the user
        # keeps typing past a freshly completed ``---`` separator line.
        self._live_split_pending = False
        if initial_panes is not None:
            # Explicit pane seeding: one verbatim pane per entry, never split on
            # an embedded ``---`` or lifted frontmatter. Used by bulk
            # kill-and-edit so each killed agent maps to exactly one pane.
            self._stack = PromptStackState.from_panes(initial_panes)
        else:
            self._stack = self._state_from_text(initial_value)

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
        if mode_suffix:
            # Border titles parse Rich markup; escape literal mode brackets.
            mode_suffix = mode_suffix.replace("[", "\\[")
            title = f"{title} {mode_suffix}"
        chip = self._active_jinja_chip_markup()
        if chip:
            title = f"{title}  {chip}"
        self.border_title = title

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

        ``<enter>`` submits only the selected pane, so a multi-pane stack swaps
        the ``[Esc] normal`` hint for ``[Esc] nav`` (Esc drops into normal mode,
        where the ``,j``/``,k``/``,J``/``,K``/``-`` stack keys live — see
        :meth:`normal_mode_subtitle`) and adds a ``[^S] all`` hint for the
        whole-stack submit (the portable fallback for ``<shift+enter>``).
        """
        if self._mode == "prompt" and len(self._stack) > 1:
            return "[Enter] send  [Esc] nav  [^C] cancel  [^S] all"
        return "[Enter] send  [Esc] normal  [^C] cancel"

    def normal_mode_subtitle(self) -> str:
        """Return the normal-mode subtitle, advertising the stack keys.

        In a multi-pane stack the active pane's normal-mode hints surface the
        prompt-stack comma leader and ``-`` keymap (``,j``/``,k`` move between
        panes, ``,J``/``,K`` reorder the active pane, ``,s``/``,S`` stash the
        active / all panes, ``-`` adds a new bottom pane) so the stack is
        discoverable without crowding the single-pane footer.  A single-pane
        prompt bar still advertises ``,s`` (stash this draft); feedback /
        approve-prompt bars keep the original normal-mode hints since they are
        not stashable.
        """
        if self._mode == "prompt" and len(self._stack) > 1:
            return (
                "[,j ,k] pane  [,J ,K] move  [,s ,S] stash  "
                "[,f] fm  [-] add  [i] insert"
            )
        if self._mode == "prompt":
            return "[Esc] clear  [i] insert  [,s] stash  [,f] fm  [^C] cancel"
        return "[Esc] clear  [i] insert  [^C] cancel"

    def compose(self) -> ComposeResult:
        """Compose the input bar: completion panel, frontmatter panel, stack.

        The frontmatter panel sits directly above ``#prompt-stack`` (prompt mode
        only — feedback / approve-prompt bars are not multi-agent surfaces) and
        starts hidden, auto-showing on mount when the prompt already carries
        frontmatter or when the user triggers it with a leading ``---``.
        """
        self._placeholder = self._compute_placeholder()
        yield Static("", id="prompt-completion", classes="hidden")
        if self._mode == "prompt":
            yield FrontmatterPanel(
                self._stack.frontmatter,
                id="frontmatter-panel",
                classes="hidden",
            )
        with Vertical(id="prompt-stack"):
            yield from self._build_pane_widgets()

    def _compute_placeholder(self) -> str:
        """Return the empty-pane placeholder text for the current mode."""
        if self._mode == "feedback":
            return "Type plan feedback...  [^G] editor  [^J] newline"
        if self._mode == "approve_prompt":
            return "Type coder prompt...  [^G] editor  [^J] newline"
        return (
            "Type prompt  [^K] history  [^T] complete  [^R] find  "
            "[^G] editor  [^Y] workflow  [^J] newline"
        )

    def on_mount(self) -> None:
        """Focus the active pane on mount and position its cursor at end."""
        text_area = self.active_text_area()
        text_area.focus()
        self._cursor_to_end(text_area)

        # Border title and subtitle
        self._refresh_title()
        self.set_prompt_mode_subtitle(self.insert_mode_subtitle())
        if self._mode in ("feedback", "approve_prompt"):
            self.add_class("feedback-mode")
        text_area._warm_current_xprompt_assist_entries()
        text_area._on_prompt_completion_context_changed()
        self._apply_active_classes()
        self.auto_show_frontmatter_panel()
        self._schedule_height_update()
