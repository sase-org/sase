"""Tests for the ProviderDisablesIndicator top-bar pill."""

from __future__ import annotations

import pytest
from rich.text import Text

from sase.ace.testing import AcePage
from sase.ace.tui.widgets.provider_disables_indicator import (
    ProviderDisablesIndicator,
    _ACTIVE_STYLE,
)
from sase.llm_provider.provider_disable import (
    PROVIDER_DISABLE_WIRE_SCHEMA_VERSION,
    TemporaryProviderDisable,
)

_MODULE = "sase.ace.tui.widgets.provider_disables_indicator"


def _disable(
    provider: str = "claude",
    *,
    expires_at: float | None = 1_000.0,
    source: str = "test",
) -> TemporaryProviderDisable:
    return TemporaryProviderDisable(
        version=PROVIDER_DISABLE_WIRE_SCHEMA_VERSION,
        provider=provider,
        created_at=100.0,
        expires_at=expires_at,
        source=source,
    )


def test_no_provider_disables_renders_empty() -> None:
    assert ProviderDisablesIndicator._build_content({}).plain == ""


def test_single_provider_disable_renders_countdown() -> None:
    text = ProviderDisablesIndicator._build_content(
        {"claude": _disable(expires_at=3_820.0)},
        now=100.0,
    )

    assert text.plain == " CLAUDE off 1h2m "
    assert str(text.style) == _ACTIVE_STYLE


def test_single_provider_disable_until_cleared_renders_infinity() -> None:
    text = ProviderDisablesIndicator._build_content(
        {"claude": _disable(expires_at=None)},
        now=100.0,
    )

    assert text.plain == " CLAUDE off ∞ "


def test_multiple_provider_disables_name_first_provider_and_count_rest() -> None:
    text = ProviderDisablesIndicator._build_content(
        {
            "grok": _disable("grok", expires_at=3_820.0),
            "claude": _disable("claude", expires_at=None),
            "codex": _disable("codex", expires_at=5_000.0),
        },
        now=100.0,
    )

    assert text.plain == " CLAUDE +2 "


def test_expired_provider_disable_renders_empty() -> None:
    text = ProviderDisablesIndicator._build_content(
        {"claude": _disable(expires_at=99.0)},
        now=100.0,
    )

    assert text.plain == ""


def test_tooltip_lists_active_provider_disables() -> None:
    tooltip = ProviderDisablesIndicator._build_tooltip(
        {
            "claude": _disable("claude", expires_at=None, source="ace"),
            "codex": _disable("codex", expires_at=3_820.0, source="usage_limit"),
            "grok": _disable("grok", expires_at=4_000.0, source="external_plugin"),
        },
        now=100.0,
    )

    assert tooltip == (
        "Disabled providers:\n"
        "CLAUDE - manual, until cleared\n"
        "CODEX - usage-limit automatic, 1h2m left\n"
        "GROK - external plugin, 1h5m left\n"
        "New launches route around them; running processes continue.\n"
        "Press ,m for Launch Control."
    )


def test_initial_content_uses_peek_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        f"{_MODULE}.peek_active_provider_disables",
        lambda: {"claude": _disable(expires_at=None)},
    )

    rendered = ProviderDisablesIndicator()._build_initial_content()

    assert isinstance(rendered, Text)
    assert rendered.plain == " CLAUDE off ∞ "


async def test_provider_disables_indicator_is_mounted() -> None:
    async with AcePage() as page:
        indicator = page.query_one_widget(
            "#provider-disables-indicator",
            ProviderDisablesIndicator,
        )

    assert isinstance(indicator, ProviderDisablesIndicator)


async def test_click_opens_models_panel(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    async with AcePage() as page:
        monkeypatch.setattr(
            page.app,
            "_open_models_panel",
            lambda: calls.append("opened"),
        )
        indicator = page.query_one_widget(
            "#provider-disables-indicator",
            ProviderDisablesIndicator,
        )
        await indicator.on_click()
        await page.pause()

    assert calls == ["opened"]
