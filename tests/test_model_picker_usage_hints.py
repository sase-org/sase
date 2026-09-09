"""Model-picker capacity hints coexist with advisories and never change routing."""

from __future__ import annotations

from sase.ace.tui.modals.model_picker_options import rows_to_options
from sase.ace.tui.modals.model_picker_rows import (
    AliasSelectionContext,
    build_model_rows,
)
from sase.llm_provider.config import ModelAliasSelectorMember
from tests.llm_provider.test_usage_hints import (
    _claude_model_specific_low,
    _claude_shared_rejected_and_model_healthy,
    _codex_unknown_scope,
)
from tests._models_panel_helpers import make_alias_view


def test_picker_shared_rejection_is_on_header_not_every_model() -> None:
    rows = build_model_rows(
        usage_providers=(_claude_shared_rejected_and_model_healthy(),)
    )
    header = next(row for row in rows if row.option_id == "__header_claude__")
    opus = next(row for row in rows if row.option_id == "opus")
    sonnet = next(row for row in rows if row.option_id == "sonnet")

    assert header.capacity_severity == "rejected"
    assert header.capacity_label is not None
    assert "0% left" in header.capacity_label
    assert opus.capacity_label is None
    assert sonnet.capacity_label is None
    assert opus.disabled is False
    assert sonnet.disabled is False


def test_picker_low_model_window_stays_on_that_model() -> None:
    rows = build_model_rows(usage_providers=(_claude_model_specific_low(),))
    header = next(row for row in rows if row.option_id == "__header_claude__")
    opus = next(row for row in rows if row.option_id == "opus")
    sonnet = next(row for row in rows if row.option_id == "sonnet")

    assert header.capacity_label is None
    assert opus.capacity_label is not None
    assert "6% left" in opus.capacity_label
    assert sonnet.capacity_label is None


def test_picker_unknown_scope_stays_on_the_provider_header() -> None:
    rows = build_model_rows(usage_providers=(_codex_unknown_scope(),))
    header = next(row for row in rows if row.option_id == "__header_codex__")
    model = next(row for row in rows if row.option_id == "gpt-5.5")

    assert header.capacity_label is not None
    assert "scope unknown" in header.capacity_label
    assert model.capacity_label is None


def test_picker_capacity_coexists_with_model_advisory() -> None:
    contributor = "muse-spark-1.2-contributor"
    provider = _claude_model_specific_low()
    provider["provider"] = "muse"
    provider["windows"][1]["applicability"] = {
        "kind": "models",
        "model_ids": [contributor],
    }
    provider["known_constraints"][0]["window_key"] = provider["windows"][1]["key"]
    provider["attention"] = {
        "kind": "low",
        "provider": "muse",
        "window_key": provider["windows"][1]["key"],
    }

    rows = build_model_rows(usage_providers=(provider,))
    flagged = next(row for row in rows if row.option_id == contributor)

    assert flagged.advisory_label == "trains on your data"
    assert flagged.capacity_label is not None
    assert "6% left" in flagged.capacity_label
    option = next(
        option
        for option in rows_to_options([flagged])
        if option is not None and option.id == contributor
    )
    assert "⚠ trains on your data" in str(option.prompt)
    assert "! " in str(option.prompt)
    assert "6% left" in str(option.prompt)


def test_picker_capacity_does_not_reorder_or_disable_models() -> None:
    without = [
        row.option_id
        for row in build_model_rows(usage_providers=())
        if row.kind in {"provider", "model"}
    ]
    with_hints = [
        row.option_id
        for row in build_model_rows(
            usage_providers=(
                _claude_shared_rejected_and_model_healthy(),
                _claude_model_specific_low(),
            )
        )
        if row.kind in {"provider", "model"}
    ]

    assert without == with_hints
    rows = build_model_rows(
        usage_providers=(_claude_shared_rejected_and_model_healthy(),)
    )
    assert all(
        not row.disabled or row.kind == "provider" for row in rows if row.is_model
    )


def test_picker_alias_row_shows_member_constraint_without_combined_percent() -> None:
    views = (
        make_alias_view(
            "large",
            "role",
            provider="claude",
            model="opus",
            selector_mode="round_robin",
            selector_members=(
                ModelAliasSelectorMember(
                    value="claude/opus",
                    target="claude/opus",
                    effort=None,
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
        ),
    )
    context = AliasSelectionContext(
        views=views,
        target_alias="medium",
        operation="persistent",
    )
    rows = build_model_rows(
        alias_context=context,
        usage_providers=(_claude_model_specific_low(),),
    )
    alias = next(row for row in rows if row.alias_name == "large")

    assert alias.capacity_label is not None
    assert "opus" in alias.capacity_label
    assert "6% left" in alias.capacity_label
    assert "46%" not in (alias.capacity_label or "")
