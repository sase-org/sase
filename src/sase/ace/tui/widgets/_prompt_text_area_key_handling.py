"""PromptTextArea key dispatch."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from textual.events import Key

from sase.ace.tui.widgets._prompt_text_area_actions import prompt_bar_class
from sase.ace.tui.widgets._vcs_mru_cycling import VcsMruCycleKey

if TYPE_CHECKING:
    from textual.widgets import TextArea as _MixinBase

    from sase.ace.tui.widgets.prompt_completion import PromptCompletionSettings
    from sase.ace.tui.widgets.xprompt_arg_assist import ActiveXPromptArgHint
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


class PromptTextAreaKeyHandlingMixin(_MixinBase):
    """PromptTextArea key handling kept separate from widget construction."""

    if TYPE_CHECKING:
        _active_xprompt_arg_hint: ActiveXPromptArgHint | None
        _completion_kind: str
        _file_completion_active: bool
        _count_prefix: str
        _insert_g_prefix_pending: bool
        _pending_keys: str
        _pending_operator: str
        _vcs_mru_index: int | None
        _vim_mode: str

        def _accept_file_completion(self) -> bool: ...
        def _accept_or_build_soft_completion(self) -> bool: ...
        def _apply_xprompt_colon_arg_hint(self) -> bool: ...
        def _apply_xprompt_named_arg_hint(self) -> bool: ...
        def _can_apply_xprompt_arg_action(self) -> bool: ...
        def _clear_insert_g_prefix(self) -> None: ...
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
        def _try_advance_tabstop(self) -> bool: ...
        def _try_expand_snippet(self) -> bool: ...
        def _try_auto_xprompt_completion(self) -> bool: ...
        def _try_file_completion_tab(self) -> bool: ...
        def _try_vcs_project_completion(self) -> bool: ...
        def action_open_editor(self) -> None: ...
        def action_open_prompt_history(self) -> None: ...
        def action_submit_prompt(self) -> None: ...
        def action_submit_prompt_stack(self) -> None: ...

    async def _on_key(self, event: Key) -> None:
        """Intercept keys before TextArea's default handler inserts characters."""
        if self._is_prompt_search_active():
            self._clear_insert_g_prefix()
            if self._handle_prompt_search_key(event):
                event.stop()
                event.prevent_default()
                return

        if self._handle_insert_g_prefix_key(event):
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

        # Whole-stack submit. ``^S`` joins the stack into one multi-prompt.
        if event.key == "ctrl+s":
            event.stop()
            event.prevent_default()
            self.action_submit_prompt_stack()
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
        # ``Up`` / ``Down`` fall through to the TextArea's own cursor movement in
        # both single- and multi-pane stacks.
        #
        # Bare normal-mode ``K`` has no vim command of its own here, so it is
        # swallowed as a prompt-local no-op -- without this it would bubble to
        # the app-level Agents-tab ``K`` panel-focus binding while the prompt
        # body owns focus. A pending normal-mode prefix (``g``, an operator, or
        # a count) lets ``K`` fall through so ``gK`` / ``dK`` / ``2K`` keep
        # reaching their own handling.
        if (
            self._vim_mode == "normal"
            and (event.character or event.key) == "K"
            and not self._pending_keys
            and not self._pending_operator
            and not self._count_prefix
        ):
            event.stop()
            event.prevent_default()
            return

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
            if self._handle_normal_mode_key(event):
                event.stop()
                event.prevent_default()
            elif event.key == "ctrl+g":
                event.stop()
                event.prevent_default()
            return

        # INSERT mode: Escape enters NORMAL mode.
        if event.key == "escape":
            if self._file_completion_active:
                event.stop()
                event.prevent_default()
                self._clear_file_completion()
                self._clear_soft_completion(cancel_timer=True)
                self._clear_xprompt_arg_hint()
                return
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

        # Active file completion navigation / acceptance.
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

        if event.key in ("ctrl+n", "ctrl+p") and self._handle_vcs_mru_cycle_key(
            cast(VcsMruCycleKey, event.key)
        ):
            event.stop()
            event.prevent_default()
            return

        # Ctrl+T in INSERT mode: trigger file path completion.
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

        # Detect '#@' trigger before the '@' is inserted (skip in feedback mode).
        if event.character == "@":
            bar = self._find_prompt_bar()
            if bar and bar._mode != "feedback":
                row, col = self.cursor_location
                if col > 0:
                    line = self.document.get_line(row)
                    if line[col - 1] == "#":
                        PromptInputBar = prompt_bar_class()
                        bar.post_message(PromptInputBar.SnippetRequested())
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
        if (
            self._vim_mode == "insert"
            and not self._file_completion_active
            and self._prompt_completion_settings().auto_xprompt_menu
            and _is_auto_xprompt_menu_character(event.character)
        ):
            self._try_auto_xprompt_completion()
        self._refresh_xprompt_arg_hint_from_cursor()
        self._on_prompt_completion_context_changed()

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

        key = event.key if event.key == "enter" else event.character or event.key
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
            dispatch(key, target_mode="insert")
        return True

    def _try_jinja_auto_pair(self, event: Key) -> bool:
        """Auto-pair Jinja delimiters after the second opener character."""
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
