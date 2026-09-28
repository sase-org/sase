"""Provider-priority pill builders for the ACE top bar.

The priority pill now renders inside the merged ``overrides:`` group owned
by :class:`AliasOverridesIndicator`; this module keeps the static pill and
tooltip builders so plain-text and palette tests can keep calling them.
"""

from __future__ import annotations

from typing import Any

from rich.text import Text

from sase.llm_provider.load_balancing import MemberAvailability
from sase.llm_provider.provider_priority import (
    ProviderAvailability,
    ProviderRoutingContext,
    TemporaryProviderPriority,
    classify_provider_availability,
)
from sase.llm_provider.registry import provider_routing_facts

from ._override_pill import (
    PROVIDER_DISABLE_PALETTE,
    PROVIDER_PRIORITY_PALETTE,
    PROVIDER_SOFT_DISABLE_PALETTE,
    build_override_pill,
    format_pill_remaining,
    format_remaining_until,
)


class ProviderPriorityIndicator:
    """Static builders for the priority pill inside the merged overrides group."""

    @staticmethod
    def _build_content(
        priority: TemporaryProviderPriority | None,
        *,
        priority_availability: ProviderAvailability | None = None,
        now: float | None = None,
    ) -> Text:
        """Build the priority pill; empty when no active priority."""
        if priority is None:
            return Text("")
        remaining = format_pill_remaining(priority.expires_at, now)
        if remaining is None:
            return Text("")
        state = ProviderPriorityIndicator._priority_state_label(priority_availability)
        trailing = remaining if state == "priority" else f"{state} {remaining}"
        return build_override_pill(
            subject=f"{priority.provider.upper()} ★",
            effort=None,
            trailing=trailing,
            palette=ProviderPriorityIndicator._priority_palette(priority_availability),
        )

    @staticmethod
    def _build_tooltip(
        priority: TemporaryProviderPriority | None,
        *,
        priority_availability: ProviderAvailability | None = None,
        now: float | None = None,
    ) -> str | None:
        """Build the priority-only tooltip."""
        if priority is None:
            return None
        if priority.expires_at is None:
            remaining = "until cleared"
        else:
            rendered = format_remaining_until(priority.expires_at, now)
            if not rendered:
                return None
            remaining = f"{rendered} left"
        label = ProviderPriorityIndicator._priority_tooltip_label(priority_availability)
        return "\n".join(
            (
                "Provider priority:",
                f"{priority.provider.upper()} - {label} · {remaining}",
                ProviderPriorityIndicator._priority_tooltip_detail(
                    priority_availability
                ),
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
        label = ProviderPriorityIndicator._priority_state_label(priority_availability)
        return "preferred" if label == "priority" else label

    @staticmethod
    def _priority_tooltip_detail(
        priority_availability: ProviderAvailability | None,
    ) -> str:
        """Return the long-form tooltip detail for priority intent."""
        label = ProviderPriorityIndicator._priority_state_label(priority_availability)
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
        label = ProviderPriorityIndicator._priority_state_label(priority_availability)
        if label == "soft-disabled":
            return PROVIDER_SOFT_DISABLE_PALETTE
        if label == "unavailable":
            return PROVIDER_DISABLE_PALETTE
        return PROVIDER_PRIORITY_PALETTE


__all__ = ["ProviderPriorityIndicator"]
