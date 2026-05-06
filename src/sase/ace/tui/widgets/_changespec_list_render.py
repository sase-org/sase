"""Render path for the ChangeSpec list widget.

The grouped (banner + CL) render is factored out of
:class:`ChangeSpecList` so the widget module stays focused on widget
plumbing (events, highlight, patch).  ``render_grouped`` takes the
widget instance as its first argument and mutates its bookkeeping
fields directly — it is part of the widget's implementation, just
factored into module scope for file size.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from rich.text import Text
from textual.widgets.option_list import Option

from ...changespec import ChangeSpec
from ..models.changespec_groups import (
    ChangeSpecGroupingMode,
    build_changespec_tree,
)
from ..models.artifact_indicator import ArtifactIndicator
from ..models.group_fold import GroupFoldRegistry, GroupKey
from ._changespec_list_banner import (
    CS_MIN_BANNER_WIDTH,
    banner_natural_width,
    format_changespec_banner_option,
)
from ._changespec_list_helpers import (
    calculate_entry_display_width,
    compute_mentor_stats,
    format_changespec_option,
    row_signature,
)

if TYPE_CHECKING:
    from .changespec_list import ChangeSpecList

#: Sentinel ``_row_entries`` value for banner rows.
_BANNER_ROW = -1

#: Padding added to the widest content width to size the panel — accounts
#: for border, scrollbar, and visual breathing room.
_PADDING = 8


def render_grouped(
    widget: ChangeSpecList,
    changespecs: list[ChangeSpec],
    current_idx: int,
    *,
    show_hideable: bool,
    show_submitted: bool,
    jump_hints: dict[int, str] | None,
    grouping_mode: ChangeSpecGroupingMode,
    fold_registry: GroupFoldRegistry | None,
    current_group_key: GroupKey | None,
    banner_jump_hints: dict[GroupKey, str] | None,
    artifact_indicators: dict[str, ArtifactIndicator] | None,
    now: datetime | None,
) -> None:
    """Render banner rows + CL rows for the active grouping mode.

    The grouped path always does a full rebuild — the patch path
    guards against grouped renders by gating on
    ``option_count == len(self._changespecs)`` so a stale patch can
    never write to a row whose option index is offset by banner
    rows.
    """
    tree = build_changespec_tree(
        changespecs,
        mode=grouping_mode,
        fold_registry=fold_registry,
        now=now,
    )

    # First pass: format CL rows so we know the widest content.
    cs_options: dict[int, Option] = {}
    cs_widths: dict[int, int] = {}
    cs_signatures: dict[int, tuple[Any, ...]] = {}
    cs_render_ctx: dict[int, dict[str, Any]] = {}
    max_cs_width = 0
    for i, cs in enumerate(changespecs):
        is_marked = i in widget._marked_indices
        stats = compute_mentor_stats(cs)
        hint = (jump_hints or {}).get(i)
        artifact_indicator = (artifact_indicators or {}).get(cs.name)
        cs_options[i] = format_changespec_option(
            cs,
            is_selected=(i == current_idx and current_group_key is None),
            is_marked=is_marked,
            show_hideable=show_hideable,
            show_submitted=show_submitted,
            mentor_stats=stats,
            hint_char=hint,
            artifact_indicator=artifact_indicator,
        )
        cs_widths[i] = calculate_entry_display_width(
            cs,
            is_marked=is_marked,
            show_hideable=show_hideable,
            show_submitted=show_submitted,
            mentor_stats=stats,
            hint_char=hint,
            artifact_indicator=artifact_indicator,
        )
        max_cs_width = max(max_cs_width, cs_widths[i])
        cs_signatures[i] = row_signature(
            cs,
            is_selected=(i == current_idx and current_group_key is None),
            is_marked=is_marked,
            show_hideable=show_hideable,
            show_submitted=show_submitted,
            mentor_stats=stats,
            hint_char=hint,
            artifact_indicator=artifact_indicator,
        )
        cs_render_ctx[i] = {
            "show_hideable": show_hideable,
            "show_submitted": show_submitted,
            "mentor_stats": stats,
            "artifact_indicator": artifact_indicator,
        }

    # Banner width: at least CS_MIN_BANNER_WIDTH and at least the
    # widest CL row so the rule fully spans the panel.
    banner_min = max(CS_MIN_BANNER_WIDTH, max_cs_width)
    max_banner_natural = 0
    for entry in tree:
        if entry.kind == "group" and entry.group is not None:
            banner_hint = (banner_jump_hints or {}).get(entry.group.group_key)
            max_banner_natural = max(
                max_banner_natural,
                banner_natural_width(entry.group, banner_hint),
            )
    banner_width = max(banner_min, max_banner_natural)

    # Walk the tree and emit Options.
    highlighted_row: int | None = None
    banner_seq = 0
    spacer_seq = 0
    seen_first_l0 = False
    for entry in tree:
        if entry.kind == "group" and entry.group is not None:
            group = entry.group
            if group.level == 0:
                if seen_first_l0:
                    spacer = Option(
                        Text(""),
                        id=f"cs-spacer:{spacer_seq}",
                        disabled=True,
                    )
                    spacer_seq += 1
                    widget.add_option(spacer)
                    widget._row_entries.append(_BANNER_ROW)
                seen_first_l0 = True
            selectable = group.is_collapsed
            banner_hint = (
                (banner_jump_hints or {}).get(group.group_key) if selectable else None
            )
            option = format_changespec_banner_option(
                group,
                width=banner_width,
                sequence=banner_seq,
                selectable=selectable,
                hint_char=banner_hint,
            )
            banner_seq += 1
            row_index = len(widget._row_entries)
            widget.add_option(option)
            widget._row_entries.append(_BANNER_ROW)
            if selectable:
                widget._banner_at_row[row_index] = group
                widget._banner_row_by_key[group.group_key] = row_index
                if (
                    current_group_key is not None
                    and group.group_key == current_group_key
                    and highlighted_row is None
                ):
                    highlighted_row = row_index
            continue

        if entry.changespec_idx is None:
            continue
        i = entry.changespec_idx
        row_index = len(widget._row_entries)
        widget.add_option(cs_options[i])
        widget._row_entries.append(i)
        widget._option_idx_by_changespec_name[changespecs[i].name] = i
        widget._row_widths_by_idx[i] = cs_widths[i]
        widget._last_row_signature_by_idx[i] = cs_signatures[i]
        widget._row_render_ctx[i] = cs_render_ctx[i]
        if current_group_key is None and i == current_idx:
            highlighted_row = row_index

    optimal_width = max(max_cs_width, banner_width) + _PADDING
    widget._target_width = optimal_width
    widget.post_message(widget.WidthChanged(optimal_width))

    try:
        if highlighted_row is not None:
            widget.highlighted = highlighted_row
    finally:
        widget._programmatic_update = False
