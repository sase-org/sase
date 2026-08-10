"""Tests for Models-panel row aggregation in :mod:`sase.llm_provider.alias_view`."""

from __future__ import annotations

import pytest

from sase.llm_provider import (
    AliasView,
    BucketView,
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

    user_rows = rows[9:]
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


def test_models_panel_rows_treat_retired_coder_aliases_as_user_aliases(
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
                        "description": "Extra coding helper.",
                        "bucket": "coding",
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
                    "coding": {"description": "Configured coding roles."},
                    "research": {"description": "Research roles."},
                },
            },
        },
    )
    patch_available_providers(monkeypatch)

    set_alias_override("helper", "codex/gpt-5.6-sol", 3600.0, source="test")
    try:
        rows = build_models_panel_rows()
    finally:
        clear_alias_override("helper")

    assert [row.name for row in rows] == [
        "default",
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
        "claude_coder",
        "coder",
    ]
    coding_buckets = [
        row for row in rows if isinstance(row, BucketView) and row.name == "coding"
    ]
    assert len(coding_buckets) == 1
    bucket = coding_buckets[0]
    assert bucket.description == "Configured coding roles."
    assert [member.name for member in bucket.members] == ["helper"]
    assert [member.kind for member in bucket.members] == ["user"]
    assert [member.configured for member in bucket.members] == [True]
    assert bucket.alias_count == 1
    assert bucket.override_count == 1
    assert bucket.model_summary == "codex/gpt-5.6-sol"
    assert bucket.model_counts == (("codex/gpt-5.6-sol", 1),)

    user_by_name = {
        row.name: row
        for row in rows
        if isinstance(row, AliasView) and row.kind == "user"
    }
    assert user_by_name["coder"].configured_source == "builtin"
    assert user_by_name["claude_coder"].configured_source == "builtin"


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
        "epic_lander",
        "big_epic_lander",
        "phase_worker",
        "smartest",
        "smart",
        "cheap",
        "cheaper",
        "cheapest",
    ]
    phase_workers = rows[3]
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
