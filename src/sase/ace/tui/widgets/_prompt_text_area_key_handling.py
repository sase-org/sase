"""PromptTextArea key dispatch."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from textual.events import Key

from sase.ace.tui.widgets._alt_syntax_editing import (
    plan_alt_brace_pair,
    plan_alt_separator,
)
from sase.ace.tui.widgets._paired_text_editing import (
    TextEdit,
    plan_pair_close_skip,
    plan_pair_insert,
)
from sase.ace.tui.widgets._prompt_text_area_actions import prompt_bar_class

if TYPE_CHECKING:
    from textual.widgets import TextArea as _MixinBase

    from sase.ace.tui.widgets._vcs_mru_cycling import VcsMruCycleKey
    from sase.ace.tui.widgets.prompt_completion import PromptCompletionSettings
    from sase.ace.tui.widgets.prompt_text_area import PromptTextArea
    from sase.ace.tui.widgets.xprompt_arg_assist import (
        ActiveXPromptArgHint,
        PendingOptionalSpacer,
    )
else:
    _MixinBase = object


def _is_auto_xprompt_menu_character(character: str | None) -> bool:
    """Return True for printable non-whitespace inserted characters."""
    return (
        character is not None
        and len(character) == 1
        and character.isprintable()
        and not character.isspace()
    )


def _resolve_g_prefix_second_key(event: Key) -> str:
    """Return the canonical key used to dispatch a prompt ``g`` continuation."""
    character = event.character
    if character and len(character) == 1 and character.isprintable():
        return character
    return event.key


class PromptTextAreaKeyHandlingMixin(_MixinBase):
    """PromptTextArea key handling kept separate from widget construction."""

    if TYPE_CHECKING:
        _active_xprompt_arg_hint: ActiveXPromptArgHint | None
        _pending_optional_spacer: PendingOptionalSpacer | None
        _completion_kind: str
        _file_completion_active: bool
        _count_prefix: str
        _insert_g_prefix_pending: bool
        _normal_g_prefix_pending: bool
        _pending_keys: str
        _pending_operator: str
        _vcs_mru_index: int | None
        _vim_mode: str

        def _absolute_offset(self, location: tuple[int, int]) -> int: ...
        def _location_from_absolute(self, offset: int) -> tuple[int, int]: ...
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
        def _consume_optional_spacer_colon(
            self,
            pending: PendingOptionalSpacer,
        ) -> bool: ...
        def _delete_selected_file_completion(self) -> bool: ...
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
        def _replace_via_keyboard(
            self,
            insert: str,
            start: tuple[int, int],
            end: tuple[int, int],
        ) -> None: ...
        def _show_insert_g_prefix_hints(self) -> None: ...
        def _show_normal_g_prefix_hints(self) -> None: ...
        def _try_advance_tabstop(self) -> bool: ...
        def _try_auto_placeholder_completion(self) -> bool: ...
        def _try_expand_snippet(self) -> bool: ...
        def _try_auto_prompt_reference_completion(self) -> bool: ...
        def _try_auto_xprompt_completion(self) -> bool: ...
        def _try_file_completion_tab(self) -> bool: ...
        def _try_vcs_project_completion(self) -> bool: ...
        def action_open_editor(self) -> None: ...
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
            and (settings.auto_xprompt_menu or settings.auto_directive_menu)
            and _is_auto_xprompt_menu_character(character)
        ):
            self._try_auto_prompt_reference_completion()
        self._refresh_xprompt_arg_hint_from_cursor()
        self._on_prompt_completion_context_changed()

    async def _on_key(self, event: Key) -> None:
        """Intercept keys before TextArea's default handler inserts characters."""
        # A just-accepted optional-only xprompt left a trailing spacer
        # (``#name ``); the next typed ``:`` replaces it in place so the common
        # ``#name:`` colon-argument flow needs no manual backspace. The spacer is
        # a one-shot convenience: any other key (or a cursor that has moved off
        # it) drops the pending state and lets the colon insert normally.
        pending_spacer = self._pending_optional_spacer
        if pending_spacer is not None:
            self._pending_optional_spacer = None
            if event.character == ":" and self._consume_optional_spacer_colon(
                pending_spacer
            ):
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
                self._accept_file_completion()
            else:
                bar = self._find_prompt_bar()
                if bar is not None and bar.is_multi_pane() and self.text.strip():
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

        # Prompt-stack pane focus and reorder migrated to the prompt ``g``
        # prefix: ``gj`` / ``gk`` focus the next / previous pane and ``gJ`` /
        # ``gK`` reorder the active pane (dispatched through the vim ``g``
        # pending state in ``_handle_normal_pending_key``). Bare normal-mode
        # ``J`` is therefore free again for vim's line join, and normal-mode
        # ``K`` is handled by the vim dispatcher as a preview lookup command.
        # Normal-mode ``Up`` / ``Down`` fall through to the TextArea's own cursor
        # movement in both single- and multi-pane stacks.

        # Prompt-stack add-pane and the xprompt properties panel toggle both
        # migrated to the prompt ``g`` prefix: ``g-`` appends a new empty bottom
        # pane (``add_bottom_pane``) and ``g=`` toggles the frontmatter panel
        # (``toggle_frontmatter_panel``), dispatched through the vim ``g`` pending
        # state in ``_handle_normal_pending_key``. The old insert-mode structural
        # chords (``Ctrl+-`` / ``ctrl+underscore`` and ``Ctrl+Shift+=``) no
        # longer fire here; insert-mode users reach the same prompt-local table
        # through the ``Ctrl+G`` prefix. The structural actions still clear
        # transient completion state internally, just as the old chord handlers
        # did before mutating the stack.

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
            if event.key == "ctrl+d" and self._completion_kind == "file_history":
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

        # Tab in INSERT mode: expand snippet or advance tabstop; never insert a
        # literal tab.
        if event.key == "tab":
            event.stop()
            event.prevent_default()
            self._clear_soft_completion(cancel_timer=True)
            if self._try_expand_snippet():
                return
            self._try_advance_tabstop()
            return

        if self._try_jinja_auto_pair(event):
            event.stop()
            event.prevent_default()
            return

        if self._try_prompt_text_pair_edit(event):
            event.stop()
            event.prevent_default()
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
        # Auto-open the ``#+`` project completion menu when the ``+`` completes
        # a valid trigger token. The refresh above already narrows an open menu,
        # so only try to open when one is not already active.
        if (
            event.character == "+"
            and self._vim_mode == "insert"
            and not self._file_completion_active
        ):
            self._try_vcs_project_completion()
        self._open_auto_reference_completion_after_change(event.character)

    def _handle_insert_g_prefix_key(self, event: Key) -> bool:
        """Handle the INSERT-mode ``Ctrl+G`` prompt-local prefix."""
        if self._vim_mode != "insert":
            self._clear_insert_g_prefix()
            return False

        if not self._insert_g_prefix_pending:
            if event.key != "ctrl+g":
                return False
            self._insert_g_prefix_pending = True
            self._show_insert_g_prefix_hints()
            return True

        if event.key == "escape":
            self._clear_insert_g_prefix()
            return True

        key = _resolve_g_prefix_second_key(event)
        if key == "g" or event.key == "ctrl+g":
            self._clear_insert_g_prefix()
            self.action_open_editor()
            return True

        self._clear_insert_g_prefix()
        bar = self._find_prompt_bar()
        dispatch = (
            getattr(bar, "dispatch_g_prefix_key", None) if bar is not None else None
        )
        if callable(dispatch):
            dispatch(key, target_mode="insert", via_ctrl_g=True)
        return True

    def _handle_normal_g_prefix_key(self, event: Key) -> bool:
        """Handle the NORMAL-mode ``Ctrl+G`` prompt-local prefix.

        Mirrors :meth:`_handle_insert_g_prefix_key` so NORMAL-mode ``Ctrl+G``
        opens the same prompt-local ``^G`` prefix (hint panel, editor entry, and
        prompt-specific continuations) that INSERT-mode ``Ctrl+G`` does, while
        still shadowing the app-level ``Ctrl+G`` binding. The only behavioral
        difference is that continuations dispatch with ``target_mode="normal"``
        so pane focus / reorder land in NORMAL mode, matching the vim ``g``
        prefix. The vim ``g`` pending path is untouched; this is its own state.
        """
        if self._vim_mode != "normal":
            self._clear_normal_g_prefix()
            return False

        if not self._normal_g_prefix_pending:
            if event.key != "ctrl+g":
                return False
            self._normal_g_prefix_pending = True
            self._show_normal_g_prefix_hints()
            return True

        if event.key == "escape":
            self._clear_normal_g_prefix()
            return True

        key = _resolve_g_prefix_second_key(event)
        if key == "g" or event.key == "ctrl+g":
            self._clear_normal_g_prefix()
            self.action_open_editor()
            return True

        self._clear_normal_g_prefix()
        bar = self._find_prompt_bar()
        dispatch = (
            getattr(bar, "dispatch_g_prefix_key", None) if bar is not None else None
        )
        if callable(dispatch):
            dispatch(key, target_mode="normal", via_ctrl_g=True)
        return True

    def _try_jinja_auto_pair(self, event: Key) -> bool:
        """Auto-pair Jinja delimiters after the second opener character.

        Generic ``{`` pairing already turned the first brace into ``{|}``, so
        the common path consumes that auto-inserted ``}`` and rebuilds it as the
        full Jinja pair. A literal first ``{`` followed by whitespace/EOF (a
        manually-authored buffer or undo/redo state) is still handled so the
        behavior matches whatever brace context the user is sitting in.
        """
        if event.character not in ("{", "%", "#"):
            return False
        start, end = self.selection
        if start != end:
            return False
        row, col = self.cursor_location
        if col <= 0:
            return False
        line = self.document.get_line(row)
        if line[col - 1] != "{":
            return False

        # ``{|}``: generic pairing inserted the closing brace; consume it and
        # rebuild the whole delimiter so the final cursor sits mid-pair.
        if col < len(line) and line[col] == "}":
            bodies = {"{": "{{  }}", "%": "{%  %}", "#": "{#  #}"}
            body = bodies[event.character]
            self._replace_via_keyboard(body, (row, col - 1), (row, col + 1))
            self.cursor_location = (row, col - 1 + 3)
            self._clear_soft_completion(cancel_timer=True)
            self._clear_file_completion()
            self._clear_xprompt_arg_hint()
            self._on_prompt_completion_context_changed()
            return True

        # Literal first ``{`` with nothing (or whitespace) following it.
        if col < len(line) and not line[col].isspace():
            return False
        pairs = {
            "{": ("{  }}", 2),
            "%": ("%  %}", 2),
            "#": ("#  #}", 2),
        }
        insert, cursor_delta = pairs[event.character]
        self._replace_via_keyboard(insert, (row, col), (row, col))
        self.cursor_location = (row, col + cursor_delta)
        self._clear_soft_completion(cancel_timer=True)
        self._clear_file_completion()
        self._clear_xprompt_arg_hint()
        self._on_prompt_completion_context_changed()
        return True

    def _try_prompt_text_pair_edit(self, event: Key) -> bool:
        """Auto-pair brackets/quotes and normalize ``|`` separators.

        Dispatch order for the typed character: ``|`` runs alternation separator
        normalization inside a live ``%{...}`` span; a closer that already sits
        under the cursor moves over instead of duplicating (close-skip); an
        opener inserts its matching closer at a safe position. Returns False
        (letting the default insertion path run) for every other key, when there
        is an active selection, or when the cursor is not in an applicable
        position.
        """
        char = event.character
        if not char or len(char) != 1:
            return False
        start, end = self.selection
        if start != end:
            return False
        text = self.text
        offset = self._absolute_offset(self.cursor_location)
        if char == "|":
            plan = plan_alt_separator(text, offset)
        else:
            plan = plan_pair_close_skip(text, offset, char)
            if plan is None and char == "{":
                plan = plan_alt_brace_pair(text, offset)
            if plan is None:
                plan = plan_pair_insert(text, offset, char)
        if plan is None:
            return False
        self._apply_planned_text_edit(plan)
        if char == "(":
            self._open_auto_reference_completion_after_change(char)
        return True

    def _apply_planned_text_edit(self, plan: TextEdit) -> None:
        """Apply a :class:`TextEdit` and clear transient completion state."""
        self._replace_via_keyboard(
            plan.text,
            self._location_from_absolute(plan.start),
            self._location_from_absolute(plan.end),
        )
        self.cursor_location = self._location_from_absolute(plan.cursor)
        self._clear_soft_completion(cancel_timer=True)
        self._clear_file_completion()
        self._clear_xprompt_arg_hint()
        self._on_prompt_completion_context_changed()
