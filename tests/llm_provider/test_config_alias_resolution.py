"""Tests for LLM provider model alias resolution."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from sase.config import core as config_core
from sase.llm_provider import config as llm_config
from sase.llm_provider.config import resolve_model_alias
from sase.llm_provider.registry import resolve_model_provider
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


def test_worker_other_and_phase_worker_are_not_special_aliases(
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
    assert "phase_worker" not in names
    # The role aliases are the implicit policy now.
    assert {
        "default",
        "coder",
        "epic_lander",
        "big_epic_lander",
        "small_phase_worker",
        "medium_phase_worker",
        "large_phase_worker",
        "smartest",
        "cheaper",
        "cheapest",
    } <= names
    assert "epic_creator" not in names


def test_unconfigured_retired_aliases_resolve_to_bare_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without explicit config, ``worker``/``other`` are plain unknown tokens."""
    mock_provider_config(monkeypatch, {"provider": "claude"})

    assert resolve_model_alias("worker") == "worker"
    assert resolve_model_alias("other") == "other"
    assert resolve_model_alias("phase_worker") == "phase_worker"


def test_launch_alias_override_wins_and_follows_alias_chains(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "model_aliases": {
                "builtin": {"coder": "claude/opus"},
                "custom": {
                    "phase_worker": {
                        "model": "codex/o3",
                        "description": "Explicit custom phase role.",
                    }
                },
            },
        },
    )

    overrides = {"coder": "@phase_worker", "phase_worker": "claude/sonnet"}
    assert resolve_model_alias("@coder", overrides) == "claude/sonnet"
    assert resolve_model_provider("@coder", overrides) == ("claude", "sonnet")


def test_launch_phase_worker_override_has_no_builtin_effect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(monkeypatch, {"provider": "claude"})
    monkeypatch.setattr(
        "sase.llm_provider.config._resolved_target_is_available",
        lambda target: target.startswith("claude/"),
    )

    overrides = {"phase_worker": "codex/o3"}
    assert resolve_model_alias("@small_phase_worker", overrides) == "claude/opus"
    assert resolve_model_alias("@medium_phase_worker", overrides) == "claude/opus"
    assert resolve_model_alias("@large_phase_worker", overrides) == (
        "claude/claude-fable-5"
    )
    assert resolve_model_alias("@phase_worker", overrides) == "phase_worker"


def test_launch_size_phase_override_is_independent_for_that_size(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(monkeypatch, {"provider": "claude"})

    overrides = {
        "medium_phase_worker": "claude/sonnet",
        "large_phase_worker": "codex/o3",
    }
    assert resolve_model_alias("@small_phase_worker", overrides) == "claude/opus"
    assert resolve_model_alias("@medium_phase_worker", overrides) == "claude/sonnet"
    assert resolve_model_alias("@large_phase_worker", overrides) == "codex/o3"


def test_launch_coder_override_shadows_configured_provider_coder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "model_aliases": {
                "builtin": {
                    "coder": "claude/opus",
                    "claude_coder": "codex/o3",
                }
            },
        },
    )

    assert (
        resolve_model_alias("@claude_coder", {"coder": "claude/sonnet"})
        == "claude/sonnet"
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
        lambda: {"coder": temporary},
    )

    assert resolve_model_alias("@coder", {"coder": "claude/sonnet"}) == (
        "claude/sonnet"
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
            "@coder",
            {"coder": "@medium_phase_worker", "medium_phase_worker": "@coder"},
        )
        == "@coder"
    )
