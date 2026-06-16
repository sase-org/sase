"""Stack navigation and structural actions for PromptInputBar."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sase.ace.tui.widgets.prompt_stack import PromptStackState
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea

if TYPE_CHECKING:
    from textual.widgets import Static as _MixinBase
else:
    _MixinBase = object


@dataclass(frozen=True)
class StashedPromptPane:
    """One captured prompt-bar pane handed to the app for persistence.

    The bar captures presentation-side state only (the stripped pane ``text``,
    the bar's shared YAML ``frontmatter``, and the pane's original
    ``pane_index``); the app layer enriches it with id / timestamp / project
    before writing through ``prompt_stash_facade`` (boundary rule D6).
    """

    text: str
    frontmatter: str = ""
    pane_index: int = 0


class PromptInputBarStackActionsMixin(_MixinBase):
    """Prompt stack keymaps, live splitting, and completion cleanup."""

    if TYPE_CHECKING:
        Stashed: Any
        _live_split_pending: bool
        _mode: str
        _stack: PromptStackState

        def _apply_active_classes(self) -> None: ...
        def _rebuild_stack(self, enter_mode: str | None = None) -> None: ...
        def _schedule_height_update(self) -> None: ...
        def _sync_state_from_widgets(self) -> None: ...
        def active_text_area(self) -> PromptTextArea: ...
        def hide_file_completions(self) -> None: ...
        def hide_soft_completion(self) -> None: ...

    def focus_relative(self, delta: int) -> bool:
        """Move pane focus by *delta* in normal mode (``,j`` / ``,k``).

        Navigation is a pure focus change; no pane is rebuilt, so each pane
        keeps its cursor and edit state.  The newly active pane enters vim
        normal mode so the user can keep browsing the stack with the comma
        leader.  Returns ``True`` when the selection moved.
        """
        if len(self._stack) <= 1:
            return False
        self._clear_active_completion_state()
        if not self._stack.move_focus(delta):
            return False
        self._apply_active_classes()
        text_area = self.active_text_area()
        text_area.focus()
        text_area._enter_normal_mode()
        self._schedule_height_update()
        return True

    def move_active_pane(self, delta: int) -> bool:
        """Reorder the active pane by *delta* (``,J`` down / ``,K`` up).

        The live pane texts are synced into the model first so the rebuild
        preserves what the user has typed; the moved pane stays active and in
        normal mode for repeated reordering.  Returns ``True`` when it moved.
        """
        if len(self._stack) <= 1:
            return False
        self._sync_state_from_widgets()
        self._clear_active_completion_state()
        if not self._stack.move_selected(delta):
            return False
        self._rebuild_stack(enter_mode="normal")
        return True

    def add_bottom_pane(self) -> None:
        """Append a new empty bottom pane and drop into it (the ``-`` keymap).

        Only meaningful in prompt mode; feedback / approve-prompt bars are not
        multi-agent surfaces, so it is a no-op elsewhere.  The new pane is
        focused in insert mode so the user can immediately type the next agent
        prompt, pushing the previous panes up.
        """
        if self._mode != "prompt":
            return
        self._sync_state_from_widgets()
        self._clear_active_completion_state()
        self._stack.append_bottom("")
        self._rebuild_stack(enter_mode="insert")

    def stash_active_pane(self) -> None:
        """Stash the active pane's draft for later (the ``,s`` keymap).

        Prompt mode only — feedback / approve-prompt bars are not stashable, so
        it is a no-op there.  The pane's stripped text + the bar's shared YAML
        frontmatter are captured into a single stash entry and the pane is
        removed; when it was the last pane the whole bar empties and the app
        unmounts it (``dismiss_bar``) through the post-submit path, which does
        *not* re-record the text as cancelled history.  An empty pane stashes
        nothing — an empty ``Stashed`` is posted so the app can toast a no-op.
        """
        if self._mode != "prompt":
            return
        self._sync_state_from_widgets()
        text = self._stack.selected_item.text.strip()
        if not text:
            self.post_message(self.Stashed([], source="current", dismiss_bar=False))
            return
        pane = StashedPromptPane(
            text=text,
            frontmatter=self._stack.frontmatter,
            pane_index=self._stack.selected_index,
        )
        self._clear_active_completion_state()
        removed = self._stack.remove_selected()
        self.post_message(
            self.Stashed([pane], source="current", dismiss_bar=not removed)
        )
        if removed:
            self._rebuild_stack(enter_mode="insert")

    def stash_all_panes(self) -> None:
        """Stash every non-empty pane in the bar (the ``,S`` keymap).

        Prompt mode only.  Each non-empty pane becomes its own stash entry —
        order preserved, original ``pane_index`` recorded — and all of them
        carry the bar's shared frontmatter, then the whole bar is dismissed
        (``dismiss_bar``).  When no pane has text it is a no-op and an empty
        ``Stashed`` is posted so the app can toast.
        """
        if self._mode != "prompt":
            return
        self._sync_state_from_widgets()
        panes = [
            StashedPromptPane(
                text=stripped,
                frontmatter=self._stack.frontmatter,
                pane_index=index,
            )
            for index, item in enumerate(self._stack.items)
            if (stripped := item.text.strip())
        ]
        if not panes:
            self.post_message(self.Stashed([], source="all", dismiss_bar=False))
            return
        self._clear_active_completion_state()
        self.post_message(self.Stashed(panes, source="all", dismiss_bar=True))

    def _live_split_active_pane(self) -> None:
        """Split the active pane when a ``---`` line was just typed into it.

        Deferred from ``on_text_area_changed`` so the pane is never unmounted
        while still handling its own text change.  The canonical parser decides
        whether a real split happens, so separators inside fenced code blocks or
        YAML frontmatter never trigger one.  After a split the new bottom pane
        is focused in insert mode to keep drafting.
        """
        self._live_split_pending = False
        if self._mode != "prompt":
            return
        self._sync_state_from_widgets()
        if not self._stack.split_selected_live():
            return
        self._clear_active_completion_state()
        self._rebuild_stack(enter_mode="insert")

    def _clear_active_completion_state(self) -> None:
        """Drop completion / soft-completion / arg-hint state before mutation."""
        try:
            text_area = self.active_text_area()
        except Exception:
            text_area = None
        if text_area is not None:
            text_area._clear_file_completion()
            text_area._clear_soft_completion(cancel_timer=True)
            text_area._clear_xprompt_arg_hint()
        self.hide_file_completions()
        self.hide_soft_completion()

    def _maybe_live_split(self, text_area: PromptTextArea) -> None:
        """Schedule a live split when *text_area*'s cursor line became ``---``."""
        if self._mode != "prompt" or self._live_split_pending:
            return
        if getattr(text_area, "_vim_mode", "insert") != "insert":
            return
        row = text_area.cursor_location[0]
        if text_area.document.get_line(row).rstrip() != "---":
            return
        self._live_split_pending = True
        self.call_after_refresh(self._live_split_active_pane)
