"""Tests for the shipped load-balanced size model aliases."""

from __future__ import annotations

import pytest

from sase.llm_provider import config as llm_config
from sase.llm_provider.config import (
    resolve_model_alias,
    resolve_model_alias_with_effort,
)
from sase.llm_provider.load_balancing import parse_model_alias_selector
from sase.llm_provider.model_alias_policy import (
    LARGE_MODEL_ALIAS_NAME,
    MEDIUM_MODEL_ALIAS_NAME,
    SMALL_MODEL_ALIAS_NAME,
    XLARGE_MODEL_ALIAS_NAME,
    XSMALL_MODEL_ALIAS_NAME,
    implicit_alias_targets,
)
from tests._model_alias_defaults_fixture import frozen_selector_member
from tests.llm_provider._provider_config_helpers import mock_provider_config


def test_small_size_alias_rotates_its_pool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(monkeypatch, {"provider": "claude"})
    monkeypatch.setattr(
        llm_config,
        "_resolved_target_is_available",
        lambda _target: True,
    )

    first = resolve_model_alias_with_effort("@small", consume=True)
    second = resolve_model_alias_with_effort("@small", consume=True)

    assert (first.target, first.effort) == frozen_selector_member(
        SMALL_MODEL_ALIAS_NAME, 0
    )
    assert (second.target, second.effort) == frozen_selector_member(
        SMALL_MODEL_ALIAS_NAME, 1
    )


def test_size_aliases_use_independent_rotations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(monkeypatch, {"provider": "claude"})
    monkeypatch.setattr(
        llm_config,
        "_resolved_target_is_available",
        lambda _target: True,
    )

    xsmall_first = resolve_model_alias_with_effort("@xsmall", consume=True)
    medium_first = resolve_model_alias_with_effort("@medium", consume=True)
    xsmall_second = resolve_model_alias_with_effort("@xsmall", consume=True)
    medium_second = resolve_model_alias_with_effort("@medium", consume=True)

    assert (xsmall_first.target, xsmall_first.effort) == frozen_selector_member(
        XSMALL_MODEL_ALIAS_NAME, 0
    )
    assert (medium_first.target, medium_first.effort) == frozen_selector_member(
        MEDIUM_MODEL_ALIAS_NAME, 0
    )
    assert (xsmall_second.target, xsmall_second.effort) == frozen_selector_member(
        XSMALL_MODEL_ALIAS_NAME, 1
    )
    assert (medium_second.target, medium_second.effort) == frozen_selector_member(
        MEDIUM_MODEL_ALIAS_NAME, 1
    )


@pytest.mark.parametrize(
    ("alias", "expectations"),
    [
        (
            "@xsmall",
            {
                "claude/": ("claude/claude-haiku-4-5", None),
                "codex/": ("codex/gpt-5.6-luna", "low"),
                "grok/": ("grok/grok-4.6", "low"),
            },
        ),
        (
            "@small",
            {
                "claude/": ("claude/sonnet", "low"),
                "codex/": ("codex/gpt-5.6-terra", "low"),
                "grok/": ("grok/grok-4.6", "low"),
            },
        ),
        (
            "@medium",
            {
                "claude/": ("claude/sonnet", "medium"),
                "codex/": ("codex/gpt-5.6-terra", "medium"),
                "grok/": ("grok/grok-4.6", "medium"),
            },
        ),
        (
            "@large",
            {
                "claude/": ("claude/opus", "high"),
                "codex/": ("codex/gpt-5.6-sol", "high"),
                "grok/": ("grok/grok-4.6", "high"),
            },
        ),
        (
            "@xlarge",
            {
                "claude/": ("claude/opus", "xhigh"),
                "codex/": ("codex/gpt-5.6-sol", "xhigh"),
                "grok/": ("grok/grok-4.6", "xhigh"),
            },
        ),
    ],
)
def test_packaged_defaults_select_correct_effort_per_provider(
    monkeypatch: pytest.MonkeyPatch,
    real_model_alias_defaults: None,
    alias: str,
    expectations: dict[str, tuple[str, str | None]],
) -> None:
    mock_provider_config(monkeypatch, {"provider": "claude"})

    for prefix, (expected_target, expected_effort) in expectations.items():
        monkeypatch.setattr(
            llm_config,
            "_resolved_target_is_available",
            lambda target, prefix=prefix: target.startswith(prefix),
        )

        selected = resolve_model_alias_with_effort(alias, consume=True)

        assert selected.target == expected_target
        assert selected.effort == expected_effort


