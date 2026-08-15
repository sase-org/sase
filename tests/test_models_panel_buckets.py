"""Models panel bucket rendering tests."""

from sase.ace.tui.modals.models_panel_rendering import (
    OWNERSHIP_ACCENT,
    description_text_for_row,
    render_bucket_row,
)
from sase.llm_provider import BucketView
from tests._models_panel_helpers import make_alias_view, make_override


def test_render_bucket_row_contains_count_and_override_state() -> None:
    bucket = BucketView(
        name="research",
        description="Research roles.",
        members=(
            make_alias_view(
                "research_a",
                "user",
                bucket="research",
                override=make_override(),
            ),
            make_alias_view("research_b", "user", bucket="research"),
        ),
    )

    line = render_bucket_row(bucket, provider_model_width=13).plain

    assert "▸ bucket" in line
    assert "research" in line
    assert "2 aliases" in line
    assert "override · 1 active" in line


def test_render_bucket_row_and_description_surface_custom_builtin_warnings() -> None:
    bucket = BucketView(
        name="worker",
        description="Phase roles.",
        members=(
            make_alias_view(
                "small",
                "role",
                configured=True,
                configured_source="custom",
                override=make_override(),
            ),
            make_alias_view("medium", "role"),
        ),
    )

    line = render_bucket_row(bucket, provider_model_width=13).plain
    description = description_text_for_row(bucket).plain

    assert "▸ ! bucket" in line
    assert "! 1 misplaced" in line
    assert "1 override" in line
    assert description.splitlines() == [
        "! Misplaced builtin alias: @small",
        "Move its model value from llm_provider.model_aliases.custom to "
        "llm_provider.model_aliases.builtin.",
    ]


def test_render_custom_bucket_with_warning_and_override() -> None:
    bucket = BucketView(
        name="worker",
        description="Phase roles.",
        members=(
            make_alias_view(
                "small",
                "role",
                configured=True,
                configured_source="custom",
                override=make_override(),
            ),
            make_alias_view("phase_reviewer", "user", bucket="worker"),
        ),
    )

    line = render_bucket_row(bucket, provider_model_width=13).plain

    assert line.startswith("▌ ▸ ! bucket")
    assert line.endswith("! 1 misplaced · 1 override")


def test_render_user_bucket_uses_ownership_gutter_and_accent() -> None:
    bucket = BucketView(
        name="research",
        description="Research roles.",
        members=(make_alias_view("researcher", "user", bucket="research"),),
    )

    rendered = render_bucket_row(bucket, provider_model_width=13)
    bucket_state = [
        span
        for span in rendered.spans
        if rendered.plain[span.start : span.end] == "bucket"
    ][-1]

    assert rendered.plain.startswith("▌ ▸ bucket")
    assert OWNERSHIP_ACCENT.lower() in str(bucket_state.style).lower()


def test_description_text_for_bucket_shows_description_and_model_mix() -> None:
    bucket = BucketView(
        name="research",
        description="Research roles.",
        members=(
            make_alias_view(
                "research_a",
                "user",
                provider="codex",
                model="gpt-5.6-sol",
                bucket="research",
            ),
            make_alias_view(
                "research_b",
                "user",
                provider="claude",
                model="opus",
                bucket="research",
            ),
            make_alias_view(
                "research_c",
                "user",
                provider="codex",
                model="gpt-5.6-sol",
                bucket="research",
            ),
        ),
    )

    text = description_text_for_row(bucket).plain

    assert text.splitlines() == [
        "Research roles.",
        "codex/gpt-5.6-sol ×2 · claude/opus ×1",
    ]


def test_description_text_for_bucket_distinguishes_effort_variants() -> None:
    bucket = BucketView(
        name="research",
        description="Research roles.",
        members=(
            make_alias_view(
                "research_a", "user", provider="claude", model="opus", effort="medium"
            ),
            make_alias_view(
                "research_b", "user", provider="claude", model="opus", effort="medium"
            ),
            make_alias_view("research_c", "user", provider="claude", model="opus"),
        ),
    )

    assert description_text_for_row(bucket).plain.splitlines() == [
        "Research roles.",
        "claude/opus@medium ×2 · claude/opus ×1",
    ]
