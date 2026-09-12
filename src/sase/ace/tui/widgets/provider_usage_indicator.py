"""Compact provider-usage indicator for the ACE application header."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol, cast

from rich.text import Text
from textual.events import Click
from textual.widgets import Static
from textual.worker import Worker, WorkerState

from sase.llm_provider.usage.peek import (
    cached_usage_indicator_projection,
    refresh_usage_peek_cache,
    usage_attention_enabled,
    usage_peek_change_token,
)

from ._provider_usage_indicator import (
    UsageProviderGroup,
    build_usage_indicator_segment,
    usage_indicator_groups,
    usage_indicator_open_provider,
    usage_indicator_tooltip_lines,
)
from ._text_signature import text_signature

_USAGE_PEEK_WORKER_GROUP = "provider-usage-indicator-peek"


class _ProviderUsageApp(Protocol):
    def action_open_provider_usage(self, provider: str | None = None) -> None: ...


class ProviderUsageIndicator(Static):
    """Shows selected usage windows in a right-aligned header cluster."""

    def __init__(self, **kwargs: Any) -> None:
        self._usage_groups: tuple[UsageProviderGroup, ...] = ()
        self._usage_open_provider: str | None = None
        self._usage_peek_in_flight = False
        self._usage_peek_loaded = False
        self._usage_peek_token: tuple[Any, ...] | None = None
        self._pending_usage_token: tuple[Any, ...] | None = None
        self._usage_budget = 0
        self._sync_usage_groups()
        self._content_signature = text_signature(Text(""))
        super().__init__(Text(""), **kwargs)
        self.tooltip = None

    @property
    def usage_open_provider(self) -> str | None:
        """Return the provider a usage click should open, if any."""
        return self._usage_open_provider

    def set_usage_budget(self, budget: int) -> None:
        """Apply a measured header cell budget; zero keeps the cluster empty."""
        normalized = max(0, int(budget))
        if normalized == self._usage_budget:
            return
        self._usage_budget = normalized
        if self.is_mounted:
            self._apply_content()

    def on_mount(self) -> None:
        """Poll through the lock-free peek cache on the header cadence."""
        self.watch(self.app, "theme", self._app_theme_changed, init=False)
        self._apply_content()
        self._schedule_usage_peek_if_needed()
        self.set_interval(30.0, self.refresh)

    def on_unmount(self) -> None:
        """Drop in-flight reload state so late worker results cannot paint."""
        self._usage_peek_in_flight = False

    def _app_theme_changed(self) -> None:
        """Repaint bucket colors after an app theme switch."""
        if self.is_mounted:
            self._apply_content()

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
        if not self.is_mounted:
            self._usage_peek_in_flight = False
            return
        if event.state == WorkerState.SUCCESS:
            self._usage_peek_in_flight = False
            self._usage_peek_loaded = True
            self._usage_peek_token = self._pending_usage_token
            self._apply_content()
        elif event.state in {WorkerState.ERROR, WorkerState.CANCELLED}:
            self._usage_peek_in_flight = False

    async def on_click(self, event: Click) -> None:
        """Open Usage without expanding Header, including overflow/fallback clicks."""
        event.stop()
        event.prevent_default()
        cast(_ProviderUsageApp, self.app).action_open_provider_usage()

    def _apply_content(self, *, now: float | None = None) -> None:
        """Update content and tooltip from one current peek snapshot."""
        if not self.is_mounted:
            return
        self._sync_usage_groups(now=now)
        content = self._build_content(
            self._usage_groups,
            usage_budget=self._usage_budget,
            dark=self._current_dark_theme(),
        )
        tooltip = self._build_tooltip(self._usage_groups)
        self._replace_content(content, tooltip)

    def _sync_usage_groups(self, *, now: float | None = None) -> None:
        """Rebuild usage groups from the memory-only peek snapshot and clock."""
        if not usage_attention_enabled():
            self._usage_groups = ()
            self._usage_open_provider = None
            return
        projection = cached_usage_indicator_projection(now=now)
        groups = usage_indicator_groups(
            projection.entries,
            dark=self._current_dark_theme(),
            now=projection.generated_at,
        )
        self._usage_groups = groups
        self._usage_open_provider = usage_indicator_open_provider(groups)

    def _current_dark_theme(self) -> bool:
        """Return whether the active app theme is dark, defaulting to dark."""
        try:
            return bool(self.app.current_theme.dark)
        except Exception:
            return True

    def _replace_content(self, content: Text, tooltip: str | None) -> None:
        """Update the widget only when the selected rendering actually changed."""
        signature = text_signature(content)
        if signature != self._content_signature:
            self.update(content)
            self._content_signature = signature
        if self.tooltip != tooltip:
            self.tooltip = tooltip

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

    @staticmethod
    def _build_content(
        usage_groups: Sequence[UsageProviderGroup] = (),
        *,
        usage_budget: int | None = None,
        dark: bool = True,
    ) -> Text:
        """Build the quiet usage cluster for *usage_groups*."""
        if not usage_groups:
            return Text("")
        return build_usage_indicator_segment(
            usage_groups,
            budget=usage_budget,
            dark=dark,
        )

    @staticmethod
    def _build_tooltip(
        usage_groups: Sequence[UsageProviderGroup] = (),
    ) -> str | None:
        """Build full-disclosure usage facts for every selected window."""
        usage_lines = list(usage_indicator_tooltip_lines(usage_groups))
        if not usage_lines:
            return None
        return "\n".join(
            (
                "Usage windows:",
                "Included subscription allowance readings from provider CLIs.",
                *usage_lines,
                "Notation: compact names omit weekly/all-model defaults; "
                "a middle dot separates windows of the same provider; "
                "5h/mo name non-weekly windows; scope? means the provider did "
                "not expose exact applicability.",
                "Neutral text marks a retained stale/unknown-age reading; ↻ marks "
                "a passed reset awaiting a new observation; +N counts hidden "
                "windows.",
                "Click to open Providers · Usage.",
                "The Usage command is also reachable from the command palette.",
            )
        )


__all__ = ["ProviderUsageIndicator"]
