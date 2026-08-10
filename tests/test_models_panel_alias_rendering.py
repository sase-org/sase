"""Models panel alias-row and state rendering tests."""

import pytest

import sase.ace.tui.modals.models_panel as models_panel
from sase.ace.tui.modals.models_panel import (
    _description_text_for_view,
    _kind_label,
    _provider_model_column_width,
    _render_alias_row,
    _state_tag,
)
from sase.ace.tui.modals.models_panel_rendering import (
    custom_builtin_shadow_warning_message,
    render_empty_custom_hint,
    render_section_header,
    _section_count_label,
)
from sase.llm_provider import ModelsPanelSection
from tests._models_panel_helpers import (
    make_alias_view,
    make_override,
    make_pool_members,
)


def test_custom_builtin_warning_message_uses_singular_guidance() -> None:
    assert custom_builtin_shadow_warning_message(["small_worker"]) == (
        "Builtin alias @small_worker is configured under "
        "llm_provider.model_aliases.custom. Move its model value from "
        "llm_provider.model_aliases.custom to llm_provider.model_aliases.builtin."
    )


def test_state_tag_configured() -> None:
    view = make_alias_view(
        "myalias",
        "user",
        configured=True,
        configured_value="claude/opus",
    )
    text = _state_tag(view, now=0.0)
    assert text.plain == "configured"


def test_state_tag_configured_reference_uses_shared_reference_accent() -> None:
    configured = _state_tag(
        make_alias_view(
            "medium_worker",
            "role",
            configured=True,
            configured_value="@default",
        ),
        now=0.0,
    )
    implicit = _state_tag(
        make_alias_view("big_epic_lander", "role"),
        now=0.0,
    )

    assert configured.plain == "configured → @default"
    configured_target = next(
        span
        for span in configured.spans
        if configured.plain[span.start : span.end] == "@default"
    )
    implicit_target = next(
        span
        for span in implicit.spans
        if implicit.plain[span.start : span.end] == "@smartest"
    )
    assert configured_target.style == implicit_target.style
    assert "#87d7ff" in str(configured_target.style).lower()


def test_state_tag_configured_reference_includes_effort_overlay() -> None:
    text = _state_tag(
        make_alias_view(
            "medium_worker",
            "role",
            configured=True,
            configured_value="@default@high",
        ),
        now=0.0,
    )

    assert text.plain == "configured → @default @ high"


def test_state_tag_implicit_default() -> None:
    text = _state_tag(make_alias_view("default", "default"), now=0.0)
    assert text.plain == "implicit"


def test_state_tag_implicit_role() -> None:
    text = _state_tag(make_alias_view("medium_worker", "role"), now=0.0)
    assert text.plain == "implicit → @smart"


def test_state_tag_implicit_big_epic_lander() -> None:
    text = _state_tag(make_alias_view("big_epic_lander", "role"), now=0.0)
    assert text.plain == "implicit → @smartest"


def test_state_tag_implicit_concrete_size_worker() -> None:
    text = _state_tag(make_alias_view("medium_worker", "role"), now=0.0)
    assert text.plain == "implicit → @smart"


def test_custom_builtin_warning_survives_active_override() -> None:
    view = make_alias_view(
        "small_worker",
        "role",
        configured=True,
        configured_value="@default",
        configured_source="custom",
    )
    overridden = make_alias_view(
        "small_worker",
        "role",
        configured=True,
        configured_value="@default",
        configured_source="custom",
        override=make_override(),
    )

    line = _render_alias_row(view, now=0.0, provider_model_width=12).plain
    override_line = _render_alias_row(
        overridden, now=0.0, provider_model_width=12
    ).plain
    description = _description_text_for_view(view).plain

    assert line.startswith("  ! role")
    assert "configured → @default" in line
    assert override_line.startswith("  ! role")
    assert "override · 1h left" in override_line
    assert description.splitlines() == [
        "! Misplaced builtin alias: @small_worker",
        "Move its model value from llm_provider.model_aliases.custom to "
        "llm_provider.model_aliases.builtin.",
    ]


