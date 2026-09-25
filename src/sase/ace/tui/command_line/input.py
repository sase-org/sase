"""Command Line input widget: a single-line vim field with an implicit prefix.

The ``❯ sase `` prefix is dim and non-editable — the ``sase`` prefix is
implicit — and a leading ``sase `` the user types or pastes is stripped at
once. Escape follows the panel rules: INSERT with an empty line hides the
panel, otherwise the field drops to NORMAL mode. ``;`` on an empty line hops
to the Command Palette.

The completion-popup phase layers the resolver overlay on top: token-role
highlight spans (command paths, options, quoted strings) plus a red
undercurl for advisory diagnostics, following the ``_highlights`` overlay
approach from ``widgets/_jinja_highlight.py``. Popup keys (Tab, Shift-Tab,
``ctrl+n``/``ctrl+p``, ``↑``/``↓`` while the menu is active, ``ctrl+f``, and
menu-active Enter/Escape) are routed to the screen's popup state machine
before vim handling. ``ctrl+r`` toggles fuzzy history search the same way.
"""

from __future__ import annotations

import dataclasses
from typing import Any

from rich.style import Style
from textual.events import Key
from textual.widgets._text_area import TextAreaTheme

from sase.ace.tui.command_line.session import strip_implicit_prefix
from sase.ace.tui.keymaps.app_keymaps import CommandLineKeymaps
from sase.ace.tui.keymaps.defaults import load_builtin_command_line_defaults
from sase.ace.tui.keymaps.key_validation import (
    is_unbound_key,
    split_key_alternatives,
)
from sase.ace.tui.widgets.single_line_vim_text_area import SingleLineVimTextArea
from sase.completion.command_line_grammar import LineContext

#: Dim, non-editable prefix rendered before the editable text.
COMMAND_LINE_PREFIX = "❯ sase "

#: Theme carrying the resolver overlay styles.
_COMMAND_LINE_THEME_NAME = "sase-command-line"

#: Resolver token roles mapped to overlay style names.
_ROLE_STYLE_NAMES = {
    "command": "cmdline.command",
    "subcommand": "cmdline.command",
    "option": "cmdline.option",
    "option_name": "cmdline.option",
    "quoted": "cmdline.string",
    "string": "cmdline.string",
}

#: Style for advisory diagnostic undercurl spans.
_DIAGNOSTIC_STYLE_NAME = "cmdline.diagnostic"

#: Fixed zsh menu-select keys offered to the screen's popup state machine
#: before vim handling. The configurable history keys (``history_prev``,
#: ``history_next``, ``history_search``) join this set at runtime from the
#: live ``CommandLineKeymaps``.
_MENU_KEYS = frozenset(
    {
        "tab",
        "shift+tab",
        "ctrl+n",
        "ctrl+p",
        "ctrl+f",
        "enter",
        "escape",
    }
)

#: Scope fields that capture keys for transcript block navigation, in plan
#: order. The screen dispatches a matched field to its block handler.
BLOCK_NAV_ACTION_FIELDS: tuple[str, ...] = (
    "block_next",
    "block_prev",
    "block_first",
    "block_last",
    "block_toggle_expand",
    "block_pager",
    "block_kill",
    "block_rerun",
    "block_rerun_confirm",
    "block_edit",
    "block_copy_output",
    "block_copy_command",
    "block_procs",
    "block_remove",
    "block_focus_input",
)

#: The block action whose keys also enter the transcript from an unselected
#: NORMAL input (``k``/``↑`` by default).
ENTER_TRANSCRIPT_ACTION = "block_prev"


def command_line_keymaps_for(obj: Any) -> CommandLineKeymaps:
    """Return the live ``:`` Command Line scope for *obj*.

    *obj* is the input widget, the panel screen, or the app itself. Falls
    back to the bundled defaults when no registry is reachable (unmounted
    widget, teardown races).
    """
    try:
        app = getattr(obj, "app", obj)
        keymaps = getattr(getattr(app, "_keymap_registry", None), "command_line", None)
        if isinstance(keymaps, CommandLineKeymaps):
            return keymaps
    except Exception:  # noqa: BLE001 - keymap reads always degrade.
        pass
    return CommandLineKeymaps(**load_builtin_command_line_defaults())


def binding_matches_key(binding: str, key: str, character: str = "") -> bool:
    """True when a key event matches one alternative of a keymap *binding*.

    ``character`` covers platform ``shift+x`` spellings whose ``event.key``
    differs (``shift+g`` versus ``G``): a single-character event character
    matches a single-character alternative. ``unbound`` never matches.
    """
    if not key and not character:
        return False
    if not binding or is_unbound_key(binding):
        return False
    alternatives = [part for part in split_key_alternatives(binding) if part]
    if key and key in alternatives:
        return True
    if (
        character
        and len(character) == 1
        and character in {part for part in alternatives if len(part) == 1}
    ):
        return True
    return False


