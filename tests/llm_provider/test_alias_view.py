"""Tests for alias resolution in :mod:`sase.llm_provider.alias_view`."""

from __future__ import annotations

import pytest

from sase.llm_provider import build_alias_views
from sase.llm_provider.load_balancing import parse_model_alias_selector
from sase.llm_provider.model_alias_policy import implicit_alias_targets
from tests._model_alias_defaults_fixture import (
    FROZEN_SELECTOR_MEMBER_DETAILS,
    FROZEN_TARGETS,
    frozen_selector_provider_model_effort,
)
from tests.llm_provider._provider_config_helpers import (
    mock_provider_config,
    patch_available_providers,
)


def test_includes_size_and_user_aliases(
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
    patch_available_providers(monkeypatch)

    views = build_alias_views()
    by_name = {v.name: v for v in views}
    targets = implicit_alias_targets()

    for alias in ("xsmall", "small", "medium", "large", "xlarge"):
        assert by_name[alias].kind == "role"
        assert by_name[alias].configured is False
        assert by_name[alias].implicit_fallback is None
        assert by_name[alias].implicit_value == FROZEN_TARGETS[alias]
        selector = parse_model_alias_selector(targets[alias])
        assert selector is not None
        assert by_name[alias].selector_mode == selector.mode
        assert [
            (member.target, member.effort) for member in by_name[alias].selector_members
        ] == list(FROZEN_SELECTOR_MEMBER_DETAILS[alias])

    assert "default" not in by_name
    assert "medium_worker" not in by_name
    assert "smart" not in by_name
    assert "coder" not in by_name

    myalias = by_name["myalias"]
    assert myalias.kind == "user"
    assert myalias.configured is True
    assert myalias.configured_value == "claude/opus"


def test_retired_provider_coder_aliases_hidden_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(monkeypatch, {"provider": "claude"})

    by_name = {v.name: v for v in build_alias_views()}

    assert "fakey_coder" not in by_name
    assert "claude_coder" not in by_name
    assert "codex_coder" not in by_name


def test_configured_fakey_coder_alias_still_surfaces(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "model_aliases": {
                "custom": {
                    "fakey_coder": {
                        "model": "fakey/fakey-large",
                        "description": "Explicit fakey coder.",
                    }
                }
            },
        },
    )

    by_name = {v.name: v for v in build_alias_views()}

    assert by_name["fakey_coder"].kind == "user"
    assert by_name["fakey_coder"].configured is True
    assert by_name["fakey_coder"].configured_value == "fakey/fakey-large"


def test_size_aliases_are_first_and_user_aliases_are_ordered(
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
    patch_available_providers(monkeypatch)

    names = [v.name for v in build_alias_views()]

    assert names[:5] == ["xsmall", "small", "medium", "large", "xlarge"]
    assert names.index("alpha") < names.index("zeta")


def test_xlarge_view_uses_pool_availability_before_last_resort(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(monkeypatch, {"provider": "claude"})
    patch_available_providers(monkeypatch)
    monkeypatch.setattr(
        "sase.llm_provider.config._resolved_target_is_available",
        lambda target: target.startswith("codex/"),
    )

    xlarge = {view.name: view for view in build_alias_views()}["xlarge"]

    assert (xlarge.provider, xlarge.model, xlarge.effort) == (
        frozen_selector_provider_model_effort("xlarge", 1)
    )
    assert xlarge.selector_mode == "round_robin"
    selected = next(member for member in xlarge.selector_members if member.selected)
    assert selected.provider == "codex"
    assert selected.last_resort is False


def test_configured_retired_coder_alias_is_user_owned_when_custom(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "model_aliases": {
                "custom": {
                    "coder": {
                        "model": "codex/o3",
                        "description": "Explicit coder alias.",
                    }
                }
            },
        },
    )
    patch_available_providers(monkeypatch)

    coder = {v.name: v for v in build_alias_views()}["coder"]
    assert coder.kind == "user"
    assert coder.configured is True
    assert coder.configured_value == "codex/o3"


def test_configured_provider_coder_alias_is_user_owned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "model_aliases": {
                "custom": {
                    "codex_coder": {
                        "model": "codex/o3",
                        "description": "Explicit legacy alias.",
                    }
                },
            },
        },
    )
    patch_available_providers(monkeypatch)

    by_name = {v.name: v for v in build_alias_views()}
    codex_coder = by_name["codex_coder"]

    assert codex_coder.kind == "user"
    assert codex_coder.configured is True
    assert codex_coder.provider == "codex"
    assert codex_coder.model == "o3"
    assert codex_coder.implicit_value is None
    assert codex_coder.implicit_fallback is None


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
    patch_available_providers(monkeypatch)

    blogger = {v.name: v for v in build_alias_views()}["blogger"]

    assert blogger.kind == "user"
    assert blogger.configured is True
    assert blogger.configured_value == "claude/opus"
    assert blogger.configured_source == "custom"
    assert blogger.description == "Draft blog posts."
    assert blogger.bucket == "writing"


def test_alias_views_carry_direct_and_chain_inherited_effort(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "model_aliases": {
                "custom": {
                    "direct": {
                        "model": "claude/opus@medium",
                        "description": "Direct effort.",
                    },
                    "chained": {
                        "model": "@direct@high",
                        "description": "Inherited effort.",
                    },
                }
            },
        },
    )
    patch_available_providers(monkeypatch)

    by_name = {view.name: view for view in build_alias_views()}
    assert (by_name["direct"].provider, by_name["direct"].model) == (
        "claude",
        "opus",
    )
    assert by_name["direct"].effort == "medium"
    assert by_name["chained"].effort == "high"


def test_pool_alias_view_uses_marked_next_member_for_all_badge_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "model_aliases": {
                "custom": {
                    "pool": {
                        "model": "claude/opus@medium | codex/o3@high",
                        "description": "Pool.",
                    }
                }
            },
        },
    )
    patch_available_providers(monkeypatch)
    monkeypatch.setattr(
        "sase.llm_provider.config._resolved_target_is_available",
        lambda _target: True,
    )

    first = {view.name: view for view in build_alias_views()}["pool"]
    first_next = next(member for member in first.selector_members if member.selected)
    assert (first.provider, first.model, first.effort) == (
        first_next.provider,
        "opus",
        first_next.effort,
    )

    from sase.llm_provider.config import resolve_model_alias

    resolve_model_alias("@pool", consume=True)
    second = {view.name: view for view in build_alias_views()}["pool"]
    second_next = next(member for member in second.selector_members if member.selected)
    assert (second.provider, second.model, second.effort) == (
        second_next.provider,
        "o3",
        second_next.effort,
    )
    assert second.effort == "high"
