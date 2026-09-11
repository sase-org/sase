"""ProviderDisablesIndicator usage badge composition tests."""

from __future__ import annotations

import pytest
from rich.color import Color
from rich.text import Text

from sase.ace.tui.widgets._override_pill import (
    PROVIDER_DISABLE_PALETTE,
    PROVIDER_PRIORITY_PALETTE,
    PROVIDER_SOFT_DISABLE_PALETTE,
)
from sase.ace.tui.widgets._provider_usage_indicator import (
    UsageBadge,
    usage_indicator_badges,
)
from sase.ace.tui.widgets.provider_disables_indicator import ProviderDisablesIndicator
from sase.llm_provider.provider_disable import (
    PROVIDER_DISABLE_MODE_SOFT,
    TemporaryProviderDisable,
)
from sase.llm_provider.provider_priority import TemporaryProviderPriority
from tests._provider_disables_indicator_helpers import (
    _CONSOLE,
    _FROZEN_NOW,
    _disable,
    _priority,
    _segments_with_offsets,
    _usage_badges,
    _usage_entry,
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
