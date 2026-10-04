"""Mini-xprompt target pane lifecycle for ``PromptInputBar``."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Any, Literal

from sase.ace.tui.widgets._prompt_input_bar_stack_models import PromptFocusRestore
from sase.ace.tui.widgets.prompt_stack import (
    MiniMacroPaneTarget,
    SourceFingerprint,
    mini_macro_draft_hash,
)

if TYPE_CHECKING:
    from textual.widgets import Static as _MixinBase

    from sase.ace.tui.modals.mini_macro_name_modal import MiniMacroNameResult
    from sase.ace.tui.widgets.prompt_stack import PromptStackItem, PromptStackState
    from sase.ace.tui.widgets.prompt_text_area import PromptTextArea
else:
    _MixinBase = object


class PromptInputBarMiniMacroPaneMixin(_MixinBase):
    """Open, retarget, close, and save-request pane-scoped mini-macro drafts."""

    if TYPE_CHECKING:
        MiniMacroPaneSaveRequested: Any
        MiniMacroTargetRequested: Any
        _generation: int
        _mini_macro_focus_restore: PromptFocusRestore | None
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

    def request_mini_macro_target_pane(self) -> None:
        """Ask the app to open the mini-macro name panel."""
        if self._mode != "prompt":
            return
        self._sync_state_from_widgets()

        def _post_request() -> None:
            try:
                origin = self.active_text_area()
            except Exception:
                return
            initial_name = ""
            current_location_path: str | None = None
            mini = self._stack.mini_macro_item
            if mini is not None and mini.mini_macro_target is not None:
                initial_name = mini.mini_macro_target.name
                current_location_path = mini.mini_macro_target.location_path
            self.post_message(
                self.MiniMacroTargetRequested(
                    origin_bar=self,
                    origin_pane_id=origin.id or "",
                    initial_name=initial_name,
                    current_location_path=current_location_path,
                )
            )

        auxiliary = self._stack.auxiliary_item
        if auxiliary is not None and not auxiliary.is_mini_macro_pane:
            self._confirm_discard_dirty_snippet(_post_request)
            return
        _post_request()

    def request_save_mini_macro_target_pane(
        self,
        origin_text_area: PromptTextArea | None = None,
    ) -> None:
        """Ask the app/save phase to review-save the active mini-macro pane."""
        if self._mode != "prompt":
            return
        self._sync_state_from_widgets()
        if not self._stack.selected_item.is_mini_macro_pane:
            return
        if origin_text_area is None:
            try:
                origin_text_area = self.active_text_area()
            except Exception:
                return
        self.post_message(
            self.MiniMacroPaneSaveRequested(
                origin_bar=self,
                origin_pane_id=origin_text_area.id or "",
            )
        )

    def open_mini_macro_target_pane(
        self,
        result: MiniMacroNameResult,
        *,
        origin_pane_id: str,
        body: str,
        frontmatter: str,
        loaded_markdown: str | None,
        loaded_fingerprint: SourceFingerprint | None,
        destination_exists: bool,
    ) -> bool:
        """Open or retarget the single pinned mini-macro pane."""
        if self._mode != "prompt" or not self.is_mounted:
            return False
        self._sync_state_from_widgets()
        mini_index = self._stack.mini_macro_index
        if mini_index is not None:
            current = self._stack.mini_macro_item
            if current is None or current.mini_macro_target is None:
                return False
            draft_frontmatter = current.mini_macro_target.frontmatter
            baseline_hash = mini_macro_draft_hash(frontmatter, body)
            target = self._mini_macro_target_from_result(
                result,
                frontmatter=draft_frontmatter,
                body=body,
                loaded_markdown=loaded_markdown,
                loaded_fingerprint=loaded_fingerprint,
                destination_exists=destination_exists,
                clean_hash=baseline_hash,
            )
            self._stack.retarget_mini_macro_pane(target)
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

        target = self._mini_macro_target_from_result(
            result,
            frontmatter=frontmatter,
            body=body,
            loaded_markdown=loaded_markdown,
            loaded_fingerprint=loaded_fingerprint,
            destination_exists=destination_exists,
        )
        self._mini_macro_focus_restore = restore
        self._clear_active_completion_state()
        self._stack.append_mini_macro_pane(body, target)
        self._rebuild_stack(enter_mode="insert")
        self.refresh_frontmatter_panel_from_stack()
        return True

    def close_mini_macro_target(
        self,
        reason: Literal["saved", "discarded", "replaced"],
    ) -> bool:
        """Close the mini-macro pane and restore the pane that opened it."""
        del reason
        if self._mode != "prompt":
            return False
        self._sync_state_from_widgets()
        if self._stack.mini_macro_item is None:
            return False
        if self._stack.selected_item.is_mini_macro_pane:
            self._clear_active_completion_state()
        removed = self._stack.remove_mini_macro_pane()
        if removed is None:
            return False
        restore = self._mini_macro_focus_restore
        self._mini_macro_focus_restore = None
        self._rebuild_stack(restore_focus=restore)
        self.refresh_frontmatter_panel_from_stack()
        return True

    def reload_mini_macro_target_body(
        self,
        body: str,
        *,
        frontmatter: str,
        loaded_markdown: str | None,
        loaded_fingerprint: SourceFingerprint | None,
    ) -> bool:
        """Replace the mini-macro draft with the current source definition."""
        if self._mode != "prompt" or not self.is_mounted:
            return False
        self._sync_state_from_widgets()
        index = self._stack.mini_macro_index
        mini = self._stack.mini_macro_item
        if index is None or mini is None or mini.mini_macro_target is None:
            return False
        mini.text = body
        mini.mini_macro_target = replace(
            mini.mini_macro_target,
            exists=True,
            frontmatter=frontmatter,
            loaded_body=body,
            loaded_markdown=loaded_markdown,
            loaded_fingerprint=loaded_fingerprint,
            clean_hash=mini_macro_draft_hash(frontmatter, body),
            derived_from=None,
            save_warning=None,
            changed_on_disk=False,
        )
        self._stack.selected_index = index
        self._clear_active_completion_state()
        self._rebuild_stack(enter_mode="insert")
        self.refresh_frontmatter_panel_from_stack()
        return True

    def mark_mini_macro_target_written(
        self,
        *,
        item_id: str,
        body: str,
        frontmatter: str,
        source_markdown: str | None,
        loaded_fingerprint: SourceFingerprint,
    ) -> bool:
        """Mark the mounted mini-macro draft clean after a successful write."""
        if self._mode != "prompt" or not self.is_mounted:
            return False
        self._sync_state_from_widgets()
        mini = self._stack.mini_macro_item
        if mini is None or mini.item_id != item_id or mini.mini_macro_target is None:
            return False
        mini.text = body
        mini.mini_macro_target = replace(
            mini.mini_macro_target,
            exists=True,
            frontmatter=frontmatter,
            loaded_body=body,
            loaded_markdown=source_markdown,
            loaded_fingerprint=loaded_fingerprint,
            clean_hash=mini_macro_draft_hash(frontmatter, body),
            derived_from=None,
            save_warning=None,
            changed_on_disk=False,
        )
        self._refresh_title()
        self.refresh_frontmatter_panel_from_stack()
        self.refresh_cursor_readouts()
        return True

    def mark_mini_macro_changed_on_disk(
        self,
        *,
        item_id: str,
        changed: bool,
    ) -> bool:
        """Record whether the mounted mini target changed externally."""
        if self._mode != "prompt" or not self.is_mounted:
            return False
        self._sync_state_from_widgets()
        mini = self._stack.mini_macro_item
        if mini is None or mini.item_id != item_id or mini.mini_macro_target is None:
            return False
        if mini.mini_macro_target.changed_on_disk == changed:
            return True
        mini.mini_macro_target = replace(
            mini.mini_macro_target,
            changed_on_disk=changed,
        )
        self._refresh_title()
        self.refresh_cursor_readouts()
        return True

    def mini_macro_target_origin_available(self, pane_id: str) -> bool:
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
    def _mini_macro_target_from_result(
        result: MiniMacroNameResult,
        *,
        frontmatter: str,
        body: str,
        loaded_markdown: str | None,
        loaded_fingerprint: SourceFingerprint | None,
        destination_exists: bool,
        clean_hash: str | None = None,
    ) -> MiniMacroPaneTarget:
        target = result.destination
        derived_from = None
        if result.action in {"fork", "override"} and result.existing_definition:
            derived_from = result.existing_definition.display_path
        return MiniMacroPaneTarget(
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
            clean_hash=clean_hash or mini_macro_draft_hash(frontmatter, body),
            derived_from=derived_from,
            save_warning=result.save_warning,
            changed_on_disk=False,
        )


__all__ = ["PromptInputBarMiniMacroPaneMixin"]
