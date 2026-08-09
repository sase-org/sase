"""Banner row rendering for the Patches tab group headings.

Patch banners reuse the colors / glyphs / rules that the Agents-tab
banners use (see ``_agent_list_styling``) so the two tabs feel like the
same visual language at a glance.  L0 banners (project / date bucket /
status bucket) get the strong sky-blue bar treatment.  L1 subgroup
banners use the cooler ``▎`` / light-rule treatment, and L2 hourly
BY_DATE banners use the dim-gray ``▸`` branch glyph with a teal label.
"""

from __future__ import annotations

from rich.cells import cell_len
from rich.text import Text
from textual.widgets.option_list import Option

from sase.project_display_names import humanize_cl_name

from ..models.patch_groups import PatchGroupRow
from ._agent_list_styling import (
    _CHANGESPEC_BANNER_BAR_STYLE,
    _CHANGESPEC_BANNER_RULE_STYLE,
    _CHANGESPEC_BAR_GLYPH,
    _CHANGESPEC_RULE,
    _NAME_ROOT_BANNER_BRANCH_STYLE,
    _NAME_ROOT_BANNER_LABEL_STYLE,
    _NAME_ROOT_BRANCH_GLYPH,
    _NAME_ROOT_RULE,
    _PROJECT_BANNER_BAR_STYLE,
    _PROJECT_BANNER_RULE_STYLE,
    _PROJECT_BAR_GLYPH,
    _PROJECT_RULE,
)

#: Minimum banner rule width.  Matches the agent-list constant so the two
#: tabs render banners at the same visual weight.
CS_MIN_BANNER_WIDTH = 40

_MIN_RULE_CELLS = 2
_LABEL_RULE_GAP = " "
_RULE_CHIP_GAP = "  "


def _banner_label(group: PatchGroupRow) -> str:
    """Visible heading text for *group*."""
    if not group.group_key:
        return ""
    return humanize_cl_name(group.group_key[-1])


def _banner_chip(group: PatchGroupRow) -> str:
    """Right-aligned ``N PRs`` summary chip for *group*."""
    n = len(group.patch_indices)
    return f"{n} PR{'s' if n != 1 else ''}"


def _banner_parts(group: PatchGroupRow) -> tuple[str, str, str, str, str]:
    """Return the styled prefix/label/rule pieces for *group*."""
    if group.level == 0:
        return (
            f"{_PROJECT_BAR_GLYPH} ",
            _PROJECT_BANNER_BAR_STYLE,
            _PROJECT_BANNER_BAR_STYLE,
            _PROJECT_RULE,
            _PROJECT_BANNER_RULE_STYLE,
        )
    if group.level == 1:
        return (
            f"{_CHANGESPEC_BAR_GLYPH} ",
            _CHANGESPEC_BANNER_BAR_STYLE,
            _CHANGESPEC_BANNER_BAR_STYLE,
            _CHANGESPEC_RULE,
            _CHANGESPEC_BANNER_RULE_STYLE,
        )
    return (
        f"{_NAME_ROOT_BRANCH_GLYPH} ",
        _NAME_ROOT_BANNER_BRANCH_STYLE,
        _NAME_ROOT_BANNER_LABEL_STYLE,
        _NAME_ROOT_RULE,
        _NAME_ROOT_BANNER_BRANCH_STYLE,
    )


def _truncate_label(label: str, *, max_width: int, style: str) -> Text:
    """Return styled label text no wider than *max_width* cells."""
    if max_width <= 0:
        return Text()
    label_text = Text(label, style=style)
    label_text.truncate(max_width, overflow="ellipsis")
    return label_text


def format_patch_banner_option(
    group: PatchGroupRow,
    *,
    width: int,
    sequence: int,
    selectable: bool = False,
    hint_char: str | None = None,
) -> Option:
    """Render one Patch group banner Option.

    ``selectable=True`` is reserved for collapsed banners — Phase 4 will
    use it to keep cursor navigation on the heading row when its group
    is folded.  Expanded banners stay disabled so j/k flies through Patch rows
    rows in grouped mode just like it does in flat mode.

    ``sequence`` lets non-contiguous emissions of the same key (e.g. the
    same name root appearing under two projects) keep distinct Option
    ids; the Option id encodes ``sequence:level:key`` so OptionList can
    address each row uniquely.
    """
    key_str = "/".join(group.group_key)
    if width <= 0:
        return Option(
            Text(),
            id=f"cs_group:{sequence}:{group.level}:{key_str}",
            disabled=not selectable,
        )

    label = _banner_label(group)
    chip = _banner_chip(group)
    prefix, prefix_style, label_style, rule_char, rule_style = _banner_parts(group)

    hint_text = f"[{hint_char}] " if hint_char is not None else ""
    reserved_cells = (
        cell_len(hint_text)
        + cell_len(prefix)
        + cell_len(_LABEL_RULE_GAP)
        + _MIN_RULE_CELLS
        + cell_len(_RULE_CHIP_GAP)
        + cell_len(chip)
    )
    label_text = _truncate_label(
        label,
        max_width=max(0, width - reserved_cells),
        style=label_style,
    )
    rule_cells = max(
        _MIN_RULE_CELLS,
        width
        - (
            cell_len(hint_text)
            + cell_len(prefix)
            + label_text.cell_len
            + cell_len(_LABEL_RULE_GAP)
            + cell_len(_RULE_CHIP_GAP)
            + cell_len(chip)
        ),
    )

    text = Text()
    if hint_text:
        text.append(hint_text, style="bold #FFFF00")
    text.append(prefix, style=prefix_style)
    text.append(label_text)
    text.append(
        _LABEL_RULE_GAP + rule_char * rule_cells + _RULE_CHIP_GAP + chip,
        style=rule_style,
    )

    if text.cell_len > width:
        text.truncate(width, overflow="ellipsis")

    return Option(
        text,
        id=f"cs_group:{sequence}:{group.level}:{key_str}",
        disabled=not selectable,
    )


def banner_natural_width(group: PatchGroupRow, hint_char: str | None) -> int:
    """Lower bound on banner cell width before padding kicks in.

    Used to size banner widths so the rule has at least two ``rule_char``
    cells before the chip.  Mirrors the calculation in
    :func:`format_patch_banner_option`.
    """
    label = _banner_label(group)
    chip = _banner_chip(group)
    prefix, *_ = _banner_parts(group)
    hint_text = f"[{hint_char}] " if hint_char is not None else ""
    return (
        cell_len(hint_text)
        + cell_len(prefix)
        + cell_len(label)
        + cell_len(_LABEL_RULE_GAP)
        + _MIN_RULE_CELLS
        + cell_len(_RULE_CHIP_GAP)
        + cell_len(chip)
    )
