"""Tests for Models-panel row aggregation in :mod:`sase.llm_provider.alias_view`."""

from __future__ import annotations

import pytest

from sase.llm_provider import (
    AliasView,
    BucketView,
    CODERS_BUCKET_DESCRIPTION,
    PHASE_WORKER_BUCKET_DESCRIPTION,
    TemporaryLLMOverride,
    build_models_panel_rows,
    clear_alias_override,
    set_alias_override,
)
from tests.llm_provider._provider_config_helpers import (
    mock_provider_config,
    patch_available_providers,
)


def _user_view(
    name: str,
    provider: str,
    model: str,
    *,
    bucket: str | None = None,
    override: TemporaryLLMOverride | None = None,
) -> AliasView:
    return AliasView(
        name=name,
        kind="user",
        configured=True,
        configured_value=f"{provider}/{model}",
        provider=provider,
        model=model,
        override=override,
        configured_source="custom",
        description=f"{name} role.",
        bucket=bucket,
    )


def test_bucket_view_derived_fields() -> None:
    override = TemporaryLLMOverride(
        provider="codex",
        model="gpt-5.6-sol",
        raw_model="codex/gpt-5.6-sol",
        created_at=0.0,
        expires_at=None,
        source="test",
    )
    bucket = BucketView(
        name="research",
        description="Research roles.",
        members=(
            _user_view("research_a", "codex", "gpt-5.6-sol", override=override),
            _user_view("research_b", "claude", "opus"),
            _user_view("research_c", "codex", "gpt-5.6-sol"),
        ),
    )

    assert bucket.alias_count == 3
    assert bucket.override_count == 1
    assert bucket.model_summary == "codex/gpt-5.6-sol +1"
    assert bucket.model_counts == (
        ("codex/gpt-5.6-sol", 2),
        ("claude/opus", 1),
    )


def test_models_panel_rows_fold_buckets_before_ungrouped_aliases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "model_aliases": {
                "custom": {
                    "zeta": {
                        "model": "codex/gpt-5.6-sol",
                        "description": "Research C.",
                        "bucket": "research",
                    },
                    "beta": {
                        "model": "claude/opus",
                        "description": "Research B.",
                        "bucket": "research",
                    },
                    "gamma": {
                        "model": "codex/o3",
                        "description": "Coding role.",
                        "bucket": "coding",
                    },
                    "alpha": {
                        "model": "claude/haiku",
                        "description": "Ungrouped role.",
                    },
                },
                "buckets": {
                    "research": {"description": "Research roles."},
                    "unused": {"description": "No members."},
                },
            },
        },
    )
    patch_available_providers(monkeypatch)

    rows = build_models_panel_rows()
    assert [row.name for row in rows] == [
        "default",
        "coders",
        "epic_lander",
        "big_epic_lander",
        "phase_worker",
        "smartest",
        "smart",
        "cheap",
        "cheaper",
        "cheapest",
        "coding",
        "research",
        "alpha",
    ]
    assert all(row.name not in {"coder", "claude_coder", "codex_coder"} for row in rows)

    user_rows = rows[10:]
    assert [row.name for row in user_rows] == ["coding", "research", "alpha"]
    coding, research, alpha = user_rows
    assert isinstance(coding, BucketView)
    assert coding.description is None
    assert isinstance(research, BucketView)
    assert research.description == "Research roles."
    assert [member.name for member in research.members] == ["beta", "zeta"]
    assert isinstance(alpha, AliasView)
    assert alpha.bucket is None
    assert all(row.name != "unused" for row in user_rows)


