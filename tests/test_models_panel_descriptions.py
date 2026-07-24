"""Models panel alias-description rendering tests."""

import pytest

from sase.ace.tui.modals.models_panel import _description_text_for_view
from sase.llm_provider.config import ModelAliasSelectorMember
from tests._models_panel_helpers import (
    make_alias_view,
    make_override,
    make_pool_members,
)


def test_description_text_for_builtin_alias() -> None:
    text = _description_text_for_view(
        make_alias_view(
            "default",
            "default",
            description="Model used when a prompt has no %model directive.",
        )
    )

    assert text.plain == "Model used when a prompt has no %model directive."


def test_description_text_for_custom_alias() -> None:
    text = _description_text_for_view(
        make_alias_view(
            "blogger",
            "user",
            configured=True,
            configured_source="custom",
            description="Draft and edit blog posts.",
        )
    )

    assert text.plain == "Draft and edit blog posts."


def test_description_text_distinguishes_fallback_and_selected_candidate() -> None:
    members = (
        ModelAliasSelectorMember(
            value="claude/claude-fable-5",
            target="claude/claude-fable-5",
            effort=None,
            provider="claude",
            available=False,
        ),
        ModelAliasSelectorMember(
            value="codex/gpt-5.6-sol",
            target="codex/gpt-5.6-sol",
            effort=None,
            provider="codex",
            available=True,
            selected=True,
        ),
    )
    text = _description_text_for_view(
        make_alias_view(
            "smartest",
            "role",
            description="Highest-capability model used by large phases.",
            selector_mode="fallback",
            selector_members=members,
        )
    )

    assert text.plain.splitlines() == [
        "Highest-capability model used by large phases.",
        "fallback: × claude/claude-fable-5 · → ✓ codex/gpt-5.6-sol",
    ]


def test_description_text_preserves_pool_rendering() -> None:
    members = (
        ModelAliasSelectorMember(
            value="claude/opus",
            target="claude/opus",
            effort="medium",
            provider="claude",
            available=True,
            selected=True,
        ),
        ModelAliasSelectorMember(
            value="codex/gpt-5.5",
            target="codex/gpt-5.5",
            effort=None,
            provider="codex",
            available=False,
        ),
    )
    text = _description_text_for_view(
        make_alias_view(
            "cheaper",
            "role",
            selector_mode="round_robin",
            selector_members=members,
        )
    )

    assert text.plain == "pool: → ✓ claude/opus@medium · × codex/gpt-5.5"


def test_description_text_for_user_alias_without_description_hints_config_path() -> (
    None
):
    text = _description_text_for_view(
        make_alias_view(
            "blogger",
            "user",
            configured=True,
            configured_source="builtin",
            description=None,
        )
    )

    assert "no description" in text.plain
    assert "llm_provider.model_aliases.custom.blogger.description" in text.plain


def test_description_text_marks_next_pool_member_and_dims_others() -> None:
    text = _description_text_for_view(
        make_alias_view(
            "pool",
            "user",
            configured=True,
            description="Pool alias.",
            selector_mode="round_robin",
            selector_members=make_pool_members((True, False), next_index=0),
        )
    )

    assert text.plain.splitlines() == [
        "Pool alias.",
        "pool: → ✓ claude/opus@medium · × codex/gpt-5.5",
    ]
    arrow = next(
        span for span in text.spans if text.plain[span.start : span.end] == "→ "
    )
    assert "bold" in str(arrow.style).lower()


def test_description_text_pool_override_suspends_next_marker() -> None:
    text = _description_text_for_view(
        make_alias_view(
            "pool",
            "user",
            configured=True,
            description="Pool alias.",
            override=make_override(),
            selector_mode="round_robin",
            selector_members=make_pool_members(),
        )
    )

    assert text.plain.splitlines() == [
        "Pool alias.",
        "pool (suspended by override): ✓ claude/opus@medium · ✓ codex/gpt-5.5",
    ]
    assert "→" not in text.plain


@pytest.mark.parametrize(
    ("default_effort", "expected"),
    [
        ("xhigh", "effort: medium · overrides default xhigh"),
        ("medium", "effort: medium · matches default"),
        (None, "effort: medium · no default configured"),
    ],
)
def test_description_text_explains_effort_provenance(
    default_effort: str | None,
    expected: str,
) -> None:
    text = _description_text_for_view(
        make_alias_view(
            "focused",
            "user",
            configured=True,
            description="Focused alias.",
            effort="medium",
        ),
        default_effort,
    )

    assert text.plain.splitlines() == ["Focused alias.", expected]
