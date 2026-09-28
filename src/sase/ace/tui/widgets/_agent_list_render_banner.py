"""Banner row rendering for project / Patch / bucket / name-root
group banners, plus a memoized wrapper backed by
:class:`AgentRenderCache`.
"""

from typing import Literal

from rich.cells import cell_len
from textual.widgets.option_list import Option

from ..models.agent import Agent
from ..models.agent_groups import (
    GroupingMode,
    GroupRow,
    banner_label,
    banner_summary_text,
    compute_banner_summary,
)
from ._agent_list_render_cache import AgentRenderCache, banner_render_key
from ._agent_list_render_layout import render_tier_gutter
from ._agent_list_render_rail import RAIL_BUCKET_GLYPHS
from ._agent_list_styling import (
    _PATCH_BANNER_BAR_STYLE,
    _PATCH_BANNER_RULE_STYLE,
    _PATCH_BAR_GLYPH,
    _PATCH_RULE,
    _NAME_ROOT_BANNER_BRANCH_STYLE,
    _NAME_ROOT_BANNER_LABEL_STYLE,
    _NAME_ROOT_BRANCH_GLYPH,
    _NAME_ROOT_RULE,
    _PROJECT_BANNER_BAR_STYLE,
    _PROJECT_BANNER_RULE_STYLE,
    _PROJECT_BAR_GLYPH,
    _PROJECT_RULE,
    _TIER_GUIDE_SEGMENT_WIDTH,
)

BannerMarkState = Literal["none", "partial", "all"]


