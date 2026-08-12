"""Tests for sase.plan_tier_presentation."""

from __future__ import annotations

import pytest

from sase.plan_tier_presentation import (
    GENERIC_PLAN_ACCENT,
    GENERIC_PLAN_LABEL,
    PLAN_TIER_PRESENTATIONS,
    normalize_plan_tier_value,
    plan_tier_presentation,
)
from sase.sdd.plan_tiers import normalize_plan_tier


class TestPlanTierPresentations:
    def test_tale_label_and_accent(self) -> None:
        presentation = PLAN_TIER_PRESENTATIONS["tale"]
        assert presentation.label == "Tale"
        assert presentation.accent_color == "#FFD75F"
        assert presentation.rich_style == "bold #FFD75F"

    def test_epic_label_and_accent(self) -> None:
        presentation = PLAN_TIER_PRESENTATIONS["epic"]
        assert presentation.label == "Epic"
        assert presentation.accent_color == "#AF87FF"
        assert presentation.rich_style == "bold #AF87FF"

    def test_generic_fallback_constants(self) -> None:
        assert GENERIC_PLAN_LABEL == "Plan"
        assert GENERIC_PLAN_ACCENT == "#5FD7FF"


class TestNormalizePlanTierValue:
    @pytest.mark.parametrize("value", ["tale", "epic", "TALE", " Epic ", "Tale "])
    def test_accepts_known_spellings(self, value: str) -> None:
        assert normalize_plan_tier_value(value) == normalize_plan_tier(value)

    @pytest.mark.parametrize("value", [None, "", "bogus", "tale2", 42, object()])
    def test_rejects_unknown_values(self, value: object) -> None:
        assert normalize_plan_tier_value(value) is None

    def test_delegates_to_shared_normalizer(self) -> None:
        # normalize_plan_tier already strips/lowercases; the presentation
        # layer must not reimplement that logic separately.
        assert normalize_plan_tier_value("  EPIC  ") == normalize_plan_tier("  EPIC  ")


class TestPlanTierPresentationLookup:
    def test_returns_presentation_for_valid_tier(self) -> None:
        assert plan_tier_presentation("epic") is PLAN_TIER_PRESENTATIONS["epic"]

    def test_raises_for_invalid_tier(self) -> None:
        with pytest.raises(ValueError):
            plan_tier_presentation("bogus")


def test_auto_approve_kind_styles_values_unchanged() -> None:
    from sase.ace.tui.widgets.prompt_panel._agent_display_header_metadata import (
        _AUTO_APPROVE_KIND_STYLES,
    )

    assert _AUTO_APPROVE_KIND_STYLES == {
        "plan": ("⚡ PLAN", "bold #5FD7FF"),
        "tale": ("⚡ TALE", "bold #FFD75F"),
        "epic": ("⚡ EPIC", "bold #AF87FF"),
    }
