"""Models panel alias state rendering tests."""

import pytest

import sase.llm_provider.alias_view as alias_view_module
from sase.ace.tui.modals.models_panel import (
    _description_text_for_view,
    _render_alias_row,
    _state_tag,
)
from sase.llm_provider.config import ModelAliasSelectorMember
from sase.llm_provider.provider_disable import (
    PROVIDER_DISABLE_WIRE_SCHEMA_VERSION,
    TemporaryProviderDisable,
)
from tests._models_panel_helpers import (
    make_alias_view,
    make_override,
    make_pool_members,
)


def make_disable(
    provider: str = "codex",
    *,
    expires_at: float | None = None,
) -> TemporaryProviderDisable:
    return TemporaryProviderDisable(
        version=PROVIDER_DISABLE_WIRE_SCHEMA_VERSION,
        provider=provider,
        created_at=0.0,
        expires_at=expires_at,
        source="test",
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
            "medium",
            "role",
            configured=True,
            configured_value="@large",
        ),
        now=0.0,
    )
    other_configured = _state_tag(
        make_alias_view(
            "xlarge",
            "role",
            configured=True,
            configured_value="@small",
        ),
        now=0.0,
    )

    assert configured.plain == "configured → @large"
    configured_target = next(
        span
        for span in configured.spans
        if configured.plain[span.start : span.end] == "@large"
    )
    other_target = next(
        span
        for span in other_configured.spans
        if other_configured.plain[span.start : span.end] == "@small"
    )
    assert configured_target.style == other_target.style
    assert "#87d7ff" in str(configured_target.style).lower()


def test_state_tag_configured_reference_includes_effort_overlay() -> None:
    text = _state_tag(
        make_alias_view(
            "medium",
            "role",
            configured=True,
            configured_value="@large@high",
        ),
        now=0.0,
    )

    assert text.plain == "configured → @large @ high"


def test_state_tag_implicit_size_alias_shows_bare_implicit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        alias_view_module, "implicit_model_alias_fallback", lambda _name: None
    )
    text = _state_tag(make_alias_view("large", "role"), now=0.0)
    assert text.plain == "implicit"


def test_custom_builtin_warning_survives_active_override() -> None:
    view = make_alias_view(
        "small",
        "role",
        configured=True,
        configured_value="@large",
        configured_source="custom",
    )
    overridden = make_alias_view(
        "small",
        "role",
        configured=True,
        configured_value="@large",
        configured_source="custom",
        override=make_override(),
    )

    line = _render_alias_row(view, now=0.0, provider_model_width=12).plain
    override_line = _render_alias_row(
        overridden, now=0.0, provider_model_width=12
    ).plain
    description = _description_text_for_view(view).plain

    assert line.startswith("  ! small")
    assert "configured → @large" in line
    assert override_line.startswith("  ! small")
    assert "override · 1h left" in override_line
    assert description.splitlines() == [
        "! Misplaced builtin alias: @small",
        "Move its model value from llm_provider.model_aliases.custom to "
        "llm_provider.model_aliases.builtin.",
    ]


def test_state_tag_override_with_remaining() -> None:
    view = make_alias_view("medium", "role", override=make_override(expires_at=3600.0))
    text = _state_tag(view, now=0.0)
    assert text.plain == "override · 1h left"


def test_state_tag_override_until_cleared() -> None:
    view = make_alias_view("medium", "role", override=make_override(expires_at=None))
    text = _state_tag(view, now=0.0)
    assert text.plain == "override · until cleared"


def test_state_tag_paused_override_names_disabled_provider() -> None:
    view = make_alias_view(
        "medium",
        "role",
        override=make_override(),
        override_paused_by_provider_disable=make_disable("codex"),
    )

    text = _state_tag(view, now=0.0)

    assert text.plain == "override paused · CODEX disabled"
    assert "#FFAF5F" in str(text.style)


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


def test_state_tag_pool_chip_ignores_last_resort_members() -> None:
    members = make_pool_members((True, True)) + (
        ModelAliasSelectorMember(
            value="grok/grok-4.6@xhigh",
            target="grok/grok-4.6",
            effort="xhigh",
            provider="grok",
            available=True,
            last_resort=True,
        ),
    )
    view = make_alias_view(
        "large",
        "role",
        configured=True,
        configured_value=(
            "(claude/opus@xhigh | codex/gpt-5.6-sol@xhigh) || grok/grok-4.6@xhigh"
        ),
        selector_mode="round_robin",
        selector_members=members,
    )

    assert _state_tag(view, now=0.0).plain == "configured · pool 2/2"


def test_state_tag_counts_sparing_members_as_available() -> None:
    view = make_alias_view(
        "pool",
        "user",
        configured=True,
        configured_value="claude/opus | codex/gpt-5.5",
        selector_mode="round_robin",
        selector_members=make_pool_members((True, True), sparing=(True, False)),
    )

    assert _state_tag(view, now=0.0).plain == "configured · pool 2/2"


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


def test_paused_override_pool_shows_live_selector_description() -> None:
    view = make_alias_view(
        "pool",
        "user",
        configured=True,
        override=make_override(),
        override_paused_by_provider_disable=make_disable("codex"),
        selector_mode="round_robin",
        selector_members=make_pool_members((False, True), next_index=1),
    )

    description = _description_text_for_view(view).plain

    assert (
        "Stored override codex/o3 is paused because CODEX is disabled." in description
    )
    assert "resumes when the provider is enabled" in description
    assert "pool: × claude/opus@medium · → ✓ codex/gpt-5.5" in description
    assert "suspended by override" not in description
