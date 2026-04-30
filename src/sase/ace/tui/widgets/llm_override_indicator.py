"""LLM model status indicator for the ace TUI top bar."""

from __future__ import annotations

import math
import time
from typing import Any

from rich.text import Text
from textual.widgets import Static

from sase.llm_provider.registry import format_provider_model_label
from sase.llm_provider.temporary_override import (
    TemporaryLLMOverride,
    get_active_temporary_override,
    resolve_effective_default_provider_model,
)

_ACTIVE_STYLE = "bold #1a1a1a on #D7AF5F"
_DEFAULT_STYLE = "dim cyan"


def _format_remaining_until(expires_at: float | None, now: float | None = None) -> str:
    """Render an expiry timestamp as a compact remaining-time label."""
    if expires_at is None:
        return "until cleared"

    current = time.time() if now is None else now
    remaining = expires_at - current
    if remaining <= 0:
        return ""

    total_minutes = max(1, math.ceil(remaining / 60.0))
    hours, minutes = divmod(total_minutes, 60)
    if hours and minutes:
        return f"{hours}h{minutes}m"
    if hours:
        return f"{hours}h"
    return f"{minutes}m"


class LLMOverrideIndicator(Static):
    """Shows the default model or active temporary override in the top bar."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(self._build_content(), **kwargs)

    def on_mount(self) -> None:
        """Refresh immediately, then keep the countdown fresh."""
        self.refresh()
        self.set_interval(30.0, self.refresh)

    def refresh(self, *args: Any, **kwargs: Any) -> Any:
        """Refresh indicator content, preserving Widget.refresh kwargs."""
        if args or kwargs:
            return super().refresh(*args, **kwargs)
        self.update(self._build_content())
        return super().refresh()

    @staticmethod
    def _build_content(
        override: TemporaryLLMOverride | None = None,
        *,
        now: float | None = None,
    ) -> Text:
        """Build the indicator content for the current model state."""
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
        remaining = _format_remaining_until(override.expires_at, now)
        if not remaining:
            return None

        label = format_provider_model_label(override.provider, override.model)
        return Text(f" Override {label} {remaining} ", style=_ACTIVE_STYLE)

    @staticmethod
    def _build_default_content() -> Text:
        """Build the calm default model content."""
        try:
            provider_name, model_name = resolve_effective_default_provider_model()
        except Exception:
            return Text(" unavailable ", style=_DEFAULT_STYLE)

        label = format_provider_model_label(provider_name, model_name)
        return Text(f" {label} ", style=_DEFAULT_STYLE)
