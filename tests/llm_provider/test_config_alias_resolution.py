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
from sase.llm_provider.model_alias_policy import (
    CHEAP_MODEL_ALIAS_NAME,
    SMART_MODEL_ALIAS_NAME,
    SMARTER_MODEL_ALIAS_NAME,
)
from sase.llm_provider.registry import resolve_model_provider
from tests._model_alias_defaults_fixture import (
    frozen_selector_member,
)
from tests.llm_provider._provider_config_helpers import mock_provider_config


@patch("sase.llm_provider.config.get_llm_provider_config")
def test_resolve_model_alias_handles_chains_and_cycles(
    mock_config: MagicMock,
) -> None:
    """Alias chains resolve, but cycles fall back to the raw input."""
    mock_config.return_value = {
        "model_aliases": {
            "builtin": {
                "other": "review",
                "review": "opus",
                "a": "b",
                "b": "a",
            }
        }
    }

    assert resolve_model_alias("other") == "opus"
    assert resolve_model_alias("missing") == "missing"
    assert resolve_model_alias("a") == "a"


def test_resolve_model_alias_reuses_aliases_without_config_io(tmp_path) -> None:
    """Repeated alias resolution does not stat, glob, or re-read unchanged config."""
    (tmp_path / "sase.yml").write_text(
        "llm_provider:\n  model_aliases:\n    builtin:\n      default: claude/opus\n",
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
        assert resolve_model_alias("default") == "claude/opus"
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
            assert resolve_model_alias("default") == "claude/opus"

        assert load_provider_config.call_count == first_load_count


def test_alias_value_may_reference_another_alias_with_at(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Alias values can reference other aliases with the ``@`` marker."""
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "model_aliases": {
                "builtin": {
                    "fast": "codex/o4-mini",
                    "claude_coder": "@fast",
                }
            },
        },
    )

    assert resolve_model_alias("claude_coder") == "codex/o4-mini"
    assert resolve_model_provider("claude_coder") == ("codex", "o4-mini")


def test_alias_at_reference_cycle_falls_back_to_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A cyclic ``@`` reference chain fails closed to the original input."""
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "model_aliases": {"builtin": {"x": "@y", "y": "@x"}},
        },
    )

    assert resolve_model_alias("x") == "x"


def test_self_referential_default_does_not_recurse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A ``default: @default`` self-cycle is detected and never recurses."""
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "model_aliases": {"builtin": {"default": "@default"}},
        },
    )

    # Fails closed to the input rather than recursing on the special branch.
    assert resolve_model_alias("default") == "default"


def test_unknown_at_reference_resolves_to_bare_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A dangling ``@`` reference to a non-alias resolves to the bare token."""
    mock_provider_config(monkeypatch, {"provider": "claude", "model_aliases": {}})

    # `@nope` references an alias that is neither configured nor special.
    assert resolve_model_alias("@nope") == "nope"


