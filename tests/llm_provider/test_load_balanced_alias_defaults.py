"""Tests for the shipped load-balanced model aliases."""

from __future__ import annotations

import pytest

from sase.llm_provider import config as llm_config
from sase.llm_provider.config import (
    resolve_model_alias,
    resolve_model_alias_with_effort,
)
from sase.llm_provider.model_alias_policy import (
    CHEAP_MODEL_ALIAS_NAME,
    CHEAPER_MODEL_ALIAS_NAME,
    CHEAPEST_MODEL_ALIAS_NAME,
)
from tests._model_alias_defaults_fixture import frozen_selector_member
from tests.llm_provider._provider_config_helpers import mock_provider_config


def test_small_phase_and_cheap_share_one_rotation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(monkeypatch, {"provider": "claude"})
    monkeypatch.setattr(
        llm_config,
        "_resolved_target_is_available",
        lambda _target: True,
    )

    small = resolve_model_alias_with_effort("@small_worker", consume=True)
    cheap = resolve_model_alias_with_effort("@cheap", consume=True)

    assert (small.target, small.effort) == frozen_selector_member(
        CHEAP_MODEL_ALIAS_NAME, 0
    )
    assert (cheap.target, cheap.effort) == frozen_selector_member(
        CHEAP_MODEL_ALIAS_NAME, 1
    )


def test_xsmall_phase_and_cheaper_share_one_rotation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(monkeypatch, {"provider": "claude"})
    monkeypatch.setattr(
        llm_config,
        "_resolved_target_is_available",
        lambda _target: True,
    )

    xsmall = resolve_model_alias_with_effort("@xsmall_worker", consume=True)
    cheaper = resolve_model_alias_with_effort("@cheaper", consume=True)

    assert (xsmall.target, xsmall.effort) == frozen_selector_member(
        CHEAPER_MODEL_ALIAS_NAME, 0
    )
    assert (cheaper.target, cheaper.effort) == frozen_selector_member(
        CHEAPER_MODEL_ALIAS_NAME, 1
    )


def test_cheap_and_cheaper_use_independent_rotations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(monkeypatch, {"provider": "claude"})
    monkeypatch.setattr(
        llm_config,
        "_resolved_target_is_available",
        lambda _target: True,
    )

    cheap_first = resolve_model_alias_with_effort("@cheap", consume=True)
    cheaper_first = resolve_model_alias_with_effort("@cheaper", consume=True)
    cheap_second = resolve_model_alias_with_effort("@cheap", consume=True)
    cheaper_second = resolve_model_alias_with_effort("@cheaper", consume=True)

    assert (cheap_first.target, cheap_first.effort) == frozen_selector_member(
        CHEAP_MODEL_ALIAS_NAME, 0
    )
    assert (cheaper_first.target, cheaper_first.effort) == frozen_selector_member(
        CHEAPER_MODEL_ALIAS_NAME, 0
    )
    assert (cheap_second.target, cheap_second.effort) == frozen_selector_member(
        CHEAP_MODEL_ALIAS_NAME, 1
    )
    assert (cheaper_second.target, cheaper_second.effort) == frozen_selector_member(
        CHEAPER_MODEL_ALIAS_NAME, 1
    )


def test_implicit_cheapest_pool_peeks_and_consumes_independently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(monkeypatch, {"provider": "claude"})
    monkeypatch.setattr(
        llm_config,
        "_resolved_target_is_available",
        lambda _target: True,
    )

    assert (
        resolve_model_alias("@cheapest")
        == frozen_selector_member(CHEAPEST_MODEL_ALIAS_NAME, 0)[0]
    )
    assert (
        resolve_model_alias("@cheapest")
        == frozen_selector_member(CHEAPEST_MODEL_ALIAS_NAME, 0)[0]
    )
    assert (
        resolve_model_alias("@cheapest", consume=True)
        == frozen_selector_member(CHEAPEST_MODEL_ALIAS_NAME, 0)[0]
    )
    assert (
        resolve_model_alias("@cheapest")
        == frozen_selector_member(CHEAPEST_MODEL_ALIAS_NAME, 1)[0]
    )
    assert (
        resolve_model_alias("@cheapest", consume=True)
        == (frozen_selector_member(CHEAPEST_MODEL_ALIAS_NAME, 1)[0])
    )
    assert (
        resolve_model_alias("@cheapest", consume=True)
        == frozen_selector_member(CHEAPEST_MODEL_ALIAS_NAME, 0)[0]
    )


def test_cheap_cheaper_and_cheapest_use_independent_rotations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(monkeypatch, {"provider": "claude"})
    monkeypatch.setattr(
        llm_config,
        "_resolved_target_is_available",
        lambda _target: True,
    )

    cheap_first = resolve_model_alias_with_effort("@cheap", consume=True)
    cheaper_first = resolve_model_alias_with_effort("@cheaper", consume=True)
    cheapest_first = resolve_model_alias_with_effort("@cheapest", consume=True)
    cheap_second = resolve_model_alias_with_effort("@cheap", consume=True)
    cheaper_second = resolve_model_alias_with_effort("@cheaper", consume=True)
    cheapest_second = resolve_model_alias_with_effort("@cheapest", consume=True)

    assert (cheap_first.target, cheap_first.effort) == frozen_selector_member(
        CHEAP_MODEL_ALIAS_NAME, 0
    )
    assert (cheaper_first.target, cheaper_first.effort) == frozen_selector_member(
        CHEAPER_MODEL_ALIAS_NAME, 0
    )
    assert (cheapest_first.target, cheapest_first.effort) == frozen_selector_member(
        CHEAPEST_MODEL_ALIAS_NAME, 0
    )
    assert (cheap_second.target, cheap_second.effort) == frozen_selector_member(
        CHEAP_MODEL_ALIAS_NAME, 1
    )
    assert (cheaper_second.target, cheaper_second.effort) == frozen_selector_member(
        CHEAPER_MODEL_ALIAS_NAME, 1
    )
    assert (cheapest_second.target, cheapest_second.effort) == frozen_selector_member(
        CHEAPEST_MODEL_ALIAS_NAME, 1
    )


@pytest.mark.parametrize(
    ("alias", "expected"),
    [
        (CHEAP_MODEL_ALIAS_NAME, frozen_selector_member(CHEAP_MODEL_ALIAS_NAME, 1)),
        (
            CHEAPER_MODEL_ALIAS_NAME,
            frozen_selector_member(CHEAPER_MODEL_ALIAS_NAME, 1),
        ),
        (
            CHEAPEST_MODEL_ALIAS_NAME,
            frozen_selector_member(CHEAPEST_MODEL_ALIAS_NAME, 1),
        ),
    ],
)
def test_implicit_cheap_pools_skip_unavailable_provider(
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


def test_prior_cheapest_fingerprint_does_not_carry_cursor_to_shipped_pool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg: dict[str, object] = {
        "provider": "claude",
        "model_aliases": {
            "builtin": {"cheapest": "claude/opus@medium | codex/gpt-5.5"}
        },
    }
    mock_provider_config(monkeypatch, cfg)
    monkeypatch.setattr(
        llm_config,
        "_resolved_target_is_available",
        lambda _target: True,
    )
    assert resolve_model_alias("@cheapest", consume=True) == "claude/opus"

    cfg["model_aliases"] = {}
    llm_config._get_model_aliases_for_token.cache_clear()

    assert (
        resolve_model_alias("@cheapest", consume=True)
        == frozen_selector_member(CHEAPEST_MODEL_ALIAS_NAME, 0)[0]
    )
