"""Tests for the ProviderDisablesIndicator top-bar pill."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from rich.text import Text

from sase.ace.testing import AcePage
from sase.ace.tui.widgets._override_pill import (
    PROVIDER_PRIORITY_PALETTE,
    PROVIDER_SOFT_DISABLE_PALETTE,
)
from sase.ace.tui.widgets.provider_disables_indicator import (
    ProviderDisablesIndicator,
    _ACTIVE_STYLE,
)
from sase.llm_provider.usage.hints import CapacityHint
from sase.llm_provider.provider_disable import (
    PROVIDER_DISABLE_MODE_SOFT,
    PROVIDER_DISABLE_WIRE_SCHEMA_VERSION,
    TemporaryProviderDisable,
)
from sase.llm_provider.provider_priority import (
    PROVIDER_PRIORITY_WIRE_SCHEMA_VERSION,
    TemporaryProviderPriority,
    provider_availability_facts,
    provider_routing_context_from_parts,
)
from tests._usage_view_helpers import FROZEN_NOW, usage_provider

_MODULE = "sase.ace.tui.widgets.provider_disables_indicator"


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


def test_no_provider_disables_renders_empty() -> None:
    assert ProviderDisablesIndicator._build_content({}).plain == ""


def test_single_provider_disable_renders_countdown() -> None:
    text = ProviderDisablesIndicator._build_content(
        {"claude": _disable(expires_at=3_820.0)},
        now=100.0,
    )

    assert text.plain == " CLAUDE off 1h2m "
    assert str(text.style) == _ACTIVE_STYLE


def test_multi_day_provider_disable_renders_day_unit() -> None:
    text = ProviderDisablesIndicator._build_content(
        {"codex": _disable("codex", expires_at=100.0 + 3 * 86400 + 4 * 3600)},
        now=100.0,
    )

    assert text.plain == " CODEX off 3d4h "


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
        "CLAUDE - hard · manual, until cleared\n"
        "CODEX - hard · usage-limit automatic, 1h2m left\n"
        "GROK - hard · external plugin, 1h5m left\n"
        "Hard disables skip the provider on new launches; "
        "running processes continue.\n"
        "Pools spare a soft provider while another member can cover; "
        "|| fallbacks and explicit %model still use it.\n"
        "Press ,m for Config > Launch."
    )


def test_tooltip_renders_day_unit_for_multi_day_disable() -> None:
    tooltip = ProviderDisablesIndicator._build_tooltip(
        {
            "codex": _disable(
                "codex",
                expires_at=100.0 + 3 * 86400 + 4 * 3600,
                source="usage_limit",
            ),
        },
        now=100.0,
    )

    assert tooltip == (
        "Disabled providers:\n"
        "CODEX - hard · usage-limit automatic, 3d4h left\n"
        "Hard disables skip the provider on new launches; "
        "running processes continue.\n"
        "Pools spare a soft provider while another member can cover; "
        "|| fallbacks and explicit %model still use it.\n"
        "Press ,m for Config > Launch."
    )


def test_soft_provider_disable_renders_soft_countdown() -> None:
    text = ProviderDisablesIndicator._build_content(
        {
            "claude": _disable(
                expires_at=3_820.0,
                mode=PROVIDER_DISABLE_MODE_SOFT,
            )
        },
        now=100.0,
    )

    assert text.plain == " CLAUDE soft 1h2m "
    assert str(text.style) == PROVIDER_SOFT_DISABLE_PALETTE.base_style


def test_mixed_provider_disables_prefer_hard_in_pill() -> None:
    text = ProviderDisablesIndicator._build_content(
        {
            "claude": _disable(
                "claude",
                expires_at=None,
                mode=PROVIDER_DISABLE_MODE_SOFT,
            ),
            "codex": _disable("codex", expires_at=5_000.0),
        },
        now=100.0,
    )

    assert text.plain == " CODEX +1 "
    assert str(text.style) == _ACTIVE_STYLE


def test_soft_only_multiple_provider_disables_use_soft_palette() -> None:
    text = ProviderDisablesIndicator._build_content(
        {
            "claude": _disable(
                "claude",
                expires_at=None,
                mode=PROVIDER_DISABLE_MODE_SOFT,
            ),
            "codex": _disable(
                "codex",
                expires_at=5_000.0,
                mode=PROVIDER_DISABLE_MODE_SOFT,
            ),
        },
        now=100.0,
    )

    assert text.plain == " CLAUDE +1 "
    assert str(text.style) == PROVIDER_SOFT_DISABLE_PALETTE.base_style


def test_provider_priority_renders_priority_pill() -> None:
    text = ProviderDisablesIndicator._build_content(
        {},
        priority=_priority("codex", expires_at=3_820.0),
        now=100.0,
    )

    assert text.plain == " CODEX ★ priority 1h2m "
    assert str(text.style) == PROVIDER_PRIORITY_PALETTE.base_style


def test_provider_priority_combines_with_disable_pill() -> None:
    text = ProviderDisablesIndicator._build_content(
        {"claude": _disable("claude", expires_at=None)},
        priority=_priority("codex", expires_at=3_820.0),
        now=100.0,
    )

    assert text.plain == " CODEX ★ 1h2m +1 "


def test_hard_disabled_provider_priority_renders_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_priority_facts(monkeypatch)
    priority = _priority("codex", expires_at=3_820.0)
    disable = _disable("codex", expires_at=None)
    context = provider_routing_context_from_parts(
        {"codex": disable},
        priority,
        captured_at=100.0,
    )

    text = ProviderDisablesIndicator._build_content(
        dict(context.provider_disables),
        priority=context.priority,
        priority_availability=ProviderDisablesIndicator._priority_availability(context),
        now=100.0,
    )

    assert text.plain == " CODEX ★ unavailable 1h2m +1 "


def test_soft_disabled_provider_priority_renders_soft_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_priority_facts(monkeypatch)
    priority = _priority("codex", expires_at=3_820.0)
    disable = _disable(
        "codex",
        expires_at=None,
        mode=PROVIDER_DISABLE_MODE_SOFT,
    )
    context = provider_routing_context_from_parts(
        {"codex": disable},
        priority,
        captured_at=100.0,
    )

    text = ProviderDisablesIndicator._build_content(
        dict(context.provider_disables),
        priority=context.priority,
        priority_availability=ProviderDisablesIndicator._priority_availability(context),
        now=100.0,
    )

    assert text.plain == " CODEX ★ soft-disabled 1h2m +1 "
    assert str(text.style) == PROVIDER_SOFT_DISABLE_PALETTE.base_style


def test_missing_cli_provider_priority_renders_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_priority_facts(monkeypatch, cli_available=False)
    priority = _priority("codex", expires_at=3_820.0)
    context = provider_routing_context_from_parts({}, priority, captured_at=100.0)

    priority_availability = ProviderDisablesIndicator._priority_availability(context)
    text = ProviderDisablesIndicator._build_content(
        dict(context.provider_disables),
        priority=context.priority,
        priority_availability=priority_availability,
        now=100.0,
    )
    tooltip = ProviderDisablesIndicator._build_tooltip(
        dict(context.provider_disables),
        priority=context.priority,
        priority_availability=priority_availability,
        now=100.0,
    )

    assert text.plain == " CODEX ★ unavailable 1h2m "
    assert "CODEX - unavailable · 1h2m left" in (tooltip or "")


def test_tooltip_lists_soft_mode() -> None:
    tooltip = ProviderDisablesIndicator._build_tooltip(
        {
            "claude": _disable(
                "claude",
                expires_at=None,
                source="ace",
                mode=PROVIDER_DISABLE_MODE_SOFT,
            )
        },
        now=100.0,
    )

    assert tooltip is not None
    assert "CLAUDE - soft · manual, until cleared" in tooltip
    assert "Pools spare a soft provider" in tooltip


def test_tooltip_lists_provider_priority() -> None:
    tooltip = ProviderDisablesIndicator._build_tooltip(
        {"claude": _disable("claude", expires_at=None, source="ace")},
        priority=_priority("codex", expires_at=3_820.0),
        now=100.0,
    )

    assert tooltip is not None
    assert tooltip.startswith("Provider routing state:\n")
    assert "CODEX - preferred · 1h2m left" in tooltip
    assert "CLAUDE - hard · manual, until cleared" in tooltip


def test_initial_content_uses_peek_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    context = provider_routing_context_from_parts(
        {"claude": _disable(expires_at=None)},
        None,
        captured_at=100.0,
    )
    peek = MagicMock(return_value=context)
    monkeypatch.setattr(f"{_MODULE}.peek_provider_routing_context", peek)
    monkeypatch.setattr(f"{_MODULE}.cached_usage_peek", lambda: ((), frozenset()))

    rendered = ProviderDisablesIndicator()._build_initial_content()

    assert isinstance(rendered, Text)
    assert rendered.plain == " CLAUDE off ∞ "
    peek.assert_called()


async def test_provider_disables_indicator_is_mounted() -> None:
    async with AcePage() as page:
        indicator = page.query_one_widget(
            "#provider-disables-indicator",
            ProviderDisablesIndicator,
        )

    assert isinstance(indicator, ProviderDisablesIndicator)


def _usage_items() -> tuple[CapacityHint, CapacityHint]:
    return (
        CapacityHint(
            kind="rejected",
            label="0% left · Week · all",
            provider="grok",
            window_key="weekly",
            scope="Week · all",
            remaining_percent=0.0,
        ),
        CapacityHint(
            kind="low",
            label="12% left · Shared 5h",
            provider="codex",
            window_key="shared",
            scope="Shared 5h",
            remaining_percent=12.5,
        ),
    )


def test_usage_attention_renders_micro_total_beside_disable_when_budget_is_tiny() -> (
    None
):
    text = ProviderDisablesIndicator._build_content(
        {"claude": _disable(expires_at=None)},
        usage_items=_usage_items(),
        usage_budget=3,
        now=100.0,
    )

    assert "CLAUDE off ∞" in text.plain
    assert "!2" in text.plain


def test_priority_pill_does_not_suppress_usage_attention() -> None:
    text = ProviderDisablesIndicator._build_content(
        {},
        priority=_priority("codex", expires_at=3_820.0),
        usage_items=_usage_items()[:1],
        width=80,
        now=100.0,
    )

    assert "CODEX ★ priority 1h2m" in text.plain
    assert "GROK" in text.plain


def test_usage_tooltip_lists_attention_items() -> None:
    tooltip = ProviderDisablesIndicator._build_tooltip(
        {"claude": _disable("claude", expires_at=None, source="ace")},
        usage_items=_usage_items(),
        now=100.0,
    )

    assert tooltip is not None
    assert "CLAUDE - hard · manual, until cleared" in tooltip
    assert "Usage attention:" in tooltip
    assert "GROK - rejected · 0% left · Week · all" in tooltip
    assert "Providers · Usage" in tooltip


def test_usage_tooltip_lists_failing_collector_health_lines() -> None:
    provider = usage_provider(
        "codex",
        collection_reason="vendor_drift",
        collector_health={
            "state": "failing",
            "consecutive_failures": 5,
            "failing_since": FROZEN_NOW - 172_800.0,
            "last_success_at": FROZEN_NOW - 259_200.0,
        },
    )
    tooltip = ProviderDisablesIndicator._build_tooltip(
        {},
        usage_items=(
            CapacityHint(
                kind="collection_problem",
                label="usage failing",
                provider="codex",
            ),
        ),
        usage_providers=(provider,),
        now=FROZEN_NOW,
    )

    assert tooltip is not None
    assert "CODEX - collection problem · usage failing" in tooltip
    assert "collector health: failing · vendor drift · 5x" in tooltip
    assert "failing since: 2d ago" in tooltip
    assert "last success: 3d ago" in tooltip


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
        indicator._usage_open_provider = None
        await indicator.on_click()
        await page.pause()

    assert calls == ["opened"]


async def test_click_opens_provider_usage_when_attention_is_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    async with AcePage() as page:

        async def _run_action(action: str, *args: object, **kwargs: object) -> None:
            calls.append(action)

        monkeypatch.setattr(page.app, "run_action", _run_action)
        indicator = page.query_one_widget(
            "#provider-disables-indicator",
            ProviderDisablesIndicator,
        )
        indicator._usage_open_provider = "grok"
        await indicator.on_click()
        await page.pause()

    assert calls == ["open_provider_usage"]
