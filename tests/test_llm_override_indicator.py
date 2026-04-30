"""Tests for the LLMOverrideIndicator widget rendering."""

from __future__ import annotations

import json
import time

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.widgets.llm_override_indicator import (
    LLMOverrideIndicator,
    _elide_middle,
    _format_remaining_until,
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
) -> TemporaryLLMOverride:
    """Build a test override."""
    return TemporaryLLMOverride(
        provider=provider,
        model=model,
        raw_model=f"{provider}/{model}",
        created_at=100.0,
        expires_at=expires_at,
        source="test",
    )


def test_inactive_renders_default_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sase.ace.tui.widgets.llm_override_indicator.resolve_effective_default_provider_model",
        lambda: ("codex", "gpt-5.5"),
    )

    text = LLMOverrideIndicator._build_content()

    assert text.plain == " Model CODEX(gpt-5.5) "
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

    assert text.plain == " Model CLAUDE(sonnet) "


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

    assert text.plain == " Model CLAUDE(sonnet) "
    assert not path.exists()


def test_long_label_is_elided_in_the_middle() -> None:
    text = LLMOverrideIndicator._build_content(
        _override(provider="verylongprovider", model="extremely-long-model-name"),
        now=100.0,
        label_max_width=18,
    )

    assert text.plain == " Override VERYLONG...l-name) 15m "


def test_long_default_label_is_elided_in_the_middle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.ace.tui.widgets.llm_override_indicator.resolve_effective_default_provider_model",
        lambda: ("verylongprovider", "extremely-long-model-name"),
    )

    text = LLMOverrideIndicator._build_content(label_max_width=18)

    assert text.plain == " Model VERYLONG...l-name) "


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

    assert text.plain == " Model unavailable "


def test_elide_middle_handles_short_labels() -> None:
    assert _elide_middle("CODEX(o3)", 24) == "CODEX(o3)"


def test_remaining_subminute_rounds_up_to_one_minute() -> None:
    assert _format_remaining_until(130.0, now=100.0) == "1m"


async def test_llm_override_indicator_is_mounted() -> None:
    async with AcePage() as page:
        indicator = page.query_one_widget(
            "#llm-override-indicator", LLMOverrideIndicator
        )

    assert isinstance(indicator, LLMOverrideIndicator)
