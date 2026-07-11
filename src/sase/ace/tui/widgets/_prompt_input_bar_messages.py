"""Textual messages emitted by ``PromptInputBar``."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.message import Message

from sase.ace.tui.widgets._prompt_input_bar_stack_models import StashedPromptPane

if TYPE_CHECKING:
    from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
    from sase.ace.tui.widgets.prompt_stack import XPromptBinding
    from sase.ace.tui.widgets.prompt_text_area import PromptTextArea


class Submitted(Message, namespace="prompt_input_bar"):
    """Message sent when prompt is submitted.

    Phase 4 distinguishes the two stack submit shapes:

    - ``whole_stack`` is set by the submit chooser when the whole stack was
      joined into one multi-prompt string; the app unmounts the bar and routes
      ``value`` through the existing multi-prompt launch rules.
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
    before. ``record_segments`` controls whether a joined multi-prompt is also
    expanded into per-segment history entries.
    """

    def __init__(
        self,
        cancelled_text: str = "",
        mode: str = "prompt",
        *,
        keep_bar: bool = False,
        record_segments: bool = True,
    ) -> None:
        super().__init__()
        self.cancelled_text = cancelled_text
        self.mode = mode
        self.keep_bar = keep_bar
        self.record_segments = record_segments


class Stashed(Message, namespace="prompt_input_bar"):
    """Message sent when the user stashes one or more prompt-bar panes.

    The bar (presentation-only) captures the pane text(s) + the shared YAML
    frontmatter into ``panes`` and removes them; the app layer persists them
    through ``prompt_stash_facade`` and refreshes the top-bar indicator
    (boundary rule D6).  ``panes`` is empty when a stash command found nothing
    stashable, so the app shows a "nothing to stash" toast without touching the
    store.  ``dismiss_bar`` is set when stashing emptied the bar and the app
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
    """Message sent when the user asks to open the stashed-prompts panel.

    Presentation-only (boundary rule D6): the bar just signals intent and
    forwards its current ``mode`` so the app can guard restore to prompt bars
    (feedback / approve-prompt bars toast a no-op). The app reads the stash
    snapshot, opens the unified picker, and applies the per-entry pop/keep/delete
    choices on confirm.
    """

    def __init__(self, mode: str = "prompt") -> None:
        super().__init__()
        self.mode = mode


class UpdatePinnedRequested(Message, namespace="prompt_input_bar"):
    """Message sent when the user asks to update an existing pinned stash.

    The bar captures every non-empty prompt pane plus shared frontmatter, but
    leaves the stack mounted and unchanged. The app layer chooses the pinned
    target and rewrites that row through ``prompt_stash_facade``.
    """

    def __init__(self, panes: list[StashedPromptPane]) -> None:
        super().__init__()
        self.panes = panes


class SaveAsXpromptRequested(Message, namespace="prompt_input_bar"):
    """Message sent when the user asks to save the draft as an xprompt.

    The message carries two distinct save sources:

    - ``panes`` is the *xprompt* body source: every non-empty prompt pane plus
      shared frontmatter (the stack stays mounted and unchanged). A
      frontmatter-only draft is carried as one empty pane with frontmatter so
      the app can still serialize it. The app joins these panes with
      ``\n---\n`` for xprompt creation / overwrite.
    - ``snippet_body`` is the *snippet* body source: only the active pane's
      stripped text, so choosing "Create a new snippet..." saves that single
      pane even when the stack holds several ``---`` panes. ``None`` marks a
      legacy/direct event that carried no separate snippet source, in which case
      the app falls back to the single-pane body when that is unambiguous.

    ``single_pane`` reflects whether the bar held exactly one prompt pane *before*
    empty panes were filtered out. It is retained only as compatibility/context;
    the snippet option is now always offered, with ``snippet_body`` as its
    source.
    """

    def __init__(
        self,
        panes: list[StashedPromptPane],
        *,
        single_pane: bool = False,
        snippet_body: str | None = None,
        origin_bar: PromptInputBar | None = None,
    ) -> None:
        super().__init__()
        self.panes = panes
        self.single_pane = single_pane
        self.snippet_body = snippet_body
        self.origin_bar = origin_bar


