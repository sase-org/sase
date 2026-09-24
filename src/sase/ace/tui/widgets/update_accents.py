"""Shared update visual language for the badge, Update panel, and toast.

The updates badge is the top bar's only deep chip: a deep moss surface
with bright lime ink. Every other filled chip on the row is a bright
background with dark ink, so the badge is told apart by lightness, not
hue, and stays distinct in every color-vision condition.

Hue is identity; state lives inside the chip. The badge never changes
hue. A pending sase-core Rust rebuild adds a bright lime inset ``core``
tag (dark ink on lime, the identity accent filled in) following the top
bar's existing two-part pill grammar. While SASE is updating, a green
gear inset (the same lime fill with dark ink) leads the badge so the
running update reads as the updates lane's proc gear against the deep
moss chip. Agent CLIs share the same moss surface with sage ink,
differing by label and ink tone, not by borrowing another hue.

The glyph is ``⬆`` (U+2B06): a solid pictogram matching the row's ``⚙ ≡ ★``
neighbors instead of punctuation, keeps the "up = upgrade" direction, is in
both bundled Fira Code weights, and is always one cell wide; it is shared by
the top-bar badge, the Update panel, and the plugins browser.
"""

from __future__ import annotations

from rich.text import Text

UPDATE_GLYPH = "⬆"
UPDATES_SURFACE = "#244A14"
UPDATES_ACCENT = "#AFFF87"
AGENT_CLI_ACCENT = "#AFD7AF"
CORE_TAG_LABEL = "core"
CORE_TAG_INK = "#1a1a1a"
UPDATE_CAUTION_ACCENT = "#FFAF5F"


def build_core_tag() -> Text:
    """The inset ``core`` tag marking a pending sase-core Rust rebuild."""
    return Text(f" {CORE_TAG_LABEL} ", style=f"bold {CORE_TAG_INK} on {UPDATES_ACCENT}")


__all__ = [
    "AGENT_CLI_ACCENT",
    "CORE_TAG_INK",
    "CORE_TAG_LABEL",
    "UPDATE_CAUTION_ACCENT",
    "UPDATE_GLYPH",
    "UPDATES_ACCENT",
    "UPDATES_SURFACE",
    "build_core_tag",
]
