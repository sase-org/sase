"""LLM model status indicator for the ace TUI top bar."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from rich.text import Text
from textual.widgets import Static
from textual.worker import Worker, WorkerState

from sase.llm_provider.launch_default_peek import peek_launch_default_change_token
from sase.llm_provider.model_launch_settings import (
    DEFAULT_MODEL_FIELD,
    build_launch_model_setting_snapshot,
)
from sase.llm_provider.registry import format_provider_model_label
from sase.llm_provider.temporary_override import (
    TemporaryLLMOverride,
    get_active_temporary_override,
    peek_active_temporary_override,
    resolve_effective_default_provider_model,
)

from ._override_pill import (
    DEFAULT_LANE_PALETTE,
    build_override_pill,
    format_pill_remaining,
    format_tooltip_remaining,
    format_tooltip_target,
)

_ACTIVE_STYLE = DEFAULT_LANE_PALETTE.base_style
_DEFAULT_STYLE = "dim cyan"
_PLACEHOLDER_TEXT = " ... "
_UNAVAILABLE_TEXT = " unavailable "
_DEFAULT_WORKER_GROUP = "llm-indicator-default"

# Only affordable because the periodic tick is now pure peek (a time-gated
# config-token read plus a few os.stat calls) instead of the locking,
# self-cleaning override read this widget used to perform every tick. Do not
# "optimize" the tick back into a locking read on the theory that fewer,
# heavier calls beat more, cheaper ones -- see launch_default_peek.py.
_POLL_INTERVAL_SECONDS = 5.0


@dataclass(frozen=True, slots=True)
class _LaunchDefaultSnapshot:
    """Resolved launch default plus rotation context for the tooltip."""

    provider: str
    model: str
    referenced_alias: str | None
    selector_mode: str | None
    member_count: int


class LLMOverrideIndicator(Static):
    """Shows the default model or active temporary override in the top bar."""

    def __init__(self, **kwargs: Any) -> None:
        self._cached_default: tuple[str, str] | None = None
        self._cached_default_failed = False
        self._cached_snapshot: _LaunchDefaultSnapshot | None = None
        self._cached_default_token: tuple[object, ...] | None = None
        self._pending_resolve_token: tuple[object, ...] | None = None
        self._resolve_in_flight = False
        self._override_active_last_tick = False
        super().__init__(self._build_initial_content(), **kwargs)
        self.tooltip = self._build_tooltip(peek_active_temporary_override())

    def on_mount(self) -> None:
        """Resolve the default provider off the UI thread, then poll."""
        self._apply_content()
        self._override_active_last_tick = peek_active_temporary_override() is not None
        self._schedule_default_resolution_if_needed()
        self.set_interval(_POLL_INTERVAL_SECONDS, self.refresh)

    def refresh(self, *args: Any, **kwargs: Any) -> Any:
        """Refresh indicator content, preserving Widget.refresh kwargs."""
        if args or kwargs:
            return super().refresh(*args, **kwargs)

        override_active = peek_active_temporary_override() is not None
        override_lapsed = self._override_active_last_tick and not override_active
        self._override_active_last_tick = override_active

        if not override_active:
            cold_start = self._cached_default is None and not self._resolve_in_flight
            token_changed = (
                peek_launch_default_change_token() != self._cached_default_token
            )
            if (
                cold_start
                or self._cached_default_failed
                or token_changed
                or override_lapsed
            ):
                self._schedule_default_resolution_if_needed()

        self._apply_content()
        return super().refresh()

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        """Pick up the resolved default once the background worker finishes."""
        worker = event.worker
        if worker.group != _DEFAULT_WORKER_GROUP:
            return
        if event.state == WorkerState.SUCCESS:
            self._resolve_in_flight = False
            result = worker.result
            if isinstance(result, _LaunchDefaultSnapshot):
                self._cached_default = (result.provider, result.model)
                self._cached_snapshot = result
                self._cached_default_failed = False
                self._cached_default_token = self._pending_resolve_token
            else:
                self._cached_default_failed = True
            self._apply_content()
        elif event.state == WorkerState.ERROR:
            self._resolve_in_flight = False
            self._cached_default_failed = True
            self._apply_content()
        elif event.state == WorkerState.CANCELLED:
            self._resolve_in_flight = False

    def invalidate_cached_default(self) -> None:
        """Drop the cached launch default after provider routing changes."""
        self._cached_default = None
        self._cached_default_failed = False
        self._cached_snapshot = None
        self._cached_default_token = None
        self._schedule_default_resolution_if_needed()
        self._apply_content()

    async def on_click(self) -> None:
        """Open Launch settings."""
        await self.app.run_action("open_models_panel")

    def _schedule_default_resolution_if_needed(self) -> None:
        """Launch the off-thread default-resolution worker, if appropriate."""
        if peek_active_temporary_override() is not None:
            return

        self._resolve_in_flight = True
        self._pending_resolve_token = peek_launch_default_change_token()

        def task() -> _LaunchDefaultSnapshot | None:
            try:
                snapshot = build_launch_model_setting_snapshot(
                    DEFAULT_MODEL_FIELD, consume=False
                )
            except Exception:
                return None
            return _LaunchDefaultSnapshot(
                provider=snapshot.provider,
                model=snapshot.model,
                referenced_alias=snapshot.referenced_alias,
                selector_mode=snapshot.selector_mode,
                member_count=len(snapshot.selector_members),
            )

        self.run_worker(
            task,
            thread=True,
            exclusive=True,
            group=_DEFAULT_WORKER_GROUP,
        )

    def _build_initial_content(self, *, now: float | None = None) -> Text:
        """Render content from cached state without cold provider resolution."""
        override = peek_active_temporary_override(now)
        if override is not None:
            override_content = self._build_override_content(override, now=now)
            if override_content is not None:
                return override_content
        return self._build_cached_default_content()

    def _apply_content(self, *, now: float | None = None) -> None:
        """Update content and tooltip from one current override snapshot."""
        override = peek_active_temporary_override(now)
        if override is not None:
            override_content = self._build_override_content(override, now=now)
            if override_content is not None:
                self.update(override_content)
                self.tooltip = self._build_tooltip(override, now=now)
                return
        self.update(self._build_cached_default_content())
        self.tooltip = self._build_tooltip(None, now=now)

    def _build_cached_default_content(self) -> Text:
        """Render the default-model line using already-resolved values."""
        if self._cached_default is not None:
            label = format_provider_model_label(*self._cached_default)
            return Text(f" {label} ", style=_DEFAULT_STYLE)
        if self._cached_default_failed:
            return Text(_UNAVAILABLE_TEXT, style=_DEFAULT_STYLE)
        return Text(_PLACEHOLDER_TEXT, style=_DEFAULT_STYLE)

    @staticmethod
    def _build_content(
        override: TemporaryLLMOverride | None = None,
        *,
        now: float | None = None,
    ) -> Text:
        """Build the indicator content synchronously (default-resolve path).

        Kept for tests and any caller that explicitly wants a synchronous
        snapshot. Live widget instances use the cached/async path instead.
        """
        override = override if override is not None else get_active_temporary_override()
        if override is not None:
            override_content = LLMOverrideIndicator._build_override_content(
                override,
                now=now,
            )
            if override_content is not None:
                return override_content

        return LLMOverrideIndicator._build_default_content()

    @staticmethod
    def _build_override_content(
        override: TemporaryLLMOverride,
        *,
        now: float | None = None,
    ) -> Text | None:
        """Build the high-signal content for an active temporary override."""
        remaining = format_pill_remaining(override.expires_at, now)
        if remaining is None:
            return None

        return build_override_pill(
            subject=format_provider_model_label(override.provider, override.model),
            effort=override.effort,
            trailing=remaining,
            palette=DEFAULT_LANE_PALETTE,
        )

    def _build_tooltip(
        self,
        override: TemporaryLLMOverride | None,
        *,
        now: float | None = None,
    ) -> str:
        """Build long-form override or launch-default details."""
        if override is not None:
            return "\n".join(
                (
                    "Temporary override on launch default",
                    format_tooltip_target(override),
                    format_tooltip_remaining(override.expires_at, now),
                    "Press ,m for Config > Launch.",
                )
            )

        if self._cached_default is not None:
            default_label = format_provider_model_label(*self._cached_default)
        elif self._cached_default_failed:
            default_label = "unavailable"
        else:
            default_label = "resolving..."

        lines = [f"Launch default: {default_label}"]
        snapshot = self._cached_snapshot
        if snapshot is not None and snapshot.selector_mode == "round_robin":
            subject = (
                f"@{snapshot.referenced_alias}"
                if snapshot.referenced_alias
                else "This launch default"
            )
            lines.append(
                f"{subject} rotates across {snapshot.member_count} models; "
                f"{default_label} is next."
            )
        lines.append("No temporary override active.")
        lines.append("Press ,m for Config > Launch.")
        return "\n".join(lines)

    @staticmethod
    def _build_default_content() -> Text:
        """Build the calm default model content via synchronous resolution."""
        try:
            provider_name, model_name = resolve_effective_default_provider_model()
        except Exception:
            return Text(_UNAVAILABLE_TEXT, style=_DEFAULT_STYLE)

        label = format_provider_model_label(provider_name, model_name)
        return Text(f" {label} ", style=_DEFAULT_STYLE)
