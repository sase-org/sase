"""Shared rendering grammar for ACE top-bar model-override pills.

Both lanes render ``<subject>[@<effort>] <time>`` over a lane-specific accent:
gold for the ``default`` launch lane and violet for every other alias. Subjects
use the primary foreground while effort and trailing state use a recessive,
contrast-safe secondary foreground.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass

from rich.text import Text

from sase.llm_provider.registry import format_provider_model_label
from sase.llm_provider.temporary_override import TemporaryLLMOverride

UNTIL_CLEARED_GLYPH = "∞"


@dataclass(frozen=True)
class _PillPalette:
    """Two-tone foreground palette over one lane accent background."""

    accent: str
    secondary: str

    @property
    def base_style(self) -> str:
        return f"bold #1a1a1a on {self.accent}"

    @property
    def secondary_style(self) -> str:
        return f"not bold {self.secondary} on {self.accent}"


DEFAULT_LANE_PALETTE = _PillPalette(accent="#D7AF5F", secondary="#4F3D18")
ALIAS_LANE_PALETTE = _PillPalette(accent="#AF87FF", secondary="#3A2A5F")


def format_remaining_until(
    expires_at: float | None,
    now: float | None = None,
) -> str:
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


def format_pill_remaining(
    expires_at: float | None,
    now: float | None = None,
) -> str | None:
    """Render remaining time for a pill, collapsing expired overrides."""
    if expires_at is None:
        return UNTIL_CLEARED_GLYPH
    return format_remaining_until(expires_at, now) or None


def format_tooltip_remaining(
    expires_at: float | None,
    now: float | None = None,
) -> str:
    """Render the long-form remaining-time line for a tooltip."""
    if expires_at is None:
        return "Until cleared"
    return f"{format_remaining_until(expires_at, now)} left"


def format_tooltip_target(override: TemporaryLLMOverride) -> str:
    """Render an override target with the canonical spaced effort connective."""
    target = format_provider_model_label(override.provider, override.model)
    if override.effort:
        return f"{target} @ {override.effort}"
    return target


def build_override_pill(
    *,
    subject: str,
    effort: str | None,
    trailing: str,
    palette: _PillPalette,
) -> Text:
    """Build one two-tone ``<subject>[@<effort>] <trailing>`` pill."""
    text = Text(f" {subject}", style=palette.base_style)
    if effort:
        text.append(f"@{effort}", style=palette.secondary_style)
    text.append(f" {trailing} ", style=palette.secondary_style)
    return text