def test_models_panel_rows_coalesce_custom_coders_members(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "model_aliases": {
                "builtin": {
                    "coder": "claude/sonnet",
                    "claude_coder": "codex/o3",
                },
                "custom": {
                    "helper": {
                        "model": "claude/sonnet",
                        "description": "Extra coder helper.",
                        "bucket": "coders",
                    },
                    "zeta": {
                        "model": "codex/o3",
                        "description": "Research role.",
                        "bucket": "research",
                    },
                    "alpha": {
                        "model": "claude/haiku",
                        "description": "Ungrouped role.",
                    },
                },
                "buckets": {
                    "coders": {"description": "Configured coder roles."},
                    "research": {"description": "Research roles."},
                },
            },
        },
    )
    patch_available_providers(monkeypatch)

    set_alias_override("codex_coder", "codex/gpt-5.6-sol", 3600.0, source="test")
    try:
        rows = build_models_panel_rows()
    finally:
        clear_alias_override("codex_coder")

    assert [row.name for row in rows] == [
        "default",
        "coders",
        "epic_lander",
        "big_epic_lander",
        "phase_worker",
        "smartest",
        "smart",
        "cheap",
        "cheaper",
        "cheapest",
        "research",
        "alpha",
    ]
    coder_buckets = [
        row for row in rows if isinstance(row, BucketView) and row.name == "coders"
    ]
    assert len(coder_buckets) == 1
    bucket = coder_buckets[0]
    assert bucket.description == "Configured coder roles."
    assert [member.name for member in bucket.members] == [
        "coder",
        "claude_coder",
        "codex_coder",
        "helper",
    ]
    assert [member.kind for member in bucket.members] == [
        "role",
        "provider_coder",
        "provider_coder",
        "user",
    ]
    assert [member.configured for member in bucket.members] == [True, True, False, True]
    assert bucket.alias_count == 4
    assert bucket.override_count == 1
    assert bucket.model_summary == "claude/sonnet +2"
    assert bucket.model_counts == (
        ("claude/sonnet", 2),
        ("codex/gpt-5.6-sol", 1),
        ("codex/o3", 1),
    )


def test_models_panel_coders_bucket_uses_builtin_fallback_description(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(monkeypatch, {"provider": "claude", "model_aliases": {}})
    patch_available_providers(monkeypatch)

    rows = build_models_panel_rows()
    coders = next(row for row in rows if row.name == "coders")

    assert isinstance(coders, BucketView)
    assert coders.description == CODERS_BUCKET_DESCRIPTION


def test_models_panel_phase_worker_bucket_coalesces_builtin_and_custom_members(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "model_aliases": {
                "builtin": {"large_phase_worker": "codex/o3"},
                "custom": {
                    "phase_worker": {
                        "model": "claude/sonnet",
                        "description": "Explicit custom phase role.",
                        "bucket": "phase_worker",
                    },
                    "phase_reviewer": {
                        "model": "claude/opus",
                        "description": "Reviews completed phases.",
                        "bucket": "phase_worker",
                    },
                },
                "buckets": {"phase_worker": {"description": "Configured phase roles."}},
            },
        },
    )
    patch_available_providers(monkeypatch)

    set_alias_override(
        "medium_phase_worker", "codex/gpt-5.6-sol", 3600.0, source="test"
    )
    try:
        rows = build_models_panel_rows()
    finally:
        clear_alias_override("medium_phase_worker")

    assert [row.name for row in rows] == [
        "default",
        "coders",
        "epic_lander",
        "big_epic_lander",
        "phase_worker",
        "smartest",
        "smart",
        "cheap",
        "cheaper",
        "cheapest",
    ]
    phase_workers = rows[4]
    assert isinstance(phase_workers, BucketView)
    assert phase_workers.description == "Configured phase roles."
    assert [member.name for member in phase_workers.members] == [
        "xsmall_phase_worker",
        "small_phase_worker",
        "medium_phase_worker",
        "large_phase_worker",
        "xlarge_phase_worker",
        "phase_reviewer",
        "phase_worker",
    ]
    assert phase_workers.alias_count == 7
    assert phase_workers.override_count == 1


def test_models_panel_phase_worker_bucket_uses_builtin_fallback_description(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(monkeypatch, {"provider": "claude", "model_aliases": {}})
    patch_available_providers(monkeypatch)

    rows = build_models_panel_rows()
    phase_workers = next(row for row in rows if row.name == "phase_worker")

    assert isinstance(phase_workers, BucketView)
    assert phase_workers.description == PHASE_WORKER_BUCKET_DESCRIPTION
    assert phase_workers.alias_count == 5
