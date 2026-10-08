"""The shared ``❯ sase <name>`` command chip renderer.

Every surface that names a plugin-mounted command — help, CLI result panels,
``sase plugin list`` and ``show``, the Updates tab, and toasts — renders the
same chip through this module, so ``❯ sase listen`` always means "a command a
plugin gave you". Rich is imported lazily so dispatch never pays for it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from rich.text import Text

#: Glyph that marks a command as plugin-provided.
CHIP_GLYPH = "❯"

ChipState = Literal["new", "removed", "problem"]


def format_command_chip(name: str) -> str:
    """Return the plain-text ``❯ sase <name>`` chip."""
    return f"{CHIP_GLYPH} sase {name}"


def format_command_chip_with_state(name: str, state: ChipState | None = None) -> str:
    """Return the plain-text chip with an optional lifecycle state label."""
    chip = format_command_chip(name)
    if state == "new":
        return f"{chip}  new command"
    if state == "removed":
        return f"{chip}  removed"
    return chip


def rich_command_chip(name: str, state: ChipState | None = None) -> Text:
    """Return the chip as a Rich ``Text`` in the Updates accent.

    The base chip uses bold magenta; ``removed`` renders yellow and
    ``problem`` renders bold red so problem rows stand out in help and
    result panels.
    """
    from rich.text import Text

    if state == "removed":
        style = "yellow"
    elif state == "problem":
        style = "bold red"
    else:
        style = "bold magenta"
    return Text(format_command_chip_with_state(name, state), style=style)