def test_shipped_large_round_robins_claude_codex_grok(
    monkeypatch: pytest.MonkeyPatch,
    real_model_alias_defaults: None,
) -> None:
    selector = parse_model_alias_selector(
        implicit_alias_targets()[LARGE_MODEL_ALIAS_NAME]
    )
    assert selector is not None
    assert selector.members == (
        "claude/opus@high",
        "codex/gpt-5.6-sol@high",
        "grok/grok-4.6@high",
    )
    assert selector.fallback_members == ()

    mock_provider_config(monkeypatch, {"provider": "claude"})
    monkeypatch.setattr(
        llm_config,
        "_resolved_target_is_available",
        lambda _target: True,
    )
    selected = [resolve_model_alias("@large", consume=True) for _ in range(3)]
    assert selected == ["claude/opus", "codex/gpt-5.6-sol", "grok/grok-4.6"]


@pytest.mark.parametrize(
    "alias",
    [
        XSMALL_MODEL_ALIAS_NAME,
        SMALL_MODEL_ALIAS_NAME,
        MEDIUM_MODEL_ALIAS_NAME,
        LARGE_MODEL_ALIAS_NAME,
        XLARGE_MODEL_ALIAS_NAME,
    ],
)
def test_shipped_size_aliases_have_no_antigravity_member(
    real_model_alias_defaults: None,
    alias: str,
) -> None:
    selector = parse_model_alias_selector(implicit_alias_targets()[alias])
    assert selector is not None
    members = (*selector.members, *selector.fallback_members)
    assert not any(member.startswith("agy/") for member in members)


@pytest.mark.parametrize(
    ("alias", "expected"),
    [
        (XSMALL_MODEL_ALIAS_NAME, frozen_selector_member(XSMALL_MODEL_ALIAS_NAME, 1)),
        (SMALL_MODEL_ALIAS_NAME, frozen_selector_member(SMALL_MODEL_ALIAS_NAME, 1)),
        (MEDIUM_MODEL_ALIAS_NAME, frozen_selector_member(MEDIUM_MODEL_ALIAS_NAME, 0)),
    ],
)
def test_size_alias_pools_skip_unavailable_provider(
    monkeypatch: pytest.MonkeyPatch,
    alias: str,
    expected: tuple[str, str | None],
) -> None:
    mock_provider_config(monkeypatch, {"provider": "claude"})
    monkeypatch.setattr(
        llm_config,
        "_resolved_target_is_available",
        lambda target: target.startswith("codex/"),
    )

    consumed = resolve_model_alias_with_effort(f"@{alias}", consume=True)
    peeked = resolve_model_alias_with_effort(f"@{alias}")
    assert (consumed.target, consumed.effort) == expected
    assert (peeked.target, peeked.effort) == expected


def test_xlarge_pool_skips_unavailable_member_before_last_resort(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A `(A | B) || C` last-resort skips an unavailable pool member first."""
    mock_provider_config(monkeypatch, {"provider": "claude"})
    monkeypatch.setattr(
        llm_config,
        "_resolved_target_is_available",
        lambda target: target.startswith("codex/"),
    )

    selected = resolve_model_alias_with_effort("@xlarge", consume=True)

    assert (selected.target, selected.effort) == frozen_selector_member(
        XLARGE_MODEL_ALIAS_NAME, 1
    )


def test_size_alias_pool_peeks_and_consumes_independently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(monkeypatch, {"provider": "claude"})
    monkeypatch.setattr(
        llm_config,
        "_resolved_target_is_available",
        lambda _target: True,
    )

    assert (
        resolve_model_alias("@small")
        == frozen_selector_member(SMALL_MODEL_ALIAS_NAME, 0)[0]
    )
    assert (
        resolve_model_alias("@small")
        == frozen_selector_member(SMALL_MODEL_ALIAS_NAME, 0)[0]
    )
    assert (
        resolve_model_alias("@small", consume=True)
        == frozen_selector_member(SMALL_MODEL_ALIAS_NAME, 0)[0]
    )
    assert (
        resolve_model_alias("@small")
        == frozen_selector_member(SMALL_MODEL_ALIAS_NAME, 1)[0]
    )
    assert (
        resolve_model_alias("@small", consume=True)
        == frozen_selector_member(SMALL_MODEL_ALIAS_NAME, 1)[0]
    )
    assert (
        resolve_model_alias("@small", consume=True)
        == frozen_selector_member(SMALL_MODEL_ALIAS_NAME, 0)[0]
    )
