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


def test_grouped_pool_normalizes_and_accepts_last_resort_tail() -> None:
    grouped = parse_model_alias_selector("(A | B)")
    assert grouped is not None
    assert grouped.mode == "round_robin"
    assert grouped.members == ("A", "B")
    assert grouped.fallback_members == ()
    assert grouped.normalized == "A | B"

    tailed = parse_model_alias_selector("(A | B) || C")
    assert tailed is not None
    assert tailed.members == ("A", "B")
    assert tailed.fallback_members == ("C",)
    assert tailed.normalized == "(A | B) || C"

    weighted = parse_model_alias_selector("(A | 3 B) || C")
    assert weighted is not None
    assert weighted.members == ("A", "B")
    assert weighted.weights == (1, 3)
    assert weighted.fallback_members == ("C",)
    assert weighted.normalized == "(A | 3 B) || C"

    chain = parse_model_alias_selector("(A | B) || C || D")
    assert chain is not None
    assert chain.fallback_members == ("C", "D")
    assert chain.normalized == "(A | B) || C || D"

    shipped = parse_model_alias_selector(
        "(claude/opus@xhigh | codex/gpt-5.6-sol@xhigh) || grok/grok-4.6@xhigh"
    )
    bare = parse_model_alias_selector("claude/opus@xhigh | codex/gpt-5.6-sol@xhigh")
    assert shipped is not None
    assert bare is not None
    assert shipped.fingerprint == bare.fingerprint


def test_grouped_selector_parser_rejects_invalid_last_resort_forms() -> None:
    with pytest.raises(ModelAliasSelectorError, match="cannot mix"):
        parse_model_alias_selector("A | B || C")
    with pytest.raises(
        ModelAliasSelectorError,
        match=r"parentheses may only wrap a '\|' load-balanced pool",
    ):
        parse_model_alias_selector("(A || B) || C")
    with pytest.raises(
        ModelAliasSelectorError,
        match=r"parentheses may only wrap a '\|' load-balanced pool",
    ):
        parse_model_alias_selector("(A | B || C)")
    with pytest.raises(ModelAliasSelectorError, match="nested parentheses"):
        parse_model_alias_selector("((A | B)) || C")
    with pytest.raises(
        ModelAliasSelectorError,
        match="last-resort candidates cannot be parenthesized pools",
    ):
        parse_model_alias_selector("(A | B) || (C | D)")
    with pytest.raises(ModelAliasSelectorError, match="empty last-resort candidate"):
        parse_model_alias_selector("(A | B) ||")
    with pytest.raises(
        ModelAliasSelectorError,
        match="ordered fallback chains cannot weight candidates",
    ) as weighted_tail:
        parse_model_alias_selector("(A | B) || 2 C")
    assert "remove the '2 ' prefix from candidate 1" in str(weighted_tail.value)


def test_selector_parser_accepts_and_normalizes_pool_weights() -> None:
    pool = parse_model_alias_selector("claude/opus | 3 codex/gpt-5.5")
    assert pool is not None
    assert pool.members == ("claude/opus", "codex/gpt-5.5")
    assert pool.weights == (1, 3)
    assert pool.normalized == "claude/opus | 3 codex/gpt-5.5"
    assert pool.weighted is True

    dropped_default = parse_model_alias_selector("1 claude/opus | 3 codex/gpt-5.5")
    assert dropped_default is not None
    assert dropped_default.members == ("claude/opus", "codex/gpt-5.5")
    assert dropped_default.weights == (1, 3)
    assert dropped_default.normalized == "claude/opus | 3 codex/gpt-5.5"

    alias_member = parse_model_alias_selector("3 @medium@high | claude/opus")
    assert alias_member is not None
    assert alias_member.members == ("@medium@high", "claude/opus")
    assert alias_member.weights == (3, 1)
    assert alias_member.normalized == "3 @medium@high | claude/opus"

    leading_zeros = parse_model_alias_selector("03 claude/opus | codex/gpt-5.5")
    assert leading_zeros is not None
    assert leading_zeros.weights == (3, 1)
    assert leading_zeros.normalized == "3 claude/opus | codex/gpt-5.5"

    unweighted = parse_model_alias_selector("claude/opus | codex/gpt-5.5")
    assert unweighted is not None
    assert unweighted.weights == (1, 1)
    assert unweighted.weighted is False
    legacy_payload = json.dumps(
        unweighted.members, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    assert unweighted.fingerprint == hashlib.sha256(legacy_payload).hexdigest()
    assert pool.fingerprint != unweighted.fingerprint
    assert parse_model_alias_selector("3 claude/opus") is None


def test_selector_parser_rejects_invalid_and_fallback_weights() -> None:
    range_message = "load-balanced pool weights must be between 1 and 99"
    with pytest.raises(ModelAliasSelectorError, match=range_message) as zero:
        parse_model_alias_selector("A | 0 B")
    assert "got '0'" in str(zero.value)
    with pytest.raises(ModelAliasSelectorError, match=range_message) as over:
        parse_model_alias_selector("A | 100 B")
    assert "got '100'" in str(over.value)
    with pytest.raises(ModelAliasSelectorError, match=range_message) as negative:
        parse_model_alias_selector("A | -2 B")
    assert "got '-2'" in str(negative.value)
    with pytest.raises(ModelAliasSelectorError, match=range_message) as plus:
        parse_model_alias_selector("A | +2 B")
    assert "got '+2'" in str(plus.value)
    with pytest.raises(ModelAliasSelectorError, match=range_message) as decimal:
        parse_model_alias_selector("A | 2.5 B")
    assert "got '2.5'" in str(decimal.value)
    with pytest.raises(
        ModelAliasSelectorError,
        match="ordered fallback chains cannot weight candidates",
    ) as fallback:
        parse_model_alias_selector("A || 2 B")
    assert "remove the '2 ' prefix from candidate 2" in str(fallback.value)


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
