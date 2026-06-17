"""PromptTextArea key dispatch."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from textual.events import Key

from sase.ace.tui.widgets._prompt_text_area_actions import prompt_bar_class
from sase.ace.tui.widgets._vcs_mru_cycling import VcsMruCycleKey
from sase.ace.tui.widgets.frontmatter_panel import FRONTMATTER_PANEL_BODY_TOGGLE_KEYS

if TYPE_CHECKING:
    from textual.widgets import TextArea as _MixinBase

    from sase.ace.tui.widgets.xprompt_arg_assist import ActiveXPromptArgHint
else:
    _MixinBase = object


class PromptTextAreaKeyHandlingMixin(_MixinBase):
    """PromptTextArea key handling kept separate from widget construction."""

    if TYPE_CHECKING:
        _active_xprompt_arg_hint: ActiveXPromptArgHint | None
        _completion_kind: str
        _file_completion_active: bool
        _count_prefix: str
        _pending_keys: str
        _pending_operator: str
        _vcs_mru_index: int | None
        _vim_mode: str

        def _accept_file_completion(self) -> bool: ...
        def _accept_or_build_soft_completion(self) -> bool: ...
        def _apply_xprompt_colon_arg_hint(self) -> bool: ...
        def _apply_xprompt_named_arg_hint(self) -> bool: ...
        def _can_apply_xprompt_arg_action(self) -> bool: ...
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
        def _handle_vcs_mru_cycle_key(self, key: VcsMruCycleKey) -> bool: ...
        def _handle_visual_mode_key(self, event: Key) -> bool: ...
        def _move_file_completion(self, delta: int) -> bool: ...
        def _on_prompt_completion_context_changed(self) -> None: ...
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
        def _try_advance_tabstop(self) -> bool: ...
        def _try_expand_snippet(self) -> bool: ...
        def _try_file_completion_tab(self) -> bool: ...
        def action_open_prompt_history(self) -> None: ...
        def action_submit_prompt(self) -> None: ...
        def action_submit_prompt_stack(self) -> None: ...

    async def _on_key(self, event: Key) -> None:
        """Intercept keys before TextArea's default handler inserts characters."""
        if event.key == "enter":
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

        # Selected-pane submit accelerator for prompt stacks. ``Enter`` opens
        # the chooser, while ``Ctrl+Shift+S`` keeps the old direct drain-one-pane
        # path.
        if event.key == "ctrl+shift+s":
            bar = self._find_prompt_bar()
            if bar is not None and bar.is_multi_pane():
                event.stop()
                event.prevent_default()
                self.action_submit_prompt()
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

        # Prompt-stack pane focus on normal-mode ``K`` / ``J`` -- ``K`` focuses
        # the previous/higher pane and ``J`` the next/lower pane. These are
        # NORMAL-mode-only structural keys (they retire vim's ``J`` line join):
        # only real multi-pane stacks move focus, but bare normal-mode ``J`` /
        # ``K`` are always swallowed here -- even in a single pane, where there
        # is no pane to focus -- so they never leak to the app-level Agents-tab
        # ``J`` / ``K`` panel-focus bindings. A pending normal-mode prefix
        # (comma leader, operator, count) suppresses the focus controls so
        # ``,J`` / ``dJ`` / ``2J`` keep falling through to their own handling.
        if self._vim_mode == "normal" and (event.character or event.key) in (
            "J",
            "K",
        ):
            if (
                not self._pending_keys
                and not self._pending_operator
                and not self._count_prefix
            ):
                event.stop()
                event.prevent_default()
                bar = self._find_prompt_bar()
                if bar is not None and bar.is_multi_pane():
                    delta = -1 if (event.character or event.key) == "K" else 1
                    bar.focus_relative(delta, target_mode="normal")
                return

        # Prompt-stack pane reorder on normal-mode ``Up`` / ``Down`` -- ``Up``
        # moves the active pane higher/earlier and ``Down`` lower/later,
        # mirroring the vertical stack layout. NORMAL-mode-only (insert-mode
        # ``up`` / ``down`` stay cursor / completion navigation) and consumed
        # only in a real multi-pane stack: a single pane keeps normal-mode arrow
        # cursor movement, so the event falls through untouched. A pending
        # normal-mode prefix likewise falls through.
        if (
            self._vim_mode == "normal"
            and event.key in ("up", "down")
            and not self._pending_keys
            and not self._pending_operator
            and not self._count_prefix
        ):
            bar = self._find_prompt_bar()
            if bar is not None and bar.is_multi_pane():
                event.stop()
                event.prevent_default()
                delta = -1 if event.key == "up" else 1
                bar.move_active_pane(delta, target_mode="normal")
                return

        # Prompt-stack add-pane. ``Ctrl+-`` is ``ctrl+minus`` when the terminal
        # stack preserves Kitty CSI-u disambiguation, but legacy / tmux paths
        # collapse it to the ``0x1f`` control byte that Textual reports as
        # ``ctrl+underscore`` (shared with Ctrl+_ and Ctrl+/). All those legacy
        # physical chords are indistinguishable, so they append a new empty
        # bottom pane and drop into it.
        #
        # Unlike the normal-mode-only ``K``/``J`` focus and ``Up``/``Down``
        # reorder keys, add-pane works while typing (insert) or browsing
        # (normal), and the event is always swallowed so the chord never falls
        # through to text insertion, completion, normal-mode editing, or
        # app-level bindings. ``add_bottom_pane`` no-ops outside prompt mode, so
        # feedback / approve-prompt bars stay non-stackable.
        if event.key in ("ctrl+minus", "ctrl+underscore") and self._vim_mode in {
            "insert",
            "normal",
        }:
            event.stop()
            event.prevent_default()
            bar = self._find_prompt_bar()
            if bar is not None:
                bar.add_bottom_pane()
            return

        # XPrompt properties panel toggle. ``Ctrl+Shift+=`` shows and focuses
        # the frontmatter panel from the body, and deactivates it again -- the
        # structural sibling of ``,f``. Like the stack chords it works while
        # typing (insert) or browsing (normal) and is always swallowed so it
        # never falls through to text insertion, completion, normal-mode editing,
        # or app-level bindings.
        # ``toggle_frontmatter_panel`` no-ops outside prompt mode, so feedback /
        # approve-prompt bars (which mount no panel) stay inert.
        if event.key in FRONTMATTER_PANEL_BODY_TOGGLE_KEYS and self._vim_mode in {
            "insert",
            "normal",
        }:
            event.stop()
            event.prevent_default()
            self._clear_soft_completion(cancel_timer=True)
            self._clear_file_completion()
            self._clear_xprompt_arg_hint()
            bar = self._find_prompt_bar()
            if bar is not None:
                bar.toggle_frontmatter_panel()
            return

        if self._vim_mode in {"visual", "visual_line"}:
            if self._handle_visual_mode_key(event):
                event.stop()
                event.prevent_default()
            return

        if self._vim_mode == "normal":
            if self._handle_normal_mode_key(event):
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
        self._refresh_xprompt_arg_hint_from_cursor()
        self._on_prompt_completion_context_changed()

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
