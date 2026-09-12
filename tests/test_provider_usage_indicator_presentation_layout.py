"""Budget packing, overflow, and projection tests for the usage header.

Text, grouping, and tooltip coverage lives in
``test_provider_usage_indicator_presentation.py``. Color, style, and
contrast coverage lives in
``test_provider_usage_indicator_presentation_style.py``.
"""

from __future__ import annotations

import pytest
from rich.cells import cell_len

from sase.ace.tui.widgets._provider_usage_indicator import (
    build_usage_indicator_segment,
    usage_indicator_groups,
)
from sase.ace.tui.widgets._usage_indicator_palette import (
    _usage_badge_surface_color,
    usage_neutral_color,
)
from sase.llm_provider.usage.store import provider_usage_project_indicator
from tests._provider_usage_indicator_presentation_helpers import (
    FROZEN_NOW,
    _entry,
    _groups,
    _indicator_snapshot,
    _dot_styles,
    _scope,
    _style_for,
    _weekly_usage_window,
)


def test_partial_overflow_keeps_complete_windows_and_hidden_total() -> None:
    default = _entry(provider="claude", window_key="weekly", remaining_percent=62.0)
    fable = _entry(
        provider="claude",
        window_key="weekly:claude-fable-5",
        weekly_all=False,
        scope=_scope(kind="product", product="claude", model_ids=("claude-fable-5",)),
        remaining_percent=7.0,
        seconds_until_reset=115_200.0,
        resets_at=FROZEN_NOW + 115_200.0,
        display_attention="very_low",
    )
    session = _entry(
        provider="claude",
        window_key="session",
        weekly_all=False,
        period_kind="session",
        duration_seconds=None,
        remaining_percent=18.0,
        seconds_until_reset=7_740.0,
        resets_at=FROZEN_NOW + 7_740.0,
        display_attention="low",
    )
    codex = _entry(provider="codex", remaining_percent=81.0)
    groups = _groups(default, fable, session, codex)
    expected = " 🎭 62% 3d4h · fable 7% 1d8h  +2 "

    segment = build_usage_indicator_segment(groups, budget=cell_len(expected))

    assert segment.plain == expected
    assert len(_dot_styles(segment)) == 1
    assert "(" not in segment.plain
    assert ")" not in segment.plain


def test_budget_packing_falls_back_through_the_full_ladder() -> None:
    grok = _entry(provider="grok", remaining_percent=4.0, display_attention="rejected")
    codex = _entry(provider="codex", remaining_percent=50.0)
    claude = _entry(provider="claude", remaining_percent=62.0)
    groups = _groups(grok, codex, claude)

    full = build_usage_indicator_segment(groups)
    assert cell_len(full.plain) == full.cell_len

    overflow = build_usage_indicator_segment(groups, budget=full.cell_len - 1)
    assert overflow.cell_len <= full.cell_len - 1
    assert overflow.plain.strip().endswith("+1")
    assert "🛰️" in overflow.plain

    count_only = build_usage_indicator_segment(groups, budget=cell_len(" usage 3 "))
    assert count_only.plain == " usage 3 "

    padded_total = build_usage_indicator_segment(groups, budget=cell_len(" 3 "))
    assert padded_total.plain == " 3 "

    bare = build_usage_indicator_segment(groups, budget=1)
    assert bare.plain == "3"
    assert build_usage_indicator_segment(groups, budget=0).plain == ""


def test_every_budget_from_zero_through_full_fits_without_dangling_tokens() -> None:
    groups = _groups(
        _entry(provider="claude", remaining_percent=62.0),
        _entry(
            provider="claude",
            window_key="weekly:claude-fable-5",
            weekly_all=False,
            scope=_scope(
                kind="product", product="claude", model_ids=("claude-fable-5",)
            ),
            remaining_percent=7.0,
        ),
        _entry(provider="codex", remaining_percent=81.0),
        _entry(provider="grok", remaining_percent=4.0, display_attention="rejected"),
    )
    full = build_usage_indicator_segment(groups)
    previous = -1
    for budget in range(full.cell_len + 2):
        segment = build_usage_indicator_segment(groups, budget=budget)
        assert segment.cell_len <= budget
        stripped = segment.plain.strip()
        assert not stripped.startswith("·")
        assert not stripped.endswith("·")
        assert " ·  · " not in segment.plain
        if budget == 0:
            assert segment.plain == ""
        if segment.cell_len:
            assert segment.cell_len >= previous or previous <= 0
        previous = max(previous, segment.cell_len)
    exact = build_usage_indicator_segment(groups, budget=full.cell_len)
    assert exact.plain == full.plain
    neighbor = build_usage_indicator_segment(groups, budget=full.cell_len - 1)
    assert neighbor.cell_len <= full.cell_len - 1


