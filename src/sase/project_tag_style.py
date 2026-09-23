"""Shared accent styling for ``+<project>`` tag surfaces (D5/D6).

Centralizes the two operations every remaining raw-prompt surface needs:

- tag accent lookup for fixed-width project columns (history, stash), with a
  fail-open fallback to the surface's historical style.
- Rich ``Text`` tag overlays for preview bodies that are plain today: the
  caller humanizes (tagifies) first, then overlays only the ``+tag``
  substrings, leaving the rest of the prompt in its current style.
"""

from __future__ import annotations

from rich.text import Text


def accent_for_project_ref(ref: str | None) -> str | None:
    """Return the accent hex for a project *ref*, or ``None`` when unknown.

    Matches directory keys, display names, and aliases case-insensitively
    against the warm tag catalog snapshot. Never touches disk or spawns
    processes: render paths must use the peek snapshot and fall back when
    the catalog is cold. Disabled projects and ``home`` carry no accent
    (``None``), matching the chip.
    """
    if not ref:
        return None
    try:
        from sase.project_tags.catalog import peek_project_tag_catalog
    except Exception:
        return None
    try:
        catalog = peek_project_tag_catalog()
    except Exception:
        return None
    if catalog is None:
        return None
    folded = ref.casefold()
    try:
        targets = catalog.targets
    except Exception:
        return None
    for target in targets:
        try:
            candidates = [target.key, target.name]
            aliases = getattr(target, "aliases", ())
            if isinstance(aliases, (list, tuple)):
                candidates.extend(aliases)
        except Exception:
            continue
        if any(
            isinstance(item, str) and item.casefold() == folded for item in candidates
        ):
            accent = getattr(target, "accent", None)
            return accent if isinstance(accent, str) else None
    return None


def project_column_style(ref: str | None, *, fallback: str = "cyan") -> str:
    """Return the Rich style for a project column value.

    Resolved projects render in their accent (``bold <accent>`` is applied
    by callers that need it; this returns the bare accent color for column
    text). Unknown, disabled, or cold-catalog refs keep *fallback* so rows
    never go unstyled.
    """
    accent = accent_for_project_ref(ref)
    return accent if accent else fallback


def rich_text_with_project_tags(
    humanized_source: str,
    *,
    base_style: str | None = None,
) -> Text:
    """Return *humanized_source* as Rich ``Text`` with tag accents overlaid.

    *humanized_source* must already be tagified (``humanize_vcs_refs_in_text``).
    The whole text keeps *base_style*; only ``+<project>`` substrings gain
    the chip styling (``dim <accent>`` sigil, ``bold <accent>`` name). Never
    raises: tokenization failures return the plain base-styled text.
    """
    text = Text(humanized_source, style=base_style or "")
    if "+" not in humanized_source:
        return text
    try:
        from sase.ace.tui.util.xprompt_syntax import stylize_project_tags

        stylize_project_tags(text, humanized_source)
    except Exception:
        return text
    return text


def append_tagified_text(
    parent: Text,
    humanized_source: str,
    base_style: str = "",
) -> None:
    """Append *humanized_source* to *parent* with tag accents overlaid.

    Records the append offset first so the tag overlay lands on the new
    region only, preserving the caller's fixed-width row layout. Never
    raises.
    """
    if not humanized_source:
        return
    try:
        start = len(parent.plain)
        parent.append(humanized_source, style=base_style)
        if "+" not in humanized_source:
            return
        from sase.ace.tui.util.xprompt_syntax import stylize_project_tags

        stylize_project_tags(parent, humanized_source, region_start=start)
    except Exception:
        try:
            parent.append(humanized_source, style=base_style)
        except Exception:
            pass


__all__ = [
    "accent_for_project_ref",
    "append_tagified_text",
    "project_column_style",
    "rich_text_with_project_tags",
]
