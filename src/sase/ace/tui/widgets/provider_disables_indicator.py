"""Temporary provider-disable indicator for the ACE top bar."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from rich.text import Text
from textual.widgets import Static
from textual.worker import Worker, WorkerState

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
from sase.llm_provider.usage.hints import (
    CapacityHint,
    indicator_usage_attention,
    indicator_usage_items,
)
from sase.llm_provider.usage.peek import (
    cached_usage_peek,
    refresh_usage_peek_cache,
    usage_attention_enabled,
    usage_peek_change_token,
)

from ._override_pill import (
    PROVIDER_DISABLE_PALETTE,
    PROVIDER_PRIORITY_PALETTE,
    PROVIDER_SOFT_DISABLE_PALETTE,
    PROVIDER_USAGE_PALETTE,
    build_override_pill,
    format_pill_remaining,
    format_remaining_until,
)

_ACTIVE_STYLE = PROVIDER_DISABLE_PALETTE.base_style
_USAGE_PEEK_WORKER_GROUP = "provider-usage-peek"
_COMPACT_USAGE_WIDTH = 120


class ProviderDisablesIndicator(Static):
    """Shows active machine-wide provider disables in one compact pill."""

    def __init__(self, **kwargs: Any) -> None:
        self._usage_items: tuple[CapacityHint, ...] = ()
        self._usage_open_provider: str | None = None
        self._usage_peek_in_flight = False
        self._usage_peek_loaded = False
        self._usage_peek_token: tuple[int, int] | None = None
        self._pending_usage_token: tuple[int, int] | None = None
        context = self._active_provider_routing_context()
        priority_state = self._priority_availability(context)
        self._sync_usage_items()
        super().__init__(
            self._build_content(
                context.provider_disables,
                priority=context.priority,
                priority_availability=priority_state,
                usage_items=self._usage_items,
            ),
            **kwargs,
        )
        self.tooltip = self._build_tooltip(
            context.provider_disables,
            priority=context.priority,
            priority_availability=priority_state,
            usage_items=self._usage_items,
        )

    @property
    def usage_open_provider(self) -> str | None:
        """Return the provider a usage click should open, if any."""
        return self._usage_open_provider

    def on_mount(self) -> None:
        """Poll through the lock-free peek cache on the top-bar cadence."""
        self._apply_content()
        self._schedule_usage_peek_if_needed()
        self.set_interval(30.0, self.refresh)

    def refresh(self, *args: Any, **kwargs: Any) -> Any:
        """Rebuild content on a bare refresh, preserving Widget.refresh kwargs."""
        if args or kwargs:
            return super().refresh(*args, **kwargs)
        self._schedule_usage_peek_if_needed()
        self._apply_content()
        return super().refresh()

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        """Repaint after an off-thread usage-store peek finishes."""
        worker = event.worker
        if worker.group != _USAGE_PEEK_WORKER_GROUP:
            return
        if event.state == WorkerState.SUCCESS:
            self._usage_peek_in_flight = False
            self._usage_peek_loaded = True
            self._usage_peek_token = self._pending_usage_token
            self._apply_content()
        elif event.state in {WorkerState.ERROR, WorkerState.CANCELLED}:
            self._usage_peek_in_flight = False

    async def on_click(self) -> None:
        """Open Usage when attention is present, otherwise Launch settings."""
        if self._usage_open_provider:
            await self.app.run_action("open_provider_usage")
            return
        await self.app.run_action("open_models_panel")

    def _build_initial_content(self, *, now: float | None = None) -> Text:
        """Render the current provider-disable map."""
        context = self._active_provider_routing_context(now=now)
        self._sync_usage_items()
        return self._build_content(
            context.provider_disables,
            priority=context.priority,
            priority_availability=self._priority_availability(context),
            usage_items=self._usage_items,
            now=now,
        )

    def _apply_content(self, *, now: float | None = None) -> None:
        """Update content and tooltip from one current peek snapshot."""
        context = self._active_provider_routing_context(now=now)
        priority_state = self._priority_availability(context)
        self._sync_usage_items()
        width = self._terminal_width()
        self.update(
            self._build_content(
                context.provider_disables,
                priority=context.priority,
                priority_availability=priority_state,
                usage_items=self._usage_items,
                width=width,
                now=now,
            )
        )
        self.tooltip = self._build_tooltip(
            context.provider_disables,
            priority=context.priority,
            priority_availability=priority_state,
            usage_items=self._usage_items,
            now=now,
        )

    def _sync_usage_items(self) -> None:
        """Copy the memory-only usage peek into the indicator's display fields."""
        providers, eligible = cached_usage_peek()
        items = indicator_usage_items(providers, eligible)
        item, _count = indicator_usage_attention(providers, eligible)
        self._usage_items = items
        self._usage_open_provider = None if item is None else item.provider

    def _schedule_usage_peek_if_needed(self) -> None:
        """Load usage snapshots off the UI thread when the change token drifts."""
        if self._usage_peek_in_flight or not usage_attention_enabled():
            return
        token = usage_peek_change_token()
        if self._usage_peek_loaded and token == self._usage_peek_token:
            return
        self._usage_peek_in_flight = True
        self._pending_usage_token = token
        self.run_worker(
            refresh_usage_peek_cache,
            thread=True,
            exclusive=True,
            group=_USAGE_PEEK_WORKER_GROUP,
        )

    def _terminal_width(self) -> int | None:
        """Return the attached app width, or ``None`` before mount."""
        try:
            width = self.app.size.width
        except Exception:
            return None
        return int(width) if width else None

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
        usage_items: Sequence[CapacityHint] = (),
        width: int | None = None,
        now: float | None = None,
    ) -> Text:
        """Build the pill for routing state plus quiet usage attention."""
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
        routing = priority_pill or disable_pill
        return ProviderDisablesIndicator._append_usage_content(
            routing,
            usage_items,
            width=width,
        )

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
    def _append_usage_content(
        routing: Text,
        usage_items: Sequence[CapacityHint] = (),
        *,
        width: int | None = None,
    ) -> Text:
        """Append quiet usage attention without replacing a routing pill."""
        if not usage_items:
            return routing
        count = len(usage_items)
        compact = width is not None and width < _COMPACT_USAGE_WIDTH
        if compact:
            trailing = f"usage +{count}" if count > 1 else "usage"
        else:
            item = usage_items[0]
            trailing = item.label
            if item.provider:
                trailing = f"{item.provider.upper()} {trailing}"
            if count > 1:
                trailing = f"{trailing} +{count - 1}"
        combined = routing.copy() if routing.plain else Text()
        combined.append(" !", style=PROVIDER_USAGE_PALETTE.base_style)
        combined.append(
            f" {trailing} ",
            style=PROVIDER_USAGE_PALETTE.secondary_style,
        )
        return combined

    @staticmethod
    def _build_tooltip(
        disables: dict[str, TemporaryProviderDisable],
        *,
        priority: TemporaryProviderPriority | None = None,
        priority_availability: ProviderAvailability | None = None,
        usage_items: Sequence[CapacityHint] = (),
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
        usage_lines = [
            (f"{item.provider.upper()} - {item.kind.replace('_', ' ')} · {item.label}")
            for item in usage_items
        ]
        if not lines and not usage_lines:
            return None
        parts: list[str] = []
        if lines:
            if has_priority and has_disables:
                heading = "Provider routing state:"
            elif has_priority:
                heading = "Provider priority:"
            else:
                heading = "Disabled providers:"
            parts.extend(
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
        if usage_lines:
            if parts:
                parts.append("")
            parts.extend(
                (
                    "Usage attention:",
                    *usage_lines,
                    "Click to open this provider's Providers · Usage view.",
                    "The Usage command is also reachable from the command palette.",
                )
            )
        return "\n".join(parts)

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


__all__ = ["ProviderDisablesIndicator"]