def test_fallback_ladder_uses_ellipsis_when_total_digits_do_not_fit() -> None:
    groups = _groups(
        *(_entry(provider=f"p{index}", remaining_percent=62.0) for index in range(12))
    )

    assert build_usage_indicator_segment(groups, budget=1).plain == "…"


def test_provider_badge_requires_owned_outer_margin() -> None:
    groups = _groups(_entry(provider="claude", remaining_percent=62.0))
    full = build_usage_indicator_segment(groups)

    segment = build_usage_indicator_segment(groups, budget=full.cell_len - 1)

    assert full.plain == " 🎭 62% 3d4h "
    assert "🎭" not in segment.plain


@pytest.mark.parametrize("dark", [True, False])
def test_overflow_and_fallback_disclosure_render_bold_neutral_on_badge_surface(
    dark: bool,
) -> None:
    grok = _entry(provider="grok", remaining_percent=4.0, display_attention="rejected")
    codex = _entry(provider="codex", remaining_percent=50.0)
    claude = _entry(provider="claude", remaining_percent=62.0)
    groups = _groups(grok, codex, claude, dark=dark)
    full = build_usage_indicator_segment(groups, dark=dark)
    neutral = usage_neutral_color(dark=dark)
    badge_surface = _usage_badge_surface_color(dark=dark)

    overflow = build_usage_indicator_segment(
        groups, budget=full.cell_len - 1, dark=dark
    )
    plus_one_style = _style_for(overflow, "+1")

    count_only = build_usage_indicator_segment(
        groups, budget=cell_len(" usage 3 "), dark=dark
    )
    count_style = _style_for(count_only, "usage 3")

    for style in (plus_one_style, count_style):
        assert style.bold is True
        assert style.color is not None
        assert style.color.get_truecolor().hex == neutral.lower()
        assert style.bgcolor is not None
        assert style.bgcolor.get_truecolor().hex == badge_surface.lower()


def test_real_projection_selection_boundary_and_renderer_integration() -> None:
    snapshot = _indicator_snapshot(
        _weekly_usage_window(
            key="weekly",
            label="Week",
            remaining_percent=90.0,
            resets_at=FROZEN_NOW + 1_000.0,
            applicability={"kind": "account"},
        ),
        _weekly_usage_window(
            key="fable-1999",
            label="Fable 19.99",
            remaining_percent=19.99,
            resets_at=FROZEN_NOW + 2_000.0,
            applicability={"kind": "models", "model_ids": ["claude-fable-5"]},
        ),
        _weekly_usage_window(
            key="fable-20",
            label="Fable 20",
            remaining_percent=20.0,
            resets_at=FROZEN_NOW + 3_000.0,
            applicability={"kind": "models", "model_ids": ["claude-fable-5"]},
        ),
    )

    projection = provider_usage_project_indicator(
        snapshot,
        indicator={
            "default": {"below_remaining_percent": 20},
            "weekly_all": "always",
        },
        eligible_providers=["claude"],
        now=FROZEN_NOW,
    )
    assert [entry["window_key"] for entry in projection.entries] == [
        "fable-1999",
        "weekly",
    ]
    segment = build_usage_indicator_segment(
        usage_indicator_groups(projection.entries, dark=True, now=FROZEN_NOW)
    )
    assert "🎭 90%" in segment.plain
    assert "fable 19%" in segment.plain
    assert "20%" not in segment.plain

    override_projection = provider_usage_project_indicator(
        snapshot,
        indicator={
            "default": {"below_remaining_percent": 20},
            "weekly_all": "always",
            "providers": {"claude": {"windows": {"fable-20": "always"}}},
        },
        eligible_providers=["claude"],
        now=FROZEN_NOW,
    )
    override_segment = build_usage_indicator_segment(
        usage_indicator_groups(override_projection.entries, dark=True, now=FROZEN_NOW)
    )
    assert "fable [fable-1999] 19%" in override_segment.plain
    assert "fable [fable-20] 20%" in override_segment.plain

    always_projection = provider_usage_project_indicator(
        snapshot,
        indicator={"default": "always"},
        eligible_providers=["claude"],
        now=FROZEN_NOW,
    )
    assert {entry["window_key"] for entry in always_projection.entries} == {
        "weekly",
        "fable-1999",
        "fable-20",
    }

    never_projection = provider_usage_project_indicator(
        snapshot,
        indicator={"enabled": False},
        eligible_providers=["claude"],
        now=FROZEN_NOW,
    )
    assert never_projection.entries == ()
    assert (
        build_usage_indicator_segment(
            usage_indicator_groups(never_projection.entries, dark=True, now=FROZEN_NOW)
        ).plain
        == ""
    )
