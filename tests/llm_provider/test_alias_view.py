"""Tests for :mod:`sase.llm_provider.alias_view` (the Models-panel data layer).

Phase 2 (epic sase-5e) aggregation helper: covers kind/provenance
classification, deterministic ordering, and the temporary-override merge for
both ``default`` and non-``default`` aliases.
"""

from __future__ import annotations

import pytest

from sase.llm_provider import (
    AliasView,
    BucketView,
    CODERS_BUCKET_DESCRIPTION,
    PHASE_WORKER_BUCKET_DESCRIPTION,
    TemporaryLLMOverride,
    build_alias_views,
    build_models_panel_rows,
    clear_alias_override,
    set_alias_override,
)
from tests.llm_provider._provider_config_helpers import mock_provider_config


def _patch_providers(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the registered providers so ``<provider>_coder`` rows are stable."""
    monkeypatch.setattr(
        "sase.llm_provider.registry.registered_provider_names",
        lambda: ["claude", "codex"],
    )


def test_includes_default_role_provider_coder_and_user_aliases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "model_aliases": {
                "custom": {
                    "myalias": {
                        "model": "claude/opus",
                        "description": "Test alias.",
                    }
                }
            },
        },
    )
    _patch_providers(monkeypatch)

    views = build_alias_views()
    by_name = {v.name: v for v in views}

    assert by_name["default"].kind == "default"
    assert by_name["default"].configured is False
    assert by_name["coder"].kind == "role"
    assert by_name["big_epic_lander"].kind == "role"
    assert by_name["phase_worker"].kind == "role"
    assert by_name["small_phase_worker"].kind == "role"
    assert by_name["medium_phase_worker"].kind == "role"
    assert by_name["large_phase_worker"].kind == "role"
    assert by_name["smartest"].kind == "role"
    assert by_name["claude_coder"].kind == "provider_coder"
    assert by_name["codex_coder"].kind == "provider_coder"

    myalias = by_name["myalias"]
    assert myalias.kind == "user"
    assert myalias.configured is True
    assert myalias.configured_value == "claude/opus"


def test_default_is_first_and_groups_are_ordered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "model_aliases": {
                "custom": {
                    "zeta": {"model": "claude/opus", "description": "Zeta alias."},
                    "alpha": {"model": "codex/o3", "description": "Alpha alias."},
                }
            },
        },
    )
    _patch_providers(monkeypatch)

    names = [v.name for v in build_alias_views()]

    assert names[0] == "default"
    # role aliases follow default, in canonical order
    role_slice = names[1:9]
    assert role_slice == [
        "coder",
        "epic_lander",
        "big_epic_lander",
        "phase_worker",
        "small_phase_worker",
        "medium_phase_worker",
        "large_phase_worker",
        "smartest",
    ]
    # provider_coder aliases come next, alphabetically
    assert names.index("claude_coder") < names.index("codex_coder")
    assert names.index("codex_coder") < names.index("alpha")
    # user aliases come last, alphabetically
    assert names.index("alpha") < names.index("zeta")


def test_configured_value_shadows_role_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(
        monkeypatch,
        {"provider": "claude", "model_aliases": {"builtin": {"coder": "codex/o3"}}},
    )
    _patch_providers(monkeypatch)

    coder = {v.name: v for v in build_alias_views()}["coder"]
    assert coder.kind == "role"
    assert coder.configured is True
    assert coder.configured_value == "codex/o3"


@pytest.mark.parametrize(
    ("configured_value", "expected"),
    [
        ("@default", "default"),
        ("claude/opus", None),
        (None, None),
    ],
)
def test_alias_view_references(
    configured_value: str | None,
    expected: str | None,
) -> None:
    view = AliasView(
        name="coder",
        kind="role",
        configured=configured_value is not None,
        configured_value=configured_value,
        provider="claude",
        model="opus",
        override=None,
    )

    assert view.references == expected


def test_big_epic_alias_view_exposes_immediate_implicit_fallback() -> None:
    view = AliasView(
        name="big_epic_lander",
        kind="role",
        configured=False,
        configured_value=None,
        provider="claude",
        model="opus",
        override=None,
    )

    assert view.implicit_fallback == "epic_lander"


def test_unconfigured_provider_coder_follows_configured_coder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An implicit ``<provider>_coder`` row resolves through a configured ``coder``.

    This is what the Models panel displays for an unconfigured provider-coder
    alias: its effective provider/model must match the generic ``coder`` alias,
    not the ``@default`` target.
    """
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "model_aliases": {
                "builtin": {
                    "default": "codex/gpt-5.6-sol",
                    "coder": "claude/sonnet",
                }
            },
        },
    )
    _patch_providers(monkeypatch)

    by_name = {v.name: v for v in build_alias_views()}
    codex_coder = by_name["codex_coder"]

    assert codex_coder.kind == "provider_coder"
    assert codex_coder.configured is False
    # Effective target follows @coder (claude/sonnet), not @default.
    assert codex_coder.provider == "claude"
    assert codex_coder.model == "sonnet"