def test_state_tag_override_with_remaining() -> None:
    view = make_alias_view(
        "medium_worker", "role", override=make_override(expires_at=3600.0)
    )
    text = _state_tag(view, now=0.0)
    assert text.plain == "override · 1h left"


def test_state_tag_override_until_cleared() -> None:
    view = make_alias_view(
        "medium_worker", "role", override=make_override(expires_at=None)
    )
    text = _state_tag(view, now=0.0)
    assert text.plain == "override · until cleared"


@pytest.mark.parametrize(
    ("availability", "expected", "color"),
    [
        ((True, True), "configured · pool 2/2", "#87d787"),
        ((False, True), "configured · pool 1/2", "#ffd75f"),
        ((False, False), "configured · pool 0/2", "#d78787"),
    ],
)
def test_state_tag_pool_availability_chip(
    availability: tuple[bool, bool],
    expected: str,
    color: str,
) -> None:
    view = make_alias_view(
        "pool",
        "user",
        configured=True,
        configured_value="claude/opus | codex/gpt-5.5",
        selector_mode="round_robin",
        selector_members=make_pool_members(availability),
    )

    text = _state_tag(view, now=0.0)
    chip = next(
        span
        for span in text.spans
        if text.plain[span.start : span.end].startswith("pool ")
    )
    assert text.plain == expected
    assert color in str(chip.style).lower()


def test_state_tag_overridden_pool_keeps_override_chip() -> None:
    view = make_alias_view(
        "pool",
        "user",
        configured=True,
        override=make_override(),
        selector_mode="round_robin",
        selector_members=make_pool_members(),
    )

    assert _state_tag(view, now=0.0).plain == "override · 1h left"


def test_render_alias_row_contains_name_provider_and_state() -> None:
    view = make_alias_view("medium_worker", "role", provider="codex", model="o3")
    width = _provider_model_column_width([view])
    line = _render_alias_row(view, now=0.0, provider_model_width=width).plain
    assert "medium_worker" in line
    assert "CODEX(o3)" in line
    assert "implicit" in line


def test_render_alias_row_ownership_gutter_is_semantic() -> None:
    builtin = make_alias_view(
        "smart",
        "role",
        configured=True,
        configured_source="custom",
    )
    user = make_alias_view(
        "researcher",
        "user",
        configured=True,
        configured_source="builtin",
    )

    builtin_line = _render_alias_row(builtin, now=0.0, provider_model_width=12).plain
    user_line = _render_alias_row(user, now=0.0, provider_model_width=12).plain

    assert builtin_line.startswith("  ! role")
    assert not builtin_line.startswith("▌")
    assert user_line.startswith("▌ user")


def test_render_section_header_aligns_counts_with_row_state_column() -> None:
    view = make_alias_view(
        "researcher",
        "user",
        configured=True,
        provider="codex",
        model="gpt-5.6-sol",
    )
    width = _provider_model_column_width([view])
    section = ModelsPanelSection("user", (view,), alias_count=1, bucket_count=0)

    header = render_section_header(section, provider_model_width=width).plain
    row = _render_alias_row(view, now=0.0, provider_model_width=width).plain

    assert header.startswith("▌ ── Custom ")
    assert header.index("1 alias") == row.index("configured")


def test_section_count_label_singularizes_and_omits_zero_buckets() -> None:
    one = ModelsPanelSection("builtin", (), alias_count=1, bucket_count=0)
    many = ModelsPanelSection("user", (), alias_count=3, bucket_count=1)

    assert _section_count_label(one) == "1 alias"
    assert _section_count_label(many) == "3 aliases · 1 bucket"


def test_empty_custom_hint_names_custom_config_path() -> None:
    hint = render_empty_custom_hint().plain

    assert hint.startswith("  No custom aliases")
    assert "llm_provider.model_aliases.custom" in hint


def test_render_alias_row_includes_effort_in_measured_badge() -> None:
    view = make_alias_view(
        "focused",
        "user",
        configured=True,
        provider="codex",
        model="o3",
        effort="max",
    )

    width = _provider_model_column_width([view])
    line = _render_alias_row(view, now=0.0, provider_model_width=width).plain

    assert width == len("CODEX(o3) @ max")
    assert "CODEX(o3) @ max" in line


