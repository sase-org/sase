"""Banner row rendering for the CLs tab group headings.

ChangeSpec banners reuse the colors / glyphs / rules that the Agents-tab
banners use (see ``_agent_list_styling``) so the two tabs feel like the
same visual language at a glance.  L0 banners (project / date bucket /
status bucket) get the strong sky-blue bar treatment; L1 sibling-root
banners (only emitted in ``BY_PROJECT``) use the dim-gray branch glyph
and teal label so they read as a secondary nesting level under the
project header.
"""

from __future__ import annotations

from rich.text import Text
from textual.widgets.option_list import Option

from ..models.changespec_groups import ChangeSpecGroupRow
from ._agent_list_styling import (
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


def _banner_label(group: ChangeSpecGroupRow) -> str:
    """Visible heading text for *group*."""
    if not group.group_key:
        return ""
    return group.group_key[-1]


def _banner_chip(group: ChangeSpecGroupRow) -> str:
    """Right-aligned ``N CLs`` summary chip for *group*."""
    n = len(group.changespec_indices)
    return f"{n} CL{'s' if n != 1 else ''}"


def format_changespec_banner_option(
    group: ChangeSpecGroupRow,
    *,
    width: int,
    sequence: int,
    selectable: bool = False,
    hint_char: str | None = None,
) -> Option:
    """Render one ChangeSpec group banner Option.

    ``selectable=True`` is reserved for collapsed banners — Phase 4 will
    use it to keep cursor navigation on the heading row when its group
    is folded.  Expanded banners stay disabled so j/k flies through CL
    rows in grouped mode just like it does in flat mode.

    ``sequence`` lets non-contiguous emissions of the same key (e.g. the
    same name root appearing under two projects) keep distinct Option
    ids; the Option id encodes ``sequence:level:key`` so OptionList can
    address each row uniquely.
    """
    label = _banner_label(group)
    chip = _banner_chip(group)

    if group.level == 0:
        prefix = f"{_PROJECT_BAR_GLYPH} "
        prefix_style = _PROJECT_BANNER_BAR_STYLE
        label_style = _PROJECT_BANNER_BAR_STYLE
        rule_char = _PROJECT_RULE
        rule_style = _PROJECT_BANNER_RULE_STYLE
    else:
        prefix = f"{_NAME_ROOT_BRANCH_GLYPH} "
        prefix_style = _NAME_ROOT_BANNER_BRANCH_STYLE
        label_style = _NAME_ROOT_BANNER_LABEL_STYLE
        rule_char = _NAME_ROOT_RULE
        rule_style = _NAME_ROOT_BANNER_BRANCH_STYLE

    text = Text()
    if hint_char is not None:
        text.append(f"[{hint_char}] ", style="bold #FFFF00")
    hint_cells = 4 if hint_char is not None else 0
    text.append(prefix, style=prefix_style)
    text.append(label, style=label_style)

    used = hint_cells + len(prefix) + len(label) + 1 + 2 + len(chip)
    pad_len = max(2, width - used)
    text.append(" " + rule_char * pad_len + "  " + chip, style=rule_style)

    key_str = "/".join(group.group_key)
    return Option(
        text,
        id=f"cs_group:{sequence}:{group.level}:{key_str}",
        disabled=not selectable,
    )


def banner_natural_width(group: ChangeSpecGroupRow, hint_char: str | None) -> int:
    """Lower bound on banner cell width before padding kicks in.

    Used to size banner widths so the rule has at least two ``rule_char``
    cells before the chip.  Mirrors the calculation in
    :func:`format_changespec_banner_option`.
    """
    label = _banner_label(group)
    chip = _banner_chip(group)
    prefix_len = 2  # bar glyph + space
    hint_cells = 4 if hint_char is not None else 0
    return hint_cells + prefix_len + len(label) + 1 + 2 + len(chip)
