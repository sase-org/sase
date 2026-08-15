"""Tests for the shipped load-balanced size model aliases."""

from __future__ import annotations

import pytest

from sase.llm_provider import config as llm_config
from sase.llm_provider.config import (
    resolve_model_alias,
    resolve_model_alias_with_effort,
)
from sase.llm_provider.model_alias_policy import (
    MEDIUM_MODEL_ALIAS_NAME,
    SMALL_MODEL_ALIAS_NAME,
    XLARGE_MODEL_ALIAS_NAME,
    XSMALL_MODEL_ALIAS_NAME,
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


def test_xsmall_packaged_defaults_select_correct_effort_per_provider(
    monkeypatch: pytest.MonkeyPatch,
    real_model_alias_defaults: None,
) -> None:
    mock_provider_config(monkeypatch, {"provider": "claude"})

    expectations = {
        "claude/": ("claude/sonnet", "medium"),
        "codex/": ("codex/gpt-5.5", "medium"),
        "grok/": ("grok/grok-4.6", "medium"),
        "agy/": ("agy/gemini-3.7-flash-high", None),
    }
    for prefix, (expected_target, expected_effort) in expectations.items():
        monkeypatch.setattr(
            llm_config,
            "_resolved_target_is_available",
            lambda target, prefix=prefix: target.startswith(prefix),
        )

        xsmall = resolve_model_alias_with_effort("@xsmall", consume=True)

        assert xsmall.target == expected_target
        assert xsmall.effort == expected_effort


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


def test_xlarge_ordered_fallback_selects_available_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
