"""Tests for :mod:`sase.llm_provider.alias_view` (the Models-panel data layer).

Phase 2 (epic sase-5e) aggregation helper: covers kind/provenance
classification, deterministic ordering, and the temporary-override merge for
both ``default`` and non-``default`` aliases.
"""

from __future__ import annotations

import pytest

from sase.llm_provider import (
    build_alias_views,
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
                    "default": "codex/gpt-5.6",
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
