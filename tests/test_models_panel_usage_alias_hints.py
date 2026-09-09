"""Alias-detail capacity hints must not consume round-robin or change routing."""

from __future__ import annotations

from sase.ace.tui.modals.models_panel_rendering_descriptions import (
    description_text_for_view,
)
from sase.llm_provider import config as llm_config
from sase.llm_provider.config import ModelAliasSelectorMember
from tests._models_panel_helpers import make_alias_view
from tests.llm_provider._load_balanced_alias_helpers import (
    configure_pool,
    pool_member_snapshot,
)
from tests.llm_provider.test_usage_hints import _claude_model_specific_low


def test_alias_detail_lists_member_capacity_without_combined_percent() -> None:
    claude = _claude_model_specific_low()
    view = make_alias_view(
        "large",
        "role",
        description="Highest-capability model used by large phases.",
        selector_mode="round_robin",
        selector_members=(
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
                available=True,
            ),
        ),
    )
    text = description_text_for_view(view, usage_providers=(claude,))

    assert "pool:" in text.plain
    assert "claude/opus" in text.plain
    assert "6% left" in text.plain
    assert "46%" not in text.plain


def test_alias_capacity_inspection_does_not_advance_round_robin(
    monkeypatch,
) -> None:
    configure_pool(monkeypatch)
    before = pool_member_snapshot()
    view = make_alias_view(
        "pool",
        "user",
        configured=True,
        selector_mode="round_robin",
        selector_members=before,
        provider="claude",
        model="opus",
    )
    description_text_for_view(
        view,
        usage_providers=(_claude_model_specific_low(),),
    )
    after = pool_member_snapshot()

    assert [member.selected for member in before] == [
        member.selected for member in after
    ]
    assert [member.available for member in before] == [
        member.available for member in after
    ]
    llm_config.resolve_model_alias("@pool", consume=True)
    consumed = pool_member_snapshot()
    assert [member.selected for member in consumed] != [
        member.selected for member in before
    ]
