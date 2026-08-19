"""Tests for LLM provider model alias resolution."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from sase.config import core as config_core
from sase.llm_provider import config as llm_config
from sase.llm_provider.config import (
    model_alias_description,
    model_alias_kind,
    resolve_model_alias,
)
from sase.llm_provider.registry import resolve_model_provider
from tests._model_alias_defaults_fixture import frozen_selector_member
from tests.llm_provider._provider_config_helpers import mock_provider_config


@patch("sase.llm_provider.config.get_llm_provider_config")
def test_resolve_model_alias_handles_custom_chains_and_cycles(
    mock_config: MagicMock,
) -> None:
    mock_config.return_value = {
        "model_aliases": {
            "custom": {
                "other": {"model": "@review", "description": "Other alias."},
                "review": {"model": "opus", "description": "Review alias."},
                "a": {"model": "@b", "description": "Cycle A."},
                "b": {"model": "@a", "description": "Cycle B."},
            }
        }
    }

    assert resolve_model_alias("other") == "opus"
    assert resolve_model_alias("missing") == "missing"
    assert resolve_model_alias("a") == "a"


def test_resolve_model_alias_reuses_aliases_without_config_io(tmp_path) -> None:
    (tmp_path / "sase.yml").write_text(
        "llm_provider:\n  model_aliases:\n    builtin:\n      medium: claude/opus\n",
        encoding="utf-8",
    )

    with (
        patch("sase.config.core.CONFIG_DIR", tmp_path),
        patch("sase.config.core.Path.cwd", return_value=tmp_path / "no_local"),
        patch.object(
            llm_config,
            "get_llm_provider_config",
            wraps=llm_config.get_llm_provider_config,
        ) as load_provider_config,
    ):
        clear_count_before = load_provider_config.call_count
        assert resolve_model_alias("medium") == "claude/opus"
        first_load_count = load_provider_config.call_count
        assert first_load_count > clear_count_before

        with (
            patch.object(
                config_core,
                "stat_token",
                side_effect=AssertionError("unexpected config stat"),
            ),
            patch.object(
                config_core,
                "_get_overlay_paths",
                side_effect=AssertionError("unexpected config glob"),
            ),
        ):
            assert resolve_model_alias("medium") == "claude/opus"

        assert load_provider_config.call_count == first_load_count


def test_alias_value_may_reference_another_alias_with_at(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "model_aliases": {
                "custom": {
                    "fast": {
                        "model": "codex/o4-mini",
                        "description": "Fast alias.",
                    },
                    "claude_coder": {
                        "model": "@fast",
                        "description": "Explicit legacy alias.",
                    },
                }
            },
        },
    )

    assert resolve_model_alias("claude_coder") == "codex/o4-mini"
    assert resolve_model_provider("claude_coder") == ("codex", "o4-mini")


def test_alias_at_reference_cycle_falls_back_to_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "model_aliases": {
                "custom": {
                    "x": {"model": "@y", "description": "X."},
                    "y": {"model": "@x", "description": "Y."},
                }
            },
        },
    )

    assert resolve_model_alias("x") == "x"


def test_unknown_at_reference_resolves_to_bare_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(monkeypatch, {"provider": "claude", "model_aliases": {}})

    assert resolve_model_alias("@nope") == "nope"


def test_only_size_aliases_are_special(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.llm_provider.config import _special_model_alias_names

    mock_provider_config(monkeypatch, {"provider": "claude"})

    names = _special_model_alias_names()
    assert names == {"xsmall", "small", "medium", "large", "xlarge"}
    assert "worker" not in names
    assert "default" not in names
    assert "epic_creator" not in names


def test_size_alias_uses_shipped_pool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(monkeypatch, {"provider": "claude"})
    monkeypatch.setattr(
        "sase.llm_provider.config._resolved_target_is_available",
        lambda _target: True,
    )
    monkeypatch.setattr(
        "sase.llm_provider.load_balancing.select_model_alias_pool_member",
        lambda *_args, **_kwargs: 0,
    )

    expected = frozen_selector_member("large", 0)[0]
    assert resolve_model_alias("@large") == expected


def test_unconfigured_retired_aliases_resolve_to_bare_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(monkeypatch, {"provider": "claude"})

    for alias in (
        "worker",
        "other",
        "default",
        "epic_lander",
        "big_epic_lander",
        "medium_worker",
        "smart",
        "cheap",
        "epic_creator",
    ):
        assert resolve_model_alias(alias) == alias


def test_configured_epic_creator_has_no_builtin_presentation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "model_aliases": {
                "custom": {
                    "epic_creator": {
                        "model": "@medium",
                        "description": "Explicit custom alias.",
                    }
                }
            },
        },
    )

    assert model_alias_kind("epic_creator") == "user"
    assert model_alias_description("epic_creator") == "Explicit custom alias."


def test_launch_alias_override_wins_and_follows_alias_chains(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "model_aliases": {
                "custom": {
                    "worker": {
                        "model": "codex/o3",
                        "description": "Explicit custom phase role.",
                    },
                    "reviewer": {
                        "model": "claude/opus",
                        "description": "Review alias.",
                    },
                },
            },
        },
    )

    overrides = {"reviewer": "@worker", "worker": "claude/sonnet"}
    assert resolve_model_alias("@reviewer", overrides) == "claude/sonnet"
    assert resolve_model_provider("@reviewer", overrides) == ("claude", "sonnet")


def test_launch_worker_override_has_no_builtin_effect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(monkeypatch, {"provider": "claude"})
    monkeypatch.setattr(
        "sase.llm_provider.config._resolved_target_is_available",
        lambda target: target.startswith("claude/"),
    )

    overrides = {"worker": "codex/o3"}
    assert (
        resolve_model_alias("@small", overrides)
        == frozen_selector_member("small", 0)[0]
    )
    assert (
        resolve_model_alias("@medium", overrides)
        == frozen_selector_member("medium", 1)[0]
    )
    assert resolve_model_alias("@large", overrides) == "claude/opus"
    assert resolve_model_alias("@worker", overrides) == "worker"


def test_launch_size_override_is_independent_for_that_size(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(monkeypatch, {"provider": "claude"})

    overrides = {
        "medium": "claude/sonnet",
        "large": "codex/o3",
    }
    assert (
        resolve_model_alias("@small", overrides)
        == frozen_selector_member("small", 0)[0]
    )
    assert resolve_model_alias("@medium", overrides) == "claude/sonnet"
    assert resolve_model_alias("@large", overrides) == "codex/o3"


def test_launch_generic_coder_override_does_not_shadow_configured_provider_coder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "model_aliases": {
                "custom": {
                    "claude_coder": {
                        "model": "codex/o3",
                        "description": "Explicit legacy alias.",
                    }
                }
            },
        },
    )

    assert (
        resolve_model_alias("@claude_coder", {"coder": "claude/sonnet"}) == "codex/o3"
    )
    assert (
        resolve_model_alias(
            "@claude_coder",
            {"coder": "claude/sonnet", "claude_coder": "codex/o4-mini"},
        )
        == "codex/o4-mini"
    )


def test_launch_alias_override_beats_machine_temporary_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(monkeypatch, {"provider": "claude"})
    temporary = MagicMock(provider="codex", model="o3")
    monkeypatch.setattr(
        "sase.llm_provider.config._active_alias_overrides",
        lambda: {"medium": temporary},
    )

    assert (
        resolve_model_alias("@medium", {"medium": "claude/sonnet"}) == "claude/sonnet"
    )


def test_launch_alias_override_cycle_falls_back_to_original(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(monkeypatch, {"provider": "claude"})

    assert (
        resolve_model_alias(
            "@medium",
            {
                "medium": "@large",
                "large": "@medium",
            },
        )
        == "@medium"
    )
