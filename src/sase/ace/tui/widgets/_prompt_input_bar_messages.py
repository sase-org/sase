"""Textual messages emitted by ``PromptInputBar``."""

from __future__ import annotations

from textual.message import Message

from sase.ace.tui.widgets._prompt_input_bar_stack_actions import StashedPromptPane


class Submitted(Message, namespace="prompt_input_bar"):
    """Message sent when prompt is submitted.

    Phase 4 distinguishes the two stack submit shapes:

    - ``whole_stack`` is set when the whole stack was joined into one
      multi-prompt string (``<ctrl+s>``); the app
      unmounts the bar and routes ``value`` through the existing multi-prompt
      launch rules.
    - ``keep_bar`` is set when only the selected pane was submitted while other
      panes remain; the app launches ``value`` but leaves the bar mounted so the
      remaining panes can be submitted next.
    """

    def __init__(
        self,
        value: str,
        mode: str = "prompt",
        *,
        whole_stack: bool = False,
        keep_bar: bool = False,
    ) -> None:
        super().__init__()
        self.value = value
        self.mode = mode
        self.whole_stack = whole_stack
        self.keep_bar = keep_bar


class Cancelled(Message, namespace="prompt_input_bar"):
    """Message sent when input is cancelled.

    ``keep_bar`` is set when only the selected pane was cancelled while other
    panes remain; the app records ``cancelled_text`` as cancelled history but
    leaves the bar mounted.  Without it the whole bar is being dismissed, as
    before.
    """

    def __init__(
        self,
        cancelled_text: str = "",
        mode: str = "prompt",
        *,
        keep_bar: bool = False,
    ) -> None:
        super().__init__()
        self.cancelled_text = cancelled_text
        self.mode = mode
        self.keep_bar = keep_bar


class Stashed(Message, namespace="prompt_input_bar"):
    """Message sent when the user stashes one or more prompt-bar panes.

    The bar (presentation-only) captures the pane text(s) + the shared YAML
    frontmatter into ``panes`` and removes them; the app layer persists them
    through ``prompt_stash_facade`` and refreshes the top-bar indicator
    (boundary rule D6).  ``panes`` is empty when there was nothing to stash (an
    empty pane), so the app shows a "nothing to stash" toast without touching
    the store.  ``dismiss_bar`` is set when stashing emptied the bar and the app
    should unmount it via the post-submit path, so the stashed text is never
    *also* recorded as cancelled history.
    """

    def __init__(
        self,
        panes: list[StashedPromptPane],
        *,
        source: str = "current",
        dismiss_bar: bool = False,
    ) -> None:
        super().__init__()
        self.panes = panes
        self.source = source
        self.dismiss_bar = dismiss_bar


class RestoreRequested(Message, namespace="prompt_input_bar"):
    """Message sent when the user asks to restore stashed prompts (``,P``).

    Presentation-only (boundary rule D6): the bar just signals intent and
    forwards its current ``mode`` so the app can guard restore to prompt bars
    (feedback / approve-prompt bars toast a no-op).  The app reads the stash
    snapshot, opens the picker, and on confirm pops the chosen entries and loads
    them back into the bar.
    """

    def __init__(self, mode: str = "prompt") -> None:
        super().__init__()
        self.mode = mode


class EditorRequested(Message, namespace="prompt_input_bar"):
    """Message sent when user requests external editor (Ctrl+G)."""

    def __init__(
        self,
        current_text: str = "",
        cursor_row: int = 0,
        cursor_col: int = 0,
    ) -> None:
        super().__init__()
        self.current_text = current_text
        self.cursor_row = cursor_row
        self.cursor_col = cursor_col


class AllEditorRequested(Message, namespace="prompt_input_bar"):
    """Message sent when user requests the whole-stack editor (Ctrl+Shift+G).

    Unlike :class:`EditorRequested` (which edits only the active pane), this opens
    the entire prompt stack as xprompt markdown.  The bar owns the serialization,
    so the message carries no payload: the handler reads the joined markdown off
    the mounted bar and reloads the edited result back as a stack.
    """


class HistoryRequested(Message, namespace="prompt_input_bar"):
    """Message sent when user requests the prompt history picker."""

    def __init__(
        self,
        vcs_prefix: str = "",
        show_cancelled: bool = False,
        initial_filter: str = "",
        preserve_prompt_bar: bool = False,
    ) -> None:
        super().__init__()
        self.vcs_prefix = vcs_prefix
        self.show_cancelled = show_cancelled
        self.initial_filter = initial_filter
        self.preserve_prompt_bar = preserve_prompt_bar


class SnippetRequested(Message, namespace="prompt_input_bar"):
    """Message sent when user requests snippet modal ('#@')."""


class WorkflowEditorRequested(Message, namespace="prompt_input_bar"):
    """Message sent when user requests workflow YAML editor (Ctrl+Y)."""