def format_banner_option(
    group: GroupRow,
    agents: list[Agent],
    *,
    width: int,
    sequence: int,
    selectable: bool = False,
    mode: GroupingMode = GroupingMode.STANDARD,
    tier_styles: tuple[str, ...] = (),
    hint_char: str | None = None,
    mark_state: BannerMarkState = "none",
) -> Option:
    """Render a group banner row Option.

    All levels share the shape ``<gutter><prefix> <label> <rule…>  <chip>``
    with the chip right-aligned to ``width`` so banner chips line up with
    the runtime suffix column on agent rows.  ``tier_styles`` injects the
    leading tier-guide gutter (one ``│  `` segment per ancestor L0/L1
    banner).  Glyphs and colors differ by grouping mode:

    - STANDARD L0 (project): bold sky-blue ``▌`` bar + label, dim sky-blue
      heavy rule ``━`` and chip.
    - STANDARD L1 (Patch, 3-level mode), BY_DATE L1 subgroup
      banners (1-hour ``HH:00``, calendar day, week range), and
      name-root banners that own dotted-name prefix subgroups: cooler
      accent + ``▎`` bar, light rule ``─``.
    - BY_DATE L0 (date bucket): bold sky-blue label + heavy rule, no
      project bar — the bucket name is the visual anchor.
    - BY_STATUS L0 (status bucket): leading rail bucket glyph (``?`` for
      ``Stopped``) in its rail style + bold sky-blue label + heavy rule.
    - BY_MACHINE L1 (status subgroup): ``▎`` bar + rail bucket glyph (e.g.
      ``▎ ▶ Running``) in its rail style + label, light rule ``─`` —
      always the middle-tier register, even when the subgroup has no
      name-root children.
    - L1/L2/L3 (name-root) in any mode: dim-gray ``▸`` branch glyph, teal
      label, dim-gray light rule ``─`` and chip.

    Banner Options are marked ``disabled`` while expanded so OptionList
    cursor navigation skips those headings. Collapsed banners remain in
    the cursor flow as selectable rows.
    """
    label = banner_label(group)
    summary = compute_banner_summary(group, agents, mode=mode)
    chip = banner_summary_text(summary)

    # Only STANDARD mode uses agents' Patch names for banner rows;
    # BY_DATE / BY_STATUS collapse the project + Patch layers into
    # the bucket.  BY_DATE's real L1 time windows still reuse the same
    # visual register as STANDARD Patch banners.
    panel_uses_patch = mode is GroupingMode.STANDARD and any(a.cl_name for a in agents)
    is_patch_banner = (
        group.level == 1 and panel_uses_patch and len(group.group_key) == 2
    )
    is_middle_tier_banner = (
        is_patch_banner
        or (group.level == 1 and mode is GroupingMode.BY_DATE)
        or (group.level == 1 and mode is GroupingMode.BY_MACHINE)
        or (group.level > 0 and group.has_child_groups)
    )
    if group.level == 0 and mode is GroupingMode.STANDARD:
        prefix = f"{_PROJECT_BAR_GLYPH} "
        rule_char = _PROJECT_RULE
        prefix_style = _PROJECT_BANNER_BAR_STYLE
        label_style = _PROJECT_BANNER_BAR_STYLE
        rule_style = _PROJECT_BANNER_RULE_STYLE
    elif group.level == 0:
        # Bucket banner (BY_DATE / BY_STATUS): drop the project bar so the
        # bucket name leads.  In BY_STATUS mode, prepend the rail bucket
        # glyph in its rail style so both densities share one language.
        if mode is GroupingMode.BY_STATUS and label in RAIL_BUCKET_GLYPHS:
            glyph, glyph_style = RAIL_BUCKET_GLYPHS[label]
            prefix = f"{glyph} "
            prefix_style = glyph_style
        else:
            prefix = ""
            prefix_style = _PROJECT_BANNER_BAR_STYLE
        rule_char = _PROJECT_RULE
        label_style = _PROJECT_BANNER_BAR_STYLE
        rule_style = _PROJECT_BANNER_RULE_STYLE
    elif is_middle_tier_banner:
        prefix = f"{_PATCH_BAR_GLYPH} "
        rule_char = _PATCH_RULE
        prefix_style = _PATCH_BANNER_BAR_STYLE
        label_style = _PATCH_BANNER_BAR_STYLE
        rule_style = _PATCH_BANNER_RULE_STYLE
    else:
        prefix = f"{_NAME_ROOT_BRANCH_GLYPH} "
        rule_char = _NAME_ROOT_RULE
        prefix_style = _NAME_ROOT_BANNER_BRANCH_STYLE
        label_style = _NAME_ROOT_BANNER_LABEL_STYLE
        rule_style = _NAME_ROOT_BANNER_BRANCH_STYLE

    # Status subgroup banners (BY_MACHINE L1) insert the bucket's rail
    # glyph between the ``▎`` bar and the label, echoing the glyphs
    # BY_STATUS L0 banners already use.  Each glyph carries its own rail
    # style; the bar keeps the middle-tier accent.
    prefix_segments: list[tuple[str, str]] = [(prefix, prefix_style)]
    if (
        group.level == 1
        and mode is GroupingMode.BY_MACHINE
        and label in RAIL_BUCKET_GLYPHS
    ):
        glyph, glyph_style = RAIL_BUCKET_GLYPHS[label]
        prefix_segments = [(prefix, prefix_style), (f"{glyph} ", glyph_style)]
        prefix = f"{prefix}{glyph} "

    text = render_tier_gutter(tier_styles)
    gutter_cells = len(tier_styles) * _TIER_GUIDE_SEGMENT_WIDTH
    hint_cells = 0
    if hint_char is not None:
        hint_text = f"[{hint_char}] "
        text.append(hint_text, style="bold #FFFF00")
        hint_cells = cell_len(hint_text)
    mark_cells = 0
    if mark_state == "all":
        mark_text = "[✓] "
        text.append(mark_text, style="bold #00D700")
        mark_cells = cell_len(mark_text)
    elif mark_state == "partial":
        mark_text = "[~] "
        text.append(mark_text, style="dim #00D700")
        mark_cells = cell_len(mark_text)
    for segment_text, segment_style in prefix_segments:
        text.append(segment_text, style=segment_style)
    text.append(label, style=label_style)
    if chip:
        # ``<gutter><hint><prefix><label> <rule…>  <chip>``: 1-cell gap
        # before the rule, 2-cell gap before the chip.  Widths are terminal
        # cells (``cell_len``), not Python characters, so double-width
        # label or chip text still right-aligns the chip.
        used = (
            gutter_cells
            + hint_cells
            + mark_cells
            + cell_len(prefix)
            + cell_len(label)
            + 1
            + 2
            + cell_len(chip)
        )
        pad_len = max(2, width - used)
        text.append(
            " " + rule_char * pad_len + "  " + chip,
            style=rule_style,
        )
    else:
        used = (
            gutter_cells
            + hint_cells
            + mark_cells
            + cell_len(prefix)
            + cell_len(label)
            + 1
        )
        pad_len = max(2, width - used)
        text.append(" " + rule_char * pad_len, style=rule_style)

    # Sequence-prefixed id keeps banner Options unique even when the
    # same group key is split into multiple non-contiguous clusters.
    key_str = "/".join(group.group_key)
    return Option(
        text,
        id=f"group:{sequence}:{group.level}:{key_str}",
        disabled=not selectable,
    )


def cached_format_banner_option(
    cache: AgentRenderCache,
    group: GroupRow,
    agents: list[Agent],
    *,
    width: int,
    sequence: int,
    selectable: bool = False,
    mode: GroupingMode = GroupingMode.STANDARD,
    tier_styles: tuple[str, ...] = (),
    hint_char: str | None = None,
    mark_state: BannerMarkState = "none",
) -> Option:
    """Memoized wrapper for :func:`format_banner_option`."""
    key = banner_render_key(
        group,
        agents,
        width=width,
        sequence=sequence,
        selectable=selectable,
        mode=mode,
        tier_styles=tier_styles,
        hint_char=hint_char,
        mark_state=mark_state,
    )
    hit = cache.get_banner(key)
    if hit is not None:
        return hit
    option = format_banner_option(
        group,
        agents,
        width=width,
        sequence=sequence,
        selectable=selectable,
        mode=mode,
        tier_styles=tier_styles,
        hint_char=hint_char,
        mark_state=mark_state,
    )
    cache.put_banner(key, option)
    return option
