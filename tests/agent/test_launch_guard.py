"""Unit tests for the fail-closed hard-disable launch guard."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from sase.agent.launch_guard import (
    DisabledProviderLaunchError,
    LaunchUnitsPayloadError,
    blocked_launch_units,
    parse_launch_units_payload,
    plan_launch_units,
)
from sase.agent.launch_request_planning import build_preview_plan
from sase.core.paths import sase_home
from tests.agent._launch_guard_helpers import (
    disable,
    install_disables,
    pin_cli_available,
    pin_default_codex,
)
from tests._xprompt_swarm_helpers import patch_catalog, xp


def _candidate_prompts(prompt: str) -> list[str]:
    return [
        candidate.prompt
        for unit in plan_launch_units(prompt)
        for candidate in unit.candidates
    ]


def _preview_prompts(prompt: str) -> list[str]:
    _query, plan = build_preview_plan(prompt)
    return [slot.prompt for slot in plan.slots]


def test_blocked_launch_units_skips_planning_when_no_hard_disable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_disables(monkeypatch, {})

    def _boom(_prompt: str) -> object:
        raise AssertionError("planning must not run on the empty hard-disable path")

    with patch("sase.agent.multi_prompt.parse_multi_prompt", side_effect=_boom):
        assert blocked_launch_units("%model:claude/opus do work") == ()


def test_explicit_model_on_hard_disabled_provider_is_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pin_cli_available(monkeypatch)
    install_disables(monkeypatch, {"claude": disable("claude")})

    blocked = blocked_launch_units("%model:claude/opus Fix the flaky selector")

    assert len(blocked) == 1
    unit = blocked[0]
    assert unit.blocked
    assert unit.index == 1
    assert unit.total == 1
    assert unit.blocking_providers == ("claude",)
    assert unit.single_model == "claude/opus"
    message = str(DisabledProviderLaunchError.from_unit(unit))
    assert "claude/opus" in message
    assert "%model" in message
    assert "Config > Launch" in message


def test_explicit_model_on_soft_disabled_provider_is_not_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pin_cli_available(monkeypatch)
    install_disables(
        monkeypatch,
        {"claude": disable("claude", mode="soft")},
    )

    assert blocked_launch_units("%model:claude/opus Fix the flaky selector") == ()

    units = plan_launch_units("%model:claude/opus Fix the flaky selector")
    assert len(units) == 1
    assert not units[0].blocked
    assert units[0].candidates[0].provider == "claude"


def test_four_segment_prompt_blocks_only_the_hard_disabled_units(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pin_cli_available(monkeypatch)
    pin_default_codex(monkeypatch)
    install_disables(monkeypatch, {"claude": disable("claude")})
    prompt = (
        "first agent\n---\n"
        "%model:claude/opus second agent\n---\n"
        "third agent\n---\n"
        "%model:claude/opus fourth agent"
    )

    blocked = blocked_launch_units(prompt)

    assert [(unit.index, unit.total) for unit in blocked] == [(2, 4), (4, 4)]
    assert all(unit.blocking_providers == ("claude",) for unit in blocked)


def test_exhausted_pool_lists_each_blocking_provider_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pin_cli_available(monkeypatch)
    install_disables(
        monkeypatch,
        {"claude": disable("claude"), "codex": disable("codex")},
    )

    blocked = blocked_launch_units("%model:@large do the work")

    assert len(blocked) == 1
    assert blocked[0].blocked
    assert set(blocked[0].blocking_providers) == {"claude", "codex"}
    assert len(blocked[0].blocking_providers) == 2


def test_pool_with_one_enabled_member_is_not_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pin_cli_available(monkeypatch)
    install_disables(monkeypatch, {"claude": disable("claude")})

    assert blocked_launch_units("%model:@large do the work") == ()


def test_fallback_skips_hard_disabled_first_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pin_cli_available(monkeypatch)
    install_disables(monkeypatch, {"claude": disable("claude")})

    assert blocked_launch_units("%model:@xlarge do the work") == ()


def test_model_fanout_is_unblocked_when_one_branch_can_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pin_cli_available(monkeypatch)
    install_disables(monkeypatch, {"claude": disable("claude")})
    prompt = "%{%m:claude/opus | %m:codex/gpt-5.5}\nReview the patch"

    assert blocked_launch_units(prompt) == ()
    units = plan_launch_units(prompt)
    assert len(units) == 1
    assert not units[0].blocked
    assert units[0].single_model is None
    assert len(units[0].candidates) == 2


def test_model_fanout_is_blocked_when_every_branch_is_hard_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pin_cli_available(monkeypatch)
    install_disables(
        monkeypatch,
        {"claude": disable("claude"), "codex": disable("codex")},
    )
    prompt = "%{%m:claude/opus | %m:codex/gpt-5.5}\nReview the patch"

    blocked = blocked_launch_units(prompt)
    assert len(blocked) == 1
    assert blocked[0].blocked
    assert blocked[0].single_model is None
    assert set(blocked[0].blocking_providers) == {"claude", "codex"}


def test_repeat_on_a_blocked_provider_is_one_unit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pin_cli_available(monkeypatch)
    install_disables(monkeypatch, {"claude": disable("claude")})

    blocked = blocked_launch_units("%repeat:3 %model:claude/opus Do the work")

    assert len(blocked) == 1
    assert blocked[0].blocked
    assert len(blocked[0].candidates) == 3
    assert blocked[0].single_model == "claude/opus"


@pytest.mark.parametrize(
    "prompt",
    (
        "do the work",
        "first\n---\nsecond\n---\nthird",
        "%{%m:claude/opus | %m:codex/gpt-5.5}\nReview",
        "%repeat:3 Do the work",
        "%alt(Describe, Explain) the change",
    ),
)
def test_plan_launch_units_matches_preview_plan_slot_prompts(
    monkeypatch: pytest.MonkeyPatch,
    prompt: str,
) -> None:
    pin_cli_available(monkeypatch)
    pin_default_codex(monkeypatch)
    install_disables(monkeypatch, {})

    assert _candidate_prompts(prompt) == _preview_prompts(prompt)


def test_plan_launch_units_matches_preview_plan_for_xprompt_swarm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pin_cli_available(monkeypatch)
    pin_default_codex(monkeypatch)
    install_disables(monkeypatch, {})
    catalog = {"three": xp("three", "alpha\n---\nbeta\n---\ngamma")}
    with patch_catalog(catalog):
        assert _candidate_prompts("#!three") == _preview_prompts("#!three")


def test_guard_does_not_move_the_pool_cursor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pin_cli_available(monkeypatch)
    install_disables(
        monkeypatch,
        {"claude": disable("claude"), "codex": disable("codex")},
    )
    path = Path(sase_home()) / "llm_lb.json"
    before = path.read_bytes() if path.exists() else None

    blocked_launch_units("%model:@large do the work")

    after = path.read_bytes() if path.exists() else None
    assert after == before


def test_parse_launch_units_payload_accepts_strict_entries() -> None:
    units = parse_launch_units_payload(
        [
            {
                "prompt": "kept agent",
                "template_group": "xprompt:team:0",
                "swarm_xprompts": ["team"],
            },
            {"prompt": "other", "template_group": None, "swarm_xprompts": []},
        ]
    )

    assert len(units) == 2
    assert units[0].prompt == "kept agent"
    assert units[0].template_group == "xprompt:team:0"
    assert units[0].swarm_xprompts == ("team",)
    assert units[1].template_group is None


@pytest.mark.parametrize(
    "payload",
    (
        "not-a-list",
        [{"prompt": "x"}],
        [
            {
                "prompt": "x",
                "template_group": None,
                "swarm_xprompts": [],
                "extra": 1,
            }
        ],
        [{"prompt": "  ", "template_group": None, "swarm_xprompts": []}],
        [{"prompt": "x", "template_group": 1, "swarm_xprompts": []}],
        [{"prompt": "x", "template_group": None, "swarm_xprompts": "team"}],
    ),
)
def test_parse_launch_units_payload_rejects_malformed_entries(payload: object) -> None:
    with pytest.raises(LaunchUnitsPayloadError):
        parse_launch_units_payload(payload)
