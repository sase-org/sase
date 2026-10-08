"""The shared ``❯ sase <name>`` command chip renderer.

Every surface that names a plugin-mounted command — help, CLI result panels,
``sase plugin list`` and ``show``, the Updates tab, and toasts — renders the
same chip through this module, so ``❯ sase listen`` always means "a command a
plugin gave you".
"""

from __future__ import annotations

#: Glyph that marks a command as plugin-provided.
CHIP_GLYPH = "❯"


def format_command_chip(name: str) -> str:
    """Return the plain-text ``❯ sase <name>`` chip."""
    return f"{CHIP_GLYPH} sase {name}"
