"""Agent tab strip overflow: tier probing and active-centered windows.

Pure helpers behind
:class:`sase.ace.tui.widgets.agent_tab_strip.AgentTabStrip`. Only public
names cross module boundaries here; the widget probe inside
:func:`tier_for_width` is imported lazily so this module stays free of
import cycles.
"""

from __future__ import annotations

from rich.cells import cell_len

from sase.core.agent_tab import AgentTabKey

from ._agent_tab_strip_model import AgentTabDescriptor, AgentTabStripTier


def tier_for_width(
    descriptors: tuple[AgentTabDescriptor, ...],
    width: int,
    *,
    active_key: AgentTabKey | None = None,
) -> AgentTabStripTier:
    """Return the richest tier whose full-list render fits *width*."""
    from ._agent_tab_strip_strip import AgentTabStrip

    if width <= 0:
        return "full"
    for tier in ("full", "compact", "micro"):
        probe = AgentTabStrip(descriptors, active_key, _probe_only=True)
        rendered_width = cell_len(probe._build_content(tier).plain)  # noqa: SLF001
        if rendered_width <= width:
            return tier  # type: ignore[return-value]
    return "micro"


def overflow_window(
    descriptors: tuple[AgentTabDescriptor, ...],
    active_key: AgentTabKey | None,
    *,
    max_visible: int,
) -> tuple[tuple[AgentTabDescriptor, ...], int, int]:
    """Return ``(visible, hidden_before, hidden_after)`` around the active tab.

    The window is active-centered: it keeps up to *max_visible* chips with
    the active tab centered when possible, pinned to an edge otherwise.
    ``max_visible`` below 1 shows the active tab alone.
    """
    if not descriptors:
        return (), 0, 0
    width = max(1, int(max_visible))
    try:
        active_idx = next(
            idx for idx, desc in enumerate(descriptors) if desc.key == active_key
        )
    except StopIteration:
        active_idx = 0
    if len(descriptors) <= width:
        return tuple(descriptors), 0, 0
    half = width // 2
    start = min(max(0, active_idx - half), len(descriptors) - width)
    end = start + width
    return tuple(descriptors[start:end]), start, len(descriptors) - end


def overflow_needs_attention(
    descriptors: tuple[AgentTabDescriptor, ...],
    visible: tuple[AgentTabDescriptor, ...],
) -> tuple[bool, bool]:
    """Return ``(prev_attention, next_attention)`` for hidden tabs."""

    def _needs(desc: AgentTabDescriptor) -> bool:
        return bool(desc.has_arrival or desc.stopped or desc.failed or desc.unread)

    visible_keys = {desc.key for desc in visible}
    prev = any(_needs(desc) for desc in descriptors if desc.key not in visible_keys)
    # Split hidden need by position relative to the visible window.
    if not visible:
        return prev, False
    first_idx = next(
        (idx for idx, desc in enumerate(descriptors) if desc.key == visible[0].key),
        0,
    )
    last_idx = next(
        (idx for idx, desc in enumerate(descriptors) if desc.key == visible[-1].key),
        len(descriptors) - 1,
    )
    prev_need = any(_needs(desc) for desc in descriptors[:first_idx])
    next_need = any(_needs(desc) for desc in descriptors[last_idx + 1 :])
    return prev_need, next_need


__all__ = [
    "overflow_needs_attention",
    "overflow_window",
    "tier_for_width",
]
