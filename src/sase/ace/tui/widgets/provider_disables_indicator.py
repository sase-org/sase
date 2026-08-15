"""Temporary provider-disable indicator for the ACE top bar."""

from __future__ import annotations

from typing import Any

from rich.text import Text
from textual.widgets import Static

from sase.llm_provider.provider_disable import TemporaryProviderDisable
from sase.llm_provider.provider_disable_peek import peek_active_provider_disables

from ._override_pill import (
    PROVIDER_DISABLE_PALETTE,
    build_override_pill,
    format_pill_remaining,
    format_remaining_until,
)

_ACTIVE_STYLE = PROVIDER_DISABLE_PALETTE.base_style


class ProviderDisablesIndicator(Static):
    """Shows active machine-wide provider disables in one compact pill."""

    def __init__(self, **kwargs: Any) -> None:
        disables = self._active_provider_disables()
        super().__init__(self._build_content(disables), **kwargs)
        self.tooltip = self._build_tooltip(disables)

    def on_mount(self) -> None:
        """Poll through the lock-free peek cache on the top-bar cadence."""
        self._apply_content()
        self.set_interval(30.0, self.refresh)

    def refresh(self, *args: Any, **kwargs: Any) -> Any:
        """Rebuild content on a bare refresh, preserving Widget.refresh kwargs."""
        if args or kwargs:
            return super().refresh(*args, **kwargs)
        self._apply_content()
        return super().refresh()

    async def on_click(self) -> None:
        """Open Launch Control."""
        await self.app.run_action("open_models_panel")

    def _build_initial_content(self, *, now: float | None = None) -> Text:
        """Render the current provider-disable map."""
        return self._build_content(self._active_provider_disables(), now=now)

    def _apply_content(self, *, now: float | None = None) -> None:
        """Update content and tooltip from one current peek snapshot."""
        disables = self._active_provider_disables()
        self.update(self._build_content(disables, now=now))
        self.tooltip = self._build_tooltip(disables, now=now)

    @staticmethod
    def _active_provider_disables() -> dict[str, TemporaryProviderDisable]:
        """Return active provider disables from the lock-free display cache."""
        return dict(peek_active_provider_disables())

    @staticmethod
    def _build_content(
        disables: dict[str, TemporaryProviderDisable],
        *,
        now: float | None = None,
    ) -> Text:
        """Build the pill for zero, one, or several active disables."""
        survivors: list[tuple[str, TemporaryProviderDisable, str]] = []
        for provider, disable in sorted(disables.items()):
            remaining = format_pill_remaining(disable.expires_at, now)
            if remaining is not None:
                survivors.append((provider, disable, remaining))

        if not survivors:
            return Text("")

        provider, _disable, remaining = survivors[0]
        if len(survivors) == 1:
            return build_override_pill(
                subject=provider.upper(),
                effort=None,
                trailing=f"off {remaining}",
                palette=PROVIDER_DISABLE_PALETTE,
            )

        return build_override_pill(
            subject=provider.upper(),
            effort=None,
            trailing=f"+{len(survivors) - 1}",
            palette=PROVIDER_DISABLE_PALETTE,
        )

    @staticmethod
    def _build_tooltip(
        disables: dict[str, TemporaryProviderDisable],
        *,
        now: float | None = None,
    ) -> str | None:
        """Build sorted long-form details for active provider disables."""
        lines: list[str] = []
        for provider, disable in sorted(disables.items()):
            if format_pill_remaining(disable.expires_at, now) is None:
                continue
            if disable.expires_at is None:
                remaining = "until cleared"
            else:
                remaining = f"{format_remaining_until(disable.expires_at, now)} left"
            lines.append(f"{provider.upper()} - {remaining}")
        if not lines:
            return None
        return "\n".join(
            (
                "Disabled providers:",
                *lines,
                "New launches route around them; running processes continue.",
                "Press ,m for Launch Control.",
            )
        )


__all__ = ["ProviderDisablesIndicator"]
