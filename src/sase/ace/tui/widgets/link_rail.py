"""One-line app-owned link rail for the selected ACE entity."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from rich.cells import cell_len
from rich.text import Text
from textual.widgets import Static

from sase.ace.tui.actions.link_trail import link_trail_breadcrumb_text
from sase.ace.tui.link_rail_flag import link_rail_enabled
from sase.ace.tui.relations.link_index import LinkChip
from sase.ace.tui.relations.link_keys import (
    MAX_DIRECT_LINK_KEYS,
    LinkRailItem,
    link_key_label,
    link_rail_items,
    short_ref_label,
)
from sase.ace.tui.relations.link_subject import selected_link_subject
from sase.ace.tui.util.trace import tui_trace

_SEPARATOR = " · "
_HEADER_STYLE = "bold"
_KEY_STYLE = "bold #FFAF00"
_DIM_STYLE = "dim #808080"
_WHY_STYLE = "dim #A8A8A8"
_MISSING_STYLE = "dim #808080"
_MAX_TARGET_LABEL_CELLS = 34
_MAX_WHY_CELLS = 42

_RELATION_SIGILS = {
    "cites": "cite",
    "derives-from": "deriv",
    "implements": "impl",
    "launched": "lnch",
    "produced-by": "prod",
    "read": "read",
    "related": "rel",
    "supersedes": "sup",
}


class LinkRail(Static):
    """Read-only rail showing artifact links for the selected entity."""

    can_focus = False

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._chips: tuple[LinkChip, ...] = ()
        self._subject_accent = "#87D7FF"
        self._breadcrumb: str | None = None
        self._last_signature: tuple[Any, ...] | None = None

    def on_mount(self) -> None:
        """Start invisible; the first ready index refresh paints the rail."""

        if not self._chips:
            self.display = False

    def on_resize(self) -> None:
        """Re-run the width ladder without changing chip ordering."""

        if self._chips or self._breadcrumb:
            self._refresh()

    def refresh_from_app(self, app: Any | None = None) -> None:
        """Refresh the rail from the app's selected subject and cached links."""

        host = self.app if app is None else app
        if not link_rail_enabled():
            self.clear()
            return
        breadcrumb = link_trail_breadcrumb_text(host)
        subject = selected_link_subject(host)
        chips: Sequence[LinkChip] = ()
        if subject is not None:
            edges_for_selection = getattr(host, "link_edges_for_selection", None)
            chips = edges_for_selection() if callable(edges_for_selection) else ()
        if not chips and breadcrumb is None:
            self.clear()
            return
        accent = subject.accent if subject is not None else "#87D7FF"
        self.update_links(chips, subject_accent=accent, breadcrumb=breadcrumb)

    def update_links(
        self,
        chips: Sequence[LinkChip],
        *,
        subject_accent: str,
        breadcrumb: str | None = None,
    ) -> None:
        """Show *chips* using *subject_accent* for the header."""

        self._chips = tuple(chips)
        self._subject_accent = subject_accent or "#87D7FF"
        self._breadcrumb = breadcrumb
        self._refresh()

    def clear(self) -> None:
        """Clear the rail and remove it from the layout."""

        self._chips = ()
        self._breadcrumb = None
        self._last_signature = None
        self.display = False
        self.update("")

    def _refresh(self) -> None:
        width = _available_width(self)
        with tui_trace("widget.link_rail.update", count=len(self._chips), width=width):
            text = _render_link_rail(
                self._chips,
                subject_accent=self._subject_accent,
                width=width,
                breadcrumb=self._breadcrumb,
            )
            if text is None:
                self.clear()
                return
            signature = (
                text.plain,
                tuple((span.start, span.end, str(span.style)) for span in text.spans),
            )
            if signature == self._last_signature and self.display:
                return
            self._last_signature = signature
            self.display = True
            self.update(text)


def _render_link_rail(
    chips: Sequence[LinkChip],
    *,
    subject_accent: str = "#87D7FF",
    width: int = 0,
    breadcrumb: str | None = None,
) -> Text | None:
    """Render *chips* as the one-line rail, or ``None`` when there is no rail."""

    items = link_rail_items(tuple(chips))
    if not items:
        if not breadcrumb:
            return None
        text = Text(no_wrap=True, overflow="ellipsis")
        text.append(f" {breadcrumb}", style="dim")
        return text
    visible = min(len(items), MAX_DIRECT_LINK_KEYS)
    attempts = (
        (True, True, True, visible),
        (False, True, True, visible),
        (False, False, True, visible),
    )
    for include_why, lead_full_label, include_count, visible_count in attempts:
        text = _compose_rail(
            items,
            subject_accent=subject_accent,
            include_why=include_why,
            lead_full_label=lead_full_label,
            include_count=include_count,
            visible_count=visible_count,
            breadcrumb=breadcrumb,
        )
        if _fits(text, width):
            return text
    # Degradation ladder, continued: drop trailing chips into "+k more" with
    # the breadcrumb still shown, then again with the breadcrumb collapsed,
    # before the final no-count fallback below.
    for candidate_breadcrumb in (breadcrumb, None):
        for visible_count in range(visible - 1, -1, -1):
            text = _compose_rail(
                items,
                subject_accent=subject_accent,
                include_why=False,
                lead_full_label=False,
                include_count=True,
                visible_count=visible_count,
                breadcrumb=candidate_breadcrumb,
            )
            if _fits(text, width):
                return text
    text = _compose_rail(
        items,
        subject_accent=subject_accent,
        include_why=False,
        lead_full_label=False,
        include_count=False,
        visible_count=0,
        breadcrumb=None,
    )
    text.overflow = "ellipsis"
    return text


