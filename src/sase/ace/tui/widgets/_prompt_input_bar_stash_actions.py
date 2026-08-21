"""Prompt stack stash and save request actions."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from sase.ace.tui.prompt_stash_entries import RestoredStashPane
from sase.ace.tui.widgets._prompt_input_bar_stack_models import (
    PromptFocusRestore,
    StashedPromptPane,
    stash_cursor_for_stripped_text,
)

if TYPE_CHECKING:
    from textual.widgets import Static as _MixinBase

    from sase.ace.tui.widgets.prompt_stack import PromptStackItem, PromptStackState
else:
    _MixinBase = object


class PromptInputBarStashActionsMixin(_MixinBase):
    """Prompt pane stash, restore, and save-as-xprompt request actions."""

    if TYPE_CHECKING:
        Stashed: Any
        RestoreRequested: Any
        UpdatePinnedRequested: Any
        SaveAsXpromptRequested: Any
        WriteXpromptRequested: Any
        _mode: str
        _stack: PromptStackState

        def _clear_active_completion_state(self) -> None: ...
        def _confirm_discard_dirty_snippet(
            self,
            proceed: Callable[[], None],
        ) -> bool: ...
        def load_stack_from_xprompt_markdown(
            self,
            text: str,
            *,
            binding: object | None = None,
            preserve_target: bool = False,
            read_only_target: object | None = None,
        ) -> None: ...
        def _load_stack_from_xprompt_markdown_after_snippet_guard(
            self,
            text: str,
            *,
            binding: object | None = None,
            preserve_target: bool = False,
            read_only_target: object | None = None,
        ) -> None: ...
        def _rebuild_stack(
            self,
            enter_mode: str | None = None,
            *,
            restore_focus: PromptFocusRestore | None = None,
        ) -> None: ...
        def _sync_state_from_widgets(self) -> None: ...
        def refresh_frontmatter_panel_from_stack(self) -> None: ...

    def capture_stashable_panes(
        self, *, include_frontmatter_only: bool = True
    ) -> list[StashedPromptPane]:
        """Return the current prompt draft as stash panes without side effects."""
        if self._mode != "prompt":
            return []
        self._sync_state_from_widgets()
        selected = self._stack.selected_item
        panes = [
            self._stashed_pane_for_item(
                item,
                index,
                active=item.item_id == selected.item_id,
            )
            for index, item in enumerate(self._stack.agent_items)
            if item.text.strip()
        ]
        if panes or not include_frontmatter_only or not self._stack.frontmatter.strip():
            return panes
        return [
            StashedPromptPane(
                text="",
                frontmatter=self._stack.frontmatter,
                pane_index=self._stack.selected_index,
                cursor=(0, 0),
                active=True,
            )
        ]

    def _stashed_pane_for_item(
        self,
        item: PromptStackItem,
        pane_index: int,
        *,
        active: bool,
    ) -> StashedPromptPane:
        """Build one stash pane from a synced stack item."""
        cursor = (
            stash_cursor_for_stripped_text(item.text, item.cursor) if active else None
        )
        return StashedPromptPane(
            text=item.text.strip(),
            frontmatter=self._stack.frontmatter,
            pane_index=pane_index,
            cursor=cursor,
            active=active,
        )

    def stash_active_pane(self) -> None:
        """Stash the active pane's draft for later (the ``<Ctrl+S>`` keymap).

        Prompt mode only — feedback / approve-prompt bars are not stashable, so
        it is a no-op there.  The pane's stripped text + the bar's shared YAML
        frontmatter are captured into a single stash entry and the pane is
        removed; when it was the last pane the whole bar empties and the app
        unmounts it (``dismiss_bar``) through the post-submit path, which does
        *not* re-record the text as cancelled history.  An empty active pane
        opens the unified stash panel so the user can restore a saved prompt;
        in non-prompt bars, ``<Ctrl+S>`` remains a no-op.
        """
        if self._mode != "prompt":
            return
        self._sync_state_from_widgets()
        if self._stack.selected_item.is_auxiliary_pane:
            return
        text = self._stack.selected_item.text.strip()
        if not text:
            # Nothing to stash: surface the stash panel so an empty Ctrl+S can
            # pull a previously stashed prompt back instead of being a no-op.
            self.request_open_prompt_stash()
            return
        pane = self._stashed_pane_for_item(
            self._stack.selected_item,
            self._stack.selected_index,
            active=True,
        )
        self._clear_active_completion_state()
        removed = self._stack.remove_selected()
        self.post_message(
            self.Stashed([pane], source="current", dismiss_bar=not removed)
        )
        if removed:
            self._rebuild_stack(enter_mode="insert")

    def stash_all_panes(self) -> None:
        """Stash every non-empty pane in the bar.

        Reached by the ``gs`` / ``<Ctrl+G> s`` keymap.

        Prompt mode only. Non-empty panes are captured in order and persisted as
        one canonical bundle row, with the earliest original ``pane_index`` and
        the bar's shared frontmatter. A frontmatter-only draft is captured as an
        empty pane carrying that frontmatter. The whole bar is dismissed
        (``dismiss_bar``). When there is nothing stashable, an empty ``Stashed``
        is posted so the app can toast.
        """
        if self._mode != "prompt":
            return
        self._sync_state_from_widgets()
        if self._stack.auxiliary_is_dirty:
            self._confirm_discard_dirty_snippet(
                self._stash_all_panes_after_snippet_guard
            )
            return

        self._stash_all_panes_after_snippet_guard()

    def _stash_all_panes_after_snippet_guard(self) -> None:
        """Stash all agent panes after the snippet-discard guard has passed."""
        if self._stack.binding is not None:
            self.app.notify(
                "Stash saved without xprompt binding; restore will use save-as",
                severity="warning",
            )
        panes = self.capture_stashable_panes()
        if not panes:
            self.post_message(self.Stashed([], source="all", dismiss_bar=False))
            return
        self._clear_active_completion_state()
        self.post_message(self.Stashed(panes, source="all", dismiss_bar=True))

    def stash_all_and_load_xprompt_markdown(
        self,
        markdown: str,
        *,
        binding: object | None = None,
        read_only_target: object | None = None,
    ) -> None:
        """Stash the whole bar as one bundle, then load *markdown* in its place."""
        if self._mode != "prompt":
            return
        self._sync_state_from_widgets()
        if self._stack.auxiliary_is_dirty:
            self._confirm_discard_dirty_snippet(
                lambda: self._stash_all_and_load_xprompt_markdown_after_snippet_guard(
                    markdown,
                    binding=binding,
                    read_only_target=read_only_target,
                )
            )
            return

        self._stash_all_and_load_xprompt_markdown_after_snippet_guard(
            markdown,
            binding=binding,
            read_only_target=read_only_target,
        )

    def _stash_all_and_load_xprompt_markdown_after_snippet_guard(
        self,
        markdown: str,
        *,
        binding: object | None = None,
        read_only_target: object | None = None,
    ) -> None:
        """Stash all agent panes and load xprompt markdown after discard guard."""
        panes = self.capture_stashable_panes()
        if panes:
            self._clear_active_completion_state()
            self.post_message(self.Stashed(panes, source="all", dismiss_bar=False))
        from sase.ace.tui.widgets.prompt_stack import (
            XPromptBinding,
            XPromptReadonlyTarget,
        )

        self._load_stack_from_xprompt_markdown_after_snippet_guard(
            markdown,
            binding=binding if isinstance(binding, XPromptBinding) else None,
            read_only_target=(
                read_only_target
                if isinstance(read_only_target, XPromptReadonlyTarget)
                else None
            ),
        )

    def request_update_pinned_stash(self) -> None:
        """Ask the app to update a pinned stash from the current prompt stack."""
        if self._mode != "prompt":
            return
        panes = self.capture_stashable_panes()
        if panes:
            self._clear_active_completion_state()
        self.post_message(self.UpdatePinnedRequested(panes))

    def request_save_as_xprompt(self) -> None:
        """Ask the app to save the current prompt draft as an xprompt."""
        if self._mode != "prompt":
            return
        self._sync_state_from_widgets()
        if self._stack.selected_item.is_mini_xprompt_pane:
            requester = getattr(self, "request_mini_xprompt_target_pane", None)
            if callable(requester):
                requester()
            return
        # ``single_pane`` is captured before empty panes are filtered out and
        # kept only as context. Snippet mode is always available, with
        # ``snippet_body`` (the active pane only) as its source — so a multi-pane
        # ``---`` stack still saves just the current pane as a snippet, while
        # ``panes`` remains the full xprompt-save source.
        single_pane = self._stack.agent_count == 1
        snippet_body = (
            ""
            if self._stack.selected_item.is_auxiliary_pane
            else self._stack.selected_item.text.strip()
        )
        panes = self.capture_stashable_panes()
        if panes:
            self._clear_active_completion_state()
        self.post_message(
            self.SaveAsXpromptRequested(
                panes,
                single_pane=single_pane,
                snippet_body=snippet_body,
                origin_bar=self,
            )
        )

    def request_write_xprompt(self) -> None:
        """Write the bound definition, or fall through to save-as when unbound."""
        if self._mode != "prompt":
            return
        self._sync_state_from_widgets()
        binding = self._stack.binding
        if binding is None:
            self.request_save_as_xprompt()
            return
        panes = self.capture_stashable_panes()
        self.post_message(self.WriteXpromptRequested(panes, binding, self))

    def request_open_prompt_stash(self) -> None:
        """Ask the app to open the unified prompt-stash panel.

        Presentation-only: the bar posts ``RestoreRequested`` with its current
        mode and the app performs the snapshot read, panel display, pop/keep
        orchestration, and load (boundary rule D6). Posted in every mode so the
        app can toast a no-op when restore is unavailable.
        """
        self.post_message(self.RestoreRequested(self._mode))

    def restore_stashed_entries(
        self,
        entries: list[RestoredStashPane] | list[tuple[str, str]],
    ) -> None:
        """Append restored stash drafts as new panes.

        Prompt mode only.  Each restored pane becomes a new bottom pane,
        preserving any panes the user is already drafting.  The bar's shared
        frontmatter is adopted from the first restored entry that carries one
        when the bar has none yet.  A lone empty drafting pane is dropped so
        restored drafts don't sit beneath a blank pane.  When a pane is marked
        as the saved focus target, that pane is focused at its stored cursor;
        otherwise the last restored pane is focused at end of text.
        """
        if self._mode != "prompt" or not entries:
            return
        panes = [_coerce_restored_stash_pane(entry) for entry in entries]
        self._sync_state_from_widgets()
        self._clear_active_completion_state()
        empty_agent_id = (
            self._stack.agent_items[0].item_id
            if self._stack.agent_count == 1
            and not self._stack.agent_items[0].text.strip()
            else None
        )
        adopted_frontmatter = False
        appended_ids: list[str] = []
        for pane in panes:
            if pane.frontmatter and not self._stack.frontmatter:
                self._stack.frontmatter = pane.frontmatter
                adopted_frontmatter = True
            appended_ids.append(self._stack.append_bottom(pane.text).item_id)
        if empty_agent_id is not None:
            for index, item in enumerate(self._stack.items):
                if item.item_id != empty_agent_id:
                    continue
                del self._stack.items[index]
                if self._stack.selected_index > index:
                    self._stack.selected_index -= 1
                else:
                    self._stack.selected_index = max(
                        0,
                        min(
                            self._stack.selected_index,
                            len(self._stack.items) - 1,
                        ),
                    )
                break
        restore_focus: PromptFocusRestore | None = None
        for pane, item_id in zip(panes, appended_ids, strict=True):
            if not pane.is_focus_target:
                continue
            restore_focus = PromptFocusRestore(
                item_id=item_id,
                cursor=pane.cursor if pane.cursor is not None else (0, 0),
                vim_mode="insert",
            )
            break
        self._rebuild_stack(enter_mode="insert", restore_focus=restore_focus)
        if adopted_frontmatter:
            self.refresh_frontmatter_panel_from_stack()


def _coerce_restored_stash_pane(entry: object) -> RestoredStashPane:
    if isinstance(entry, RestoredStashPane):
        return entry
    if isinstance(entry, tuple) and len(entry) == 2:
        text, frontmatter = entry
        return RestoredStashPane(text=str(text), frontmatter=str(frontmatter))
    raise TypeError(f"unsupported restored stash pane: {type(entry)!r}")
