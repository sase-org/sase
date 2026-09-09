"""Scoped capacity hints for picker rows, alias members, and attention."""

from __future__ import annotations

from sase.llm_provider.config import ModelAliasSelectorMember
from sase.llm_provider.usage.hints import (
    alias_capacity_hint,
    capacity_hint_marker,
    capacity_hint_style,
    indicator_usage_attention,
    member_capacity_hint,
    model_capacity_hint,
    provider_header_capacity_hint,
)
from sase.llm_provider.usage.store import provider_usage_window_applies
from tests._usage_view_helpers import usage_provider, usage_window


def _constraint(window: dict[str, object], attention: str) -> dict[str, object]:
    return {
        "attention": attention,
        "freshness": window["freshness"],
        "observed_at": window["observed_at"],
        "remaining_percent": window["remaining_percent"],
        "reset_passed": window["reset_passed"],
        "used_percent": window["used_percent"],
        "vendor_state": window["vendor_state"],
        "window_key": window["key"],
    }


def _claude_shared_rejected_and_model_healthy() -> dict[str, object]:
    shared = usage_window(
        key="weekly",
        label="Week · all",
        used_percent=100.0,
        remaining_percent=0.0,
        vendor_state="rejected",
        applicability={"kind": "account"},
    )
    specific = usage_window(
        key="opus-week",
        label="Opus week",
        used_percent=10.0,
        remaining_percent=90.0,
        vendor_state="allowed",
        applicability={"kind": "models", "model_ids": ["opus"]},
    )
    return usage_provider(
        "claude",
        used_percent=100.0,
        remaining_percent=0.0,
        attention={"kind": "rejected", "provider": "claude", "window_key": "weekly"},
        scope={"kind": "account"},
        windows=[shared, specific],
        known_constraints=[_constraint(shared, "rejected")],
    )


def _claude_model_specific_low() -> dict[str, object]:
    shared = usage_window(
        key="weekly",
        label="Week · all",
        used_percent=20.0,
        remaining_percent=80.0,
        vendor_state="allowed",
        applicability={"kind": "account"},
    )
    opus = usage_window(
        key="opus-week",
        label="Opus week",
        used_percent=94.0,
        remaining_percent=6.0,
        vendor_state="warning",
        applicability={"kind": "models", "model_ids": ["opus"]},
    )
    return usage_provider(
        "claude",
        used_percent=20.0,
        remaining_percent=80.0,
        attention={"kind": "low", "provider": "claude", "window_key": "opus-week"},
        scope={"kind": "account"},
        windows=[shared, opus],
        known_constraints=[_constraint(opus, "low")],
    )


def _codex_unknown_scope() -> dict[str, object]:
    unknown = usage_window(
        key="mystery",
        label="mystery-bucket",
        used_percent=94.0,
        remaining_percent=6.0,
        vendor_state="warning",
        applicability={
            "kind": "unknown",
            "vendor_label": "bucket",
            "vendor_id": "lim",
        },
    )
    return usage_provider(
        "codex",
        used_percent=94.0,
        remaining_percent=6.0,
        attention={"kind": "low", "provider": "codex", "window_key": "mystery"},
        scope={"kind": "unknown", "vendor_label": "bucket", "vendor_id": "lim"},
        windows=[unknown],
        known_constraints=[_constraint(unknown, "low")],
    )


def test_window_applies_distinguishes_shared_model_and_unknown() -> None:
    assert provider_usage_window_applies({"kind": "account"}, "opus") == "applies"
    assert (
        provider_usage_window_applies({"kind": "models", "model_ids": ["opus"]}, "opus")
        == "applies"
    )
    assert (
        provider_usage_window_applies(
            {"kind": "models", "model_ids": ["opus"]}, "sonnet"
        )
        == "does_not_apply"
    )
    assert (
        provider_usage_window_applies(
            {"kind": "unknown", "vendor_label": "bucket", "vendor_id": "lim"},
            "opus",
        )
        == "unknown"
    )


def test_shared_rejection_stays_on_header_not_healthy_model_row() -> None:
    provider = _claude_shared_rejected_and_model_healthy()

    header = provider_header_capacity_hint(provider)
    opus = model_capacity_hint(provider, "opus")
    sonnet = model_capacity_hint(provider, "sonnet")

    assert header is not None
    assert header.kind == "rejected"
    assert "0% left" in header.label
    assert opus is None
    assert sonnet is None


def test_low_model_window_does_not_implicate_other_models() -> None:
    provider = _claude_model_specific_low()

    header = provider_header_capacity_hint(provider)
    opus = model_capacity_hint(provider, "opus")
    sonnet = model_capacity_hint(provider, "sonnet")

    assert header is None
    assert opus is not None
    assert opus.kind == "low"
    assert "6% left" in opus.label
    assert sonnet is None


def test_unknown_bucket_stays_on_the_provider_header() -> None:
    provider = _codex_unknown_scope()

    header = provider_header_capacity_hint(provider)
    model = model_capacity_hint(provider, "gpt-5.5")

    assert header is not None
    assert "scope unknown" in header.label
    assert model is None


