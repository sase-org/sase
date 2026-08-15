"""Load-balanced model-alias parsing and resolution tests."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from sase.llm_provider import config as llm_config
from sase.llm_provider.config import (
    resolve_effective_effort,
    resolve_model_alias,
    resolve_model_alias_with_effort,
)
from sase.llm_provider.load_balancing import (
    ModelAliasSelectorError,
    parse_model_alias_selector,
)
from sase.llm_provider.registry import resolve_model_provider_with_effort
from sase.xprompt.directives import PromptDirectives
from tests.llm_provider._load_balanced_alias_helpers import configure_pool
from tests.llm_provider._provider_config_helpers import mock_provider_config


def test_selector_parser_normalizes_modes_and_rejects_invalid_members() -> None:
    pool = parse_model_alias_selector(" claude/opus@medium|codex/gpt-5.5 ")
    assert pool is not None
    assert pool.mode == "round_robin"
    assert pool.members == ("claude/opus@medium", "codex/gpt-5.5")
    assert pool.normalized == "claude/opus@medium | codex/gpt-5.5"
    legacy_payload = json.dumps(
        pool.members, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    assert pool.fingerprint == hashlib.sha256(legacy_payload).hexdigest()

    fallback = parse_model_alias_selector(
        " claude/fable || codex/gpt-5.6-sol||opencode/anthropic/opus "
    )
    assert fallback is not None
    assert fallback.mode == "fallback"
    assert fallback.members == (
        "claude/fable",
        "codex/gpt-5.6-sol",
        "opencode/anthropic/opus",
    )
    assert fallback.normalized == (
        "claude/fable || codex/gpt-5.6-sol || opencode/anthropic/opus"
    )

    assert parse_model_alias_selector("claude/opus") is None
    with pytest.raises(ModelAliasSelectorError, match="empty members"):
        parse_model_alias_selector("claude/opus || || codex/gpt-5.5")
    with pytest.raises(ModelAliasSelectorError, match="cannot mix"):
        parse_model_alias_selector("claude/opus | codex/o3 || claude/sonnet")


def test_peek_is_stable_and_consumes_round_robin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_pool(monkeypatch)

    first = resolve_model_alias_with_effort("@pool")
    assert (first.target, first.effort) == ("claude/opus", "medium")
    assert resolve_model_alias("@pool") == "claude/opus"

    assert resolve_model_alias("@pool", consume=True) == "claude/opus"
    assert resolve_model_alias("@pool", consume=True) == "codex/gpt-5.5"
    assert resolve_model_alias("@pool", consume=True) == "claude/opus"


def test_outer_effort_applies_to_each_selected_pool_member_without_extra_consumption(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_pool(monkeypatch)

    first = resolve_model_alias_with_effort("@pool@high", consume=True)
    second = resolve_model_alias_with_effort("@pool@high", consume=True)
    third = resolve_model_alias_with_effort("@pool@high")

    assert (first.target, first.effort) == ("claude/opus", "high")
    assert (second.target, second.effort) == ("codex/gpt-5.5", "high")
    assert (third.target, third.effort) == ("claude/opus", "high")


def test_availability_filter_and_all_unavailable_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_pool(monkeypatch)
    monkeypatch.setattr(
        llm_config,
        "_resolved_target_is_available",
        lambda target: target.startswith("codex/"),
    )
    assert resolve_model_alias("@pool", consume=True) == "codex/gpt-5.5"
    assert resolve_model_alias("@pool", consume=True) == "codex/gpt-5.5"

    monkeypatch.setattr(
        llm_config,
        "_resolved_target_is_available",
        lambda _target: False,
    )
    # A new fingerprint retains member zero for diagnostics and does not
    # advance the cursor when there is no viable fallback.
    configure_pool(
        monkeypatch,
        "claude/sonnet@high | codex/o3",
    )
    monkeypatch.setattr(
        llm_config,
        "_resolved_target_is_available",
        lambda _target: False,
    )
    assert resolve_model_alias("@pool", consume=True) == "claude/sonnet"
    assert resolve_model_alias("@pool", consume=True) == "claude/sonnet"


def test_pool_edit_fingerprint_resets_cursor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg: dict[str, object] = {
        "provider": "claude",
        "model_aliases": {
            "custom": {
                "pool": {
                    "model": "claude/opus | codex/gpt-5.5",
                    "description": "Test pool.",
                }
            }
        },
    }
    mock_provider_config(monkeypatch, cfg)
    monkeypatch.setattr(
        llm_config,
        "_resolved_target_is_available",
        lambda _target: True,
    )
    assert resolve_model_alias("@pool", consume=True) == "claude/opus"

    cfg["model_aliases"] = {
        "custom": {
            "pool": {
                "model": "codex/o3 | claude/sonnet",
                "description": "Test pool.",
            }
        }
    }
    llm_config._get_model_aliases_for_token.cache_clear()
    assert resolve_model_alias("@pool", consume=True) == "codex/o3"


def test_temporary_override_suspends_pool_rotation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_pool(monkeypatch)
    override = MagicMock(provider="codex", model="o3")
    monkeypatch.setattr(
        llm_config,
        "_active_alias_overrides",
        lambda: {"pool": override},
    )

    assert resolve_model_alias("@pool", consume=True) == "codex/o3"
    assert resolve_model_alias("@pool", consume=True) == "codex/o3"
    assert not (Path.home() / ".sase" / "llm_lb.json").exists()


def test_alias_effort_is_split_and_has_expected_precedence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "default_effort": "low",
            "model_aliases": {
                "custom": {
                    "focused": {
                        "model": "claude/opus@medium",
                        "description": "Focused alias.",
                    }
                }
            },
        },
    )
    monkeypatch.setattr(llm_config, "_get_default_effort", lambda: "low")

    assert resolve_model_alias("@focused") == "claude/opus"
    assert resolve_model_provider_with_effort("@focused") == (
        "claude",
        "opus",
        "medium",
    )
    assert resolve_effective_effort(PromptDirectives(), "medium") == (
        "medium",
        False,
    )
    assert resolve_effective_effort(
        PromptDirectives(reasoning_effort="high"), "medium"
    ) == ("high", True)