def match_block_nav_action(
    keymaps: CommandLineKeymaps, key: str, character: str = ""
) -> str | None:
    """Return the block-nav scope field matching a key event, if any."""
    for field in BLOCK_NAV_ACTION_FIELDS:
        if binding_matches_key(getattr(keymaps, field, "") or "", key, character):
            return field
    return None


def _byte_offset(text: str, char_index: int) -> int:
    """Return the UTF-8 byte offset for a Python ``str`` index."""
    char_index = max(0, min(char_index, len(text)))
    return len(text[:char_index].encode("utf-8"))


#: NORMAL-mode keys the panel owns for transcript block navigation live in
#: ``ace.keymaps.command_line`` (the ``block_*`` actions); see
#: :func:`match_block_nav_action`. While the field is in NORMAL mode a
#: matched key is forwarded to the screen instead of editing the line;
#: INSERT mode keeps those keys as ordinary text.


class CommandLineInput(SingleLineVimTextArea):
    """Single-line vim input for the Command Line panel."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("id", "command-line-input")
        super().__init__(*args, **kwargs)
        self.resolve_context: LineContext | None = None

    def normalized_text(self) -> str:
        """Return the editable text with any typed ``sase `` prefix stripped."""
        return strip_implicit_prefix(self.text)

    def set_line(self, line: str) -> None:
        """Replace the line and move the cursor to the end."""
        self.text = strip_implicit_prefix(line)
        try:
            self.move_cursor((0, len(self.document.get_line(0))))
        except Exception:  # noqa: BLE001 - cursor restore is best effort.
            pass

    def set_resolve_context(self, context: LineContext | None) -> None:
        """Store the latest resolver response and repaint the overlay."""
        self.resolve_context = context
        try:
            self._build_highlight_map()
        except Exception:  # noqa: BLE001 - overlay is best effort.
            pass
        try:
            self.refresh()
        except Exception:  # noqa: BLE001 - unmounted refresh is best effort.
            pass

    def _refresh_ghost_for_cursor_move(self) -> None:
        """Clear or refresh ghost text after a cursor-only edit."""
        try:
            refresh = getattr(self.screen, "_update_ghost", None)
        except Exception:  # noqa: BLE001 - input may be unmounted.
            refresh = None
        if callable(refresh):
            refresh()

    def action_cursor_left(self, select: bool = False) -> None:
        """Move left, then withdraw a ghost that is no longer at line end."""
        super().action_cursor_left(select)
        self._refresh_ghost_for_cursor_move()

    def action_cursor_right(self, select: bool = False) -> None:
        """Only let right-arrow accept a ghost while the cursor is at line end."""
        self._refresh_ghost_for_cursor_move()
        super().action_cursor_right(select)
        self._refresh_ghost_for_cursor_move()

    def action_cursor_line_start(self, select: bool = False) -> None:
        """Refresh ghost text after a readline line-start move."""
        super().action_cursor_line_start(select)
        self._refresh_ghost_for_cursor_move()

    def action_cursor_line_end(self, select: bool = False) -> None:
        """Refresh ghost text after a readline line-end move."""
        super().action_cursor_line_end(select)
        self._refresh_ghost_for_cursor_move()

    def action_cursor_word_left(self, select: bool = False) -> None:
        """Refresh ghost text after a word-left move."""
        super().action_cursor_word_left(select)
        self._refresh_ghost_for_cursor_move()

    def action_cursor_word_right(self, select: bool = False) -> None:
        """Refresh ghost text after a word-right move."""
        super().action_cursor_word_right(select)
        self._refresh_ghost_for_cursor_move()

    def on_mount(self) -> None:
        """Register the overlay theme after the base widget is mounted."""
        super_on_mount = getattr(super(), "on_mount", None)
        if callable(super_on_mount):
            super_on_mount()
        self._register_command_line_theme()

    def _app_theme_changed(self) -> None:
        super_changed = getattr(super(), "_app_theme_changed", None)
        if callable(super_changed):
            super_changed()
        self._register_command_line_theme()

    def _register_command_line_theme(self) -> None:
        """Register the ``sase-command-line`` theme with overlay styles."""
        try:
            app_theme = self.app.current_theme
        except Exception:  # noqa: BLE001 - theme is best effort pre-mount.
            return
        base_name = str(getattr(self, "theme", "css") or "css")
        base: TextAreaTheme | None
        try:
            base = self._themes[base_name]
        except (KeyError, AttributeError):
            base = TextAreaTheme.get_builtin_theme(base_name)
        if base is None:
            base = TextAreaTheme.get_builtin_theme("css")
            assert base is not None
        syntax_styles = dict(base.syntax_styles)
        syntax_styles.update(
            {
                "cmdline.command": Style(color="#00D7AF", bold=True),
                "cmdline.option": Style(color="#87D7FF"),
                "cmdline.string": Style(color="#FFB86B"),
                _DIAGNOSTIC_STYLE_NAME: Style(color=app_theme.error, underline=True),
            }
        )
        theme = dataclasses.replace(
            base,
            name=_COMMAND_LINE_THEME_NAME,
            syntax_styles=syntax_styles,
        )
        self.register_theme(theme)
        self.theme = _COMMAND_LINE_THEME_NAME

    def _build_highlight_map(self) -> None:
        """Layer resolver token and diagnostic spans over base highlights."""
        super()._build_highlight_map()
        # The base constructor builds the map before __init__ sets the
        # attribute, so read it defensively.
        context = getattr(self, "resolve_context", None)
        if not context:
            return
        text = self.text
        if not text:
            return
        for token in context.get("tokens") or []:
            style_name = _ROLE_STYLE_NAMES.get(str(token.get("role", "")))
            if not style_name:
                continue
            try:
                start = int(token.get("start", 0))
                end = int(token.get("end", 0))
            except (TypeError, ValueError):
                continue
            if end <= start:
                continue
            self._highlights[0].append(
                (_byte_offset(text, start), _byte_offset(text, end), style_name)
            )
        for diagnostic in context.get("diagnostics") or []:
            try:
                start = int(diagnostic.get("start", 0))
                end = int(diagnostic.get("end", 0))
            except (TypeError, ValueError):
                continue
            if end <= start:
                end = start + 1
            self._highlights[0].append(
                (
                    _byte_offset(text, start),
                    _byte_offset(text, end),
                    _DIAGNOSTIC_STYLE_NAME,
                )
            )

    def _history_key_match(self, keymaps: CommandLineKeymaps, key: str) -> bool:
        """True when *key* drives history (prev/next/search) in INSERT mode."""
        return (
            binding_matches_key(keymaps.history_prev, key)
            or binding_matches_key(keymaps.history_next, key)
            or binding_matches_key(keymaps.history_search, key)
        )

    async def _on_key(self, event: Key) -> None:
        """Route popup and block-nav keys before Escape/hop/vim handling."""
        keymaps = command_line_keymaps_for(self)
        if getattr(self, "_vim_mode", "insert") != "normal" and (
            (event.key or "") in _MENU_KEYS
            or self._history_key_match(keymaps, event.key or "")
        ):
            handler = getattr(self.screen, "command_line_handle_key", None)
            if callable(handler):
                try:
                    if await handler(event):
                        # Consumed keys must not bubble to the panel bindings:
                        # an accepting Enter would otherwise also submit.
                        event.stop()
                        event.prevent_default()
                        return
                except Exception:  # noqa: BLE001 - fall back to vim handling.
                    pass
        if getattr(self, "_vim_mode", "insert") == "normal":
            key = event.key or ""
            character = event.character or ""
            action = match_block_nav_action(keymaps, key, character)
            selected_block = None
            try:
                selected = getattr(self.screen, "selected_block", None)
                if callable(selected):
                    selected_block = selected()
            except Exception:  # noqa: BLE001 - screen reads degrade.
                pass
            # The enter-transcript action enters the transcript from an
            # unselected NORMAL input; every other panel key remains a
            # normal vim edit until a block is selected. Once selected,
            # the full block-nav set is panel-owned.
            if action is not None and (
                selected_block is not None or action == ENTER_TRANSCRIPT_ACTION
            ):
                try:
                    handler = getattr(self.screen, "handle_block_nav_key", None)
                except Exception:  # noqa: BLE001 - screen reads degrade.
                    handler = None
                if callable(handler):
                    if handler(key, character):
                        event.stop()
                        event.prevent_default()
                        return
        if event.key == "escape" and self._vim_mode == "insert":
            if not self.text.strip():
                event.stop()
                event.prevent_default()
                await self.screen.dismiss(None)
                return
        if self._vim_mode == "insert" and binding_matches_key(
            keymaps.hop_to_palette, event.key or ""
        ):
            if not self.text.strip():
                hop = getattr(self.screen, "hop_to_palette", None)
                if callable(hop):
                    event.stop()
                    event.prevent_default()
                    await hop()
                    return
        await super()._on_key(event)
