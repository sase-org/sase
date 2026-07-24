"""Tests for the LLMOverrideIndicator widget rendering."""

from __future__ import annotations

import json
import time

import pytest
from rich.text import Text

from sase.ace.testing import AcePage
from sase.ace.tui.widgets.llm_override_indicator import (
    LLMOverrideIndicator,
    format_remaining_until,
)
from sase.llm_provider.temporary_override import (
    TemporaryLLMOverride,
    _state_path,
)


def _override(
    *,
    provider: str = "codex",
    model: str = "o3",
    expires_at: float | None = 1_000.0,
    effort: str | None = None,
) -> TemporaryLLMOverride:
    """Build a test override."""
    return TemporaryLLMOverride(
        provider=provider,
        model=model,
        raw_model=f"{provider}/{model}",
        created_at=100.0,
        expires_at=expires_at,
        source="test",
        effort=effort,
    )


def test_inactive_renders_default_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sase.ace.tui.widgets.llm_override_indicator.resolve_effective_default_provider_model",
        lambda: ("codex", "gpt-5.6-sol"),
    )

    text = LLMOverrideIndicator._build_content()

    assert text.plain == " CODEX(gpt-5.6-sol) "
    assert "cyan" in str(text.style)


def test_active_override_skips_default_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail() -> tuple[str, str]:
        raise AssertionError("default resolver should not be called")

    monkeypatch.setattr(
        "sase.ace.tui.widgets.llm_override_indicator.resolve_effective_default_provider_model",
        fail,
    )

    text = LLMOverrideIndicator._build_content(_override(expires_at=3_820.0), now=100.0)

    assert text.plain == " Override CODEX(o3) 1h2m "


def test_active_with_expiry_renders_label_and_countdown() -> None:
    text = LLMOverrideIndicator._build_content(_override(expires_at=3_820.0), now=100.0)

    assert text.plain == " Override CODEX(o3) 1h2m "
    assert "#D7AF5F" in str(text.style)


def test_active_override_renders_effort() -> None:
    text = LLMOverrideIndicator._build_content(
        _override(expires_at=3_820.0, effort="medium"),
        now=100.0,
    )

    assert text.plain == " Override CODEX(o3)@medium 1h2m "


def test_active_until_cleared_renders_without_countdown() -> None:
    text = LLMOverrideIndicator._build_content(_override(expires_at=None), now=100.0)

    assert text.plain == " Override CODEX(o3) until cleared "


def test_expired_override_renders_default_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.ace.tui.widgets.llm_override_indicator.resolve_effective_default_provider_model",
        lambda: ("claude", "sonnet"),
    )

    text = LLMOverrideIndicator._build_content(_override(expires_at=99.0), now=100.0)

    assert text.plain == " CLAUDE(sonnet) "


def test_expired_state_file_is_cleaned_up(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sase.ace.tui.widgets.llm_override_indicator.resolve_effective_default_provider_model",
        lambda: ("claude", "sonnet"),
    )
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "provider": "codex",
                "model": "o3",
                "raw_model": "codex/o3",
                "created_at": time.time() - 120,
                "expires_at": time.time() - 60,
                "source": "test",
            }
        ),
        encoding="utf-8",
    )

    text = LLMOverrideIndicator._build_content()

    assert text.plain == " CLAUDE(sonnet) "
    assert not path.exists()


def test_long_override_label_renders_fully() -> None:
    text = LLMOverrideIndicator._build_content(
        _override(provider="verylongprovider", model="extremely-long-model-name"),
        now=100.0,
    )

    assert text.plain == " Override VERYLONGPROVIDER(extremely-long-model-name) 15m "


def test_long_default_label_renders_fully(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.ace.tui.widgets.llm_override_indicator.resolve_effective_default_provider_model",
        lambda: ("verylongprovider", "extremely-long-model-name"),
    )

    text = LLMOverrideIndicator._build_content()

    assert text.plain == " VERYLONGPROVIDER(extremely-long-model-name) "


def test_default_resolution_failure_renders_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail() -> tuple[str, str]:
        raise RuntimeError("no provider")

    monkeypatch.setattr(
        "sase.ace.tui.widgets.llm_override_indicator.resolve_effective_default_provider_model",
        fail,
    )

    text = LLMOverrideIndicator._build_content()

    assert text.plain == " unavailable "


def test_remaining_subminute_rounds_up_to_one_minute() -> None:
    assert format_remaining_until(130.0, now=100.0) == "1m"


async def test_llm_override_indicator_is_mounted() -> None:
    async with AcePage() as page:
        indicator = page.query_one_widget(
            "#llm-override-indicator", LLMOverrideIndicator
        )

    assert isinstance(indicator, LLMOverrideIndicator)


def test_init_skips_cold_default_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    """``__init__`` must not trigger ``resolve_effective_default_provider_model``."""

    def fail() -> tuple[str, str]:
        raise AssertionError("default resolver should not be called during init")

    monkeypatch.setattr(
        "sase.ace.tui.widgets.llm_override_indicator.resolve_effective_default_provider_model",
        fail,
    )

    indicator = LLMOverrideIndicator()

    rendered = indicator._build_initial_content()
    assert isinstance(rendered, Text)
    assert rendered.plain == " ... "
    assert "cyan" in str(rendered.style)
    assert indicator._cached_default is None
    assert indicator._cached_default_failed is False


async def test_async_default_resolution_updates_cached_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The async resolver path populates the cached default once mounted."""

    monkeypatch.setattr(
        "sase.ace.tui.widgets.llm_override_indicator.resolve_effective_default_provider_model",
        lambda: ("claude", "sonnet"),
    )

    async with AcePage() as page:
        indicator = page.query_one_widget(
            "#llm-override-indicator", LLMOverrideIndicator
        )
        cached: tuple[str, str] | None = None
        for _ in range(20):
            await page.pause()
            cached = indicator._cached_default
            if cached is not None:
                break

    assert cached == ("claude", "sonnet")
    rendered = indicator._build_initial_content()
    assert isinstance(rendered, Text)
    assert rendered.plain == " CLAUDE(sonnet) "
