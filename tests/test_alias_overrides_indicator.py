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


# ---------------------------------------------------------------------------
# _build_combined_content / _build_combined_tooltip — merged overrides group
# ---------------------------------------------------------------------------


def _combined_disable(
    provider: str = "claude",
    *,
    expires_at: float | None = None,
):
    from sase.llm_provider.provider_disable import (
        PROVIDER_DISABLE_WIRE_SCHEMA_VERSION,
        TemporaryProviderDisable,
    )

    return TemporaryProviderDisable(
        version=PROVIDER_DISABLE_WIRE_SCHEMA_VERSION,
        provider=provider,
        created_at=100.0,
        expires_at=expires_at,
        source="test",
    )


def _combined_priority(
    provider: str = "codex",
    *,
    expires_at: float | None = None,
):
    from sase.llm_provider.provider_priority import (
        PROVIDER_PRIORITY_WIRE_SCHEMA_VERSION,
        TemporaryProviderPriority,
    )

    return TemporaryProviderPriority(
        version=PROVIDER_PRIORITY_WIRE_SCHEMA_VERSION,
        provider=provider,
        created_at=100.0,
        expires_at=expires_at,
        source="test",
    )


def _combined_context(
    disables: dict | None = None,
    priority=None,
):
    from sase.llm_provider.provider_priority import provider_routing_context_from_parts

    return provider_routing_context_from_parts(
        disables or {},
        priority,
        captured_at=100.0,
    )


def test_combined_alias_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests._provider_disables_indicator_helpers import _patch_priority_facts

    _patch_priority_facts(monkeypatch)
    overrides = {"medium": _override(expires_at=None, effort="max")}
    context = _combined_context()

    body = AliasOverridesIndicator._build_combined_content(
        overrides, context, now=100.0
    )

    assert body.plain == " @medium@max ∞ "


def test_combined_priority_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests._provider_disables_indicator_helpers import _patch_priority_facts

    _patch_priority_facts(monkeypatch)
    context = _combined_context(priority=_combined_priority())

    body = AliasOverridesIndicator._build_combined_content({}, context, now=100.0)

    assert body.plain == " CODEX ★ ∞ "


def test_combined_disable_only() -> None:
    context = _combined_context({"claude": _combined_disable()})

    body = AliasOverridesIndicator._build_combined_content({}, context, now=100.0)

    assert body.plain == " CLAUDE off ∞ "


def test_combined_all_three(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests._provider_disables_indicator_helpers import _patch_priority_facts

    _patch_priority_facts(monkeypatch)
    overrides = {"medium": _override(expires_at=None, effort="max")}
    context = _combined_context(
        {"claude": _combined_disable()},
        _combined_priority(),
    )

    body = AliasOverridesIndicator._build_combined_content(
        overrides, context, now=100.0
    )

    assert body.plain == " @medium@max ∞  CODEX ★ ∞  CLAUDE off ∞ "


def test_combined_none_renders_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests._provider_disables_indicator_helpers import _patch_priority_facts

    _patch_priority_facts(monkeypatch)
    context = _combined_context()

    body = AliasOverridesIndicator._build_combined_content({}, context, now=100.0)

    assert body.plain == ""
    assert (
        AliasOverridesIndicator._build_combined_tooltip({}, context, now=100.0) is None
    )


def test_combined_single_fact_tooltip_matches_original(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.ace.tui.widgets.provider_disables_indicator import (
        ProviderDisablesIndicator,
    )
    from sase.ace.tui.widgets.provider_priority_indicator import (
        ProviderPriorityIndicator,
    )
    from tests._provider_disables_indicator_helpers import _patch_priority_facts

    _patch_priority_facts(monkeypatch)
    overrides = {
        "medium": _override(
            provider="claude", model="opus", effort="xhigh", expires_at=3_820.0
        )
    }
    empty = _combined_context()
    assert AliasOverridesIndicator._build_combined_tooltip(
        overrides, empty, now=100.0
    ) == AliasOverridesIndicator._build_tooltip(overrides, now=100.0)

    priority = _combined_priority(expires_at=3_820.0)
    priority_context = _combined_context(priority=priority)
    availability = ProviderPriorityIndicator._priority_availability(priority_context)
    assert AliasOverridesIndicator._build_combined_tooltip(
        {}, priority_context, now=100.0
    ) == ProviderPriorityIndicator._build_tooltip(
        priority, priority_availability=availability, now=100.0
    )

    disables = {"claude": _combined_disable(expires_at=3_820.0)}
    disable_context = _combined_context(disables)
    assert AliasOverridesIndicator._build_combined_tooltip(
        {}, disable_context, now=100.0
    ) == ProviderDisablesIndicator._build_tooltip(disables, now=100.0)


def test_combined_all_three_tooltip_joins_sections_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests._provider_disables_indicator_helpers import _patch_priority_facts

    _patch_priority_facts(monkeypatch)
    overrides = {
        "medium": _override(
            provider="claude", model="opus", effort="xhigh", expires_at=3_820.0
        )
    }
    context = _combined_context(
        {"claude": _combined_disable(expires_at=3_820.0)},
        _combined_priority(expires_at=3_820.0),
    )

    tooltip = AliasOverridesIndicator._build_combined_tooltip(
        overrides, context, now=100.0
    )

    assert tooltip is not None
    assert tooltip.count("Press ,m for Config > Launch.") == 1
    assert tooltip.endswith("Press ,m for Config > Launch.")
    assert "Temporary model overrides:" in tooltip
    assert "Provider priority:" in tooltip
    assert "Disabled providers:" in tooltip
    alias_section, priority_section, disable_section = tooltip.rsplit(
        "Press ,m for Config > Launch.", 1
    )[0].split("\n\n")
    assert "@medium" in alias_section
    assert "CODEX" in priority_section
    assert "CLAUDE" in disable_section