class WriteXpromptRequested(Message, namespace="prompt_input_bar"):
    """Request a conflict-checked write to the stack's bound source."""

    def __init__(
        self,
        panes: list[StashedPromptPane],
        binding: XPromptBinding,
        origin_bar: PromptInputBar,
    ) -> None:
        super().__init__()
        self.panes = panes
        self.binding = binding
        self.origin_bar = origin_bar


class EditorRequested(Message, namespace="prompt_input_bar"):
    """Message sent when user requests the single-pane external editor."""

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
    """Message sent when user requests the whole-stack editor.

    Reached by the prompt editor keymap when the bar holds multiple panes.
    Unlike :class:`EditorRequested` (the single-pane editor), this opens the entire
    prompt stack as xprompt markdown.  The bar owns the serialization, so the
    message carries no payload: the handler reads the joined markdown off the
    mounted bar and reloads the edited result back as a stack.
    """


class HistoryRequested(Message, namespace="prompt_input_bar"):
    """Message sent when user requests the prompt history picker.

    Carries the explicit origin of the ``Ctrl+K`` trigger (mirroring
    :class:`SnippetRequested`) so a ``Ctrl+I`` load acts on the exact pane the
    modal was opened from, even if focus moves or the active pane changes while
    the modal is open. Without it the app handler re-queried the generic
    ``#prompt-input-bar`` after the modal closed and loaded into whatever pane
    happened to be active -- the staleness bug class the pane-preserving load
    fixes.

    Fields:

    - ``origin_bar``: the :class:`PromptInputBar` that owns the trigger pane.
    - ``origin_text_area``: the :class:`PromptTextArea` the history modal was
      opened from.
    - ``origin_pane_id``: that text area's stable, generation-scoped widget id,
      used as a staleness check -- a prompt-stack rebuild remounts panes under a
      fresh id, so a captured id that no longer resolves means the origin pane
      is gone.
    """

    def __init__(
        self,
        vcs_prefix: str = "",
        show_cancelled: bool = False,
        initial_filter: str = "",
        preserve_prompt_bar: bool = False,
        *,
        origin_bar: PromptInputBar | None = None,
        origin_text_area: PromptTextArea | None = None,
        origin_pane_id: str = "",
    ) -> None:
        super().__init__()
        self.vcs_prefix = vcs_prefix
        self.show_cancelled = show_cancelled
        self.initial_filter = initial_filter
        self.preserve_prompt_bar = preserve_prompt_bar
        self.origin_bar = origin_bar
        self.origin_text_area = origin_text_area
        self.origin_pane_id = origin_pane_id


class SnippetRequested(Message, namespace="prompt_input_bar"):
    """Message sent when user requests the snippet selector (``#@``).

    Carries the explicit origin of the ``#@`` trigger so the selector can act
    on the exact pane that opened it, even if focus moves or the active pane
    changes while the modal is open. Before this, the request handler re-queried
    the generic ``#prompt-input-bar`` after the modal closed and inserted into
    whatever pane happened to be active, which could miss the originating pane
    in a multi-pane stack.

    Fields:

    - ``origin_bar``: the :class:`PromptInputBar` that owns the trigger pane.
    - ``origin_text_area``: the :class:`PromptTextArea` the ``#@`` was typed
      into.
    - ``origin_pane_id``: that text area's stable, generation-scoped widget id,
      used as a staleness check -- a prompt-stack rebuild remounts panes under a
      fresh id, so a captured id that no longer resolves means the trigger pane
      is gone.
    - ``trigger_range``: the ``(start, end)`` document range covering the
      literal ``#`` that opened ``#@``. Insertion replaces only the suffix after
      the ``#`` (preserving the existing ``Enter`` behavior); a later phase can
      replace the ``#`` itself to inline-expand.
    """

    def __init__(
        self,
        *,
        origin_bar: PromptInputBar | None = None,
        origin_text_area: PromptTextArea | None = None,
        origin_pane_id: str = "",
        trigger_range: tuple[tuple[int, int], tuple[int, int]] | None = None,
    ) -> None:
        super().__init__()
        self.origin_bar = origin_bar
        self.origin_text_area = origin_text_area
        self.origin_pane_id = origin_pane_id
        self.trigger_range = trigger_range


class WorkflowEditorRequested(Message, namespace="prompt_input_bar"):
    """Message sent when user requests workflow YAML editor (Ctrl+Y)."""