def _compose_rail(
    items: tuple[LinkRailItem, ...],
    *,
    subject_accent: str,
    include_why: bool,
    lead_full_label: bool,
    include_count: bool,
    visible_count: int,
    breadcrumb: str | None = None,
) -> Text:
    total_links = sum(item.count for item in items)
    text = Text(no_wrap=True, overflow="ellipsis")
    if breadcrumb:
        text.append(f" {breadcrumb}", style="dim")
        text.append(_SEPARATOR, style="dim")
        text.append("LINKS", style=f"{_HEADER_STYLE} {subject_accent}")
    else:
        text.append(" LINKS", style=f"{_HEADER_STYLE} {subject_accent}")
    if include_count and total_links > 1:
        text.append(f" {total_links}", style=f"{_HEADER_STYLE} {subject_accent}")
    for index, item in enumerate(items[:visible_count], start=1):
        text.append(_SEPARATOR, style="dim")
        _append_item(
            text,
            item,
            index=index,
            total_link_count=total_links,
            lead=index == 1,
            include_why=include_why,
            lead_full_label=lead_full_label,
        )
    text.append(_SEPARATOR, style="dim")
    hidden_count = sum(item.count for item in items[visible_count:])
    if hidden_count:
        _append_key(text, "$0")
        text.append(f" +{hidden_count} more", style="dim")
    else:
        _append_key(text, "$0")
        text.append(" all", style="dim")
    return text


def _append_item(
    text: Text,
    item: LinkRailItem,
    *,
    index: int,
    total_link_count: int,
    lead: bool,
    include_why: bool,
    lead_full_label: bool,
) -> None:
    chip = item.chip
    _append_key(text, link_key_label(index, total_link_count))
    text.append(f" {_direction_glyph(chip)} ", style="dim")
    relation_label = chip.label if lead and lead_full_label else _relation_sigil(chip)
    text.append(relation_label, style="dim")
    text.append(" ")
    if _item_is_missing(item):
        text.append("⊘", style=_MISSING_STYLE)
        text.append(" ")
    text.append(chip.icon or "•", style=f"bold {chip.accent}")
    text.append(" ")
    target_label = _target_label(item)
    target_style = _MISSING_STYLE if _item_is_missing(item) else f"bold {chip.accent}"
    text.append(
        _ellipsize_cells(target_label, _MAX_TARGET_LABEL_CELLS), style=target_style
    )
    if _item_is_missing(item):
        text.append(" (missing)", style=_MISSING_STYLE)
    if lead and include_why and chip.why:
        text.append(" — ", style=_DIM_STYLE)
        text.append(
            f"“{_ellipsize_cells(chip.why, _MAX_WHY_CELLS)}”",
            style=_WHY_STYLE,
        )


def _append_key(text: Text, key: str) -> None:
    text.append(key, style=_KEY_STYLE)


def _direction_glyph(chip: LinkChip) -> str:
    if not chip.directed:
        return "↔"
    return "→" if chip.this_is_source else "←"


def _relation_sigil(chip: LinkChip) -> str:
    return _RELATION_SIGILS.get(chip.relation, chip.label[:4] or chip.relation[:4])


def _target_label(item: LinkRailItem) -> str:
    if item.projected_group:
        return f"{item.count} {_plural_kind(item.neighbor_kind)}"
    return short_ref_label(item.chip.neighbor_ref)


def _plural_kind(kind: str) -> str:
    if kind == "stitch":
        return "stitches"
    if kind.endswith("s"):
        return kind
    return f"{kind}s" if kind else "links"


def _item_is_missing(item: LinkRailItem) -> bool:
    return item.chip.neighbor_target is None and item.neighbor_kind != "chop"


def _available_width(widget: Static) -> int:
    try:
        width = int(widget.size.width)
    except Exception:
        return 0
    return max(0, width - 2)


def _fits(text: Text, width: int) -> bool:
    return width <= 0 or cell_len(text.plain) <= width


def _ellipsize_cells(value: str, max_cells: int) -> str:
    if max_cells <= 1:
        return "…"
    if cell_len(value) <= max_cells:
        return value
    output = ""
    used = 0
    for char in value:
        char_width = cell_len(char)
        if used + char_width >= max_cells:
            break
        output += char
        used += char_width
    return output.rstrip() + "…"


__all__ = ["LinkRail"]