def test_custom_alias_view_carries_source_and_description(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "model_aliases": {
                "custom": {
                    "blogger": {
                        "model": "claude/opus",
                        "description": "Draft blog posts.",
                        "bucket": "writing",
                    }
                }
            },
        },
    )
    _patch_providers(monkeypatch)

    blogger = {v.name: v for v in build_alias_views()}["blogger"]

    assert blogger.kind == "user"
    assert blogger.configured is True
    assert blogger.configured_value == "claude/opus"
    assert blogger.configured_source == "custom"
    assert blogger.description == "Draft blog posts."
    assert blogger.bucket == "writing"


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
    _patch_providers(monkeypatch)

    rows = build_models_panel_rows()
    assert [row.name for row in rows] == [
        "default",
        "coders",
        "epic_lander",
        "big_epic_lander",
        "phase_worker",
        "smartest",
        "coding",
        "research",
        "alpha",
    ]
    assert all(row.name not in {"coder", "claude_coder", "codex_coder"} for row in rows)

    user_rows = rows[6:]
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
    _patch_providers(monkeypatch)

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
    _patch_providers(monkeypatch)

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
                "builtin": {
                    "phase_worker": "claude/sonnet",
                    "large_phase_worker": "codex/o3",
                },
                "custom": {
                    "phase_reviewer": {
                        "model": "claude/opus",
                        "description": "Reviews completed phases.",
                        "bucket": "phase_worker",
                    }
                },
                "buckets": {"phase_worker": {"description": "Configured phase roles."}},
            },
        },
    )
    _patch_providers(monkeypatch)

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
    ]
    phase_workers = rows[4]
    assert isinstance(phase_workers, BucketView)
    assert phase_workers.description == "Configured phase roles."
    assert [member.name for member in phase_workers.members] == [
        "phase_worker",
        "small_phase_worker",
        "medium_phase_worker",
        "large_phase_worker",
        "phase_reviewer",
    ]
    assert phase_workers.alias_count == 5
    assert phase_workers.override_count == 1


def test_models_panel_phase_worker_bucket_uses_builtin_fallback_description(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(monkeypatch, {"provider": "claude", "model_aliases": {}})
    _patch_providers(monkeypatch)

    rows = build_models_panel_rows()
    phase_workers = next(row for row in rows if row.name == "phase_worker")

    assert isinstance(phase_workers, BucketView)
    assert phase_workers.description == PHASE_WORKER_BUCKET_DESCRIPTION


def test_non_default_override_wins_effective_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(
        monkeypatch,
        {"provider": "claude", "model_aliases": {}},
    )
    _patch_providers(monkeypatch)

    set_alias_override("coder", "codex/o3", 3600.0, source="test")
    try:
        coder = {v.name: v for v in build_alias_views()}["coder"]
    finally:
        clear_alias_override("coder")

    assert coder.is_overridden is True
    assert coder.override is not None
    assert coder.provider == "codex"
    assert coder.model == "o3"


def test_default_override_is_surfaced_on_default_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(
        monkeypatch,
        {"provider": "claude", "model_aliases": {}},
    )
    _patch_providers(monkeypatch)

    set_alias_override("default", "codex/o3", None, source="test")
    try:
        default = {v.name: v for v in build_alias_views()}["default"]
    finally:
        clear_alias_override("default")

    assert default.is_overridden is True
    assert default.provider == "codex"
    assert default.model == "o3"
    # An explicit nested @default reference ignores the machine-wide default
    # override and keeps representing the configured/provider default.
    assert default.selection_provider == "claude"
    assert default.selection_model == "opus"
