"""Banner row rendering for project / ChangeSpec / bucket / name-root
group banners, plus a memoized wrapper backed by
:class:`AgentRenderCache`.
"""

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
    _STATUS_BUCKET_GLYPHS,
    _TIER_GUIDE_SEGMENT_WIDTH,
)


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
) -> Option:
    """Render a group banner row Option.

    Both levels share the shape ``<gutter><prefix> <label> <rule…>  <chip>``
    with the chip right-aligned to ``width`` so banner chips line up with
    the runtime suffix column on agent rows.  ``tier_styles`` injects the
    leading tier-guide gutter (one ``│  `` segment per ancestor L0/L1
    banner).  Glyphs and colors differ by grouping mode:

    - STANDARD L0 (project): bold sky-blue ``▌`` bar + label, dim sky-blue
      heavy rule ``━`` and chip.
    - STANDARD L1 (ChangeSpec, 3-level mode): cooler accent + ``▎`` bar,
      light rule ``─``.
    - BY_DATE L0 (date bucket): bold sky-blue label + heavy rule, no
      project bar — the bucket name is the visual anchor.
    - BY_STATUS L0 (status bucket): leading status glyph (``▲`` for
      ``Needs Attention``) + bold sky-blue label + heavy rule.
    - L1/L2 (name-root) in any mode: dim-gray ``▸`` branch glyph, teal
      label, dim-gray light rule ``─`` and chip.

    Banner Options are marked ``disabled`` so OptionList cursor
    navigation skips them at full expansion.  When *selectable* is True
    (fold level < max) the banner stays in the cursor flow.
    """
    label = banner_label(group)
    summary = compute_banner_summary(group, agents)
    chip = banner_summary_text(summary)

    # Only STANDARD mode uses the ChangeSpec banner row; BY_DATE / BY_STATUS
    # collapse the project + ChangeSpec layers into the bucket so any L1
    # banner there is a name-root banner regardless of agents' cl_name.
    panel_uses_changespec = mode is GroupingMode.STANDARD and any(
        a.cl_name for a in agents
    )
    is_changespec_banner = (
        group.level == 1 and panel_uses_changespec and len(group.group_key) == 2
    )
    if group.level == 0 and mode is GroupingMode.STANDARD:
        prefix = f"{_PROJECT_BAR_GLYPH} "
        rule_char = _PROJECT_RULE
        prefix_style = _PROJECT_BANNER_BAR_STYLE
        label_style = _PROJECT_BANNER_BAR_STYLE
        rule_style = _PROJECT_BANNER_RULE_STYLE
    elif group.level == 0:
        # Bucket banner (BY_DATE / BY_STATUS): drop the project bar so the
        # bucket name leads.  In BY_STATUS mode, prepend a status glyph
        # that signals the bucket's semantics at a glance.
        if mode is GroupingMode.BY_STATUS and label in _STATUS_BUCKET_GLYPHS:
            prefix = f"{_STATUS_BUCKET_GLYPHS[label]} "
        else:
            prefix = ""
        rule_char = _PROJECT_RULE
        prefix_style = _PROJECT_BANNER_BAR_STYLE
        label_style = _PROJECT_BANNER_BAR_STYLE
        rule_style = _PROJECT_BANNER_RULE_STYLE
    elif is_changespec_banner:
        prefix = f"{_CHANGESPEC_BAR_GLYPH} "
        rule_char = _CHANGESPEC_RULE
        prefix_style = _CHANGESPEC_BANNER_BAR_STYLE
        label_style = _CHANGESPEC_BANNER_BAR_STYLE
        rule_style = _CHANGESPEC_BANNER_RULE_STYLE
    else:
        prefix = f"{_NAME_ROOT_BRANCH_GLYPH} "
        rule_char = _NAME_ROOT_RULE
        prefix_style = _NAME_ROOT_BANNER_BRANCH_STYLE
        label_style = _NAME_ROOT_BANNER_LABEL_STYLE
        rule_style = _NAME_ROOT_BANNER_BRANCH_STYLE

    text = render_tier_gutter(tier_styles)
    gutter_cells = len(tier_styles) * _TIER_GUIDE_SEGMENT_WIDTH
    if hint_char is not None:
        text.append(f"[{hint_char}] ", style="bold #FFFF00")
    hint_cells = 4 if hint_char is not None else 0
    text.append(prefix, style=prefix_style)
    text.append(label, style=label_style)
    if chip:
        # ``<gutter><hint><prefix><label> <rule…>  <chip>``: 1-cell gap
        # before the rule, 2-cell gap before the chip.
        used = gutter_cells + hint_cells + len(prefix) + len(label) + 1 + 2 + len(chip)
        pad_len = max(2, width - used)
        text.append(
            " " + rule_char * pad_len + "  " + chip,
            style=rule_style,
        )
    else:
        used = gutter_cells + hint_cells + len(prefix) + len(label) + 1
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
    )
    cache.put_banner(key, option)
    return option
