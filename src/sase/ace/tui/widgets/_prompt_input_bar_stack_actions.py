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
        RestoreRequested: Any
        _live_split_pending: bool
        _mode: str
        _stack: PromptStackState

        def _apply_active_classes(self) -> None: ...
        def _rebuild_stack(self, enter_mode: str | None = None) -> None: ...
        def _schedule_height_update(self) -> None: ...
        def _should_reserve_for_frontmatter(
            self, text_area: PromptTextArea
        ) -> bool: ...
        def _sync_state_from_widgets(self) -> None: ...
        def active_text_area(self) -> PromptTextArea: ...
        def hide_file_completions(self) -> None: ...
        def hide_soft_completion(self) -> None: ...

    def focus_relative(self, delta: int, target_mode: str = "normal") -> bool:
        """Move pane focus by *delta* (``Ctrl+Shift+J`` / ``Ctrl+Shift+K``).

        Navigation is a pure focus change; no pane is rebuilt, so each pane
        keeps its cursor and edit state.  ``target_mode`` ("normal" or
        "insert") selects the vim mode the newly active pane lands in, so the
        Ctrl+Shift shortcuts preserve whichever mode the user was already in.
        Returns ``True`` when the selection moved.
        """
        if len(self._stack) <= 1:
            return False
        self._clear_active_completion_state()
        if not self._stack.move_focus(delta):
            return False
        self._apply_active_classes()
        text_area = self.active_text_area()
        text_area.focus()
        if target_mode == "insert":
            text_area._enter_insert_mode()
        else:
            text_area._enter_normal_mode()
        self._schedule_height_update()
        return True

    def move_active_pane(self, delta: int, target_mode: str = "normal") -> bool:
        """Reorder the active pane by *delta* (``Ctrl+Shift+H``/``Ctrl+Shift+L``).

        ``delta`` of ``-1`` moves the pane higher/earlier (``Ctrl+Shift+H``) and
        ``+1`` lower/later (``Ctrl+Shift+L``).  The live pane texts are synced
        into the model first so the rebuild preserves what the user has typed;
        the moved pane stays active and lands in *target_mode* ("normal" or
        "insert"), so reordering keeps whichever vim mode the user was already
        in.  Returns ``True`` when it moved.
        """
        if len(self._stack) <= 1:
            return False
        self._sync_state_from_widgets()
        self._clear_active_completion_state()
        if not self._stack.move_selected(delta):
            return False
        self._rebuild_stack(enter_mode=target_mode)
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

    def request_restore_stash(self) -> None:
        """Ask the app to open the restore picker (the ``,P`` keymap).

        Presentation-only: the bar posts ``RestoreRequested`` with its current
        mode and the app performs the snapshot read / pop / load (boundary rule
        D6).  Posted in every mode so the app can toast a no-op when restore is
        not available (feedback / approve-prompt bars).
        """
        self.post_message(self.RestoreRequested(self._mode))

    def restore_stashed_entries(self, entries: list[tuple[str, str]]) -> None:
        """Append restored stash drafts as new panes (the ``,P`` restore path).

        Prompt mode only.  Each ``(text, frontmatter)`` becomes a new bottom
        pane, preserving any panes the user is already drafting.  The bar's
        shared frontmatter is adopted from the first restored entry that carries
        one when the bar has none yet.  A lone empty drafting pane is dropped so
        restored drafts don't sit beneath a blank pane.  The last restored pane
        is focused in insert mode so the user can keep editing.
        """
        if self._mode != "prompt" or not entries:
            return
        self._sync_state_from_widgets()
        self._clear_active_completion_state()
        drop_empty_lead = (
            len(self._stack) == 1 and not self._stack.selected_item.text.strip()
        )
        for text, frontmatter in entries:
            if frontmatter and not self._stack.frontmatter:
                self._stack.frontmatter = frontmatter
            self._stack.append_bottom(text)
        if drop_empty_lead:
            del self._stack.items[0]
            self._stack.selected_index = len(self._stack.items) - 1
        self._rebuild_stack(enter_mode="insert")

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
        # A bare leading ``---`` in a fresh empty prompt is reserved for the
        # frontmatter trigger (it opens the panel once the newline lands), so it
        # must not first split into two empty panes.
        if self._should_reserve_for_frontmatter(text_area):
            return
        self._live_split_pending = True
        self.call_after_refresh(self._live_split_active_pane)
