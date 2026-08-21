"""Tests for the AliasOverridesIndicator widget rendering.

Phase 4 (epic sase-5e): the concise, uniform top-bar pill that surfaces
temporary overrides on aliases other than the launch-default setting, next to
the gold default pill rendered by :class:`LLMOverrideIndicator`.
"""

from __future__ import annotations

import pytest
from rich.text import Text

from sase.ace.testing import AcePage
from sase.ace.tui.widgets.alias_overrides_indicator import (
    AliasOverridesIndicator,
    _ACTIVE_STYLE,
)
from sase.llm_provider.config import (
    DEFAULT_MODEL_FIELD,
    launch_model_setting_override_key,
)
from sase.llm_provider.temporary_override import TemporaryLLMOverride

_MODULE = "sase.ace.tui.widgets.alias_overrides_indicator"


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


# ---------------------------------------------------------------------------
# _build_content — pure rendering across states
# ---------------------------------------------------------------------------


def test_no_overrides_renders_empty() -> None:
    text = AliasOverridesIndicator._build_content({})

    assert text.plain == ""


def test_single_override_renders_alias_and_countdown() -> None:
    text = AliasOverridesIndicator._build_content(
        {"medium": _override(expires_at=3_820.0)}, now=100.0
    )

    assert text.plain == " @medium 1h2m "
    assert "#AF87FF" in str(text.style)


def test_single_override_until_cleared_renders_without_countdown() -> None:
    text = AliasOverridesIndicator._build_content(
        {"worker": _override(expires_at=None)}, now=100.0
    )

    assert text.plain == " @worker ∞ "


def test_single_override_renders_effort_suffix() -> None:
    text = AliasOverridesIndicator._build_content(
        {"medium": _override(expires_at=None, effort="medium")},
        now=100.0,
    )

    assert text.plain == " @medium@medium ∞ "
    assert str(text.style) == _ACTIVE_STYLE
    styled_segments = [
        (text.plain[span.start : span.end], str(span.style)) for span in text.spans
    ]
    assert ("@medium", "not bold #3A2A5F on #AF87FF") in styled_segments
    assert (" ∞ ", "not bold #3A2A5F on #AF87FF") in styled_segments


def test_single_expired_override_renders_empty() -> None:
    # Live reads prune expired entries, but the direct-call path must still
    # collapse to nothing rather than show a zero-time pill.
    text = AliasOverridesIndicator._build_content(
        {"medium": _override(expires_at=99.0)}, now=100.0
    )

    assert text.plain == ""


def test_multiple_overrides_name_first_alias_and_count_rest() -> None:
    text = AliasOverridesIndicator._build_content(
        {
            "zeta": _override(expires_at=3_820.0),
            "alpha": _override(expires_at=None),
            "mid": _override(expires_at=5_000.0),
        },
        now=100.0,
    )

    assert text.plain == " @alpha +2 "
    assert str(text.style) == _ACTIVE_STYLE


def test_multiple_overrides_prune_expired_entries_before_rendering() -> None:
    text = AliasOverridesIndicator._build_content(
        {
            "alpha": _override(expires_at=99.0),
            "medium": _override(expires_at=None),
            "zeta": _override(expires_at=50.0),
        },
        now=100.0,
    )

    assert text.plain == " @medium ∞ "


def test_tooltip_is_none_without_active_overrides() -> None:
    assert AliasOverridesIndicator._build_tooltip({}) is None
    assert (
        AliasOverridesIndicator._build_tooltip(
            {"expired": _override(expires_at=99.0)},
            now=100.0,
        )
        is None
    )


def test_tooltip_describes_single_override_target_and_effort() -> None:
    tooltip = AliasOverridesIndicator._build_tooltip(
        {
            "medium": _override(
                provider="claude",
                model="opus",
                effort="xhigh",
                expires_at=3_820.0,
            )
        },
        now=100.0,
    )

    assert tooltip == (
        "Temporary model overrides:\n"
        "@medium -> CLAUDE(opus) @ xhigh - 1h2m left\n"
        "Press ,m for Config > Launch."
    )


def test_tooltip_sorts_multiple_overrides_and_describes_until_cleared() -> None:
    tooltip = AliasOverridesIndicator._build_tooltip(
        {
            "fast": _override(provider="claude", model="haiku", expires_at=None),
            "medium": _override(
                provider="claude",
                model="opus",
                effort="xhigh",
                expires_at=3_820.0,
            ),
        },
        now=100.0,
    )

    assert tooltip == (
        "Temporary model overrides:\n"
        "@fast -> CLAUDE(haiku) - until cleared\n"
        "@medium -> CLAUDE(opus) @ xhigh - 1h2m left\n"
        "Press ,m for Config > Launch."
    )


# ---------------------------------------------------------------------------
# _active_non_default_overrides — the ``default`` lane is excluded
# ---------------------------------------------------------------------------


def test_active_non_default_overrides_drops_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        f"{_MODULE}.get_active_alias_overrides",
        lambda: {
            launch_model_setting_override_key(DEFAULT_MODEL_FIELD): _override(),
            "medium": _override(model="gpt-5.6-sol"),
        },
    )

    result = AliasOverridesIndicator._active_non_default_overrides()

    assert set(result) == {"medium"}


def test_default_only_override_renders_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        f"{_MODULE}.get_active_alias_overrides",
        lambda: {launch_model_setting_override_key(DEFAULT_MODEL_FIELD): _override()},
    )

    rendered = AliasOverridesIndicator()._build_initial_content()

    assert isinstance(rendered, Text)
    assert rendered.plain == ""


def test_initial_content_reflects_non_default_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        f"{_MODULE}.get_active_alias_overrides",
        lambda: {
            launch_model_setting_override_key(DEFAULT_MODEL_FIELD): _override(),
            "medium": _override(model="gpt-5.6-sol", expires_at=None),
        },
    )

    rendered = AliasOverridesIndicator()._build_initial_content()

    assert isinstance(rendered, Text)
    assert rendered.plain == " @medium ∞ "


# ---------------------------------------------------------------------------
# Mounting + live refresh inside the app
# ---------------------------------------------------------------------------


async def test_alias_overrides_indicator_is_mounted() -> None:
    async with AcePage() as page:
        indicator = page.query_one_widget(
            "#alias-overrides-indicator", AliasOverridesIndicator
        )

    assert isinstance(indicator, AliasOverridesIndicator)


async def test_refresh_picks_up_new_non_default_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    overrides: dict[str, TemporaryLLMOverride] = {}
    monkeypatch.setattr(
        f"{_MODULE}.get_active_alias_overrides",
        lambda: dict(overrides),
    )

    async with AcePage() as page:
        indicator = page.query_one_widget(
            "#alias-overrides-indicator", AliasOverridesIndicator
        )
        assert indicator._build_initial_content().plain == ""

        overrides["medium"] = _override(expires_at=None)
        indicator.refresh()
        await page.pause()

    assert indicator._build_initial_content().plain == " @medium ∞ "


async def test_click_opens_models_panel(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    async with AcePage() as page:
        monkeypatch.setattr(
            page.app,
            "_open_models_panel",
            lambda: calls.append("opened"),
        )
        indicator = page.query_one_widget(
            "#alias-overrides-indicator", AliasOverridesIndicator
        )
        await indicator.on_click()
        await page.pause()

    assert calls == ["opened"]
