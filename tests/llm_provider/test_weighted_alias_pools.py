"""Weighted load-balanced model-alias pool schedule and consumption tests."""

from __future__ import annotations

import pytest

from sase.llm_provider import config as llm_config
from sase.llm_provider.config import model_alias_selector_details, resolve_model_alias
from sase.llm_provider.load_balancing import _weighted_schedule
from tests.llm_provider._load_balanced_alias_helpers import configure_pool

_GROK_HEAVY = "claude/sonnet | codex/gpt-5.5 | 3 grok/grok-4.6"
_GROK_HEAVY_CYCLE = (
    "grok/grok-4.6",
    "claude/sonnet",
    "grok/grok-4.6",
    "codex/gpt-5.5",
    "grok/grok-4.6",
)


@pytest.mark.parametrize(
    ("weights", "expected"),
    [
        ((1, 1), (0, 1)),
        ((1, 1, 1), (0, 1, 2)),
        ((1, 1, 1, 1), (0, 1, 2, 3)),
        ((1, 1, 3), (2, 0, 2, 1, 2)),
        ((3, 1, 1), (0, 1, 0, 2, 0)),
        ((2, 1), (0, 1, 0)),
        ((1, 2, 3), (2, 1, 0, 2, 1, 2)),
        ((5, 1), (0, 0, 0, 1, 0, 0)),
    ],
)
def test_weighted_schedule_matches_smooth_round_robin_table(
    weights: tuple[int, ...],
    expected: tuple[int, ...],
) -> None:
    schedule = _weighted_schedule(weights)
    assert schedule == expected
    assert tuple(schedule.count(index) for index in range(len(weights))) == weights


def test_weighted_pool_consumes_two_full_cycles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_pool(monkeypatch, _GROK_HEAVY)
    selected = [resolve_model_alias("@pool", consume=True) for _ in range(10)]
    assert selected == list(_GROK_HEAVY_CYCLE * 2)
    assert selected.count("grok/grok-4.6") == 6
    assert selected.count("claude/sonnet") == 2
    assert selected.count("codex/gpt-5.5") == 2


def test_weighted_pool_skips_unavailable_members_without_banking_credit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_pool(monkeypatch, _GROK_HEAVY)
    monkeypatch.setattr(
        llm_config,
        "_resolved_target_is_available",
        lambda target: not target.startswith("grok/"),
    )
    selected = [resolve_model_alias("@pool", consume=True) for _ in range(4)]
    assert selected == [
        "claude/sonnet",
        "codex/gpt-5.5",
        "claude/sonnet",
        "codex/gpt-5.5",
    ]


def test_weighted_pool_all_down_keeps_member_zero_and_cursor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_pool(monkeypatch, _GROK_HEAVY)
    monkeypatch.setattr(
        llm_config,
        "_resolved_target_is_available",
        lambda _target: False,
    )
    assert resolve_model_alias("@pool", consume=True) == "claude/sonnet"
    assert resolve_model_alias("@pool", consume=True) == "claude/sonnet"
    details = model_alias_selector_details("pool")
    assert details is not None
    assert [member.selected for member in details.members] == [True, False, False]


def test_weighted_pool_details_report_weights_and_selected_member(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_pool(monkeypatch, _GROK_HEAVY)
    before = model_alias_selector_details("pool")
    assert before is not None
    assert [member.weight for member in before.members] == [1, 1, 3]
    assert [member.selected for member in before.members] == [False, False, True]
    assert before.members[2].value == "grok/grok-4.6"

    assert resolve_model_alias("@pool", consume=True) == "grok/grok-4.6"
    after = model_alias_selector_details("pool")
    assert after is not None
    assert [member.selected for member in after.members] == [True, False, False]
    assert after.members[0].value == "claude/sonnet"
