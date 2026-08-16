"""Shared fold-banner renderer for Artifacts panes on the group registry.

One rendering grammar — fold glyph, label, member count, optional jump
hint — used by every pane that groups already-loaded rows through
:func:`sase.ace.tui.models.artifact_groups.build_grouped_rows`.  Provider
identity, colors, and callbacks stay out of this module; the caller passes
its own contract accent.
"""

from __future__ import annotations

from rich.text import Text
from textual.widgets.option_list import Option

from ...models.artifact_groups import ArtifactGroupBanner
from .entry_navigation import prepend_jump_hint


def format_group_banner_option(
    banner: ArtifactGroupBanner,
    *,
    accent: str,
    hint_char: str | None = None,
) -> Option:
    """Render one shared fold banner row.

    Expanded banners stay visible but ``disabled`` (non-selectable, mirroring
    Patches' banner rows); collapsed banners are selectable so ``j``/``k``
    and jump hints can stop on them.
    """
    text = Text(no_wrap=True, overflow="ellipsis")
    indent = "  " * banner.level
    glyph = "▸" if banner.collapsed else "▾"
    glyph_style = f"bold {accent}" if banner.level == 0 else accent
    label_style = "bold white" if banner.level == 0 else "white"
    text.append(f"{indent}{glyph} ", style=glyph_style)
    text.append(f"{banner.label} ", style=label_style)
    text.append(f"({banner.member_count}) ", style="dim")
    text.append("─" * 8, style="dim #5F5F87")
    prompt = prepend_jump_hint(text, hint_char)
    return Option(prompt, id=banner.option_id, disabled=not banner.collapsed)


__all__ = ["format_group_banner_option"]
