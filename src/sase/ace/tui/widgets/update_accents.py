"""Shared update visual language for the badge, Update panel, and toast.

The updates badge is the top bar's only deep chip: a deep moss surface
with bright lime ink. Every other filled chip on the row is a bright
background with dark ink, so the badge is told apart by lightness, not
hue, and stays distinct in every color-vision condition.

Hue is identity; state lives inside the chip. The badge never changes
hue. A pending sase-core Rust rebuild adds a bright lime inset ``core``
tag (dark ink on lime, the identity accent filled in) following the top
bar's existing two-part pill grammar. The updates gear inset leads the
badge in one of three states with precedence green > yellow > red: green
(``updating``, the lime fill) while an update proc runs; yellow
(``restart_pending``, amber ``#FFC000``) while installed code waits for
TUI-local tasks, submissions, or installation changes before restarting
ACE and the SASE service; red
(``failed``, ``#FF5F5F``) while the most recent attempt failed. All three
gears share the same ``⚙`` glyph, 3-cell width, and bold ``#1a1a1a`` ink
in the same slot, so switching state never shifts the badge. The fills
step down in lightness as urgency rises, so states stay separable by
lightness under red-green color-vision deficiency. Agent CLIs share the
same moss surface with sage ink, differing by label and ink tone, not by
borrowing another hue.

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
UPDATE_RESTART_ACCENT = "#FFC000"
UPDATE_FAILED_ACCENT = "#FF5F5F"
UPDATE_RECOVERY_GLYPH = "↻"


def build_core_tag() -> Text:
    """The inset ``core`` tag marking a pending sase-core Rust rebuild."""
    return Text(f" {CORE_TAG_LABEL} ", style=f"bold {CORE_TAG_INK} on {UPDATES_ACCENT}")


__all__ = [
    "AGENT_CLI_ACCENT",
    "CORE_TAG_INK",
    "CORE_TAG_LABEL",
    "UPDATE_CAUTION_ACCENT",
    "UPDATE_FAILED_ACCENT",
    "UPDATE_GLYPH",
    "UPDATE_RECOVERY_GLYPH",
    "UPDATE_RESTART_ACCENT",
    "UPDATES_ACCENT",
    "UPDATES_SURFACE",
    "build_core_tag",
]
