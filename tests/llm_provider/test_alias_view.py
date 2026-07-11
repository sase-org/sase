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
    assert by_name["phase_worker"].kind == "role"
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
    role_slice = names[1:5]
    assert role_slice == ["coder", "epic_creator", "epic_lander", "phase_worker"]
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
    user_rows = [
        row
        for row in rows
        if isinstance(row, BucketView)
        or (isinstance(row, AliasView) and row.kind == "user")
    ]

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

    set_alias_override("default", "opus", None, source="test")
    try:
        default = {v.name: v for v in build_alias_views()}["default"]
    finally:
        clear_alias_override("default")

    assert default.is_overridden is True
    assert default.provider == "claude"
    assert default.model == "opus"
