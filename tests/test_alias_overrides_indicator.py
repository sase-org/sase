"""Tests for the AliasOverridesIndicator widget rendering.

Phase 4 (epic sase-5e): the concise, uniform top-bar pill that surfaces
temporary overrides on *non-*``default`` aliases, next to the gold ``default``
pill rendered by :class:`LLMOverrideIndicator`.
"""

from __future__ import annotations

import pytest
from rich.text import Text

from sase.ace.testing import AcePage
from sase.ace.tui.widgets.alias_overrides_indicator import (
    AliasOverridesIndicator,
    _ACTIVE_STYLE,
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
        {"coder": _override(expires_at=3_820.0)}, now=100.0
    )

    assert text.plain == " Override @coder 1h2m "
    assert "#AF87FF" in str(text.style)


def test_single_override_until_cleared_renders_without_countdown() -> None:
    text = AliasOverridesIndicator._build_content(
        {"phase_worker": _override(expires_at=None)}, now=100.0
    )

    assert text.plain == " Override @phase_worker until cleared "


def test_single_override_renders_effort_suffix() -> None:
    text = AliasOverridesIndicator._build_content(
        {"coder": _override(expires_at=None, effort="medium")},
        now=100.0,
    )

    assert text.plain == " Override @coder@medium until cleared "


def test_single_expired_override_renders_empty() -> None:
    # Live reads prune expired entries, but the direct-call path must still
    # collapse to nothing rather than show a zero-time pill.
    text = AliasOverridesIndicator._build_content(
        {"coder": _override(expires_at=99.0)}, now=100.0
    )

    assert text.plain == ""


def test_multiple_overrides_render_terse_count() -> None:
    text = AliasOverridesIndicator._build_content(
        {
            "coder": _override(expires_at=3_820.0),
            "phase_worker": _override(expires_at=None),
            "fast": _override(expires_at=5_000.0),
        },
        now=100.0,
    )

    assert text.plain == " Overrides ×3 "
    assert str(text.style) == _ACTIVE_STYLE


# ---------------------------------------------------------------------------
# _active_non_default_overrides — the ``default`` lane is excluded
# ---------------------------------------------------------------------------


def test_active_non_default_overrides_drops_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        f"{_MODULE}.get_active_alias_overrides",
        lambda: {
            "default": _override(),
            "coder": _override(model="gpt-5.6-sol"),
        },
    )

    result = AliasOverridesIndicator._active_non_default_overrides()

    assert set(result) == {"coder"}


def test_default_only_override_renders_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        f"{_MODULE}.get_active_alias_overrides",
        lambda: {"default": _override()},
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
            "default": _override(),
            "coder": _override(model="gpt-5.6-sol", expires_at=None),
        },
    )

    rendered = AliasOverridesIndicator()._build_initial_content()

    assert isinstance(rendered, Text)
    assert rendered.plain == " Override @coder until cleared "


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

        overrides["coder"] = _override(expires_at=None)
        indicator.refresh()
        await page.pause()

    assert indicator._build_initial_content().plain == " Override @coder until cleared "