def test_render_alias_rows_align_state_column() -> None:
    """Rows with different badge widths share one state-column start cell."""
    short = make_alias_view(
        "medium_worker",
        "role",
        provider="codex",
        model="o3",
    )
    wide = make_alias_view(
        "fast",
        "user",
        configured=True,
        configured_value="claude/haiku",
        provider="claude",
        model="haiku",
    )
    width = _provider_model_column_width([short, wide])
    assert width == len("CLAUDE(haiku)")

    short_line = _render_alias_row(short, now=0.0, provider_model_width=width).plain
    wide_line = _render_alias_row(wide, now=0.0, provider_model_width=width).plain
    short_state = _state_tag(short, now=0.0).plain
    wide_state = _state_tag(wide, now=0.0).plain

    assert short_state in short_line
    assert wide_state in wide_line
    assert short_line.index(short_state) == wide_line.index(wide_state)


def test_render_alias_row_preserves_production_length_provider_model_label() -> None:
    """A representative badge that exceeded the old cap remains readable."""
    view = make_alias_view(
        "default",
        "default",
        provider="claude",
        model="claude-fable-4-10",
    )

    width = _provider_model_column_width([view])
    line = _render_alias_row(view, now=0.0, provider_model_width=width).plain

    assert width == len("CLAUDE(claude-fable-4-10)")
    assert "CLAUDE(claude-fable-4-10)" in line
    assert "…" not in line


def test_render_alias_row_ellipsizes_long_provider_model_label() -> None:
    """An over-cap badge is ellipsized but the state tag still aligns."""
    long_view = make_alias_view(
        "mega",
        "user",
        configured=True,
        configured_value="opencode/really-long",
        provider="opencode",
        model="anthropic/claude-sonnet-4-5-extremely-long-model-name",
    )
    short = make_alias_view(
        "quick",
        "user",
        configured=True,
        provider="codex",
        model="o3",
    )

    width = _provider_model_column_width([long_view, short])
    assert width == models_panel._PROVIDER_MODEL_CELL_MAX

    long_line = _render_alias_row(long_view, now=0.0, provider_model_width=width).plain
    short_line = _render_alias_row(short, now=0.0, provider_model_width=width).plain
    long_state = _state_tag(long_view, now=0.0).plain
    short_state = _state_tag(short, now=0.0).plain

    assert "…" in long_line
    assert long_state in long_line
    assert long_line.index(long_state) == short_line.index(short_state)


def test_render_alias_row_ellipsizes_combined_badge_and_effort() -> None:
    view = make_alias_view(
        "focused",
        "user",
        configured=True,
        provider="claude",
        model="claude-fable-4-10-extra-long",
        effort="minimal",
    )

    width = _provider_model_column_width([view])
    line = _render_alias_row(view, now=0.0, provider_model_width=width).plain

    assert width == models_panel._PROVIDER_MODEL_CELL_MAX
    assert "…" in line
    assert "configured" in line


@pytest.mark.parametrize(
    ("default_effort", "comparison"),
    [
        (None, "no default configured"),
        ("medium", "overrides default medium"),
    ],
)
def test_reference_effort_description_names_configured_source(
    default_effort: str | None,
    comparison: str,
) -> None:
    view = make_alias_view(
        "medium_worker",
        "role",
        configured=True,
        configured_value="@default@high",
        effort="high",
    )

    text = _description_text_for_view(view, default_effort).plain

    assert text == f"effort: high (via @default@high) · {comparison}"


def test_medium_worker_description_omits_reference_source() -> None:
    view = make_alias_view(
        "medium_worker",
        "role",
        effort="xhigh",
    )

    text = _description_text_for_view(view, None).plain

    assert text == "effort: xhigh · no default configured"


def test_reference_effort_description_is_suppressed_during_override() -> None:
    view = make_alias_view(
        "medium_worker",
        "role",
        override=make_override(),
        effort="medium",
    )

    text = _description_text_for_view(view, "low").plain

    assert text == "effort: medium · overrides default low"
