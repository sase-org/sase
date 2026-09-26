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
from sase.llm_provider.load_balancing import (
    concatenated_selector_members,
    parse_model_alias_selector,
)
from sase.llm_provider.model_alias_policy import (
    LARGE_MODEL_ALIAS_NAME,
    MEDIUM_MODEL_ALIAS_NAME,
    SMALL_MODEL_ALIAS_NAME,
    XLARGE_MODEL_ALIAS_NAME,
    XSMALL_MODEL_ALIAS_NAME,
    implicit_alias_targets,
)
from sase.llm_provider.types import LLMInvocationOptions
from sase.xprompt.effort import EFFORT_LEVELS_ORDERED, split_model_effort
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


def _shipped_members(alias_name: str) -> tuple[str, ...]:
    """Return the shipped selector members for a size alias, in order."""
    selector = parse_model_alias_selector(implicit_alias_targets()[alias_name])
    assert selector is not None, alias_name
    return concatenated_selector_members(selector)


def test_packaged_defaults_select_correct_effort_per_provider(
    monkeypatch: pytest.MonkeyPatch,
    real_model_alias_defaults: None,
) -> None:
    """A lone available provider selects its shipped member at its shipped effort.

    Expectations derive from the shipped alias loader: with only one
    provider's targets available, resolution must land on that provider's
    first shipped member (pool rotation and ordered fallback both converge
    there). Retuning a model ID or rung needs no test edit; the graph-shape
    tripwire in ``test_model_alias_defaults.py`` still guards structural
    changes.
    """
    mock_provider_config(monkeypatch, {"provider": "claude"})

    for alias_name, target in implicit_alias_targets().items():
        selector = parse_model_alias_selector(target)
        assert selector is not None, alias_name
        seen_providers: set[str] = set()
        for member in concatenated_selector_members(selector):
            shipped_target, shipped_effort = split_model_effort(member)
            provider = shipped_target.split("/", 1)[0]
            if provider in seen_providers:
                continue
            seen_providers.add(provider)
            prefix = provider + "/"
            monkeypatch.setattr(
                llm_config,
                "_resolved_target_is_available",
                lambda target, prefix=prefix: target.startswith(prefix),
            )

            selected = resolve_model_alias_with_effort(f"@{alias_name}", consume=True)

            assert (selected.target, selected.effort) == (
                shipped_target,
                shipped_effort,
            ), alias_name


def test_shipped_medium_codex_member_launches_at_shipped_effort(
    monkeypatch: pytest.MonkeyPatch,
    real_model_alias_defaults: None,
) -> None:
    """The shipped @medium Codex member launches with Codex model/effort flags."""
    codex_members = [
        member
        for member in _shipped_members(MEDIUM_MODEL_ALIAS_NAME)
        if member.startswith("codex/")
    ]
    assert codex_members, "shipped @medium must keep a Codex launch-path member"
    expected_target, expected_effort = split_model_effort(codex_members[0])
    assert expected_effort is not None
    _, expected_model = expected_target.split("/", 1)

    mock_provider_config(monkeypatch, {"provider": "claude"})
    monkeypatch.setattr(
        llm_config,
        "_resolved_target_is_available",
        lambda target: target.startswith("codex/"),
    )

    selected = resolve_model_alias_with_effort("@medium", consume=True)
    assert (selected.target, selected.effort) == (expected_target, expected_effort)
    effort = selected.effort

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
            model_override=expected_model,
            options=LLMInvocationOptions(reasoning_effort=effort, explicit=True),
        )

    cmd = mock_popen.call_args[0][0]
    assert cmd[cmd.index("--model") + 1] == expected_model
    effort_flag = f'model_reasoning_effort="{expected_effort}"'
    assert effort_flag in cmd
    assert cmd[cmd.index(effort_flag) - 1] == "-c"


def test_shipped_large_pool_round_robins_shipped_members(
    monkeypatch: pytest.MonkeyPatch,
    real_model_alias_defaults: None,
) -> None:
    selector = parse_model_alias_selector(
        implicit_alias_targets()[LARGE_MODEL_ALIAS_NAME]
    )
    assert selector is not None
    assert selector.mode == "round_robin"
    expected = [split_model_effort(member)[0] for member in selector.members]
    assert len(expected) > 1

    mock_provider_config(monkeypatch, {"provider": "claude"})
    monkeypatch.setattr(
        llm_config,
        "_resolved_target_is_available",
        lambda _target: True,
    )
    selected = [
        resolve_model_alias("@large", consume=True) for _ in range(len(expected))
    ]
    assert selected == expected


def test_shipped_xlarge_uses_ordered_fallbacks(
    monkeypatch: pytest.MonkeyPatch,
    real_model_alias_defaults: None,
) -> None:
    selector = parse_model_alias_selector(
        implicit_alias_targets()[XLARGE_MODEL_ALIAS_NAME]
    )
    assert selector is not None
    assert selector.mode == "fallback"
    expected = [
        split_model_effort(member)
        for member in _shipped_members(XLARGE_MODEL_ALIAS_NAME)
    ]
    assert len(expected) > 1

    mock_provider_config(monkeypatch, {"provider": "claude"})
    monkeypatch.setattr(
        llm_config,
        "_resolved_target_is_available",
        lambda _target: True,
    )
    selected = [resolve_model_alias("@xlarge", consume=True) for _ in range(3)]
    assert selected == [expected[0][0]] * 3

    seen_providers: set[str] = set()
    for shipped_target, shipped_effort in expected:
        provider = shipped_target.split("/", 1)[0]
        if provider in seen_providers:
            continue
        seen_providers.add(provider)
        prefix = provider + "/"
        monkeypatch.setattr(
            llm_config,
            "_resolved_target_is_available",
            lambda target, prefix=prefix: target.startswith(prefix),
        )
        only_provider = resolve_model_alias_with_effort("@xlarge", consume=True)
        assert (only_provider.target, only_provider.effort) == (
            shipped_target,
            shipped_effort,
        )


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
