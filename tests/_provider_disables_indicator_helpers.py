"""Shared helpers for ProviderDisablesIndicator tests."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from rich.console import Console
from rich.style import Style
from rich.text import Text

from sase.ace.tui.widgets._provider_usage_indicator import UsageBadge
from sase.llm_provider.provider_disable import (
    PROVIDER_DISABLE_WIRE_SCHEMA_VERSION,
    TemporaryProviderDisable,
)
from sase.llm_provider.provider_priority import (
    PROVIDER_PRIORITY_WIRE_SCHEMA_VERSION,
    TemporaryProviderPriority,
    provider_availability_facts,
)

_MODULE = "sase.ace.tui.widgets.provider_disables_indicator"
_CONSOLE = Console(width=200)
_FROZEN_NOW = 1_800_000_000.0


def _segments_with_offsets(text: Text) -> list[tuple[int, int, Style | None]]:
    """Return each non-empty rendered run's resolved style, keyed by text offsets."""
    offset = 0
    result: list[tuple[int, int, Style | None]] = []
    for segment in text.render(_CONSOLE):
        length = len(segment.text)
        if length:
            result.append((offset, offset + length, segment.style))
        offset += length
    return result


def _usage_entry(
    *,
    provider: str,
    remaining_percent: float,
) -> dict[str, object]:
    return {
        "provider": provider,
        "window_key": "weekly",
        "window_label": "Week - all",
        "weekly_all": True,
        "period": {"kind": "weekly", "duration_seconds": 604_800.0},
        "scope": {"kind": "all_models"},
        "remaining_percent": remaining_percent,
        "used_percent": max(0.0, 100.0 - remaining_percent),
        "freshness": "fresh",
        "reset_state": "future",
        "seconds_until_reset": 273_840.0,
        "resets_at": _FROZEN_NOW + 273_840.0,
        "vendor_state": "allowed",
        "display_attention": "none",
        "collector_problem": False,
        "policy_source": "weekly_all",
        "effective_policy": {"kind": "always"},
    }


def _disable(
    provider: str = "claude",
    *,
    expires_at: float | None = 1_000.0,
    source: str = "test",
    mode: str = "hard",
) -> TemporaryProviderDisable:
    return TemporaryProviderDisable(
        version=PROVIDER_DISABLE_WIRE_SCHEMA_VERSION,
        provider=provider,
        created_at=100.0,
        expires_at=expires_at,
        source=source,
        mode=mode,
    )


def _priority(
    provider: str = "codex",
    *,
    expires_at: float | None = 1_000.0,
    source: str = "test",
) -> TemporaryProviderPriority:
    return TemporaryProviderPriority(
        version=PROVIDER_PRIORITY_WIRE_SCHEMA_VERSION,
        provider=provider,
        created_at=100.0,
        expires_at=expires_at,
        source=source,
    )


def _patch_priority_facts(
    monkeypatch: pytest.MonkeyPatch,
    *,
    cli_available: bool = True,
    registered: bool = True,
    user_facing: bool = True,
) -> None:
    monkeypatch.setattr(
        f"{_MODULE}.provider_routing_facts",
        lambda provider: provider_availability_facts(
            provider,
            registered=registered,
            user_facing=user_facing,
            cli_available=cli_available,
        ),
    )


def _usage_badges() -> tuple[UsageBadge, UsageBadge]:
    return (
        UsageBadge(
            provider="grok",
            text=Text("🛰️ ! 0% 3d4h"),
            tooltip_lines=("GROK - rejected · 0% left · Week · all",),
        ),
        UsageBadge(
            provider="codex",
            text=Text("🤖 12% 3d4h"),
            tooltip_lines=("CODEX - low · 12% left · Shared 5h",),
        ),
    )


def _mock_usage_projection(monkeypatch: pytest.MonkeyPatch) -> None:
    """Serve one fixed usage entry through the real badge-building pipeline."""
    projection = SimpleNamespace(
        entries=(_usage_entry(provider="grok", remaining_percent=7.0),),
        providers=(),
        generated_at=_FROZEN_NOW,
    )
    monkeypatch.setattr(
        f"{_MODULE}.cached_usage_indicator_projection",
        lambda **_kwargs: projection,
    )