def test_alias_members_are_not_combined_into_a_pool_percentage() -> None:
    claude = _claude_model_specific_low()
    codex = usage_provider(
        "codex",
        used_percent=54.0,
        remaining_percent=46.0,
        attention={"kind": "none", "provider": "codex", "window_key": None},
        windows=[
            usage_window(
                key="week",
                label="Week",
                used_percent=54.0,
                remaining_percent=46.0,
                vendor_state="allowed",
                applicability={"kind": "account"},
            )
        ],
    )
    members = (
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
    )

    hint = alias_capacity_hint(
        provider="claude",
        model="opus",
        selector_members=members,
        providers={"claude": claude, "codex": codex},
    )

    assert hint is not None
    assert "opus" in hint.label
    assert "6% left" in hint.label
    assert "46%" not in hint.label


def test_member_hint_includes_shared_rejection() -> None:
    provider = _claude_shared_rejected_and_model_healthy()
    hint = member_capacity_hint(provider, "opus")

    assert hint is not None
    assert hint.kind == "rejected"


def test_indicator_ranks_rejected_over_collection_then_low_and_skips_ineligible() -> (
    None
):
    rejected = _claude_shared_rejected_and_model_healthy()
    low = usage_provider(
        "codex",
        used_percent=80.0,
        remaining_percent=20.0,
        attention={"kind": "low", "provider": "codex", "window_key": "shared"},
        windows=[usage_window(key="shared", label="Shared 5h")],
        known_constraints=[
            _constraint(usage_window(key="shared", label="Shared 5h"), "low")
        ],
    )
    problem = usage_provider(
        "grok",
        used_percent=None,
        remaining_percent=None,
        collection_status="error",
        attention={
            "kind": "collection_problem",
            "provider": "grok",
            "window_key": None,
        },
        windows=[],
    )
    unused = usage_provider(
        "fakey",
        used_percent=None,
        remaining_percent=None,
        collection_status="unsupported",
        attention={
            "kind": "collection_problem",
            "provider": "fakey",
            "window_key": None,
        },
        windows=[],
    )

    item, count = indicator_usage_attention(
        (rejected, low, problem, unused),
        eligible={"claude", "codex", "grok"},
    )

    assert item is not None
    assert item.provider == "claude"
    assert item.kind == "rejected"
    assert count == 3


def test_collection_problem_hint_uses_failing_warning_identity() -> None:
    problem = usage_provider(
        "grok",
        used_percent=None,
        remaining_percent=None,
        collection_status="error",
        attention={
            "kind": "collection_problem",
            "provider": "grok",
            "window_key": None,
        },
        windows=[],
    )
    low = usage_provider(
        "codex",
        used_percent=80.0,
        remaining_percent=20.0,
        attention={"kind": "low", "provider": "codex", "window_key": "week"},
        windows=[
            usage_window(
                key="week",
                label="Week",
                used_percent=80.0,
                remaining_percent=20.0,
                applicability={"kind": "account"},
            )
        ],
    )

    header = provider_header_capacity_hint(problem)
    member = member_capacity_hint(problem, "gpt-5")
    item, count = indicator_usage_attention((low, problem), eligible={"codex", "grok"})

    assert header is not None
    assert header.label == "usage failing"
    assert header.marker == "⚠"
    assert member is not None
    assert member.label == "usage failing"
    assert capacity_hint_marker("collection_problem") == "⚠"
    assert capacity_hint_style("collection_problem") == "bold #FFAF5F"
    assert item is not None
    assert item.provider == "grok"
    assert count == 2


def test_indicator_tie_breaks_equal_rank_by_provider_id() -> None:
    alpha = usage_provider(
        "grok",
        used_percent=80.0,
        remaining_percent=20.0,
        attention={"kind": "low", "provider": "grok", "window_key": "week"},
        windows=[
            usage_window(
                key="week",
                label="Week",
                used_percent=80.0,
                remaining_percent=20.0,
                applicability={"kind": "account"},
            )
        ],
    )
    beta = usage_provider(
        "codex",
        used_percent=80.0,
        remaining_percent=20.0,
        attention={"kind": "low", "provider": "codex", "window_key": "week"},
        windows=[
            usage_window(
                key="week",
                label="Week",
                used_percent=80.0,
                remaining_percent=20.0,
                applicability={"kind": "account"},
            )
        ],
    )

    item, count = indicator_usage_attention((alpha, beta), eligible={"grok", "codex"})

    assert item is not None
    assert item.provider == "codex"
    assert count == 2


def test_healthy_fresh_state_does_not_alert() -> None:
    provider = usage_provider(
        "claude",
        used_percent=10.0,
        remaining_percent=90.0,
        attention={"kind": "none", "provider": "claude", "window_key": "weekly"},
        windows=[
            usage_window(
                key="weekly",
                label="Week · all",
                used_percent=10.0,
                remaining_percent=90.0,
                vendor_state="allowed",
                applicability={"kind": "account"},
            )
        ],
    )

    assert provider_header_capacity_hint(provider) is None
    assert model_capacity_hint(provider, "opus") is None
    item, count = indicator_usage_attention((provider,), eligible={"claude"})
    assert item is None
    assert count == 0