def test_worker_other_and_worker_are_not_special_aliases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``worker``/``other`` are no longer implicit aliases after phase 4.

    The worker lane was retired in epic sase-5d phase 4, so the legacy reserved
    ``worker``/``other`` aliases are gone from the implicit policy and only the
    role aliases remain. ``worker``/``other`` resolve now only when a user
    defines them as ordinary configured aliases.
    """
    from sase.llm_provider.config import _special_model_alias_names

    mock_provider_config(monkeypatch, {"provider": "claude"})

    names = _special_model_alias_names()
    assert "worker" not in names
    assert "other" not in names
    assert "worker" not in names
    # The role aliases are the implicit policy now.
    assert {
        "default",
        "epic_lander",
        "big_epic_lander",
        "xsmall_worker",
        "small_worker",
        "medium_worker",
        "large_worker",
        "xlarge_worker",
        "smart",
        "smarter",
        "smartest",
        "cheap",
        "cheaper",
        "cheapest",
    } <= names
    assert "epic_creator" not in names


def test_unconfigured_default_uses_shipped_fallback_before_provider_tier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(monkeypatch, {"provider": "claude"})
    monkeypatch.setattr(
        "sase.llm_provider.config._resolve_default_alias_target",
        lambda: "claude/opus",
    )
    monkeypatch.setattr(
        "sase.llm_provider.config._resolved_target_is_available",
        lambda _target: True,
    )
    monkeypatch.setattr(
        "sase.llm_provider.model_alias_resolution.select_model_alias_pool_member",
        lambda *_args, **_kwargs: 0,
    )

    expected = frozen_selector_member(SMARTER_MODEL_ALIAS_NAME, 0)[0]
    assert resolve_model_alias("@default") == expected
    assert resolve_model_alias("@large_worker") == expected


def test_configured_and_temporary_default_override_beat_shipped_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "model_aliases": {"builtin": {"default": "claude/opus"}},
        },
    )
    monkeypatch.setattr(
        "sase.llm_provider.config._resolved_target_is_available",
        lambda _target: True,
    )
    monkeypatch.setattr(
        "sase.llm_provider.model_alias_resolution.select_model_alias_pool_member",
        lambda *_args, **_kwargs: 0,
    )

    assert resolve_model_alias("@default") == "claude/opus"

    temporary = MagicMock(provider="codex", model="o3", effort=None)
    monkeypatch.setattr(
        "sase.llm_provider.config._active_alias_overrides",
        lambda: {"default": temporary},
    )
    assert resolve_model_alias("@default") == "codex/o3"


def test_unconfigured_retired_aliases_resolve_to_bare_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without explicit config, retired aliases are plain unknown tokens."""
    mock_provider_config(monkeypatch, {"provider": "claude"})

    assert resolve_model_alias("worker") == "worker"
    assert resolve_model_alias("other") == "other"
    assert resolve_model_alias("worker") == "worker"
    assert resolve_model_alias("epic_creator") == "epic_creator"


def test_configured_epic_creator_has_no_builtin_presentation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stale configured epic-creator key is treated as an ordinary user alias."""
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "model_aliases": {"builtin": {"epic_creator": "@default"}},
        },
    )

    assert model_alias_kind("epic_creator") == "user"
    assert model_alias_description("epic_creator") is None


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
        resolve_model_alias("@small_worker", overrides)
        == (frozen_selector_member(CHEAP_MODEL_ALIAS_NAME, 0)[0])
    )
    assert (
        resolve_model_alias("@medium_worker", overrides)
        == (frozen_selector_member(SMART_MODEL_ALIAS_NAME, 1)[0])
    )
    assert resolve_model_alias("@large_worker", overrides) == "claude/opus"
    assert resolve_model_alias("@worker", overrides) == "worker"


def test_launch_size_phase_override_is_independent_for_that_size(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(monkeypatch, {"provider": "claude"})

    overrides = {
        "medium_worker": "claude/sonnet",
        "large_worker": "codex/o3",
    }
    assert (
        resolve_model_alias("@small_worker", overrides)
        == (frozen_selector_member(CHEAP_MODEL_ALIAS_NAME, 0)[0])
    )
    assert resolve_model_alias("@medium_worker", overrides) == "claude/sonnet"
    assert resolve_model_alias("@large_worker", overrides) == "codex/o3"


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
        lambda: {"medium_worker": temporary},
    )

    assert (
        resolve_model_alias("@medium_worker", {"medium_worker": "claude/sonnet"})
        == "claude/sonnet"
    )


def test_launch_default_override_applies_to_explicit_default_hop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(monkeypatch, {"provider": "claude"})

    assert resolve_model_alias("@default", {"default": "codex/o3"}) == "codex/o3"


def test_launch_alias_override_cycle_falls_back_to_original(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(monkeypatch, {"provider": "claude"})

    assert (
        resolve_model_alias(
            "@medium_worker",
            {
                "medium_worker": "@large_worker",
                "large_worker": "@medium_worker",
            },
        )
        == "@medium_worker"
    )
