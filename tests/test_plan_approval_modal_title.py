"""Tests for PlanApprovalModal title rendering with provider/model badge."""

from sase.ace.tui.modals.plan_approval_modal import (
    PlanApprovalModal,
    _provider_badge_markup,
)


def test_badge_markup_empty_when_no_provider_or_model() -> None:
    assert _provider_badge_markup(None, None) == ""


def test_badge_markup_claude_contains_provider_and_model() -> None:
    markup = _provider_badge_markup("claude", "opus")
    assert "CLAUDE" in markup
    assert "opus" in markup
    assert "#FF5F00" in markup


def test_badge_markup_codex_uses_lime_theme() -> None:
    markup = _provider_badge_markup("codex", "o3")
    assert "CODEX" in markup
    assert "o3" in markup
    assert "#87FF00" in markup


def test_badge_markup_gemini_uses_google_blue() -> None:
    markup = _provider_badge_markup("gemini", "gemini-3-flash-preview")
    assert "GEMINI" in markup
    assert "gemini-3-flash-preview" in markup
    assert "#4285F4" in markup


def test_badge_markup_unknown_provider_falls_back_to_plain_label() -> None:
    markup = _provider_badge_markup("mystery", "x1")
    # Falls back to format_provider_model_label output with neutral muted color
    assert "MYSTERY(x1)" in markup


def test_badge_markup_infers_claude_from_model_name() -> None:
    markup = _provider_badge_markup(None, "opus")
    assert "CLAUDE" in markup
    assert "opus" in markup


def test_title_markup_without_badge_matches_legacy_form() -> None:
    modal = PlanApprovalModal.__new__(PlanApprovalModal)
    modal._plan_file = "/tmp/20260422_143012_my_feature.md"
    modal._llm_provider = None
    modal._model = None
    title = modal._build_title_markup()
    assert "Plan Review" in title
    assert "20260422_143012_my_feature.md" in title
    assert "CLAUDE" not in title
    assert "CODEX" not in title
    assert "GEMINI" not in title


def test_title_markup_with_badge_includes_provider_and_filename() -> None:
    modal = PlanApprovalModal.__new__(PlanApprovalModal)
    modal._plan_file = "/tmp/20260422_143012_my_feature.md"
    modal._llm_provider = "claude"
    modal._model = "opus"
    title = modal._build_title_markup()
    assert "Plan Review" in title
    assert "CLAUDE" in title
    assert "opus" in title
    assert "20260422_143012_my_feature.md" in title


def test_modal_constructor_accepts_keyword_only_provider_and_model() -> None:
    modal = PlanApprovalModal(
        "/tmp/plan.md", llm_provider="gemini", model="gemini-3-flash-preview"
    )
    assert modal._llm_provider == "gemini"
    assert modal._model == "gemini-3-flash-preview"


def test_modal_constructor_defaults_provider_and_model_to_none() -> None:
    modal = PlanApprovalModal("/tmp/plan.md")
    assert modal._llm_provider is None
    assert modal._model is None
