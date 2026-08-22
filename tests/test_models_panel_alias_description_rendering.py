"""Models panel alias description rendering tests."""

import pytest
from rich.text import Text

from sase.ace.tui.modals.models_panel import _description_text_for_view
from sase.llm_provider.config import ModelAliasSelectorMember
from tests._models_panel_helpers import (
    make_alias_view,
    make_override,
    make_pool_members,
)


def test_description_inserts_fallback_separator_and_can_select_tail() -> None:
    members = (
        ModelAliasSelectorMember(
            value="claude/opus@xhigh",
            target="claude/opus",
            effort="xhigh",
            provider="claude",
            available=False,
        ),
        ModelAliasSelectorMember(
            value="codex/gpt-5.6-sol@xhigh",
            target="codex/gpt-5.6-sol",
            effort="xhigh",
            provider="codex",
            available=False,
        ),
        ModelAliasSelectorMember(
            value="grok/grok-4.6@xhigh",
            target="grok/grok-4.6",
            effort="xhigh",
            provider="grok",
            available=True,
            selected=True,
            last_resort=True,
        ),
    )
    view = make_alias_view(
        "large",
        "role",
        description="Large launch alias.",
        selector_mode="round_robin",
        selector_members=members,
    )

    description = _description_text_for_view(view).plain
    assert description.splitlines() == [
        "Large launch alias.",
        (
            "pool: × claude/opus@xhigh · × codex/gpt-5.6-sol@xhigh · "
            "fallback: → ✓ grok/grok-4.6@xhigh"
        ),
    ]


def _style_covering(text: Text, fragment: str) -> str:
    start = text.plain.index(fragment)
    end = start + len(fragment)
    styles = [
        str(span.style) for span in text.spans if span.start < end and span.end > start
    ]
    assert styles, f"no span covers {fragment!r} in {text.plain!r}"
    return " ".join(styles).lower()


def test_description_renders_all_soft_pool_from_selected_state() -> None:
    view = make_alias_view(
        "pool",
        "user",
        configured=True,
        configured_value="claude/opus | codex/gpt-5.5",
        selector_mode="round_robin",
        selector_members=make_pool_members((True, True), sparing=(True, True)),
    )

    text = _description_text_for_view(view)
    assert (
        text.plain.splitlines()[-1] == "pool: → ✓ claude/opus@medium · × codex/gpt-5.5"
    )
    assert " soft" not in text.plain
    assert "#ffd75f" in _style_covering(text, "→ ")
    assert "bold" in _style_covering(text, "→ ")
    assert "#ffd75f" in _style_covering(text, "✓ claude/opus@medium")
    assert "#ffd75f" in _style_covering(text, "× codex/gpt-5.5")


def test_description_keeps_green_red_and_ambers_soft_members() -> None:
    members = (
        ModelAliasSelectorMember(
            value="claude/opus@medium",
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
            available=True,
            sparing=True,
        ),
        ModelAliasSelectorMember(
            value="gemini/gemini-2.5-pro",
            target="gemini/gemini-2.5-pro",
            effort=None,
            provider="gemini",
            available=False,
        ),
    )
    view = make_alias_view(
        "pool",
        "user",
        configured=True,
        configured_value=("claude/opus@medium | codex/gpt-5.5 | gemini/gemini-2.5-pro"),
        selector_mode="round_robin",
        selector_members=members,
    )

    text = _description_text_for_view(view)
    assert text.plain.splitlines()[-1] == (
        "pool: → ✓ claude/opus@medium · × codex/gpt-5.5 · × gemini/gemini-2.5-pro"
    )
    assert " soft" not in text.plain
    assert "#87d787" in _style_covering(text, "→ ")
    assert "#87d787" in _style_covering(text, "✓ claude/opus@medium")
    assert "#ffd75f" in _style_covering(text, "× codex/gpt-5.5")
    assert "#d78787" in _style_covering(text, "× gemini/gemini-2.5-pro")


def test_description_dims_sparing_members_when_pool_is_suspended() -> None:
    view = make_alias_view(
        "pool",
        "user",
        configured=True,
        override=make_override(),
        selector_mode="round_robin",
        selector_members=make_pool_members((True, True), sparing=(True, False)),
    )

    text = _description_text_for_view(view)
    assert text.plain.splitlines()[-1] == (
        "pool (suspended by override): ✓ claude/opus@medium · ✓ codex/gpt-5.5"
    )
    assert "→" not in text.plain
    assert " soft" not in text.plain
    assert "dim" in _style_covering(text, "✓ claude/opus@medium")
    assert "#ffd75f" in _style_covering(text, "✓ claude/opus@medium")
    assert "#87d787" in _style_covering(text, "✓ codex/gpt-5.5")


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
        "medium",
        "role",
        configured=True,
        configured_value="@large@high",
        effort="high",
    )

    text = _description_text_for_view(view, default_effort).plain

    assert text == f"effort: high (via @large@high) · {comparison}"


def test_medium_description_omits_reference_source() -> None:
    view = make_alias_view(
        "medium",
        "role",
        effort="xhigh",
    )

    text = _description_text_for_view(view, None).plain

    assert text == "effort: xhigh · no default configured"


def test_reference_effort_description_is_suppressed_during_override() -> None:
    view = make_alias_view(
        "medium",
        "role",
        override=make_override(),
        effort="medium",
    )

    text = _description_text_for_view(view, "low").plain

    assert text == "effort: medium · overrides default low"
