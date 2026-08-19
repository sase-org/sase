"""Last-resort tails on load-balanced model-alias pools."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from sase.llm_provider import config as llm_config
from sase.llm_provider.config import (
    model_alias_selector_details,
    resolve_model_alias,
    resolve_model_alias_with_effort,
    validate_model_alias_selector_value,
)
from sase.llm_provider.provider_disable import (
    PROVIDER_DISABLE_MODE_SOFT,
    PROVIDER_DISABLE_WIRE_SCHEMA_VERSION,
    TemporaryProviderDisable,
)
from tests.llm_provider._load_balanced_alias_helpers import configure_pool

_COMPOUND = "(claude/opus@medium | codex/gpt-5.5) || grok/grok-4.6@xhigh"


def _soft_disable(provider: str) -> TemporaryProviderDisable:
    return TemporaryProviderDisable(
        version=PROVIDER_DISABLE_WIRE_SCHEMA_VERSION,
        provider=provider,
        created_at=100.0,
        expires_at=None,
        source="test",
        mode=PROVIDER_DISABLE_MODE_SOFT,
    )


def test_pool_with_tail_round_robins_and_peek_does_not_consume(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_pool(monkeypatch, _COMPOUND)

    first = resolve_model_alias_with_effort("@pool", consume=True)
    second = resolve_model_alias_with_effort("@pool", consume=True)
    peeked = resolve_model_alias_with_effort("@pool")
    peeked_again = resolve_model_alias_with_effort("@pool")

    assert (first.target, first.effort) == ("claude/opus", "medium")
    assert (second.target, second.effort) == ("codex/gpt-5.5", None)
    assert peeked.target == "claude/opus"
    assert peeked_again.target == "claude/opus"


def test_divert_to_tail_skips_cursor_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_pool(monkeypatch, _COMPOUND)
    monkeypatch.setattr(
        llm_config,
        "_resolved_target_is_available",
        lambda target: target.startswith("grok/"),
    )
    from sase.llm_provider import load_balancing

    locked_state = MagicMock(side_effect=AssertionError("diverted tail read cursor"))
    monkeypatch.setattr(load_balancing, "_locked_state", locked_state)

    selected = resolve_model_alias_with_effort("@pool", consume=True)
    assert (selected.target, selected.effort) == ("grok/grok-4.6", "xhigh")
    locked_state.assert_not_called()
    assert not (Path.home() / ".sase" / "llm_lb.json").exists()


@pytest.mark.parametrize(
    ("available_prefixes", "expected"),
    [
        (("claude/",), "claude/opus"),
        (("codex/",), "codex/gpt-5.5"),
        (("grok/",), "grok/grok-4.6"),
        ((), "grok/grok-4.6"),
    ],
)
def test_availability_masks_select_pool_or_tail(
    monkeypatch: pytest.MonkeyPatch,
    available_prefixes: tuple[str, ...],
    expected: str,
) -> None:
    configure_pool(monkeypatch, _COMPOUND)
    monkeypatch.setattr(
        llm_config,
        "_resolved_target_is_available",
        lambda target: any(target.startswith(prefix) for prefix in available_prefixes),
    )
    from sase.llm_provider import load_balancing

    locked_state = MagicMock(wraps=load_balancing._locked_state)
    if not available_prefixes or available_prefixes == ("grok/",):
        locked_state = MagicMock(side_effect=AssertionError("tail wrote cursor"))
        monkeypatch.setattr(load_balancing, "_locked_state", locked_state)

    assert resolve_model_alias("@pool", consume=True) == expected
    if not available_prefixes or available_prefixes == ("grok/",):
        locked_state.assert_not_called()


def test_soft_disabled_pool_does_not_divert(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_pool(monkeypatch, _COMPOUND)
    monkeypatch.setattr(
        llm_config,
        "_resolved_target_is_available",
        lambda _target: True,
    )
    monkeypatch.setattr(
        "sase.llm_provider.model_alias_resolution._active_provider_disables",
        lambda: {
            "claude": _soft_disable("claude"),
            "codex": _soft_disable("codex"),
        },
    )

    first = resolve_model_alias("@pool", consume=True)
    second = resolve_model_alias("@pool", consume=True)
    assert {first, second} == {"claude/opus", "codex/gpt-5.5"}


def test_hard_disabled_pool_diverts_to_tail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_pool(monkeypatch, _COMPOUND)
    monkeypatch.setattr(
        llm_config,
        "_resolved_target_is_available",
        lambda target: target.startswith("grok/"),
    )

    assert resolve_model_alias("@pool", consume=True) == "grok/grok-4.6"


def test_outer_effort_applies_to_selected_tail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_pool(monkeypatch, _COMPOUND)
    monkeypatch.setattr(
        llm_config,
        "_resolved_target_is_available",
        lambda target: target.startswith("grok/"),
    )

    selected = resolve_model_alias_with_effort("@pool@high", consume=True)
    assert (selected.target, selected.effort) == ("grok/grok-4.6", "high")


def test_nested_selector_in_pool_or_tail_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.llm_provider._provider_config_helpers import mock_provider_config

    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "model_aliases": {
                "custom": {
                    "inner": {
                        "model": "codex/o3 | claude/sonnet",
                        "description": "Inner pool.",
                    },
                    "outer_pool": {
                        "model": "(@inner | claude/opus) || grok/grok-4.6",
                        "description": "Nested in pool.",
                    },
                    "outer_tail": {
                        "model": "(claude/opus | codex/gpt-5.5) || @inner",
                        "description": "Nested in tail.",
                    },
                }
            },
        },
    )

    assert resolve_model_alias("@outer_pool") == "@outer_pool"
    assert (
        "nested load-balanced pool '@inner'"
        in validate_model_alias_selector_value(
            "outer_pool", "(@inner | claude/opus) || grok/grok-4.6"
        )[0]
    )
    assert (
        "pool member 1"
        in validate_model_alias_selector_value(
            "outer_pool", "(@inner | claude/opus) || grok/grok-4.6"
        )[0]
    )
    assert resolve_model_alias("@outer_tail") == "@outer_tail"
    tail_errors = validate_model_alias_selector_value(
        "outer_tail", "(claude/opus | codex/gpt-5.5) || @inner"
    )
    assert "last-resort candidate 1" in tail_errors[0]
    assert "nested load-balanced pool '@inner'" in tail_errors[0]


def test_selector_details_mark_last_resort_and_selected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_pool(monkeypatch, _COMPOUND)

    before = model_alias_selector_details("pool")
    assert before is not None
    assert [member.last_resort for member in before.members] == [False, False, True]
    assert [member.selected for member in before.members] == [True, False, False]

    assert resolve_model_alias("@pool", consume=True) == "claude/opus"
    after = model_alias_selector_details("pool")
    assert after is not None
    assert [member.selected for member in after.members] == [False, True, False]

    monkeypatch.setattr(
        llm_config,
        "_resolved_target_is_available",
        lambda target: target.startswith("grok/"),
    )
    diverted = model_alias_selector_details("pool")
    assert diverted is not None
    assert [member.selected for member in diverted.members] == [False, False, True]
    assert diverted.members[2].last_resort is True
