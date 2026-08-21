"""Presentation widgets and rich text for the Admin Center home page."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.events import Click, Resize
from textual.widgets import Static

from ..keymaps import key_display_name
from .config_center_catalog import (
    _TAB_BY_ID,
    _TAB_SPECS,
    CenterTab,
    CenterTabSpec,
    config_tab_description,
)

_HOME_ID = "admin-center-home"
_HOME_LEAD = "Choose a section"
_HOME_ORIENTATION = "Configure, observe, and maintain SASE from one place."


def _home_hint_nav(tab_count: int, *, compact: bool) -> str:
    """Return the landing navigation hint for ``tab_count`` working sections."""
    if compact:
        return f"1-{tab_count}/click · Tab cycle · q/Esc close"
    return f"1-{tab_count} or click a section · Tab/Shift+Tab cycle · q/Esc close"


_HOME_LABEL_WIDTH = max(len(spec.label) for spec in _TAB_SPECS)
_HOME_DESCRIPTION_WIDTH = max(len(spec.description) for spec in _TAB_SPECS)
_HOME_ROOMY_ROW_WIDTH = 3 + 2 + _HOME_LABEL_WIDTH + 1 + _HOME_DESCRIPTION_WIDTH
_HOME_COMPACT_ROW_WIDTH = 1 + 2 + _HOME_LABEL_WIDTH + 1 + _HOME_DESCRIPTION_WIDTH
_HOME_COMPACT_BELOW_WIDTH = 96
_HOME_COMPACT_BELOW_HEIGHT = 14
_TITLE_LABEL = "SASE Admin Center"
_TITLE_TEXT = _TITLE_LABEL
_HEADER_DIVIDER_RULE = "─"
_TITLE_RULE_CHAR = "━"
_TITLE_UNDERLINE = _TITLE_RULE_CHAR * len(_TITLE_TEXT)
# Aurora accent gradient (aqua -> cyan -> sky -> indigo -> violet) swept
# across the Admin Center header title and its rule. The first stop doubles as
# the panel border color in styles.tcss.
_TITLE_GRADIENT: tuple[str, ...] = (
    "#2BE7C7",
    "#36CFEC",
    "#4FB6FF",
    "#7E8BFF",
    "#B98CFF",
)


def _gradient_color(stops: tuple[str, ...], position: float) -> str:
    """Sample a left-to-right gradient of hex ``stops`` at ``position``."""
    if position <= 0.0:
        return stops[0]
    if position >= 1.0:
        return stops[-1]
    span = position * (len(stops) - 1)
    index = int(span)
    local = span - index
    start, end = stops[index], stops[index + 1]
    channels = (
        round(
            int(start[i : i + 2], 16)
            + (int(end[i : i + 2], 16) - int(start[i : i + 2], 16)) * local
        )
        for i in (1, 3, 5)
    )
    return "#" + "".join(f"{value:02X}" for value in channels)


def gradient_text(content: str, *, bold: bool) -> Text:
    """Render ``content`` with a per-character aurora sweep."""
    text = Text()
    divisor = max(1, len(content) - 1)
    for index, char in enumerate(content):
        color = _gradient_color(_TITLE_GRADIENT, index / divisor)
        text.append(char, style=f"bold {color}" if bold else color)
    return text


def tab_description_text(
    tab: CenterTab,
    *,
    specs: dict[CenterTab, CenterTabSpec] | None = None,
) -> Text:
    """Render the active-tab caption in its accent color."""
    spec = (specs or _TAB_BY_ID)[tab]
    description = config_tab_description() if spec.id == "config" else spec.description
    return Text(f"› {description}", style=spec.accent)


def _home_lead_text() -> Text:
    """Render the landing-page lead with the Admin Center aurora sweep."""
    return gradient_text(_HOME_LEAD, bold=True)


def home_orientation_text() -> Text:
    """Render the muted orientation caption shown while home is active."""
    return Text(_HOME_ORIENTATION, style="#888888")


def _landing_key_text(spec: CenterTabSpec, *, compact: bool) -> Text:
    """Render one roomy or compact reversed numeric key chip."""
    key = str(spec.number) if compact else f" {spec.number} "
    return Text(key, style=f"bold reverse {spec.accent}")


def _landing_label_text(spec: CenterTabSpec) -> Text:
    """Render one catalog label padded to the shared landing column."""
    return Text(
        f"{spec.label:<{_HOME_LABEL_WIDTH}}",
        style=f"bold {spec.accent}",
    )


def home_hint_text(
    resume_tab: CenterTab | None,
    opener_binding: str,
    *,
    compact: bool,
    tab_count: int = len(_TAB_SPECS),
    specs: dict[CenterTab, CenterTabSpec] | None = None,
) -> Text:
    """Render the landing's one-row, catalog-derived resume affordance."""
    catalog = specs or _TAB_BY_ID
    spec = catalog.get(resume_tab) if resume_tab is not None else None
    accent = spec.accent if spec is not None else _TITLE_GRADIENT[0]
    navigation = _home_hint_nav(tab_count, compact=compact or spec is None)

    text = Text()
    text.append(f" {key_display_name(opener_binding)} ", style=f"bold reverse {accent}")
    if spec is None:
        resume_copy = (
            " resumes after first visit"
            if compact
            else " resumes after your first section visit"
        )
        text.append(resume_copy, style="#A0A0A0")
    else:
        text.append(f" resume {spec.label}", style=f"bold {spec.accent}")
    text.append(f" · {navigation}", style="#777777")
    return text


