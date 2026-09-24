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
``ctrl+n``/``ctrl+p``, ``↑``/``↓`` while the menu is active, and
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

#: Keys offered to the screen's popup state machine before vim handling.
_POPUP_KEYS = frozenset(
    {
        "tab",
        "shift+tab",
        "ctrl+n",
        "ctrl+p",
        "ctrl+r",
        "up",
        "down",
        "enter",
        "escape",
    }
)


def _byte_offset(text: str, char_index: int) -> int:
    """Return the UTF-8 byte offset for a Python ``str`` index."""
    char_index = max(0, min(char_index, len(text)))
    return len(text[:char_index].encode("utf-8"))


#: NORMAL-mode keys the panel owns for transcript block navigation. While the
#: field is in NORMAL mode these are forwarded to the screen instead of
#: editing the line; INSERT mode keeps them as ordinary text.
BLOCK_NAV_KEYS = frozenset(
    {
        "j",
        "k",
        "g",
        "G",
        "o",
        "v",
        "K",
        "r",
        "R",
        "e",
        "y",
        "Y",
        "p",
        "x",
        "i",
        "a",
        "enter",
        "up",
        "down",
        "colon",
    }
)

#: Printable characters that map to block navigation (covers ``shift+x``
#: spellings such as ``shift+g`` whose ``event.key`` differs by platform).
_BLOCK_NAV_CHARS = frozenset("jkgGovKrReyYpxia")


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

    async def _on_key(self, event: Key) -> None:
        """Route popup and block-nav keys before Escape/hop/vim handling."""
        if event.key in _POPUP_KEYS:
            handler = getattr(self.screen, "command_line_handle_key", None)
            if callable(handler):
                try:
                    if await handler(event):
                        return
                except Exception:  # noqa: BLE001 - fall back to vim handling.
                    pass
        if getattr(self, "_vim_mode", "insert") == "normal":
            nav_key = event.key or ""
            if nav_key not in BLOCK_NAV_KEYS:
                character = event.character or ""
                if len(character) == 1 and character in _BLOCK_NAV_CHARS:
                    nav_key = character
                else:
                    nav_key = ""
            if nav_key:
                try:
                    handler = getattr(self.screen, "handle_block_nav_key", None)
                except Exception:  # noqa: BLE001 - screen reads degrade.
                    handler = None
                if callable(handler):
                    event.stop()
                    event.prevent_default()
                    handler(nav_key)
                    return
        if event.key == "escape" and self._vim_mode == "insert":
            if not self.text.strip():
                event.stop()
                event.prevent_default()
                await self.screen.dismiss(None)
                return
        if event.key == "semicolon" and self._vim_mode == "insert":
            if not self.text.strip():
                hop = getattr(self.screen, "hop_to_palette", None)
                if callable(hop):
                    event.stop()
                    event.prevent_default()
                    await hop()
                    return
        await super()._on_key(event)
