"""Beautiful agent tab strip: descriptors, accents, tiers, and overflow.

Built on :class:`PanelTabStrip` behavior (terminal-cell click ranges,
resize reflow, tooltip plumbing). An immutable
:class:`AgentTabDescriptor` carries everything one chip renders; pure
helpers project descriptors, pick tiers, and slice the active-centered
overflow window so behavior tests never need a Textual pilot.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from rich.cells import cell_len
from rich.text import Text
from textual.events import Click, Resize

from sase.core.agent_tab import AgentTabKey
from sase.palette_hash import hash_palette_index
from sase.project_accents import PROJECT_ACCENTS, project_accent

from .panel_tab_strip import PanelTabStrip

MACHINE_GLYPH = "\u2328"
ARRIVAL_DOT = "\u2022"
ACTIVE_PILL_LEFT = "\u2590"
ACTIVE_PILL_RIGHT = "\u258c"
KIND_DIVIDER = "\u250a"
TAB_SEPARATOR = " \u2502 "
OVERFLOW_PREV_ID = "__overflow_prev__"
OVERFLOW_NEXT_ID = "__overflow_next__"

MACHINE_GLYPH_STYLE = "#5FD7FF"
MAIN_LABEL_STYLE = "#AFAFAF"
NEUTRAL_COUNT_STYLE = "#AFAFAF"
SEPARATOR_STYLE = "#444444"
ACTIVE_TEXT_STYLE = "bold #1C1C1C"
STALE_LABEL_STYLE = "bold #FFAF00"
INVALID_LABEL_STYLE = "bold #FF5F5F"
ATTENTION_STYLES = {
    "stopped": "bold #FFAF00",
    "failed": "bold #FF5F5F",
    "unread": "bold #1a1a1a on #FFD700",
}

AgentTabStripTier = Literal["full", "compact", "micro"]
AgentTabHealth = Literal["ok", "stale", "invalid", "offline"]
AgentTabEmptyKind = Literal["empty", "query_hides", "feed_unavailable"]


@dataclass(frozen=True, slots=True)
class AgentTabDescriptor:
    """Immutable render model for one agent tab chip."""

    key: AgentTabKey
    label: str
    glyph: str = ""
    accent: str = MAIN_LABEL_STYLE
    count: int = 0
    incomplete: bool = False
    stopped: int = 0
    failed: int = 0
    unread: int = 0
    health: AgentTabHealth = "ok"
    has_arrival: bool = False
    description: str = ""
    jump_hint: str | None = None
    machine_alias: str = ""
    is_default: bool = False


def agent_tab_accent_for_name(
    name: str,
    *,
    config_color: str = "",
    enabled_projects: tuple[str, ...] = (),
) -> str:
    """Return the accent for named tab *name*.

    Configured ``ace.agent_tabs.tabs.<name>.color`` wins. An enabled
    project key reuses ``project_accent`` so ``sase`` matches ``+sase``.
    Anything else hashes into the established project palette.
    """
    cleaned = (config_color or "").strip()
    if cleaned:
        return cleaned
    lowered = name.casefold()
    for project_key in enabled_projects:
        if project_key.casefold() == lowered:
            return project_accent(project_key, among=enabled_projects)
    return PROJECT_ACCENTS[hash_palette_index(name, len(PROJECT_ACCENTS))]


def agent_tab_label_style(descriptor: AgentTabDescriptor) -> str:
    """Return the label style for *descriptor* honoring machine health."""
    if descriptor.is_default:
        return MAIN_LABEL_STYLE
    if descriptor.glyph == MACHINE_GLYPH:
        if descriptor.health in ("invalid", "offline"):
            return INVALID_LABEL_STYLE
        if descriptor.health == "stale":
            return STALE_LABEL_STYLE
        return descriptor.accent or MACHINE_GLYPH_STYLE
    return descriptor.accent or MAIN_LABEL_STYLE


def _agent_tab_tooltip(descriptor: AgentTabDescriptor) -> str:
    """Return the hover tooltip for *descriptor*."""
    if descriptor.description:
        return descriptor.description
    parts = [descriptor.label]
    if descriptor.machine_alias:
        parts.append(f"({descriptor.machine_alias})")
    parts.append(f"{descriptor.count} agents")
    if descriptor.stopped:
        parts.append(f"S{descriptor.stopped}")
    if descriptor.failed:
        parts.append(f"F{descriptor.failed}")
    if descriptor.unread:
        parts.append(f"U{descriptor.unread}")
    return " \u00b7 ".join(parts)


def _tier_for_width(
    descriptors: tuple[AgentTabDescriptor, ...],
    width: int,
    *,
    active_key: AgentTabKey | None = None,
) -> AgentTabStripTier:
    """Return the richest tier whose full-list render fits *width*."""
    if width <= 0:
        return "full"
    for tier in ("full", "compact", "micro"):
        probe = AgentTabStrip(descriptors, active_key, _probe_only=True)
        rendered_width = cell_len(probe._build_content(tier).plain)  # noqa: SLF001
        if rendered_width <= width:
            return tier  # type: ignore[return-value]
    return "micro"


def _overflow_window(
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


def _overflow_needs_attention(
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


@dataclass(frozen=True, slots=True)
class AgentTabEmptyState:
    """One of the three visible empty causes for the active tab."""

    kind: AgentTabEmptyKind
    title: str
    detail: str = ""


def agent_tab_empty_state(
    *,
    scoped_count: int,
    tab_has_roots: bool,
    query: str = "",
    matches_elsewhere: int = 0,
    feed_unavailable: bool = False,
    tab_label: str = "this tab",
) -> AgentTabEmptyState | None:
    """Return the empty cause for the active tab, or None when not empty."""
    if scoped_count > 0:
        return None
    if feed_unavailable:
        return AgentTabEmptyState(
            kind="feed_unavailable",
            title=f"No feed for {tab_label}",
            detail="The feed is unavailable \u2014 open Admin Center \u2192 Machines.",
        )
    if (query or "").strip() and (tab_has_roots or matches_elsewhere > 0):
        detail = f"The query hides them ({matches_elsewhere} matches elsewhere)"
        if (query or "").strip():
            detail += " \u2014 clear the filter to see this tab."
        return AgentTabEmptyState(
            kind="query_hides",
            title=f"No visible agents on {tab_label}",
            detail=detail,
        )
    return AgentTabEmptyState(
        kind="empty",
        title=f"No agents on {tab_label}",
        detail="",
    )


class AgentTabStrip(PanelTabStrip):
    """Clickable agent tab strip with pills, badges, tiers, and overflow."""

    class PickerRequested(PanelTabStrip.TabClicked):
        """Message emitted when an overflow chip requests the tab picker."""

        def __init__(self, direction: str) -> None:
            super().__init__(
                OVERFLOW_PREV_ID if direction == "prev" else OVERFLOW_NEXT_ID
            )
            self.direction = direction

    def __init__(
        self,
        descriptors: tuple[AgentTabDescriptor, ...] | list[AgentTabDescriptor] = (),
        active_key: AgentTabKey | None = None,
        *,
        _probe_only: bool = False,
        **kwargs: Any,
    ) -> None:
        self._descriptors = tuple(descriptors)
        self._active_key = active_key
        self._visible_descriptors = tuple(descriptors)
        self._overflow_before = 0
        self._overflow_after = 0
        self._overflow_prev_attention = False
        self._overflow_next_attention = False
        self._resolved_width: int | None = None
        # PanelTabStrip.__init__ renders immediately via _build_content, so
        # descriptor state must exist before super().__init__ runs. The base
        # constructor already renders once; no extra update here (it needs an
        # active app, which unit probes do not have).
        if "id" not in kwargs and not _probe_only:
            kwargs["id"] = "agents-tab-strip"
        super().__init__([], None, **kwargs)

    def set_descriptors(
        self,
        descriptors: tuple[AgentTabDescriptor, ...] | list[AgentTabDescriptor],
        active_key: AgentTabKey | None,
    ) -> None:
        """Replace rendered descriptors and refresh."""
        self._descriptors = tuple(descriptors)
        self._active_key = active_key
        self.update(self._build_content())

    def visible_descriptors(self) -> tuple[AgentTabDescriptor, ...]:
        """Return the currently rendered descriptor window."""
        return tuple(getattr(self, "_visible_descriptors", self._descriptors))

    def _chip_parts(
        self,
        descriptor: AgentTabDescriptor,
        *,
        is_active: bool,
        tier: str,
        pill_style: str | None = None,
    ) -> list[tuple[str, str | None]]:
        """Return ``(fragment, style)`` parts for one chip.

        The concatenated fragments equal :meth:`_chip_text`'s plain text;
        styles give the glyph, label, count, and badges their contract
        colors. With *pill_style* every fragment shares the active pill
        body style.
        """
        label_style = agent_tab_label_style(descriptor)
        glyph_style = MACHINE_GLYPH_STYLE if descriptor.glyph else label_style
        count_text = (
            f"{descriptor.count}+" if descriptor.incomplete else str(descriptor.count)
        )
        attention: list[tuple[str, str]] = []
        if descriptor.stopped:
            attention.append((f"S{descriptor.stopped}", ATTENTION_STYLES["stopped"]))
        if descriptor.failed:
            attention.append((f"F{descriptor.failed}", ATTENTION_STYLES["failed"]))
        if tier == "full" and descriptor.unread:
            attention.append((f"U{descriptor.unread}", ATTENTION_STYLES["unread"]))
        if tier == "compact" and is_active and descriptor.unread:
            attention.append((f"U{descriptor.unread}", ATTENTION_STYLES["unread"]))
        arrival = descriptor.has_arrival and not is_active
        body: list[tuple[str, str | None]] = []

        def _emit(fragment: str, style: str | None) -> None:
            body.append((fragment, pill_style if pill_style else style))

        if tier == "micro":
            short = (
                descriptor.glyph or (descriptor.label[:3] or descriptor.label) or "tab"
            )
            if attention and not is_active:
                short_style: str | None = attention[0][1]
            else:
                short_style = glyph_style if descriptor.glyph else label_style
            _emit(short, short_style)
            for token, style in attention:
                _emit(f" {token}", style)
            if arrival:
                _emit(f" {ARRIVAL_DOT}", label_style)
            return body
        glyph_prefix = f"{descriptor.glyph} " if descriptor.glyph else ""
        if tier == "compact" and not is_active:
            if glyph_prefix:
                _emit(glyph_prefix, glyph_style)
            _emit(descriptor.label, label_style)
            for token, style in attention:
                _emit(f" {token}", style)
            if arrival:
                _emit(f" {ARRIVAL_DOT}", label_style)
            return body
        if glyph_prefix:
            _emit(glyph_prefix, glyph_style)
        _emit(descriptor.label, label_style)
        _emit(f" {count_text}", NEUTRAL_COUNT_STYLE)
        for token, style in attention:
            _emit(f" {token}", style)
        if arrival:
            _emit(f" {ARRIVAL_DOT}", label_style)
        if pill_style:
            return [
                (" " + frag if idx == 0 else frag, style)
                for idx, (frag, style) in enumerate(body)
            ] + [(" ", pill_style)]
        return body

    def _append_chip_fragments(
        self,
        append: Any,
        descriptor: AgentTabDescriptor,
        *,
        is_active: bool,
        tier: str,
        pill_style: str | None = None,
    ) -> None:
        """Append one chip's styled fragments via *append*."""
        for fragment, style in self._chip_parts(
            descriptor, is_active=is_active, tier=tier, pill_style=pill_style
        ):
            append(fragment, style)

    def _chip_text(
        self,
        descriptor: AgentTabDescriptor,
        *,
        is_active: bool,
        tier: str,
    ) -> tuple[str, list[tuple[str, str]]]:
        """Return ``(plain, styled_parts)`` for one chip (tests use plain)."""
        parts = self._chip_parts(descriptor, is_active=is_active, tier=tier)
        return "".join(frag for frag, _ in parts), [
            (frag, style or "") for frag, style in parts
        ]

    def _build_content(self, tier: str | None = None) -> Text:
        active_tier: str = self._tier if tier is None else tier
        text = Text()
        tab_ranges: dict[str, tuple[int, int]] = {}
        column = 0

        def append(fragment: str, style: str | None = None) -> None:
            nonlocal column
            text.append(fragment, style=style)
            column += cell_len(fragment)

        descriptors = self._descriptors
        visible = descriptors
        before = 0
        after = 0
        render_tier = active_tier
        # Tiers come first: the richest tier that fits the laid-out width
        # wins. Past micro an active-centered overflow window takes over.
        # Probes pass an explicit tier and must not mutate window state.
        mutate_window = tier is None
        if mutate_window:
            laid_out = self._available_tab_width()
            if laid_out > 0 and descriptors:
                render_tier = _tier_for_width(
                    descriptors, laid_out, active_key=self._active_key
                )
                self._tier = render_tier  # type: ignore[assignment]
                probe = AgentTabStrip(descriptors, self._active_key, _probe_only=True)
                micro_width = cell_len(
                    probe._build_content("micro").plain  # noqa: SLF001
                )
                # Reserve room for two overflow chips plus separators.
                if micro_width > laid_out:
                    render_tier = "micro"
                    self._tier = render_tier  # type: ignore[assignment]
                    window_size = max(1, len(descriptors) - 1)
                    while window_size > 1:
                        candidate, b, a = _overflow_window(
                            descriptors, self._active_key, max_visible=window_size
                        )
                        candidate_probe = AgentTabStrip(
                            candidate, self._active_key, _probe_only=True
                        )
                        needed = cell_len(
                            candidate_probe._build_content("micro").plain  # noqa: SLF001
                        )
                        if needed + 8 <= laid_out:
                            visible, before, after = candidate, b, a
                            break
                        window_size -= 1
                    else:
                        visible, before, after = _overflow_window(
                            descriptors, self._active_key, max_visible=1
                        )
                else:
                    visible, before, after = descriptors, 0, 0
            self._overflow_before = before
            self._overflow_after = after
            self._visible_descriptors = tuple(visible)
            prev_need, next_need = _overflow_needs_attention(descriptors, visible)
            self._overflow_prev_attention = prev_need
            self._overflow_next_attention = next_need
            active_tier = render_tier
        else:
            before = self._overflow_before
            after = self._overflow_after
            if before or after:
                visible, _, _ = _overflow_window(
                    descriptors,
                    self._active_key,
                    max_visible=max(1, len(descriptors) - before - after),
                )

        if before:
            start = column
            chip = f"\u2039{before}"
            style = "#FFAF00" if self._overflow_prev_attention else SEPARATOR_STYLE
            append(chip, style)
            tab_ranges[OVERFLOW_PREV_ID] = (start, column)
            append(" ", None)

        kind_divider_shown = False
        for index, descriptor in enumerate(visible):
            if index > 0:
                # The contract's kind divider separates machine tabs from
                # named tabs; every other boundary is the neutral separator.
                prev = visible[index - 1]
                prev_machine = bool(prev.glyph == MACHINE_GLYPH or prev.is_default)
                cur_machine = bool(
                    descriptor.glyph == MACHINE_GLYPH or descriptor.is_default
                )
                if prev_machine != cur_machine and not kind_divider_shown:
                    append(f" {KIND_DIVIDER} ", SEPARATOR_STYLE)
                    kind_divider_shown = True
                else:
                    append(TAB_SEPARATOR, SEPARATOR_STYLE)
            is_active = descriptor.key == self._active_key
            start = column
            if descriptor.jump_hint:
                append(f"[{descriptor.jump_hint}] ", "bold #FFFF00")
            if is_active:
                accent = descriptor.accent or MAIN_LABEL_STYLE
                if descriptor.is_default:
                    accent = MAIN_LABEL_STYLE
                append(ACTIVE_PILL_LEFT, accent)
                self._append_chip_fragments(
                    append,
                    descriptor,
                    is_active=True,
                    tier=active_tier,
                    pill_style=f"{ACTIVE_TEXT_STYLE} on {accent}",
                )
                append(ACTIVE_PILL_RIGHT, accent)
            else:
                self._append_chip_fragments(
                    append,
                    descriptor,
                    is_active=False,
                    tier=active_tier,
                )
            strip_id = _strip_id(descriptor.key)
            assert strip_id is not None
            tab_ranges[strip_id] = (start, column)

        if after:
            append(" ", None)
            start = column
            chip = f"{after}\u203a"
            style = "#FFAF00" if self._overflow_next_attention else SEPARATOR_STYLE
            append(chip, style)
            tab_ranges[OVERFLOW_NEXT_ID] = (start, column)

        self._tab_ranges = tab_ranges
        self._line_width = column
        return text

    def _in_agents_header(self) -> bool:
        """Return True when mounted beside the fleet-status sibling."""
        try:
            from textual.widgets import Static

            parent = self.parent
            if parent is None:
                return False
            parent.query_one("#agents-fleet-status", Static)
            return True
        except Exception:  # noqa: BLE001 - probes and bare pilots are not.
            return False

    def _status_reserved_width(self) -> int:
        """Return the header cells reserved for the fleet-status sibling.

        The strip is capped at the header width, but the row's right side
        belongs to the health/diagnostic text: reserve its measured width
        plus a gap so the overflow window leaves it room. Zero when the
        sibling is empty or unreachable (pre-mount probes).
        """
        try:
            from textual.widgets import Static

            parent = self.parent
            if parent is None:
                return 0
            status = parent.query_one("#agents-fleet-status", Static)
            rendered = status.render()
            plain = rendered.plain if isinstance(rendered, Text) else str(rendered)
            if not plain.strip():
                return 0
            return cell_len(plain) + 2
        except Exception:  # noqa: BLE001 - probes and bare pilots reserve nothing.
            return 0

    def _available_tab_width(self) -> int:
        """Return the cells available for tabs.

        Inside ``#agents-header`` (full row width) the header width minus
        padding and the status reservation wins: the content-sized strip's
        own width only ever mirrors what was last rendered, so measuring
        tiers against it collapses to compact. Anywhere else (pilot
        harnesses, probes) the laid-out or resize width applies.
        """
        try:
            parent = self.parent
            if parent is not None and self._in_agents_header():
                size = getattr(parent, "size", None)
                header_width = int(getattr(size, "width", 0) or 0)
                if header_width > 0:
                    return max(0, header_width - 2 - self._status_reserved_width())
        except Exception:  # noqa: BLE001 - fall through to the own width.
            pass
        if self._resolved_width:
            return max(0, self._resolved_width - self._status_reserved_width())
        try:
            return max(0, int(self.size.width) - self._status_reserved_width())
        except Exception:  # noqa: BLE001 - pre-mount probes have no size.
            return 0

    def _tab_id_at(self, x: int) -> str | None:
        """Return the tab id under cell offset ``x``.

        Chips render left-aligned (tabs sit on the row's left), so unlike
        the centered modal strips there is no center-pad compensation.
        """
        for tab_id, (start, end) in self._tab_ranges.items():
            if start <= x < end:
                return tab_id
        return None

    def on_resize(self, event: Resize) -> None:  # type: ignore[override]
        """Reflow tiers and the overflow window from the new width."""
        try:
            self._resolved_width = int(event.size.width)
        except Exception:  # noqa: BLE001
            self._resolved_width = None
        try:
            self.update(self._build_content())
        except Exception:  # noqa: BLE001 - pre-mount resizes have no app.
            pass
        finally:
            self._resolved_width = None

    def on_click(self, event: Click) -> None:  # type: ignore[override]
        """Post tab or picker messages for chip clicks."""
        tab_id = self._tab_id_at(event.x)
        if tab_id is None:
            return
        if tab_id in (OVERFLOW_PREV_ID, OVERFLOW_NEXT_ID):
            self.post_message(
                self.PickerRequested("prev" if tab_id == OVERFLOW_PREV_ID else "next")
            )
            return
        if tab_id != (
            _strip_id(self._active_key) if self._active_key is not None else None
        ):
            self.post_message(self.TabClicked(tab_id))

    def on_mouse_move(self, event: Any) -> None:  # type: ignore[override]
        """Show the hovered tab's tooltip."""
        try:
            from textual.events import MouseMove  # noqa: F401
        except Exception:  # noqa: BLE001
            return
        tab_id = self._tab_id_at(getattr(event, "x", -1))
        if tab_id in (None, OVERFLOW_PREV_ID, OVERFLOW_NEXT_ID):
            self.tooltip = "Show all tabs" if tab_id is not None else None
            return
        for descriptor in self._descriptors:
            if _strip_id(descriptor.key) == tab_id:
                self.tooltip = _agent_tab_tooltip(descriptor) or None
                return
        self.tooltip = None


def _strip_id(key: AgentTabKey | None) -> str | None:
    """Return the strip id for *key* (tokens, like the minimal strip)."""
    if key is None:
        return None
    from sase.core.agent_tab import agent_tab_key_token

    token = agent_tab_key_token(key)
    if token is not None:
        return token
    return f"unresolved:{key.value}"


__all__ = [
    "ACTIVE_PILL_LEFT",
    "ACTIVE_PILL_RIGHT",
    "ARRIVAL_DOT",
    "KIND_DIVIDER",
    "MACHINE_GLYPH",
    "OVERFLOW_NEXT_ID",
    "OVERFLOW_PREV_ID",
    "AgentTabDescriptor",
    "AgentTabEmptyState",
    "AgentTabStrip",
    "agent_tab_accent_for_name",
    "agent_tab_empty_state",
    "agent_tab_label_style",
]
