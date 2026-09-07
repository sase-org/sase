"""Temporary provider-disable indicator for the ACE top bar."""

from __future__ import annotations

from typing import Any

from rich.text import Text
from textual.widgets import Static

from sase.ace.tui.provider_disable_display import provider_disable_provenance_label
from sase.llm_provider.provider_disable import TemporaryProviderDisable
from sase.llm_provider.provider_disable_peek import peek_active_provider_disables
from sase.llm_provider.provider_priority import TemporaryProviderPriority
from sase.llm_provider.provider_priority_peek import peek_active_provider_priority

from ._override_pill import (
    PROVIDER_DISABLE_PALETTE,
    PROVIDER_PRIORITY_PALETTE,
    PROVIDER_SOFT_DISABLE_PALETTE,
    build_override_pill,
    format_pill_remaining,
    format_remaining_until,
)

_ACTIVE_STYLE = PROVIDER_DISABLE_PALETTE.base_style


class ProviderDisablesIndicator(Static):
    """Shows active machine-wide provider disables in one compact pill."""

    def __init__(self, **kwargs: Any) -> None:
        disables = self._active_provider_disables()
        priority = self._active_provider_priority()
        super().__init__(self._build_content(disables, priority=priority), **kwargs)
        self.tooltip = self._build_tooltip(disables, priority=priority)

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
        """Open Launch settings."""
        await self.app.run_action("open_models_panel")

    def _build_initial_content(self, *, now: float | None = None) -> Text:
        """Render the current provider-disable map."""
        return self._build_content(
            self._active_provider_disables(),
            priority=self._active_provider_priority(now=now),
            now=now,
        )

    def _apply_content(self, *, now: float | None = None) -> None:
        """Update content and tooltip from one current peek snapshot."""
        disables = self._active_provider_disables()
        priority = self._active_provider_priority(now=now)
        self.update(self._build_content(disables, priority=priority, now=now))
        self.tooltip = self._build_tooltip(disables, priority=priority, now=now)

    @staticmethod
    def _active_provider_disables() -> dict[str, TemporaryProviderDisable]:
        """Return active provider disables from the lock-free display cache."""
        return dict(peek_active_provider_disables())

    @staticmethod
    def _active_provider_priority(
        *,
        now: float | None = None,
    ) -> TemporaryProviderPriority | None:
        """Return active provider priority from the lock-free display cache."""
        return peek_active_provider_priority(now)

    @staticmethod
    def _build_content(
        disables: dict[str, TemporaryProviderDisable],
        *,
        priority: TemporaryProviderPriority | None = None,
        now: float | None = None,
    ) -> Text:
        """Build the pill for active disables, provider priority, or both."""
        disable_pill = ProviderDisablesIndicator._build_disable_content(
            disables,
            now=now,
        )
        disable_count = ProviderDisablesIndicator._active_disable_count(
            disables,
            now=now,
        )
        priority_pill = ProviderDisablesIndicator._build_priority_content(
            priority,
            now=now,
            disable_count=disable_count,
        )
        return priority_pill or disable_pill

    @staticmethod
    def _active_disable_count(
        disables: dict[str, TemporaryProviderDisable],
        *,
        now: float | None = None,
    ) -> int:
        """Return the number of active provider disables in a display snapshot."""
        return sum(
            1
            for disable in disables.values()
            if format_pill_remaining(disable.expires_at, now) is not None
        )

    @staticmethod
    def _build_disable_content(
        disables: dict[str, TemporaryProviderDisable],
        *,
        now: float | None = None,
    ) -> Text:
        """Build the provider-disable portion of the indicator pill."""
        survivors: list[tuple[bool, str, TemporaryProviderDisable, str]] = []
        for provider, disable in disables.items():
            remaining = format_pill_remaining(disable.expires_at, now)
            if remaining is not None:
                survivors.append((disable.is_soft, provider, disable, remaining))
        survivors.sort()

        if not survivors:
            return Text("")

        all_soft = all(
            is_soft for is_soft, _provider, _disable, _remaining in survivors
        )
        palette = (
            PROVIDER_SOFT_DISABLE_PALETTE if all_soft else PROVIDER_DISABLE_PALETTE
        )
        _is_soft, provider, disable, remaining = survivors[0]
        if len(survivors) == 1:
            kind = "soft" if disable.is_soft else "off"
            return build_override_pill(
                subject=provider.upper(),
                effort=None,
                trailing=f"{kind} {remaining}",
                palette=palette,
            )

        return build_override_pill(
            subject=provider.upper(),
            effort=None,
            trailing=f"+{len(survivors) - 1}",
            palette=palette,
        )

    @staticmethod
    def _build_priority_content(
        priority: TemporaryProviderPriority | None,
        *,
        now: float | None = None,
        disable_count: int = 0,
    ) -> Text:
        """Build the provider-priority portion of the indicator pill."""
        if priority is None:
            return Text("")
        remaining = format_pill_remaining(priority.expires_at, now)
        if remaining is None:
            return Text("")
        trailing = (
            f"{remaining} +{disable_count}"
            if disable_count
            else f"priority {remaining}"
        )
        return build_override_pill(
            subject=f"{priority.provider.upper()} ★",
            effort=None,
            trailing=trailing,
            palette=PROVIDER_PRIORITY_PALETTE,
        )

    @staticmethod
    def _build_tooltip(
        disables: dict[str, TemporaryProviderDisable],
        *,
        priority: TemporaryProviderPriority | None = None,
        now: float | None = None,
    ) -> str | None:
        """Build sorted long-form details for provider routing state."""
        lines: list[str] = []
        has_priority = False
        has_disables = False
        if priority is not None:
            if priority.expires_at is None:
                remaining = "until cleared"
            else:
                rendered = format_remaining_until(priority.expires_at, now)
                if rendered:
                    remaining = f"{rendered} left"
                else:
                    remaining = ""
            if remaining:
                has_priority = True
                lines.extend(
                    (
                        f"{priority.provider.upper()} - preferred · {remaining}",
                        "Pools prefer the priority provider; "
                        "other providers remain backups.",
                    )
                )
        for provider, disable in sorted(disables.items()):
            if format_pill_remaining(disable.expires_at, now) is None:
                continue
            if disable.expires_at is None:
                remaining = "until cleared"
            else:
                remaining = f"{format_remaining_until(disable.expires_at, now)} left"
            provenance = provider_disable_provenance_label(disable)
            mode = "soft" if disable.is_soft else "hard"
            lines.append(f"{provider.upper()} - {mode} · {provenance}, {remaining}")
            has_disables = True
        if not lines:
            return None
        if has_priority and has_disables:
            heading = "Provider routing state:"
        elif has_priority:
            heading = "Provider priority:"
        else:
            heading = "Disabled providers:"
        return "\n".join(
            (
                heading,
                *lines,
                "Hard disables skip the provider on new launches; "
                "running processes continue.",
                "Pools spare a soft provider while another member can cover; "
                "|| fallbacks and explicit %model still use it.",
                "Press ,m for Config > Launch.",
            )
        )


__all__ = ["ProviderDisablesIndicator"]
