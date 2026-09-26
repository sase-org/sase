"""Tests for the shipped load-balanced size model aliases."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from sase.llm_provider import config as llm_config
from sase.llm_provider.codex import CodexProvider
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
from sase.llm_provider.types import LLMInvocationOptions
from sase.xprompt.effort import EFFORT_LEVELS_ORDERED
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
                "claude/": ("claude/claude-haiku-4-5", "xhigh"),
                "codex/": ("codex/gpt-6-luna", "medium"),
                "agy/": ("agy/gemini-3.8-flash-high", None),
                "muse/": ("muse/muse-spark-1.3-contributor", "medium"),
            },
        ),
        (
            "@small",
            {
                "claude/": ("claude/sonnet", "high"),
                "codex/": ("codex/gpt-6-luna", "high"),
                "grok/": ("grok/grok-4.6", "medium"),
                "muse/": ("muse/muse-spark-1.3-contributor", "high"),
            },
        ),
        (
            "@medium",
            {
                "claude/": ("claude/sonnet", "xhigh"),
                "codex/": ("codex/gpt-6-luna", "xhigh"),
                "grok/": ("grok/grok-4.6", "high"),
                "muse/": ("muse/muse-spark-1.3-contributor", "xhigh"),
            },
        ),
        (
            "@large",
            {
                "claude/": ("claude/opus", "high"),
                "codex/": ("codex/gpt-6-sol", "xhigh"),
                "grok/": ("grok/grok-4.7", "xhigh"),
            },
        ),
        (
            "@xlarge",
            {
                "claude/": ("claude/opus", "xhigh"),
                "codex/": ("codex/gpt-6-sol", "xhigh"),
                "grok/": ("grok/grok-4.7", "xhigh"),
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


def test_shipped_medium_codex_member_launches_gpt6_luna(
    monkeypatch: pytest.MonkeyPatch,
    real_model_alias_defaults: None,
) -> None:
    """The @medium Codex member launches GPT-6 Luna at its xhigh rung."""
    mock_provider_config(monkeypatch, {"provider": "claude"})
    monkeypatch.setattr(
        llm_config,
        "_resolved_target_is_available",
        lambda target: target.startswith("codex/"),
    )

    selected = resolve_model_alias_with_effort("@medium", consume=True)
    assert selected.target == "codex/gpt-6-luna"
    effort = selected.effort
    assert effort == "xhigh"

    with (
        patch(
            "sase.llm_provider.codex.stream_and_parse_codex_json_output"
        ) as mock_stream,
        patch("sase.llm_provider.codex.subprocess.Popen") as mock_popen,
        patch("sase.llm_provider.codex.provider_timer"),
    ):
        mock_popen.return_value = MagicMock()
        mock_stream.return_value = ("response", "", 0)
        CodexProvider().invoke(
            "test",
            model_tier="large",
            suppress_output=True,
            model_override="gpt-6-luna",
            options=LLMInvocationOptions(reasoning_effort=effort, explicit=True),
        )

    cmd = mock_popen.call_args[0][0]
    assert cmd[cmd.index("--model") + 1] == "gpt-6-luna"
    assert 'model_reasoning_effort="xhigh"' in cmd
    assert cmd[cmd.index('model_reasoning_effort="xhigh"') - 1] == "-c"


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
        "codex/gpt-6-sol@xhigh",
        "grok/grok-4.7@xhigh",
    )
    assert selector.fallback_members == ()

    mock_provider_config(monkeypatch, {"provider": "claude"})
    monkeypatch.setattr(
        llm_config,
        "_resolved_target_is_available",
        lambda _target: True,
    )
    selected = [resolve_model_alias("@large", consume=True) for _ in range(3)]
    assert selected == ["claude/opus", "codex/gpt-6-sol", "grok/grok-4.7"]


def test_shipped_xlarge_uses_ordered_fallbacks(
    monkeypatch: pytest.MonkeyPatch,
    real_model_alias_defaults: None,
) -> None:
    selector = parse_model_alias_selector(
        implicit_alias_targets()[XLARGE_MODEL_ALIAS_NAME]
    )
    assert selector is not None
    assert selector.mode == "fallback"
    assert selector.members == (
        "claude/opus@xhigh",
        "codex/gpt-6-sol@xhigh",
        "grok/grok-4.7@xhigh",
    )
    assert selector.fallback_members == ()

    mock_provider_config(monkeypatch, {"provider": "claude"})
    monkeypatch.setattr(
        llm_config,
        "_resolved_target_is_available",
        lambda _target: True,
    )
    selected = [resolve_model_alias("@xlarge", consume=True) for _ in range(3)]
    assert selected == ["claude/opus", "claude/opus", "claude/opus"]

    monkeypatch.setattr(
        llm_config,
        "_resolved_target_is_available",
        lambda target: target.startswith("codex/"),
    )
    only_codex = resolve_model_alias_with_effort("@xlarge", consume=True)
    assert (only_codex.target, only_codex.effort) == ("codex/gpt-6-sol", "xhigh")

    monkeypatch.setattr(
        llm_config,
        "_resolved_target_is_available",
        lambda target: target.startswith("grok/"),
    )
    only_grok = resolve_model_alias_with_effort("@xlarge", consume=True)
    assert (only_grok.target, only_grok.effort) == ("grok/grok-4.7", "xhigh")


def test_only_shipped_xsmall_has_antigravity_member(
    real_model_alias_defaults: None,
) -> None:
    for alias in (
        XSMALL_MODEL_ALIAS_NAME,
        SMALL_MODEL_ALIAS_NAME,
        MEDIUM_MODEL_ALIAS_NAME,
        LARGE_MODEL_ALIAS_NAME,
        XLARGE_MODEL_ALIAS_NAME,
    ):
        selector = parse_model_alias_selector(implicit_alias_targets()[alias])
        assert selector is not None
        agy = [
            member
            for member in (*selector.members, *selector.fallback_members)
            if member.startswith("agy/")
        ]
        expected = (
            ["agy/gemini-3.8-flash-high"] if alias == XSMALL_MODEL_ALIAS_NAME else []
        )
        assert agy == expected


def test_shipped_size_aliases_follow_the_effort_ladder(
    real_model_alias_defaults: None,
) -> None:
    seen: dict[str, str] = {}
    for alias in (
        XLARGE_MODEL_ALIAS_NAME,
        LARGE_MODEL_ALIAS_NAME,
        MEDIUM_MODEL_ALIAS_NAME,
        SMALL_MODEL_ALIAS_NAME,
        XSMALL_MODEL_ALIAS_NAME,
    ):
        selector = parse_model_alias_selector(implicit_alias_targets()[alias])
        assert selector is not None
        members = (
            selector.members[:1] if selector.mode == "fallback" else selector.members
        )
        for member in members:
            target, _, effort = member.partition("@")
            if target.startswith("agy/"):
                assert effort == ""
                continue
            continued_from = {"grok/grok-4.6": "grok/grok-4.7"}
            previous_effort = seen.get(target) or seen.get(
                continued_from.get(target, "")
            )
            if previous_effort is None:
                assert effort == "xhigh", (alias, member)
            else:
                expected = EFFORT_LEVELS_ORDERED[
                    EFFORT_LEVELS_ORDERED.index(previous_effort) - 1
                ]
                assert effort == expected, (alias, member)
            seen[target] = effort


def test_shipped_small_aliases_carry_the_muse_contributor_member(
    real_model_alias_defaults: None,
) -> None:
    """`@medium` and below deliberately include Meta's Contributor-tier model.

    This is a deliberate, user-requested opt-in to Meta's training terms: the
    Contributor model trains on its inputs and outputs, and these pools can
    select it automatically whenever a `muse` executable is available. The
    tier mapping stays pinned to the paid model (see
    `test_model_advisories.py`); this pins the alias-pool route so a later
    cost or privacy cleanup cannot silently drop the member or re-rung it.
    """
    expected_effort = {
        MEDIUM_MODEL_ALIAS_NAME: "xhigh",
        SMALL_MODEL_ALIAS_NAME: "high",
        XSMALL_MODEL_ALIAS_NAME: "medium",
    }
    for alias in (
        XLARGE_MODEL_ALIAS_NAME,
        LARGE_MODEL_ALIAS_NAME,
        MEDIUM_MODEL_ALIAS_NAME,
        SMALL_MODEL_ALIAS_NAME,
        XSMALL_MODEL_ALIAS_NAME,
    ):
        selector = parse_model_alias_selector(implicit_alias_targets()[alias])
        assert selector is not None
        muse = [
            member
            for member in (*selector.members, *selector.fallback_members)
            if member.startswith("muse/")
        ]
        if alias in expected_effort:
            assert muse == [
                f"muse/muse-spark-1.3-contributor@{expected_effort[alias]}"
            ], alias
        else:
            assert muse == [], alias


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
