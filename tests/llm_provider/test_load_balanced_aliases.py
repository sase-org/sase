"""Load-balanced model-alias resolution and state tests."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from sase.llm_provider import config as llm_config
from sase.llm_provider.config import (
    model_alias_selector_details,
    resolve_effective_effort,
    resolve_model_alias,
    resolve_model_alias_with_effort,
    validate_model_alias_selector_value,
)
from sase.llm_provider.load_balancing import (
    ModelAliasSelectorError,
    parse_model_alias_selector,
)
from sase.llm_provider.registry import resolve_model_provider_with_effort
from sase.xprompt.directives import PromptDirectives
from tests.llm_provider._provider_config_helpers import mock_provider_config


def _configure_pool(
    monkeypatch: pytest.MonkeyPatch,
    value: str = "claude/opus@medium | codex/gpt-5.5",
) -> None:
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "model_aliases": {"builtin": {"pool": value}},
        },
    )
    llm_config._get_model_aliases_for_token.cache_clear()
    monkeypatch.setattr(
        llm_config,
        "_resolved_target_is_available",
        lambda _target: True,
    )


def _pool_member_snapshot() -> tuple[llm_config.ModelAliasSelectorMember, ...]:
    details = model_alias_selector_details("pool")
    assert details is not None
    assert details.mode == "round_robin"
    return details.members


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
    _configure_pool(monkeypatch)

    first = resolve_model_alias_with_effort("@pool")
    assert (first.target, first.effort) == ("claude/opus", "medium")
    assert resolve_model_alias("@pool") == "claude/opus"

    assert resolve_model_alias("@pool", consume=True) == "claude/opus"
    assert resolve_model_alias("@pool", consume=True) == "codex/gpt-5.5"
    assert resolve_model_alias("@pool", consume=True) == "claude/opus"


def test_outer_effort_applies_to_each_selected_pool_member_without_extra_consumption(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_pool(monkeypatch)

    first = resolve_model_alias_with_effort("@pool@high", consume=True)
    second = resolve_model_alias_with_effort("@pool@high", consume=True)
    third = resolve_model_alias_with_effort("@pool@high")

    assert (first.target, first.effort) == ("claude/opus", "high")
    assert (second.target, second.effort) == ("codex/gpt-5.5", "high")
    assert (third.target, third.effort) == ("claude/opus", "high")


def test_ordered_fallback_selects_first_available_without_cursor_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "model_aliases": {
                "builtin": {
                    "fallback": (
                        "claude/claude-fable-5@high || codex/gpt-5.6-sol@medium"
                    )
                }
            },
        },
    )
    llm_config._get_model_aliases_for_token.cache_clear()
    available: set[str] = {"claude/claude-fable-5"}
    monkeypatch.setattr(
        llm_config,
        "_resolved_target_is_available",
        lambda target: target in available,
    )

    from sase.llm_provider import load_balancing

    locked_state = MagicMock(side_effect=AssertionError("fallback read cursor state"))
    monkeypatch.setattr(load_balancing, "_locked_state", locked_state)

    first = resolve_model_alias_with_effort("@fallback", consume=True)
    assert (first.target, first.effort) == ("claude/claude-fable-5", "high")
    assert resolve_model_alias("@fallback", consume=True) == "claude/claude-fable-5"

    available.clear()
    available.add("codex/gpt-5.6-sol")
    second = resolve_model_alias_with_effort("@fallback", consume=True)
    assert (second.target, second.effort) == ("codex/gpt-5.6-sol", "medium")

    available.clear()
    assert resolve_model_alias("@fallback", consume=True) == ("claude/claude-fable-5")
    locked_state.assert_not_called()


def test_small_phase_and_cheap_share_one_rotation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(monkeypatch, {"provider": "claude"})
    monkeypatch.setattr(
        llm_config,
        "_resolved_target_is_available",
        lambda _target: True,
    )

    small = resolve_model_alias_with_effort("@small_phase_worker", consume=True)
    cheap = resolve_model_alias_with_effort("@cheap", consume=True)

    assert (small.target, small.effort) == ("claude/sonnet", "xhigh")
    assert (cheap.target, cheap.effort) == ("codex/gpt-5.5", None)


def test_xsmall_phase_and_cheaper_share_one_rotation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(monkeypatch, {"provider": "claude"})
    monkeypatch.setattr(
        llm_config,
        "_resolved_target_is_available",
        lambda _target: True,
    )

    xsmall = resolve_model_alias_with_effort("@xsmall_phase_worker", consume=True)
    cheaper = resolve_model_alias_with_effort("@cheaper", consume=True)

    assert (xsmall.target, xsmall.effort) == ("claude/sonnet", "medium")
    assert (cheaper.target, cheaper.effort) == ("codex/gpt-5.5", "medium")


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

    assert (cheap_first.target, cheap_first.effort) == (
        "claude/sonnet",
        "xhigh",
    )
    assert (cheaper_first.target, cheaper_first.effort) == (
        "claude/sonnet",
        "medium",
    )
    assert (cheap_second.target, cheap_second.effort) == ("codex/gpt-5.5", None)
    assert (cheaper_second.target, cheaper_second.effort) == (
        "codex/gpt-5.5",
        "medium",
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

    assert resolve_model_alias("@cheapest") == "claude/haiku"
    assert resolve_model_alias("@cheapest") == "claude/haiku"
    assert resolve_model_alias("@cheapest", consume=True) == "claude/haiku"
    assert resolve_model_alias("@cheapest") == "codex/gpt-5.3-codex-spark"
    assert resolve_model_alias("@cheapest", consume=True) == (
        "codex/gpt-5.3-codex-spark"
    )
    assert resolve_model_alias("@cheapest", consume=True) == "claude/haiku"


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

    assert (cheap_first.target, cheap_first.effort) == (
        "claude/sonnet",
        "xhigh",
    )
    assert (cheaper_first.target, cheaper_first.effort) == (
        "claude/sonnet",
        "medium",
    )
    assert (cheapest_first.target, cheapest_first.effort) == ("claude/haiku", None)
    assert (cheap_second.target, cheap_second.effort) == ("codex/gpt-5.5", None)
    assert (cheaper_second.target, cheaper_second.effort) == (
        "codex/gpt-5.5",
        "medium",
    )
    assert (cheapest_second.target, cheapest_second.effort) == (
        "codex/gpt-5.3-codex-spark",
        None,
    )


@pytest.mark.parametrize(
    ("alias", "expected"),
    [
        ("cheap", ("codex/gpt-5.5", None)),
        ("cheaper", ("codex/gpt-5.5", "medium")),
        ("cheapest", ("codex/gpt-5.3-codex-spark", None)),
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

    assert resolve_model_alias("@cheapest", consume=True) == "claude/haiku"


def test_availability_filter_and_all_unavailable_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_pool(monkeypatch)
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
    # A new fingerprint starts at the first member and preserves the full pool
    # when there is no viable fallback.
    _configure_pool(
        monkeypatch,
        "claude/sonnet@high | codex/o3",
    )
    monkeypatch.setattr(
        llm_config,
        "_resolved_target_is_available",
        lambda _target: False,
    )
    assert resolve_model_alias("@pool", consume=True) == "claude/sonnet"
    assert resolve_model_alias("@pool", consume=True) == "codex/o3"


def test_pool_edit_fingerprint_resets_cursor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg: dict[str, object] = {
        "provider": "claude",
        "model_aliases": {"builtin": {"pool": "claude/opus | codex/gpt-5.5"}},
    }
    mock_provider_config(monkeypatch, cfg)
    monkeypatch.setattr(
        llm_config,
        "_resolved_target_is_available",
        lambda _target: True,
    )
    assert resolve_model_alias("@pool", consume=True) == "claude/opus"

    cfg["model_aliases"] = {"builtin": {"pool": "codex/o3 | claude/sonnet"}}
    llm_config._get_model_aliases_for_token.cache_clear()
    assert resolve_model_alias("@pool", consume=True) == "codex/o3"


def test_pool_member_snapshot_marks_fresh_and_advanced_cursor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_pool(monkeypatch)

    assert [member.selected for member in _pool_member_snapshot()] == [
        True,
        False,
    ]
    resolve_model_alias("@pool", consume=True)
    assert [member.selected for member in _pool_member_snapshot()] == [
        False,
        True,
    ]


def test_pool_member_snapshot_marks_available_skip_and_all_down_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_pool(monkeypatch)
    monkeypatch.setattr(
        llm_config,
        "_resolved_target_is_available",
        lambda target: target.startswith("codex/"),
    )

    members = _pool_member_snapshot()
    assert [member.available for member in members] == [False, True]
    assert [member.selected for member in members] == [False, True]

    monkeypatch.setattr(
        llm_config,
        "_resolved_target_is_available",
        lambda _target: False,
    )
    members = _pool_member_snapshot()
    assert [member.available for member in members] == [False, False]
    assert [member.selected for member in members] == [True, False]


def test_pool_member_snapshot_resets_next_marker_after_membership_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg: dict[str, object] = {
        "provider": "claude",
        "model_aliases": {"builtin": {"pool": "claude/opus | codex/o3"}},
    }
    mock_provider_config(monkeypatch, cfg)
    monkeypatch.setattr(
        llm_config,
        "_resolved_target_is_available",
        lambda _target: True,
    )
    resolve_model_alias("@pool", consume=True)
    assert [member.selected for member in _pool_member_snapshot()] == [
        False,
        True,
    ]

    cfg["model_aliases"] = {"builtin": {"pool": "codex/gpt-5.5 | claude/sonnet"}}
    llm_config._get_model_aliases_for_token.cache_clear()
    assert [member.selected for member in _pool_member_snapshot()] == [
        True,
        False,
    ]


def test_corrupt_or_locked_state_never_crashes_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_pool(monkeypatch)
    state_path = Path.home() / ".sase" / "llm_lb.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text("{not-json", encoding="utf-8")
    assert resolve_model_alias("@pool", consume=True) == "claude/opus"

    from sase.llm_provider import load_balancing

    monkeypatch.setattr(
        load_balancing,
        "_locked_state",
        MagicMock(side_effect=OSError("lock unavailable")),
    )
    assert resolve_model_alias("@pool", consume=True) == "claude/opus"


def test_nested_pool_fails_closed_and_validation_is_actionable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "model_aliases": {
                "builtin": {
                    "outer": "@inner | claude/opus",
                    "inner": "codex/o3 | claude/sonnet",
                }
            },
        },
    )
    assert resolve_model_alias("@outer") == "@outer"
    assert (
        "nested load-balanced pool '@inner'"
        in validate_model_alias_selector_value("outer", "@inner | claude/opus")[0]
    )


def test_nested_fallback_and_mixed_selectors_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "model_aliases": {
                "builtin": {
                    "outer": "@inner || claude/opus",
                    "inner": "codex/o3 || claude/sonnet",
                    "mixed": "claude/opus | codex/o3 || claude/sonnet",
                }
            },
        },
    )

    assert resolve_model_alias("@outer") == "@outer"
    assert (
        "nested ordered fallback '@inner'"
        in (validate_model_alias_selector_value("outer", "@inner || claude/opus")[0])
    )
    assert resolve_model_alias("@mixed") == "@mixed"
    assert (
        "cannot mix"
        in validate_model_alias_selector_value(
            "mixed", "claude/opus | codex/o3 || claude/sonnet"
        )[0]
    )


def test_fallback_members_support_alias_chains_and_explicit_unknown_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "model_aliases": {
                "builtin": {
                    "primary": "missing-provider/frontier@xhigh",
                    "fallback": "@primary || codex/gpt-5.6-sol@medium",
                }
            },
        },
    )
    monkeypatch.setattr(
        llm_config,
        "_resolved_target_is_available",
        lambda _target: False,
    )

    assert resolve_model_provider_with_effort("@fallback") == (
        "missing-provider",
        "frontier",
        "xhigh",
    )


def test_fallback_validation_reports_cycles_and_depth_limits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chain = {f"hop_{index}": f"@hop_{index + 1}" for index in range(17)}
    chain["hop_17"] = "claude/opus"
    chain.update({"cycle_a": "@cycle_b", "cycle_b": "@cycle_a"})
    mock_provider_config(
        monkeypatch,
        {"provider": "claude", "model_aliases": {"builtin": chain}},
    )

    cycle_errors = validate_model_alias_selector_value(
        "owner", "@cycle_a || codex/gpt-5.6-sol"
    )
    depth_errors = validate_model_alias_selector_value(
        "owner", "@hop_0 || codex/gpt-5.6-sol"
    )

    assert "creates an alias cycle" in cycle_errors[0]
    assert "exceeds the alias resolution depth limit" in depth_errors[0]


def test_launch_and_temporary_overrides_suspend_ordered_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_provider_config(
        monkeypatch,
        {
            "provider": "claude",
            "model_aliases": {
                "builtin": {"fallback": ("claude/claude-fable-5 || codex/gpt-5.6-sol")}
            },
        },
    )
    monkeypatch.setattr(
        llm_config,
        "_resolved_target_is_available",
        lambda _target: True,
    )

    assert (
        resolve_model_alias("@fallback", {"fallback": "codex/o3"}, consume=True)
        == "codex/o3"
    )

    override = MagicMock(provider="claude", model="opus")
    monkeypatch.setattr(
        llm_config,
        "_active_alias_overrides",
        lambda: {"fallback": override},
    )
    assert resolve_model_alias("@fallback", consume=True) == "claude/opus"


def test_temporary_override_suspends_pool_rotation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_pool(monkeypatch)
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
            "model_aliases": {"builtin": {"focused": "claude/opus@medium"}},
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


def test_rotation_state_records_alias_fingerprint_and_cursor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_pool(monkeypatch)
    resolve_model_alias("@pool", consume=True)
    state_path = Path.home() / ".sase" / "llm_lb.json"
    data = json.loads(state_path.read_text(encoding="utf-8"))
    assert data["version"] == 1
    assert data["entries"]["pool"]["alias"] == "pool"
    assert data["entries"]["pool"]["cursor"] == 1
    assert len(data["entries"]["pool"]["fingerprint"]) == 64


def test_provider_availability_probe_is_cached_and_honors_path_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.llm_provider import registry

    monkeypatch.setattr(
        registry,
        "_llm_metadata_payload",
        lambda: {"providers": {"codex": {"autodetect_cli_name": "codex"}}},
    )
    monkeypatch.setenv("SASE_CODEX_PATH", "/opt/codex/bin/codex")
    which = MagicMock(return_value="/opt/codex/bin/codex")
    monkeypatch.setattr(registry.shutil, "which", which)
    registry.provider_cli_available.cache_clear()

    assert registry.provider_cli_available("codex") is True
    assert registry.provider_cli_available("codex") is True
    which.assert_called_once_with("/opt/codex/bin/codex")
