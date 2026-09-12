"""Temporary provider-disable indicator for the ACE top bar."""

from __future__ import annotations

from typing import Any

from rich.text import Text
from textual.widgets import Static

from sase.ace.tui.provider_disable_display import provider_disable_provenance_label
from sase.llm_provider.load_balancing import MemberAvailability
from sase.llm_provider.provider_disable import TemporaryProviderDisable
from sase.llm_provider.provider_priority import (
    ProviderAvailability,
    ProviderRoutingContext,
    TemporaryProviderPriority,
    classify_provider_availability,
)
from sase.llm_provider.provider_priority_peek import peek_provider_routing_context
from sase.llm_provider.registry import provider_routing_facts

from ._override_pill import (
    PROVIDER_DISABLE_PALETTE,
    PROVIDER_PRIORITY_PALETTE,
    PROVIDER_SOFT_DISABLE_PALETTE,
    build_override_pill,
    format_pill_remaining,
    format_remaining_until,
)
from ._text_signature import text_signature

_ACTIVE_STYLE = PROVIDER_DISABLE_PALETTE.base_style


class ProviderDisablesIndicator(Static):
    """Shows active machine-wide provider disables in one compact pill."""

    def __init__(self, **kwargs: Any) -> None:
        context = self._active_provider_routing_context()
        priority_state = self._priority_availability(context)
        initial_content = self._build_content(
            context.provider_disables,
            priority=context.priority,
            priority_availability=priority_state,
        )
        self._content_signature = text_signature(initial_content)
        super().__init__(
            initial_content,
            **kwargs,
        )
        self.tooltip = self._build_tooltip(
            context.provider_disables,
            priority=context.priority,
            priority_availability=priority_state,
        )

    def on_mount(self) -> None:
        """Poll routing expiration on the top-bar cadence."""
        self._apply_content()
        self.set_interval(30.0, self.refresh)

    def refresh(self, *args: Any, **kwargs: Any) -> Any:
        """Rebuild content on a bare refresh, preserving Widget.refresh kwargs."""
        if args or kwargs:
            return super().refresh(*args, **kwargs)
        self._apply_content()
        return super().refresh()

    async def on_click(self) -> None:
        """Open Launch settings for the routing pill."""
        await self.app.run_action("open_models_panel")

    def _build_initial_content(self, *, now: float | None = None) -> Text:
        """Render the current provider-disable map."""
        context = self._active_provider_routing_context(now=now)
        return self._build_content(
            context.provider_disables,
            priority=context.priority,
            priority_availability=self._priority_availability(context),
            now=now,
        )

    def _apply_content(self, *, now: float | None = None) -> None:
        """Update content and tooltip from one current peek snapshot."""
        context = self._active_provider_routing_context(now=now)
        priority_state = self._priority_availability(context)
        content = self._build_content(
            context.provider_disables,
            priority=context.priority,
            priority_availability=priority_state,
            now=now,
        )
        tooltip = self._build_tooltip(
            context.provider_disables,
            priority=context.priority,
            priority_availability=priority_state,
            now=now,
        )
        self._replace_content(content, tooltip)

    def _replace_content(self, content: Text, tooltip: str | None) -> None:
        """Update the widget only when the selected rendering actually changed."""
        signature = text_signature(content)
        if signature != self._content_signature:
            self.update(content)
            self._content_signature = signature
        if self.tooltip != tooltip:
            self.tooltip = tooltip

    @staticmethod
    def _active_provider_routing_context(
        *,
        now: float | None = None,
    ) -> ProviderRoutingContext:
        """Return active routing state from one lock-free display cache read."""
        return peek_provider_routing_context(now)

    @staticmethod
    def _build_content(
        disables: dict[str, TemporaryProviderDisable],
        *,
        priority: TemporaryProviderPriority | None = None,
        priority_availability: ProviderAvailability | None = None,
        now: float | None = None,
    ) -> Text:
        """Build the pill for routing state."""
        return ProviderDisablesIndicator._build_routing_content(
            disables,
            priority=priority,
            priority_availability=priority_availability,
            now=now,
        )

    @staticmethod
    def _build_routing_content(
        disables: dict[str, TemporaryProviderDisable],
        *,
        priority: TemporaryProviderPriority | None = None,
        priority_availability: ProviderAvailability | None = None,
        now: float | None = None,
    ) -> Text:
        """Build only the routing-state portion of the indicator pill."""
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
            priority_availability=priority_availability,
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
        priority_availability: ProviderAvailability | None = None,
        now: float | None = None,
        disable_count: int = 0,
    ) -> Text:
        """Build the provider-priority portion of the indicator pill."""
        if priority is None:
            return Text("")
        remaining = format_pill_remaining(priority.expires_at, now)
        if remaining is None:
            return Text("")
        state = ProviderDisablesIndicator._priority_state_label(priority_availability)
        trailing = (
            (
                f"{remaining} +{disable_count}"
                if state == "priority"
                else f"{state} {remaining} +{disable_count}"
            )
            if disable_count
            else f"{state} {remaining}"
        )
        return build_override_pill(
            subject=f"{priority.provider.upper()} ★",
            effort=None,
            trailing=trailing,
            palette=ProviderDisablesIndicator._priority_palette(priority_availability),
        )

    @staticmethod
    def _build_tooltip(
        disables: dict[str, TemporaryProviderDisable],
        *,
        priority: TemporaryProviderPriority | None = None,
        priority_availability: ProviderAvailability | None = None,
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
                priority_label = ProviderDisablesIndicator._priority_tooltip_label(
                    priority_availability
                )
                lines.extend(
                    (
                        f"{priority.provider.upper()} - {priority_label} · {remaining}",
                        ProviderDisablesIndicator._priority_tooltip_detail(
                            priority_availability
                        ),
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

    @staticmethod
    def _priority_availability(
        context: ProviderRoutingContext,
    ) -> ProviderAvailability | None:
        """Classify the active priority provider from one captured context."""
        priority = context.priority
        if priority is None:
            return None
        return classify_provider_availability(
            context,
            provider_routing_facts(priority.provider),
        )

    @staticmethod
    def _priority_state_label(
        priority_availability: ProviderAvailability | None,
    ) -> str:
        """Return the compact top-bar label for priority intent."""
        if priority_availability is None:
            return "priority"
        if "actual_soft_disable" in priority_availability.provenance:
            return "soft-disabled"
        if priority_availability.availability == MemberAvailability.UNAVAILABLE:
            return "unavailable"
        return "priority"

    @staticmethod
    def _priority_tooltip_label(
        priority_availability: ProviderAvailability | None,
    ) -> str:
        """Return the long-form tooltip label for priority intent."""
        label = ProviderDisablesIndicator._priority_state_label(priority_availability)
        return "preferred" if label == "priority" else label

    @staticmethod
    def _priority_tooltip_detail(
        priority_availability: ProviderAvailability | None,
    ) -> str:
        """Return the long-form tooltip detail for priority intent."""
        label = ProviderDisablesIndicator._priority_state_label(priority_availability)
        if label == "soft-disabled":
            return (
                "Priority intent remains, but pools spare the provider while "
                "another member can cover."
            )
        if label == "unavailable":
            return (
                "Priority intent remains, but routing uses backups until the "
                "provider is available."
            )
        return "Pools prefer the priority provider; other providers remain backups."

    @staticmethod
    def _priority_palette(
        priority_availability: ProviderAvailability | None,
    ) -> Any:
        """Return the top-bar palette for priority intent."""
        label = ProviderDisablesIndicator._priority_state_label(priority_availability)
        if label == "soft-disabled":
            return PROVIDER_SOFT_DISABLE_PALETTE
        if label == "unavailable":
            return PROVIDER_DISABLE_PALETTE
        return PROVIDER_PRIORITY_PALETTE


# Tests and older imports still reach the signature helper through this module.
_text_signature = text_signature


__all__ = ["ProviderDisablesIndicator"]
