"""The shared ``❯ sase <name>`` command chip renderer.

Every surface that names a plugin-mounted command — help, CLI result panels,
``sase plugin list`` and ``show``, the Updates tab, and toasts — renders the
same chip through this module, so ``❯ sase listen`` always means "a command a
plugin gave you".
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from rich.text import Text

#: Glyph that marks a command as plugin-provided.
CHIP_GLYPH = "❯"

#: Lifecycle states a chip can announce.
ChipState = Literal["new", "removed", "problem"]


def format_command_chip(name: str) -> str:
    """Return the plain-text ``❯ sase <name>`` chip."""
    return f"{CHIP_GLYPH} sase {name}"


def format_command_chip_rich(name: str, *, state: ChipState | None = None) -> Text:
    """Return the Rich ``❯ sase <name>`` chip, with an optional lifecycle state.

    Rich is imported lazily so dispatch and other hot paths never pay for it.
    """
    from rich.text import Text

    chip = Text(f"{CHIP_GLYPH} sase {name}", style="bold magenta")
    if state == "new":
        chip.append("  new command", style="green")
    elif state == "removed":
        chip.append("  command removed", style="red")
    elif state == "problem":
        chip.append("  problem", style="yellow")
    return chip
