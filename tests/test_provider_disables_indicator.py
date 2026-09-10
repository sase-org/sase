"""Tests for the ProviderDisablesIndicator top-bar pill."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from rich.color import Color
from rich.console import Console
from rich.style import Style
from rich.text import Text

from sase.ace.testing import AcePage
from sase.ace.tui.widgets._override_pill import (
    PROVIDER_DISABLE_PALETTE,
    PROVIDER_PRIORITY_PALETTE,
    PROVIDER_SOFT_DISABLE_PALETTE,
)
from sase.ace.tui.widgets.provider_disables_indicator import (
    ProviderDisablesIndicator,
    _ACTIVE_STYLE,
    _text_signature,
)
from sase.ace.tui.widgets._provider_usage_indicator import (
    UsageBadge,
    usage_indicator_badges,
)
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
    monkeypatch.setattr(
        f"{_MODULE}.cached_usage_indicator_projection",
        lambda **_kwargs: SimpleNamespace(entries=(), providers=(), generated_at=100.0),
    )

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


def test_usage_attention_renders_micro_total_beside_disable_when_budget_is_tiny() -> (
    None
):
    text = ProviderDisablesIndicator._build_content(
        {"claude": _disable(expires_at=None)},
        usage_badges=_usage_badges(),
        usage_budget=3,
        now=100.0,
    )

    assert "CLAUDE off ∞" in text.plain
    assert text.plain.strip().endswith("2")


def test_priority_pill_does_not_suppress_usage_attention() -> None:
    grok_badge = _usage_badges()[0]
    text = ProviderDisablesIndicator._build_content(
        {},
        priority=_priority("codex", expires_at=3_820.0),
        usage_badges=(grok_badge,),
        width=80,
        now=100.0,
    )

    assert "CODEX ★ priority 1h2m" in text.plain
    assert grok_badge.text.plain in text.plain


def test_usage_tooltip_lists_attention_items() -> None:
    tooltip = ProviderDisablesIndicator._build_tooltip(
        {"claude": _disable("claude", expires_at=None, source="ace")},
        usage_badges=_usage_badges(),
        now=100.0,
    )

    assert tooltip is not None
    assert "CLAUDE - hard · manual, until cleared" in tooltip
    assert "Usage windows:" in tooltip
    assert "GROK - rejected · 0% left · Week · all" in tooltip
    assert "Providers · Usage" in tooltip


def test_usage_tooltip_lists_failing_collector_health_lines() -> None:
    badge = UsageBadge(
        provider="codex",
        text=Text("🤖 ⚠"),
        tooltip_lines=(
            "CODEX - collection problem · usage failing",
            "collector health: failing · vendor drift · 5x",
            "failing since: 2d ago",
            "last success: 3d ago",
        ),
    )
    tooltip = ProviderDisablesIndicator._build_tooltip(
        {},
        usage_badges=(badge,),
        now=100.0,
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


@pytest.mark.parametrize(
    ("disables", "priority", "accent"),
    [
        pytest.param(
            {"claude": _disable("claude")},
            None,
            PROVIDER_DISABLE_PALETTE.accent,
            id="hard-disable",
        ),
        pytest.param(
            {"claude": _disable("claude", mode=PROVIDER_DISABLE_MODE_SOFT)},
            None,
            PROVIDER_SOFT_DISABLE_PALETTE.accent,
            id="soft-disable",
        ),
        pytest.param(
            {},
            _priority("codex", expires_at=3_820.0),
            PROVIDER_PRIORITY_PALETTE.accent,
            id="priority",
        ),
        pytest.param({}, None, None, id="no-routing"),
    ],
)
def test_routing_prefix_keeps_its_style_and_usage_never_inherits_its_background(
    disables: dict[str, TemporaryProviderDisable],
    priority: TemporaryProviderPriority | None,
    accent: str | None,
) -> None:
    badges = usage_indicator_badges(
        [_usage_entry(provider="grok", remaining_percent=7.0)],
        dark=True,
        now=_FROZEN_NOW,
    )
    routing = ProviderDisablesIndicator._build_routing_content(
        disables, priority=priority, now=100.0
    )
    content = ProviderDisablesIndicator._build_content(
        disables,
        priority=priority,
        usage_badges=badges,
        dark=True,
        now=100.0,
    )

    assert content.plain.startswith(routing.plain)
    prefix_len = len(routing.plain)
    routing_segments = _segments_with_offsets(routing)
    content_segments = _segments_with_offsets(content)
    content_prefix = [seg for seg in content_segments if seg[1] <= prefix_len]
    assert content_prefix == routing_segments

    if accent is not None:
        accent_color = Color.parse(accent)
        for start, _end, style in content_segments:
            if start >= prefix_len:
                assert style is not None
                assert style.bgcolor != accent_color


def test_composed_percent_and_countdown_pairs_agree_after_composition() -> None:
    badges = usage_indicator_badges(
        [_usage_entry(provider="grok", remaining_percent=7.0)],
        dark=True,
        now=_FROZEN_NOW,
    )
    content = ProviderDisablesIndicator._build_content(
        {"claude": _disable("claude")},
        usage_badges=badges,
        dark=True,
        now=100.0,
    )

    segments = {segment.text: segment.style for segment in content.render(_CONSOLE)}
    percent_style = segments["7%"]
    countdown_style = segments["3d4h"]
    assert percent_style is not None
    assert countdown_style is not None
    assert percent_style.color == countdown_style.color
    assert percent_style.bold and countdown_style.bold


def test_collector_only_usage_badge_survives_composition_with_routing() -> None:
    badge = usage_indicator_badges(
        [],
        providers=({"provider": "grok", "collector_problem": True},),
        dark=True,
        now=100.0,
    )[0]
    content = ProviderDisablesIndicator._build_content(
        {"claude": _disable("claude")},
        usage_badges=(badge,),
        dark=True,
        now=100.0,
    )

    segments = {segment.text: segment.style for segment in content.render(_CONSOLE)}
    marker_style = segments["⚠"]
    assert marker_style is not None
    accent_color = Color.parse(PROVIDER_DISABLE_PALETTE.accent)
    assert marker_style.bgcolor != accent_color
    assert marker_style.bold


def test_text_signature_changes_when_only_the_base_style_changes() -> None:
    dark_text = Text("usage 3", style="bold #B8C0CC on #242830")
    light_text = Text("usage 3", style="bold #4B535F on #E0E0E0")

    assert dark_text.plain == light_text.plain
    assert dark_text.spans == light_text.spans == []
    assert _text_signature(dark_text) != _text_signature(light_text)


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


async def test_theme_switch_repaints_usage_gaps_with_identical_plain_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_usage_projection(monkeypatch)
    dark_badges = usage_indicator_badges(
        [_usage_entry(provider="grok", remaining_percent=7.0)],
        dark=True,
        now=_FROZEN_NOW,
    )
    dark_reference = ProviderDisablesIndicator._build_content(
        {}, usage_badges=dark_badges, dark=True, now=100.0
    )
    assert "7%" in dark_reference.plain

    updates: list[Text] = []
    async with AcePage() as page:
        indicator = page.query_one_widget(
            "#provider-disables-indicator",
            ProviderDisablesIndicator,
        )
        indicator._apply_content()
        assert indicator._content_signature == _text_signature(dark_reference)

        original_update = indicator.update
        monkeypatch.setattr(
            indicator,
            "update",
            lambda renderable: (
                updates.append(renderable),
                original_update(renderable),
            )[1],
        )

        page.app.theme = "textual-light"
        page.app.refresh(layout=True)
        await page.app.wait_for_refresh()
        await page.pause()

    assert len(updates) == 1
    repainted = updates[0]
    assert repainted.plain == dark_reference.plain
    assert _segments_with_offsets(repainted) != _segments_with_offsets(dark_reference)


async def test_unchanged_apply_content_does_not_reissue_static_update(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_usage_projection(monkeypatch)
    async with AcePage() as page:
        indicator = page.query_one_widget(
            "#provider-disables-indicator",
            ProviderDisablesIndicator,
        )
        indicator._apply_content()

        calls: list[Text] = []
        original_update = indicator.update
        monkeypatch.setattr(
            indicator,
            "update",
            lambda renderable: (calls.append(renderable), original_update(renderable))[
                1
            ],
        )

        indicator._apply_content()
        indicator._apply_content()

    assert calls == []


def test_narrow_budget_collapses_then_wide_budget_restores_full_badge_packing() -> None:
    badges = usage_indicator_badges(
        [
            _usage_entry(provider="grok", remaining_percent=4.0),
            _usage_entry(provider="codex", remaining_percent=50.0),
            _usage_entry(provider="claude", remaining_percent=62.0),
        ],
        dark=True,
        now=_FROZEN_NOW,
    )
    full = ProviderDisablesIndicator._build_content(
        {}, usage_badges=badges, dark=True, now=100.0
    )
    narrow = ProviderDisablesIndicator._build_content(
        {}, usage_badges=badges, usage_budget=len(" usage 3"), dark=True, now=100.0
    )
    wide_again = ProviderDisablesIndicator._build_content(
        {}, usage_badges=badges, dark=True, now=100.0
    )

    assert narrow.plain.strip() == "usage 3"
    assert wide_again.plain == full.plain
    assert "🛰️" in full.plain and "🤖" in full.plain and "🎭" in full.plain

    tooltip = ProviderDisablesIndicator._build_tooltip(
        {}, usage_badges=badges, now=100.0
    )
    assert tooltip is not None
    for provider_upper in ("GROK", "CODEX", "CLAUDE"):
        assert provider_upper in tooltip
