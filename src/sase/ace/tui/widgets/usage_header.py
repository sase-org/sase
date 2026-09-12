"""ACE application header with a left title and right-aligned usage cluster.

Interaction with Textual's internal ``HeaderIcon`` / ``HeaderTitle`` widgets is
isolated in this adapter. Other headers and modal titles keep Textual defaults.
"""

from __future__ import annotations

from typing import Any, Protocol, cast

from textual.app import ComposeResult
from textual.events import Click, Resize
from textual.widgets import Header
from textual.widgets._header import HeaderIcon, HeaderTitle

from .provider_usage_indicator import ProviderUsageIndicator


class _ProviderUsageApp(Protocol):
    def action_open_provider_usage(self, provider: str | None = None) -> None: ...


class UsageHeader(Header):
    """Standard ACE header with usage docked to the right of a left-aligned title."""

    DEFAULT_CSS = """
    UsageHeader HeaderTitle {
        text-wrap: nowrap;
        text-overflow: ellipsis;
        content-align: left middle;
        text-align: left;
        width: 1fr;
    }

    UsageHeader #provider-usage-indicator {
        dock: right;
        width: auto;
        height: 1;
        padding: 0;
        content-align: right middle;
    }
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(show_clock=False, **kwargs)
        self._usage_budget_scheduled = False

    def compose(self) -> ComposeResult:
        yield HeaderIcon().data_bind(Header.icon)
        yield HeaderTitle()
        yield ProviderUsageIndicator(id="provider-usage-indicator")

    def on_mount(self) -> None:
        """Watch title geometry; Header._on_mount still owns title text updates.

        Textual invokes every matching handler in the MRO, so this must not be
        ``_on_mount`` (duplicate title watchers) or ``_on_click`` (the tall
        header would toggle twice and cancel expansion). Usage clicks stop
        before they reach Header's expansion handler.
        """

        def schedule_budget(*_args: object) -> None:
            self._schedule_usage_budget()

        self.watch(self.app, "title", schedule_budget, init=False)
        self.watch(self.app, "sub_title", schedule_budget, init=False)
        self.watch(self.screen, "title", schedule_budget, init=False)
        self.watch(self.screen, "sub_title", schedule_budget, init=False)
        self._schedule_usage_budget()

    def on_resize(self, _event: Resize) -> None:
        """Re-measure the usage budget when the terminal geometry changes."""
        self._schedule_usage_budget()

    async def on_click(self, event: Click) -> None:
        """Route docked usage clicks before Header toggles expansion."""
        try:
            usage = self.query_one(
                "#provider-usage-indicator",
                ProviderUsageIndicator,
            )
        except Exception:
            return
        if not usage.region.contains(event.screen_x, event.screen_y):
            return
        event.stop()
        event.prevent_default()
        cast(_ProviderUsageApp, self.app).action_open_provider_usage()

    def _schedule_usage_budget(self) -> None:
        """Coalesce geometry and title-driven usage budget updates."""
        if self._usage_budget_scheduled or not self.is_mounted:
            return
        self._usage_budget_scheduled = True
        self.call_after_refresh(self._apply_usage_budget)

    def _apply_usage_budget(self) -> None:
        self._usage_budget_scheduled = False
        if not self.is_mounted:
            return
        try:
            usage = self.query_one(
                "#provider-usage-indicator",
                ProviderUsageIndicator,
            )
        except Exception:
            return
        usage.set_usage_budget(self._measure_usage_budget())
        self._apply_title_tooltip()

    def _measure_usage_budget(self) -> int:
        """Return cells remaining after the icon and the unclipped title."""
        inner = int(self.content_size.width)
        if inner <= 0:
            return 0
        try:
            icon = self.query_one(HeaderIcon)
        except Exception:
            return 0
        icon_width = int(icon.outer_size.width)
        if icon_width <= 0:
            return 0
        title_width = int(self.format_title().cell_length)
        return max(0, inner - icon_width - title_width)

    def _apply_title_tooltip(self) -> None:
        """Expose the full title when the single-line header has to ellipsize it."""
        try:
            title = self.query_one(HeaderTitle)
        except Exception:
            return
        formatted = self.format_title()
        inner = int(self.content_size.width)
        try:
            icon_width = int(self.query_one(HeaderIcon).outer_size.width)
        except Exception:
            icon_width = 0
        available = max(0, inner - icon_width)
        if inner > 0 and formatted.cell_length > available:
            title.tooltip = formatted.plain
        else:
            title.tooltip = None


__all__ = ["UsageHeader"]
