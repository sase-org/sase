"""Temporary provider-disable indicator for the ACE top bar."""

from __future__ import annotations

from typing import Any

from rich.text import Text

from sase.ace.tui.provider_disable_display import provider_disable_provenance_label
from sase.llm_provider.provider_disable import TemporaryProviderDisable
from sase.llm_provider.provider_priority import ProviderRoutingContext
from sase.llm_provider.provider_priority_peek import peek_provider_routing_context

from ._override_pill import (
    PROVIDER_DISABLE_PALETTE,
    PROVIDER_SOFT_DISABLE_PALETTE,
    build_override_pill,
    format_pill_remaining,
    format_remaining_until,
)
from ._text_signature import text_signature
from .top_bar_group import TopBarGroup

_ACTIVE_STYLE = PROVIDER_DISABLE_PALETTE.base_style


class ProviderDisablesIndicator(TopBarGroup):
    """Shows active machine-wide provider disables in one compact pill.

    This widget owns the one routing poll that drives both routing groups:
    each refresh peeks once and pushes the same snapshot to the sibling
    ``ProviderPriorityIndicator`` so the two groups can never disagree.
    """

    GROUP_LABEL = "disabled"
    CLICK_ACTION = "open_models_panel"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        context = self._active_provider_routing_context()
        initial_content = self._build_content(
            context.provider_disables,
        )
        self._set_body(initial_content)
        self.tooltip = self._build_tooltip(
            context.provider_disables,
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

    def _build_initial_content(self, *, now: float | None = None) -> Text:
        """Render the current provider-disable map."""
        context = self._active_provider_routing_context(now=now)
        return self._build_content(
            context.provider_disables,
            now=now,
        )

    def _apply_content(self, *, now: float | None = None) -> None:
        """Update content and tooltip from one current peek snapshot."""
        context = self._active_provider_routing_context(now=now)
        content = self._build_content(
            context.provider_disables,
            now=now,
        )
        tooltip = self._build_tooltip(
            context.provider_disables,
            now=now,
        )
        self._replace_content(content, tooltip)
        self._apply_priority_sibling(context, now)

    def _apply_priority_sibling(
        self,
        context: ProviderRoutingContext,
        now: float | None,
    ) -> None:
        """Push *context* to the priority sibling when it is mounted."""
        try:
            parent = self.parent
            if parent is None:
                return
            sibling = parent.query_one("#provider-priority-indicator")
        except Exception:
            return
        apply = getattr(sibling, "apply_routing_context", None)
        if not callable(apply):
            return
        try:
            apply(context, now=now)
        except Exception:
            return

    def _replace_content(self, content: Text, tooltip: str | None) -> None:
        """Update the widget only when the selected rendering actually changed."""
        self._set_body(content)
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
        now: float | None = None,
    ) -> Text:
        """Build the disable pill."""
        return ProviderDisablesIndicator._build_disable_content(
            disables,
            now=now,
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
    def _build_tooltip(
        disables: dict[str, TemporaryProviderDisable],
        *,
        now: float | None = None,
    ) -> str | None:
        """Build sorted long-form details for disabled providers."""
        lines: list[str] = []
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
        if not lines:
            return None
        return "\n".join(
            (
                "Disabled providers:",
                *lines,
                "Hard disables skip the provider on new launches; "
                "running processes continue.",
                "Pools spare a soft provider while another member can cover; "
                "|| fallbacks and explicit %model still use it.",
                "Press ,m for Config > Launch.",
            )
        )


# Tests and older imports still reach the signature helper through this module.
_text_signature = text_signature


__all__ = ["ProviderDisablesIndicator"]
