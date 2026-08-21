"""Mini-xprompt target pane lifecycle for ``PromptInputBar``."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Any, Literal

from sase.ace.tui.widgets._prompt_input_bar_stack_models import PromptFocusRestore
from sase.ace.tui.widgets.prompt_stack import (
    MiniXPromptPaneTarget,
    SourceFingerprint,
    mini_xprompt_draft_hash,
)

if TYPE_CHECKING:
    from textual.widgets import Static as _MixinBase

    from sase.ace.tui.modals.mini_xprompt_name_modal import MiniXPromptNameResult
    from sase.ace.tui.widgets.prompt_stack import PromptStackItem, PromptStackState
    from sase.ace.tui.widgets.prompt_text_area import PromptTextArea
else:
    _MixinBase = object


class PromptInputBarMiniXPromptPaneMixin(_MixinBase):
    """Open, retarget, close, and save-request pane-scoped mini-xprompt drafts."""

    if TYPE_CHECKING:
        MiniXPromptPaneSaveRequested: Any
        MiniXPromptTargetRequested: Any
        _generation: int
        _mini_xprompt_focus_restore: PromptFocusRestore | None
        _mode: str
        _snippet_focus_restore: PromptFocusRestore | None
        _stack: PromptStackState

        def _clear_active_completion_state(self) -> None: ...
        def _confirm_discard_dirty_snippet(self, proceed: Any) -> bool: ...
        def _focus_restore_for_index(self, index: int) -> PromptFocusRestore | None: ...
        def _item_index_for_pane_id(self, pane_id: str) -> int | None: ...
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
        def refresh_frontmatter_panel_from_stack(self) -> None: ...

    def request_mini_xprompt_target_pane(self) -> None:
        """Ask the app to open the mini-xprompt name panel."""
        if self._mode != "prompt":
            return
        self._sync_state_from_widgets()

        def _post_request() -> None:
            try:
                origin = self.active_text_area()
            except Exception:
                return
            initial_name = ""
            mini = self._stack.mini_xprompt_item
            if mini is not None and mini.mini_xprompt_target is not None:
                initial_name = mini.mini_xprompt_target.name
            self.post_message(
                self.MiniXPromptTargetRequested(
                    origin_bar=self,
                    origin_pane_id=origin.id or "",
                    initial_name=initial_name,
                )
            )

        auxiliary = self._stack.auxiliary_item
        if auxiliary is not None and not auxiliary.is_mini_xprompt_pane:
            self._confirm_discard_dirty_snippet(_post_request)
            return
        _post_request()

    def request_save_mini_xprompt_target_pane(
        self,
        origin_text_area: PromptTextArea | None = None,
    ) -> None:
        """Ask the app/save phase to review-save the active mini-xprompt pane."""
        if self._mode != "prompt":
            return
        self._sync_state_from_widgets()
        if not self._stack.selected_item.is_mini_xprompt_pane:
            return
        if origin_text_area is None:
            try:
                origin_text_area = self.active_text_area()
            except Exception:
                return
        self.post_message(
            self.MiniXPromptPaneSaveRequested(
                origin_bar=self,
                origin_pane_id=origin_text_area.id or "",
            )
        )

    def open_mini_xprompt_target_pane(
        self,
        result: MiniXPromptNameResult,
        *,
        origin_pane_id: str,
        body: str,
        frontmatter: str,
        loaded_markdown: str | None,
        loaded_fingerprint: SourceFingerprint | None,
        destination_exists: bool,
    ) -> bool:
        """Open or retarget the single pinned mini-xprompt pane."""
        if self._mode != "prompt" or not self.is_mounted:
            return False
        self._sync_state_from_widgets()
        mini_index = self._stack.mini_xprompt_index
        if mini_index is not None:
            current = self._stack.mini_xprompt_item
            if current is None or current.mini_xprompt_target is None:
                return False
            target = self._mini_xprompt_target_from_result(
                result,
                frontmatter=current.mini_xprompt_target.frontmatter,
                body=body,
                loaded_markdown=loaded_markdown,
                loaded_fingerprint=loaded_fingerprint,
                destination_exists=destination_exists,
                clean_hash=current.mini_xprompt_target.clean_hash,
            )
            self._stack.retarget_mini_xprompt_pane(target)
            self.focus_item(mini_index)
            self._refresh_title()
            self.refresh_frontmatter_panel_from_stack()
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
            self._snippet_focus_restore = None

        target = self._mini_xprompt_target_from_result(
            result,
            frontmatter=frontmatter,
            body=body,
            loaded_markdown=loaded_markdown,
            loaded_fingerprint=loaded_fingerprint,
            destination_exists=destination_exists,
        )
        self._mini_xprompt_focus_restore = restore
        self._clear_active_completion_state()
        self._stack.append_mini_xprompt_pane(body, target)
        self._rebuild_stack(enter_mode="insert")
        self.refresh_frontmatter_panel_from_stack()
        return True

    def close_mini_xprompt_target(
        self,
        reason: Literal["saved", "discarded", "replaced"],
    ) -> bool:
        """Close the mini-xprompt pane and restore the pane that opened it."""
        del reason
        if self._mode != "prompt":
            return False
        self._sync_state_from_widgets()
        if self._stack.mini_xprompt_item is None:
            return False
        if self._stack.selected_item.is_mini_xprompt_pane:
            self._clear_active_completion_state()
        removed = self._stack.remove_mini_xprompt_pane()
        if removed is None:
            return False
        restore = self._mini_xprompt_focus_restore
        self._mini_xprompt_focus_restore = None
        self._rebuild_stack(restore_focus=restore)
        self.refresh_frontmatter_panel_from_stack()
        return True

    def reload_mini_xprompt_target_body(
        self,
        body: str,
        *,
        frontmatter: str,
        loaded_markdown: str | None,
        loaded_fingerprint: SourceFingerprint | None,
    ) -> bool:
        """Replace the mini-xprompt draft with the current source definition."""
        if self._mode != "prompt" or not self.is_mounted:
            return False
        self._sync_state_from_widgets()
        index = self._stack.mini_xprompt_index
        mini = self._stack.mini_xprompt_item
        if index is None or mini is None or mini.mini_xprompt_target is None:
            return False
        mini.text = body
        mini.mini_xprompt_target = replace(
            mini.mini_xprompt_target,
            exists=True,
            frontmatter=frontmatter,
            loaded_body=body,
            loaded_markdown=loaded_markdown,
            loaded_fingerprint=loaded_fingerprint,
            clean_hash=mini_xprompt_draft_hash(frontmatter, body),
            derived_from=None,
            save_warning=None,
        )
        self._stack.selected_index = index
        self._clear_active_completion_state()
        self._rebuild_stack(enter_mode="insert")
        self.refresh_frontmatter_panel_from_stack()
        return True

    def mini_xprompt_target_origin_available(self, pane_id: str) -> bool:
        """Return whether a captured origin pane can still accept a mini result."""
        if self._mode != "prompt" or not self.is_mounted:
            return False
        return not pane_id or self._item_index_for_pane_id(pane_id) is not None

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

    @staticmethod
    def _mini_xprompt_target_from_result(
        result: MiniXPromptNameResult,
        *,
        frontmatter: str,
        body: str,
        loaded_markdown: str | None,
        loaded_fingerprint: SourceFingerprint | None,
        destination_exists: bool,
        clean_hash: str | None = None,
    ) -> MiniXPromptPaneTarget:
        target = result.destination
        derived_from = None
        if result.action in {"fork", "override"} and result.existing_definition:
            derived_from = result.existing_definition.display_path
        return MiniXPromptPaneTarget(
            name=result.name,
            reference=f"#{result.name}",
            location_path=target.location_path,
            read_path=target.read_path,
            write_path=target.write_path,
            display_path=target.display_path,
            apply_target=target.apply_target,
            via_chezmoi=target.via_chezmoi,
            target_format=target.target_format,
            entry_name=target.entry_name,
            storage_name=target.storage_name,
            exists=destination_exists,
            frontmatter=frontmatter,
            loaded_body=body if loaded_markdown is not None else None,
            loaded_markdown=loaded_markdown,
            loaded_fingerprint=loaded_fingerprint,
            clean_hash=clean_hash or mini_xprompt_draft_hash(frontmatter, body),
            derived_from=derived_from,
            save_warning=result.save_warning,
        )


__all__ = ["PromptInputBarMiniXPromptPaneMixin"]
