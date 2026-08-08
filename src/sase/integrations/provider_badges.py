"""Presentation-neutral provider badges for integrations."""

from __future__ import annotations

__all__ = ["provider_emoji_badge"]

_PROVIDER_EMOJI_BADGES: dict[str, str] = {
    "claude": "🎭",
    "anthropic": "🎭",
    "codex": "🤖",
    "fakey": "🧪",
    "openai": "🤖",
    "qwen": "🐼",
    "opencode": "🐙",
    "agy": "🪐",
    "muse": "♾️",
    "meta": "♾️",
}


def _normalize_provider(provider: str | None) -> str | None:
    if provider is None:
        return None
    normalized = provider.strip().lower()
    return normalized or None


def provider_emoji_badge(provider: str | None) -> str | None:
    """Return the compact row emoji for known LLM providers."""
    normalized = _normalize_provider(provider)
    if normalized is None:
        return None
    return _PROVIDER_EMOJI_BADGES.get(normalized)
