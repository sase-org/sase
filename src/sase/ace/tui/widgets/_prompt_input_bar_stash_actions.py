"""Prompt stack stash and save request actions."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sase.ace.tui.widgets._prompt_input_bar_stack_models import StashedPromptPane

if TYPE_CHECKING:
    from textual.widgets import Static as _MixinBase

    from sase.ace.tui.widgets.prompt_stack import PromptStackState
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
        def load_stack_from_xprompt_markdown(
            self, text: str, *, binding: object | None = None
        ) -> None: ...
        def _rebuild_stack(self, enter_mode: str | None = None) -> None: ...
        def _sync_state_from_widgets(self) -> None: ...
        def refresh_frontmatter_panel_from_stack(self) -> None: ...

    def capture_stashable_panes(
        self, *, include_frontmatter_only: bool = True
    ) -> list[StashedPromptPane]:
        """Return the current prompt draft as stash panes without side effects."""
        if self._mode != "prompt":
            return []
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
        if panes or not include_frontmatter_only or not self._stack.frontmatter.strip():
            return panes
        return [
            StashedPromptPane(
                text="",
                frontmatter=self._stack.frontmatter,
                pane_index=self._stack.selected_index,
            )
        ]

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
        text = self._stack.selected_item.text.strip()
        if not text:
            # Nothing to stash: surface the stash panel so an empty Ctrl+S can
            # pull a previously stashed prompt back instead of being a no-op.
            self.request_open_prompt_stash()
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
        """Stash every non-empty pane in the bar.

        Reached by the ``gs`` / ``<Ctrl+G> s`` keymap.

        Prompt mode only.  Each non-empty pane becomes its own stash entry —
        order preserved, original ``pane_index`` recorded — and all of them carry
        the bar's shared frontmatter. A frontmatter-only draft is captured as an
        empty pane carrying that frontmatter. The whole bar is dismissed
        (``dismiss_bar``). When there is nothing stashable, an empty ``Stashed``
        is posted so the app can toast.
        """
        if self._mode != "prompt":
            return
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
        self, markdown: str, *, binding: object | None = None
    ) -> None:
        """Stash the whole bar as one bundle, then load *markdown* in its place."""
        if self._mode != "prompt":
            return
        panes = self.capture_stashable_panes()
        if panes:
            self._clear_active_completion_state()
            self.post_message(self.Stashed(panes, source="all", dismiss_bar=False))
        from sase.ace.tui.widgets.prompt_stack import XPromptBinding

        self.load_stack_from_xprompt_markdown(
            markdown,
            binding=binding if isinstance(binding, XPromptBinding) else None,
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
        # ``single_pane`` is captured before empty panes are filtered out and
        # kept only as context. The snippet save option is always offered, with
        # ``snippet_body`` (the active pane only) as its source — so a multi-pane
        # ``---`` stack still saves just the current pane as a snippet, while
        # ``panes`` remains the full xprompt-save source.
        single_pane = len(self._stack) == 1
        snippet_body = self._stack.selected_item.text.strip()
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

    def restore_stashed_entries(self, entries: list[tuple[str, str]]) -> None:
        """Append restored stash drafts as new panes.

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
        adopted_frontmatter = False
        for text, frontmatter in entries:
            if frontmatter and not self._stack.frontmatter:
                self._stack.frontmatter = frontmatter
                adopted_frontmatter = True
            self._stack.append_bottom(text)
        if drop_empty_lead:
            del self._stack.items[0]
            self._stack.selected_index = len(self._stack.items) - 1
        self._rebuild_stack(enter_mode="insert")
        if adopted_frontmatter:
            self.refresh_frontmatter_panel_from_stack()
