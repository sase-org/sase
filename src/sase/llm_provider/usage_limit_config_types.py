"""Dataclasses for usage-limit detection configuration."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ProviderUsageLimitConfig:
    """Per-provider usage-limit detection configuration."""

    patterns: list[str] = field(default_factory=list)
    exclude_patterns: list[str] = field(default_factory=list)
    disable_seconds: int | None = None  # None => fall back to global default
    honor_reset_hint: bool | None = None  # None => fall back to global default


@dataclass
class UsageLimitSettings:
    """Resolved global usage-limit settings."""

    enabled: bool = True
    disable_seconds: int = 86400  # 24h fallback when no reset hint is honored
    min_disable_seconds: int = 60
    max_disable_seconds: int = 604800  # 7d cap on any parsed reset time
    honor_reset_hint: bool = True
    notify: bool = True


@dataclass(frozen=True)
class UsageLimitDetection:
    """Result of matching a provider failure against its usage-limit config."""

    provider: str
    matched_pattern: str
    message: str  # normalized, truncated trigger snippet
    raw_message: str  # untruncated original, for the notification body
    disable_seconds: float
    expires_at: float | None
    reset_hint: str | None  # e.g. "8pm (America/New_York)" when parsed
    used_reset_hint: bool
