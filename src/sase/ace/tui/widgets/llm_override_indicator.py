"""LLM model status indicator for sase's TUI top bar."""

from __future__ import annotations

from typing import Any

from rich.text import Text
from textual.widgets import Static

from sase.ace.tui.provider_styles import ProviderTextPalette, provider_text_palette
from sase.llm_provider.config import resolve_effective_effort
from sase.llm_provider.model_directive_label import format_model_directive_label
from sase.llm_provider.model_launch_settings import (
    DEFAULT_MODEL_FIELD,
    build_launch_model_setting_snapshot,
)
from sase.llm_provider.registry import format_provider_model_label
from sase.llm_provider.temporary_override import (
    TemporaryLLMOverride,
    get_active_temporary_override,
    peek_active_temporary_override,
    resolve_effective_default_provider_model as resolve_effective_default_provider_model,
)
from sase.xprompt.directives import PromptDirectives

from ._override_pill import (
    DEFAULT_LANE_PALETTE,
    build_calm_default_pill,
    build_override_pill,
    format_pill_remaining,
    format_tooltip_remaining,
    format_tooltip_target,
)
from .launch_context_source import (
    LaunchContextSource,
    LaunchContextState,
    LaunchDefaultSnapshot,
)

_ACTIVE_STYLE = DEFAULT_LANE_PALETTE.base_style
# Neutral tone for the calm lane's unresolved states (and the no-snapshot
# fallback): the pill must never guess a provider hue before resolution lands.
_DEFAULT_STYLE = "dim cyan"
_NEUTRAL_DEFAULT_PALETTE = ProviderTextPalette(
    subject_style=_DEFAULT_STYLE,
    detail_style=_DEFAULT_STYLE,
)
_PLACEHOLDER_TEXT = " ... "
_UNAVAILABLE_TEXT = " unavailable "


class LLMOverrideIndicator(Static):
    """Shows the default model or active temporary override in the top bar.

    A render-only view over :class:`LaunchContextSource`: all polling and
    resolution lives in the app-scoped source, which pushes fresh state here
    via :meth:`apply_launch_context`. The cached fields below are the view's
    render inputs -- the source copies its state into them on broadcast, and
    ``refresh()`` re-pulls them -- so content and tooltip builders stay pure
    functions of already-resolved values.
    """

    def __init__(self, **kwargs: Any) -> None:
        self._cached_default: tuple[str, str] | None = None
        self._cached_default_failed = False
        self._cached_snapshot: LaunchDefaultSnapshot | None = None
        self._cached_default_token: tuple[object, ...] | None = None
        self._override: TemporaryLLMOverride | None = None
        super().__init__(self._build_initial_content(), **kwargs)
        self.tooltip = self._build_tooltip(peek_active_temporary_override())

    def on_mount(self) -> None:
        """Paint the source's current state (instantly resolved, no placeholder)."""

        state = self._source_state()
        if state is not None:
            self.apply_launch_context(state)
        else:
            self._apply_content()

    def refresh(self, *args: Any, **kwargs: Any) -> Any:
        """Re-render from the source state, preserving Widget.refresh kwargs."""
        if args or kwargs:
            return super().refresh(*args, **kwargs)

        state = self._source_state()
        if state is not None:
            self.apply_launch_context(state)
        else:
            self._apply_content()
        return super().refresh()

    def apply_launch_context(self, state: LaunchContextState) -> None:
        """Copy broadcast source state into the render inputs and repaint."""

        snapshot = state.default_snapshot
        self._cached_default = (
            None if snapshot is None else (snapshot.provider, snapshot.model)
        )
        self._cached_snapshot = snapshot
        self._cached_default_failed = state.default_failed
        self._cached_default_token = state.default_token
        self._override = state.override
        self._apply_content()

    async def on_click(self) -> None:
        """Open Launch settings."""
        await self.app.run_action("open_models_panel")

    def _source_state(self) -> LaunchContextState | None:
        """Return the app-scoped source state, or ``None`` when unmounted."""

        if not self.is_attached:
            return None
        try:
            source = self.app.query_one("#launch-context-source", LaunchContextSource)
        except Exception:  # noqa: BLE001 - unmounted views degrade to cache.
            return None
        return source.state

    def _build_initial_content(self, *, now: float | None = None) -> Text:
        """Render content from cached state without cold provider resolution."""
        override = peek_active_temporary_override(now)
        if override is not None:
            override_content = self._build_override_content(override, now=now)
            if override_content is not None:
                return override_content
        return self._build_cached_default_content()

    def _apply_content(self, *, now: float | None = None) -> None:
        """Update content and tooltip from the applied source state."""
        override = self._override
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
            snapshot = self._cached_snapshot
            effort = None if snapshot is None else snapshot.effort
            subject = None if snapshot is None else snapshot.directive_label
            if not subject:
                subject = format_provider_model_label(*self._cached_default)
            palette = None if snapshot is None else snapshot.palette
            return build_calm_default_pill(
                subject=subject,
                effort=effort,
                palette=palette or _NEUTRAL_DEFAULT_PALETTE,
            )
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
            effort = (
                None if self._cached_snapshot is None else self._cached_snapshot.effort
            )
            default_label = _format_default_tooltip_label(*self._cached_default, effort)
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
            snapshot = build_launch_model_setting_snapshot(
                DEFAULT_MODEL_FIELD, consume=False
            )
            level, _explicit = resolve_effective_effort(
                PromptDirectives(),
                snapshot.effort,
            )
            subject = format_model_directive_label(snapshot.provider, snapshot.model)
            palette = provider_text_palette(snapshot.provider)
        except Exception:
            return Text(_UNAVAILABLE_TEXT, style=_DEFAULT_STYLE)

        return build_calm_default_pill(subject=subject, effort=level, palette=palette)


def _format_default_tooltip_label(provider: str, model: str, effort: str | None) -> str:
    """Render the spaced calm-default tooltip target."""
    label = format_provider_model_label(provider, model)
    if effort:
        return f"{label} @ {effort}"
    return label