class ConfigCenterHeaderDivider(Static):
    """Width-aware divider between the SASE Admin Center header and content."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__("", **kwargs)

    def render(self) -> Text:
        width = max(0, int(self.size.width))
        return Text(_HEADER_DIVIDER_RULE * width, style="#444444")


class AdminCenterLandingRow(Horizontal):
    """Catalog-derived, mouse-clickable, keyboard-transparent home row."""

    can_focus = False

    def __init__(
        self,
        spec: CenterTabSpec,
        on_select: Callable[[CenterTab], None],
    ) -> None:
        super().__init__(
            id=f"admin-center-home-row-{spec.id}",
            classes="admin-center-home-row",
        )
        self._spec = spec
        self._on_select = on_select
        self._compact = False
        self.styles.width = _HOME_ROOMY_ROW_WIDTH

    def compose(self) -> ComposeResult:
        yield Static(
            _landing_key_text(self._spec, compact=self._compact),
            classes="admin-center-home-row-key",
            markup=False,
        )
        yield Static(
            _landing_label_text(self._spec),
            classes="admin-center-home-row-label",
            markup=False,
        )
        description = (
            config_tab_description()
            if self._spec.id == "config"
            else self._spec.description
        )
        yield Static(
            description,
            classes="admin-center-home-row-description",
        )

    def set_compact(self, compact: bool) -> None:
        """Repaint the key chip after the landing's synchronous reflow."""
        if compact == self._compact:
            return
        self._compact = compact
        self.styles.width = (
            _HOME_COMPACT_ROW_WIDTH if compact else _HOME_ROOMY_ROW_WIDTH
        )
        key = self.query_one(".admin-center-home-row-key", Static)
        key.update(_landing_key_text(self._spec, compact=compact))

    def on_click(self, event: Click) -> None:
        """Open this row through the modal's shared navigation path."""
        event.stop()
        self._on_select(self._spec.id)


class AdminCenterLanding(VerticalScroll):
    """Pure, bounded presentation-only home view."""

    can_focus = False

    def __init__(
        self,
        resume_tab: CenterTab | None,
        opener_binding: str,
        on_select: Callable[[CenterTab], None],
        *,
        tab_specs: tuple[CenterTabSpec, ...] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._resume_tab = resume_tab
        self._opener_binding = opener_binding
        self._on_select = on_select
        self._tab_specs = tab_specs if tab_specs is not None else _TAB_SPECS
        self._tab_by_id = {spec.id: spec for spec in self._tab_specs}
        self._compact: bool | None = None

    def compose(self) -> ComposeResult:
        with Vertical(id="admin-center-home-hero"):
            yield Static(
                _home_lead_text(),
                id="admin-center-home-lead",
                markup=False,
            )
            with Vertical(id="admin-center-home-card"):
                for spec in self._tab_specs:
                    yield AdminCenterLandingRow(spec, self._on_select)
            yield Static(
                home_hint_text(
                    self._resume_tab,
                    self._opener_binding,
                    compact=False,
                    tab_count=len(self._tab_specs),
                    specs=self._tab_by_id,
                ),
                id="admin-center-home-hint",
                markup=False,
            )

    def on_resize(self, event: Resize) -> None:
        """Toggle compact home chrome with bounded synchronous work."""
        compact = (
            event.size.width < _HOME_COMPACT_BELOW_WIDTH
            or event.size.height < _HOME_COMPACT_BELOW_HEIGHT
        )
        if compact == self._compact:
            return
        self._compact = compact
        self.set_class(compact, "-compact")
        for row in self.query(AdminCenterLandingRow):
            row.set_compact(compact)
        self.query_one("#admin-center-home-hint", Static).update(
            home_hint_text(
                self._resume_tab,
                self._opener_binding,
                compact=compact,
                tab_count=len(self._tab_specs),
                specs=self._tab_by_id,
            )
        )
