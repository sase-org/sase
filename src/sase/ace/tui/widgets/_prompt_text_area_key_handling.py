"""PromptTextArea key dispatch.

Composes the prompt pane's key-handling mixin chain and adds its top layer: the
``_on_key`` interceptor, submit / cancel / history chords, mode routing, and
INSERT-mode completion navigation. The lower layers live in
:mod:`~sase.ace.tui.widgets._prompt_text_area_key_g_prefix` (the prompt-local
``Ctrl+G`` prefix) and
:mod:`~sase.ace.tui.widgets._prompt_text_area_key_pairing` (Jinja / bracket
auto-pairs and planned text edits).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from textual.events import Key

from sase.ace.tui.widgets._prompt_bullet_editing import plan_prompt_bullet_shift
from sase.ace.tui.widgets._prompt_ordered_shift_editing import (
    plan_prompt_ordered_shift,
)
from sase.ace.tui.widgets._prompt_text_area_bar import prompt_bar_class
from sase.ace.tui.widgets._prompt_text_area_key_g_prefix import (
    PromptTextAreaKeyGPrefixMixin,
)
from sase.ace.tui.widgets._prompt_text_area_key_pairing import (
    PromptTextAreaKeyPairingMixin,
)

if TYPE_CHECKING:
    from sase.ace.tui.widgets._vcs_mru_cycling import VcsMruCycleKey
    from sase.ace.tui.widgets.artifact_ref_completion import (
        ArtifactRefCompletionContext,
    )
    from sase.ace.tui.widgets.prompt_completion import PromptCompletionSettings
    from sase.ace.tui.widgets.prompt_text_area import PromptTextArea
    from sase.ace.tui.widgets.xprompt_arg_assist import (
        ActiveXPromptArgHint,
        PendingXPromptCompletionSpacer,
    )


def _is_auto_xprompt_menu_character(character: str | None) -> bool:
    """Return True for printable non-whitespace inserted characters."""
    return (
        character is not None
        and len(character) == 1
        and character.isprintable()
        and not character.isspace()
    )


class PromptTextAreaKeyHandlingMixin(
    PromptTextAreaKeyGPrefixMixin,
    PromptTextAreaKeyPairingMixin,
):
    """PromptTextArea key handling kept separate from widget construction."""

    if TYPE_CHECKING:
        _active_xprompt_arg_hint: ActiveXPromptArgHint | None
        _pending_xprompt_completion_spacer: PendingXPromptCompletionSpacer | None
        _completion_kind: str
        _completion_selection_moved: bool
        _file_completion_active: bool
        _pending_keys: str
        _vcs_mru_index: int | None
        _vim_mode: str

        def _absolute_offset(self, location: tuple[int, int]) -> int: ...
        def _get_artifact_ref_completion_context(
            self,
        ) -> ArtifactRefCompletionContext | None: ...
        def _artifact_ref_sync_trigger(self) -> str | None: ...
        def _start_artifact_ref_sync(self, kind: str) -> None: ...
        def _accept_file_completion(self) -> bool: ...
        def _accept_or_build_soft_completion(self) -> bool: ...
        def _apply_xprompt_colon_arg_hint(self) -> bool: ...
        def _apply_xprompt_named_arg_hint(self) -> bool: ...
        def _can_apply_xprompt_arg_action(self) -> bool: ...
        def _clear_insert_g_prefix(self) -> None: ...
        def _clear_normal_g_prefix(self) -> None: ...
        def _clear_file_completion(
            self,
            *,
            clear_xprompt_arg_hint: bool = True,
        ) -> None: ...
        def _clear_soft_completion(
            self,
            *,
            cancel_timer: bool = False,
        ) -> None: ...
        def _clear_xprompt_arg_hint(self) -> None: ...
        def _consume_xprompt_completion_spacer(
            self,
            pending: PendingXPromptCompletionSpacer,
            character: str | None,
        ) -> bool: ...
        def _consume_xprompt_completion_spacer_for_tabstop(
            self,
            pending: PendingXPromptCompletionSpacer,
            *,
            retreat: bool,
        ) -> bool: ...
        def _delete_selected_file_completion(self) -> bool: ...
        def _completion_supports_delete(self) -> bool: ...
        def _enter_normal_mode(self) -> None: ...
        def _find_prompt_bar(self) -> Any: ...
        def _handle_normal_mode_key(self, event: Key) -> bool: ...
        def _handle_prompt_search_key(self, event: Key) -> bool: ...
        def _handle_vcs_mru_cycle_key(self, key: VcsMruCycleKey) -> bool: ...
        def _handle_visual_mode_key(self, event: Key) -> bool: ...
        def _is_prompt_search_active(self) -> bool: ...
        def _move_file_completion(self, delta: int) -> bool: ...
        def _on_prompt_completion_context_changed(self) -> None: ...
        def _prompt_completion_settings(self) -> PromptCompletionSettings: ...
        def _open_recursive_file_finder(self) -> None: ...
        def _open_submit_choice_panel(self) -> None: ...
        def _refresh_file_completion_from_cursor(self) -> None: ...
        def _refresh_xprompt_arg_hint_from_cursor(self) -> None: ...
        def _try_advance_tabstop(self) -> bool: ...
        def _try_retreat_tabstop(self) -> bool: ...
        def _try_auto_placeholder_completion(self) -> bool: ...
        def _try_expand_snippet(self) -> bool: ...
        def _try_auto_prompt_reference_completion(self) -> bool: ...
        def _try_file_completion_tab(self) -> bool: ...
        def _try_vcs_project_completion(self) -> bool: ...
        def action_open_prompt_history(self) -> None: ...
        def action_submit_prompt(self) -> None: ...

    def _open_auto_reference_completion_after_change(
        self,
        character: str | None,
    ) -> None:
        settings = self._prompt_completion_settings()
        if (
            self._vim_mode == "insert"
            and not self._file_completion_active
            and settings.auto != "off"
            and self._try_auto_placeholder_completion()
        ):
            self._refresh_xprompt_arg_hint_from_cursor()
            self._on_prompt_completion_context_changed()
            return
        if (
            self._vim_mode == "insert"
            and not self._file_completion_active
            and (
                settings.auto_xprompt_menu
                or settings.auto_directive_menu
                or settings.auto_artifact_menu
            )
            and _is_auto_xprompt_menu_character(character)
        ):
            self._try_auto_prompt_reference_completion()
        self._refresh_xprompt_arg_hint_from_cursor()
        self._on_prompt_completion_context_changed()

    async def _on_key(self, event: Key) -> None:
        """Intercept keys before TextArea's default handler inserts characters."""
        # A just-accepted no-required-input xprompt left a trailing spacer
        # (``#name ``). An immediate comma replaces it for both no-input and
        # optional-only entries; an immediate colon does so only for
        # optional-only entries. An immediate Tab / Shift+Tab that jumps to
        # another snippet tabstop deletes the spacer instead of rewriting it,
        # and is handled in the ``tab`` branch below rather than here because
        # tabstop jumps are INSERT-mode only. The spacer is a one-shot
        # convenience: any other key or invalidated text/cursor drops the
        # pending state.
        pending_spacer = self._pending_xprompt_completion_spacer
        if pending_spacer is not None:
            self._pending_xprompt_completion_spacer = None
            if self._consume_xprompt_completion_spacer(
                pending_spacer,
                event.character,
            ):
                self._refresh_file_completion_from_cursor()
                self._open_auto_reference_completion_after_change(event.character)
                event.stop()
                event.prevent_default()
                return

        if self._is_prompt_search_active():
            self._clear_insert_g_prefix()
            self._clear_normal_g_prefix()
            if self._handle_prompt_search_key(event):
                event.stop()
                event.prevent_default()
                return

        if self._handle_insert_g_prefix_key(event):
            event.stop()
            event.prevent_default()
            return

        if self._handle_normal_g_prefix_key(event):
            event.stop()
            event.prevent_default()
            return

        if event.key == "enter":
            if self._vim_mode == "normal" and self._pending_keys == "g":
                if self._handle_normal_mode_key(event):
                    event.stop()
                    event.prevent_default()
                    return
            event.stop()
            event.prevent_default()
            if self._file_completion_active:
                artifact_context = (
                    self._get_artifact_ref_completion_context()
                    if self._completion_kind == "artifact_ref"
                    else None
                )
                unowned_bare_at = (
                    artifact_context is not None
                    and artifact_context.stage == "kind"
                    and not artifact_context.prefix
                    and not self._completion_selection_moved
                )
                if not unowned_bare_at:
                    self._accept_file_completion()
                    return
                self._clear_file_completion()
            bar = self._find_prompt_bar()
            prompt_texts = bar.all_prompt_texts() if bar is not None else []
            active_is_auxiliary = bool(
                bar is not None and bar._stack.selected_item.is_auxiliary_pane
            )
            should_choose_submit = (
                bar is not None
                and not active_is_auxiliary
                and (bar.is_stacked() or bar.xprompt_target() is not None)
                and any(text.strip() for text in prompt_texts)
            )
            if should_choose_submit:
                self._open_submit_choice_panel()
            else:
                self._clear_xprompt_arg_hint()
                self.action_submit_prompt()
            return

        # Active-pane stash. ``^S`` is prompt-local in every vim mode.
        if event.key == "ctrl+s":
            event.stop()
            event.prevent_default()
            bar = self._find_prompt_bar()
            if bar is not None:
                bar.stash_active_pane()
            return

        if event.key == "ctrl+c":
            event.stop()
            event.prevent_default()
            self._clear_file_completion()
            self._clear_soft_completion(cancel_timer=True)
            self._clear_xprompt_arg_hint()
            bar = self._find_prompt_bar()
            if bar:
                bar.action_cancel()
            return

        if event.key == "ctrl+k":
            event.stop()
            event.prevent_default()
            self.action_open_prompt_history()
            return

        # Stack pane focus/reorder, add-pane, and frontmatter toggle live on
        # the prompt ``g`` prefix (see PromptTextAreaKeyGPrefixMixin). Bare
        # ``J`` / ``K`` stay with vim; Up/Down fall through to TextArea
        # cursor movement.

        if self._vim_mode in {"visual", "visual_line"}:
            if self._handle_visual_mode_key(event):
                event.stop()
                event.prevent_default()
            elif event.key == "ctrl+g":
                event.stop()
                event.prevent_default()
            return

        if self._vim_mode == "normal":
            # Bare and continuation ``Ctrl+G`` are already consumed above by
            # ``_handle_normal_g_prefix_key`` (the prompt-local ``^G`` prefix), so
            # this branch only handles the remaining vim normal-mode keys.
            if self._handle_normal_mode_key(event):
                event.stop()
                event.prevent_default()
            return

        # INSERT mode: Escape dismisses any active completion UI and enters
        # NORMAL mode. ``_enter_normal_mode`` already clears manual completion,
        # soft completion, and xprompt arg hints, so an open completion menu and
        # the no-completion path both land in NORMAL mode through the same
        # transition helper -- matching plain insert-mode ``Escape``.
        if event.key == "escape":
            event.stop()
            event.prevent_default()
            self._enter_normal_mode()
            return

        # Ctrl+R: open the recursive fuzzy file finder. Works whether or not
        # the Ctrl+T completion panel is open; when it is, Case A derives the
        # recursive root from the currently-selected entry.
        if event.key == "ctrl+r":
            event.stop()
            event.prevent_default()
            self._open_recursive_file_finder()
            return

        if self._active_xprompt_arg_hint is not None and event.character in (":", "("):
            if self._can_apply_xprompt_arg_action():
                event.stop()
                event.prevent_default()
                if event.character == ":":
                    self._apply_xprompt_colon_arg_hint()
                else:
                    self._apply_xprompt_named_arg_hint()
                return
            self._clear_xprompt_arg_hint()

        # Active manual completion navigation / acceptance.
        if self._file_completion_active:
            if event.key in ("ctrl+n", "down"):
                event.stop()
                event.prevent_default()
                self._move_file_completion(1)
                return
            if event.key in ("ctrl+p", "up"):
                event.stop()
                event.prevent_default()
                self._move_file_completion(-1)
                return
            if event.key == "ctrl+l":
                event.stop()
                event.prevent_default()
                self._accept_file_completion()
                return
            if event.key == "ctrl+d" and self._completion_supports_delete():
                event.stop()
                event.prevent_default()
                self._delete_selected_file_completion()
                return

        # Insert-mode ``ctrl+l`` accepts a soft completion when one is pending;
        # pane focus moved to the normal-mode ``K`` / ``J`` keys, so there is no
        # longer a focus fallback here -- an unconsumed ``ctrl+l`` falls through
        # to the app-level ``dismiss_toasts`` binding as before.
        if event.key == "ctrl+l" and self._accept_or_build_soft_completion():
            event.stop()
            event.prevent_default()
            return

        if event.key == "ctrl+n":
            event.stop()
            event.prevent_default()
            self._handle_vcs_mru_cycle_key("ctrl+n")
            return

        if event.key == "ctrl+p":
            event.stop()
            event.prevent_default()
            self._handle_vcs_mru_cycle_key("ctrl+p")
            return

        # Ctrl+T in INSERT mode: dispatch manual prompt completion.
        if event.key == "ctrl+t":
            event.stop()
            event.prevent_default()
            self._clear_soft_completion(cancel_timer=True)
            self._try_file_completion_tab()
            return

        # Tab / Shift+Tab in INSERT mode do useful snippet work first. Only
        # when expansion or tabstop movement reports no action do the keys fall
        # back to shifting the supported list item on the current logical line.
        if event.key in {"tab", "shift+tab"}:
            event.stop()
            event.prevent_default()
            self._clear_soft_completion(cancel_timer=True)
            if pending_spacer is not None and (
                self._consume_xprompt_completion_spacer_for_tabstop(
                    pending_spacer,
                    retreat=event.key == "shift+tab",
                )
            ):
                return
            if event.key == "shift+tab":
                if self._try_retreat_tabstop():
                    return
            elif self._try_expand_snippet() or self._try_advance_tabstop():
                return

            start, end = self.selection
            if start == end:
                offset = self._absolute_offset(self.cursor_location)
                dedent = event.key == "shift+tab"
                plan = plan_prompt_ordered_shift(
                    self.text,
                    offset,
                    dedent=dedent,
                ) or plan_prompt_bullet_shift(
                    self.text,
                    offset,
                    dedent=dedent,
                )
                if plan is not None:
                    self._apply_planned_text_edit(
                        plan,
                        remap_dot_capture=True,
                    )
                    return
            return

        if self._try_jinja_auto_pair(event):
            event.stop()
            event.prevent_default()
            return

        if self._try_prompt_text_pair_edit(event):
            event.stop()
            event.prevent_default()
            return

        # Detect the '@<kind>::' ref-sync gesture before the second ':' is
        # inserted: consumed entirely by `_artifact_ref_sync_trigger`'s guards.
        if event.character == ":":
            sync_kind = self._artifact_ref_sync_trigger()
            if sync_kind is not None:
                event.stop()
                event.prevent_default()
                self._start_artifact_ref_sync(sync_kind)
                return

        # Detect '#@' trigger before the '@' is inserted (skip in feedback mode).
        if event.character == "@":
            bar = self._find_prompt_bar()
            if bar and bar._mode != "feedback":
                row, col = self.cursor_location
                if col > 0:
                    line = self.document.get_line(row)
                    if line[col - 1] == "#":
                        PromptInputBar = prompt_bar_class()
                        # Capture the exact origin so the selector targets this
                        # pane even if focus or the active pane changes while the
                        # modal is open. The trigger range covers the literal
                        # '#' (the '@' was prevented), so insertion can replace
                        # only the suffix after it.
                        bar.post_message(
                            PromptInputBar.SnippetRequested(
                                origin_bar=bar,
                                origin_text_area=cast("PromptTextArea", self),
                                origin_pane_id=self.id or "",
                                trigger_range=((row, col - 1), (row, col)),
                            )
                        )
                        event.stop()
                        event.prevent_default()
                        return
        await super()._on_key(event)

        # Reset VCS MRU cycling on any non-cycling keypress.
        if self._vcs_mru_index is not None:
            self._vcs_mru_index = None

        self._refresh_file_completion_from_cursor()
        # Auto-open the ``+`` project completion menu when ``+`` completes
        # a valid trigger token. The refresh above already narrows an open menu,
        # so only try to open when one is not already active.
        if (
            event.character == "+"
            and self._vim_mode == "insert"
            and not self._file_completion_active
        ):
            self._try_vcs_project_completion()
        self._open_auto_reference_completion_after_change(event.character)
