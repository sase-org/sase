"""Snippet target pane lifecycle for ``PromptInputBar``."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from typing import TYPE_CHECKING, Any, Literal

from sase.ace.tui.widgets._prompt_input_bar_stack_models import PromptFocusRestore
from sase.ace.tui.widgets.prompt_stack import (
    SnippetPaneTarget,
    SourceFingerprint,
)

if TYPE_CHECKING:
    from textual.widgets import Static as _MixinBase

    from sase.ace.tui.modals.snippet_name_modal import SnippetNameResult
    from sase.ace.tui.widgets.prompt_stack import PromptStackItem, PromptStackState
    from sase.ace.tui.widgets.prompt_text_area import PromptTextArea
else:
    _MixinBase = object


class PromptInputBarSnippetPaneMixin(_MixinBase):
    """Open, retarget, close, and guard the pane-scoped snippet draft."""

    if TYPE_CHECKING:
        SnippetPaneSaveRequested: Any
        SnippetTargetRequested: Any
        _generation: int
        _mini_xprompt_focus_restore: PromptFocusRestore | None
        _mode: str
        _snippet_focus_restore: PromptFocusRestore | None
        _stack: PromptStackState

        def _clear_active_completion_state(self) -> None: ...
        def _pane_id(self, item: PromptStackItem) -> str: ...
        def _rebuild_stack(
            self,
            enter_mode: str | None = None,
            *,
            restore_focus: PromptFocusRestore | None = None,
        ) -> None: ...
        def _refresh_title(self, mode_suffix: str = "") -> None: ...
        def _sync_state_from_widgets(self) -> None: ...
        def active_text_area(self) -> PromptTextArea: ...
        def focus_item(self, index: int) -> int: ...
        def refresh_cursor_readouts(self) -> None: ...

    def request_snippet_target_pane(self) -> None:
        """Ask the app to open the snippet trigger-name panel."""
        if self._mode != "prompt":
            return

        def _post_request() -> None:
            try:
                origin = self.active_text_area()
            except Exception:
                return
            initial_trigger = ""
            snippet = self._stack.snippet_item
            if snippet is not None and snippet.snippet_target is not None:
                initial_trigger = snippet.snippet_target.trigger
            self.post_message(
                self.SnippetTargetRequested(
                    origin_bar=self,
                    origin_pane_id=origin.id or "",
                    initial_trigger=initial_trigger,
                )
            )

        self._sync_state_from_widgets()
        auxiliary = self._stack.auxiliary_item
        if auxiliary is not None and not auxiliary.is_snippet_pane:
            self._confirm_discard_dirty_snippet(_post_request)
            return
        _post_request()

    def request_save_snippet_target_pane(
        self,
        origin_text_area: PromptTextArea | None = None,
    ) -> None:
        """Ask the app/save phase to save the active snippet pane."""
        if self._mode != "prompt":
            return
        self._sync_state_from_widgets()
        if not self._stack.selected_item.is_snippet_pane:
            return
        if origin_text_area is None:
            try:
                origin_text_area = self.active_text_area()
            except Exception:
                return
        self.post_message(
            self.SnippetPaneSaveRequested(
                origin_bar=self,
                origin_pane_id=origin_text_area.id or "",
            )
        )

    def open_snippet_target_pane(
        self,
        result: SnippetNameResult,
        *,
        origin_pane_id: str,
        destination_exists: bool,
        loaded_fingerprint: SourceFingerprint | None,
    ) -> bool:
        """Open or retarget the single pinned snippet pane from a name result."""
        if self._mode != "prompt" or not self.is_mounted:
            return False
        self._sync_state_from_widgets()
        target = self._snippet_target_from_result(
            result,
            destination_exists=destination_exists,
            loaded_fingerprint=loaded_fingerprint,
        )
        snippet_index = self._stack.snippet_index
        if snippet_index is not None:
            self._stack.retarget_snippet_pane(target)
            self.focus_item(snippet_index)
            self._refresh_title()
            self.refresh_cursor_readouts()
            return True

        origin_index = self._origin_index_for_auxiliary_open(origin_pane_id)
        if origin_index is None:
            return False
        restore = self._focus_restore_for_index(origin_index)
        if restore is None:
            return False
        if self._stack.auxiliary_item is not None:
            if self._stack.auxiliary_is_dirty:
                return False
            self._stack.remove_auxiliary_pane()
            self._mini_xprompt_focus_restore = None
        self._snippet_focus_restore = restore
        self._clear_active_completion_state()
        self._stack.append_snippet_pane(result.existing_body or "", target)
        self._rebuild_stack(enter_mode="insert")
        return True

    def close_snippet_target(
        self,
        reason: Literal["saved", "discarded", "replaced"],
    ) -> bool:
        """Close the snippet pane and restore the pane that opened it."""
        del reason
        if self._mode != "prompt":
            return False
        self._sync_state_from_widgets()
        if self._stack.snippet_item is None:
            return False
        if self._stack.selected_item.is_snippet_pane:
            self._clear_active_completion_state()
        removed = self._stack.remove_snippet_pane()
        if removed is None:
            return False
        restore = self._snippet_focus_restore
        self._snippet_focus_restore = None
        self._rebuild_stack(restore_focus=restore)
        return True

    def refocus_pane_id(self, pane_id: str) -> bool:
        """Return focus to a generation-scoped pane id when it still exists."""
        index = self._item_index_for_pane_id(pane_id)
        if index is None:
            return False
        self.focus_item(index)
        return True

    def snippet_target_origin_available(self, pane_id: str) -> bool:
        """Return whether a captured origin pane can still accept a snippet result."""
        if self._mode != "prompt" or not self.is_mounted:
            return False
        return not pane_id or self._item_index_for_pane_id(pane_id) is not None

    def _snippet_target_from_result(
        self,
        result: SnippetNameResult,
        *,
        destination_exists: bool,
        loaded_fingerprint: SourceFingerprint | None,
    ) -> SnippetPaneTarget:
        target = result.target
        return SnippetPaneTarget(
            trigger=result.trigger,
            read_path=str(target.read_path),
            write_path=str(target.write_path),
            display_path=target.display_path,
            apply_target=(
                str(target.apply_target) if target.apply_target is not None else None
            ),
            via_chezmoi=target.via_chezmoi,
            exists=destination_exists,
            loaded_body=result.existing_body,
            loaded_fingerprint=loaded_fingerprint,
            derived_from=result.derived_from,
            save_warning=result.save_warning,
        )

    def _item_index_for_pane_id(self, pane_id: str) -> int | None:
        if not pane_id:
            return self._stack.selected_index
        for index, item in enumerate(self._stack.items):
            if self._pane_id(item) == pane_id:
                return index
        return None

    def _focus_restore_for_index(self, index: int) -> PromptFocusRestore | None:
        if index < 0 or index >= len(self._stack.items):
            return None
        item = self._stack.items[index]
        return PromptFocusRestore(
            item_id=item.item_id,
            cursor=item.cursor,
            vim_mode=item.mode,
        )

    def _origin_index_for_auxiliary_open(self, pane_id: str) -> int | None:
        index = self._item_index_for_pane_id(pane_id)
        if index is None:
            return None
        if not self._stack.items[index].is_auxiliary_pane:
            return index
        for candidate in range(len(self._stack.items) - 1, -1, -1):
            if not self._stack.items[candidate].is_auxiliary_pane:
                return candidate
        return None

    def _confirm_discard_dirty_snippet(
        self,
        proceed: Callable[[], None],
    ) -> bool:
        """Run *proceed* now or after confirming a dirty auxiliary discard."""
        if self._mode != "prompt":
            proceed()
            return True
        self._sync_state_from_widgets()
        auxiliary = self._stack.auxiliary_item
        if auxiliary is None:
            proceed()
            return True
        if not self._stack.auxiliary_is_dirty:
            proceed()
            return True

        stack = self._stack
        generation = self._generation
        item_id = auxiliary.item_id
        text = auxiliary.text
        title, detail = self._dirty_auxiliary_guard_copy(auxiliary)
        handled = False

        def _on_confirm(confirmed: bool | None) -> None:
            nonlocal handled
            if handled:
                return
            handled = True
            if confirmed is True:
                if self._dirty_snippet_guard_current(
                    stack=stack,
                    generation=generation,
                    item_id=item_id,
                    text=text,
                ):
                    proceed()
                return
            self._refocus_dirty_auxiliary()

        from sase.ace.tui.modals import ConfirmActionModal, ConfirmKind

        self.app.push_screen(
            ConfirmActionModal(
                title,
                detail,
                kind=ConfirmKind.DANGER,
                confirm_label="Discard",
                cancel_label="Keep editing",
                default="cancel",
            ),
            _on_confirm,
        )
        return False

    @staticmethod
    def _dirty_auxiliary_guard_copy(item: PromptStackItem) -> tuple[str, str]:
        if item.snippet_target is not None:
            return (
                f"Discard unsaved snippet ⇥ {item.snippet_target.trigger}?",
                "This snippet draft has unsaved changes.",
            )
        if item.mini_xprompt_target is not None:
            return (
                f"Discard unsaved mini-xprompt #{item.mini_xprompt_target.name}?",
                "This mini-xprompt draft has unsaved changes.",
            )
        return ("Discard unsaved draft?", "This draft has unsaved changes.")

    def _dirty_snippet_guard_current(
        self,
        *,
        stack: PromptStackState,
        generation: int,
        item_id: str,
        text: str,
    ) -> bool:
        if (
            not self.is_mounted
            or self._stack is not stack
            or self._generation != generation
        ):
            return False
        snippet = self._stack.auxiliary_item
        return (
            snippet is not None
            and snippet.item_id == item_id
            and snippet.text == text
            and self._stack.auxiliary_is_dirty
        )

    def _refocus_dirty_auxiliary(self) -> None:
        index = self._stack.auxiliary_index
        if index is None:
            return
        try:
            self.focus_item(index)
        except Exception:
            pass

    def reload_snippet_target_body(
        self,
        body: str,
        *,
        loaded_fingerprint: SourceFingerprint | None,
    ) -> bool:
        """Replace the snippet draft with the current disk definition."""
        if self._mode != "prompt" or not self.is_mounted:
            return False
        self._sync_state_from_widgets()
        index = self._stack.snippet_index
        snippet = self._stack.snippet_item
        if index is None or snippet is None or snippet.snippet_target is None:
            return False
        snippet.text = body
        snippet.snippet_target = replace(
            snippet.snippet_target,
            exists=True,
            loaded_body=body,
            loaded_fingerprint=loaded_fingerprint,
            derived_from=None,
            save_warning=None,
        )
        self._stack.selected_index = index
        self._clear_active_completion_state()
        self._rebuild_stack(enter_mode="insert")
        return True
