"""Tests for the kill-and-edit prompt name-rewriting contract."""

from __future__ import annotations

import pytest

from sase.ace.tui.actions.agent_workflow._entry_name_prompts import (
    KillAndEditPromptError,
    prepare_kill_and_edit_prompt,
)
from sase.ace.tui.actions.agent_workflow._entry_points import (
    _force_name_reuse_in_prompt,
)

from ._retry_edit_agent_name_helpers import (
    _EPIC_ROOT_PROMPT,
    _EPIC_ROOT_RELAUNCH,
    _configured_machine_identity,
)


_06Y_PROMPT = (
    "#gh:gh_sase-org__sase Did we ever fix the issue where "
    "`@/path/to/file` references in bead notes / descriptions were not "
    "being expanded (see sase-pv.7 bead for context)? #if_not_plan"
)


def test_force_name_reuse_rewrites_colon_name_directive() -> None:
    assert _force_name_reuse_in_prompt("%id:foo\nDo work") == "%id:!foo\nDo work"


def test_force_name_reuse_rewrites_colon_alias_directive() -> None:
    assert _force_name_reuse_in_prompt("%i:foo\nDo work") == "%i:!foo\nDo work"


def test_force_name_reuse_rewrites_parenthesized_name_directive() -> None:
    assert _force_name_reuse_in_prompt("%id(foo)\nDo work") == "%id(!foo)\nDo work"


def test_force_name_reuse_rewrites_backtick_name_directive() -> None:
    assert _force_name_reuse_in_prompt("%id:`foo`\nDo work") == "%id:`!foo`\nDo work"


def test_force_name_reuse_leaves_already_forced_name_directive() -> None:
    assert _force_name_reuse_in_prompt("%id:!foo\nDo work") == "%id:!foo\nDo work"


def test_force_name_reuse_leaves_template_without_replacement() -> None:
    assert _force_name_reuse_in_prompt("%id:@.cld\nDo work") == ("%id:@.cld\nDo work")


def test_force_name_reuse_replaces_template_with_concrete_name() -> None:
    assert _force_name_reuse_in_prompt("%id:@.cld\nDo work", "0.cld") == (
        "%id:!0.cld\nDo work"
    )


def test_force_name_reuse_leaves_bare_and_missing_name_directives() -> None:
    assert _force_name_reuse_in_prompt("%id\nDo work") == "%id\nDo work"
    assert _force_name_reuse_in_prompt("Do work") == "Do work"


def test_force_name_reuse_ignores_fenced_and_disabled_name_directives() -> None:
    prompt = (
        "```\n%id:fenced\n```\n"
        "%xprompts_enabled:false\n"
        "%i:disabled\n"
        "%xprompts_enabled:true\n"
        "Do work"
    )
    assert _force_name_reuse_in_prompt(prompt) == prompt


@pytest.mark.parametrize(
    ("raw_prompt", "agent_name", "expected"),
    [
        ("%i:foo\nDo work", "foo", "%id:!foo\nDo work"),
        ("%id:foo\nDo work", "foo", "%id:!foo\nDo work"),
        ("%id:@.cld\nDo work", "0.cld", "%id:!0.cld\nDo work"),
        ("%id:!foo\nDo work", "foo", "%id:!foo\nDo work"),
        (
            "%id:sase-8a.3\n%auto\nDo work",
            "sase-8a.3--plan",
            "%id:!sase-8a.3\n%auto\nDo work",
        ),
        (
            "%id(2, clan=sase-8k, bead=sase-8k.2)\nDo work",
            "sase-8k.2",
            "%id(!2, clan=sase-8k, bead=sase-8k.2)\nDo work",
        ),
        (
            "%id(2, clan=sase-8k, bead=sase-8k.2)\nDo work",
            "sase-8k.2--plan",
            "%id(!2, clan=sase-8k, bead=sase-8k.2)\nDo work",
        ),
        (
            "#gh:gh_sase-org__sase Describe this repo.",
            "068",
            "#gh:gh_sase-org__sase Describe this repo.",
        ),
        ("Do work", None, "Do work"),
    ],
)
def test_prepare_kill_and_edit_prompt_contract(
    raw_prompt: str,
    agent_name: str | None,
    expected: str,
) -> None:
    assert prepare_kill_and_edit_prompt(raw_prompt, agent_name) == expected


def test_prepare_kill_and_edit_prompt_family_root_keeps_clan() -> None:
    rewritten = prepare_kill_and_edit_prompt(
        _EPIC_ROOT_PROMPT,
        "sase-pw.1--plan",
        family_name="sase-pw.1",
        role_suffix="--plan",
        phase_bead_id="sase-pw.1",
        is_family_root=True,
    )
    assert rewritten == _EPIC_ROOT_RELAUNCH
    assert "family=" not in rewritten
    assert "%clan" not in rewritten


def test_prepare_kill_and_edit_epic_root_without_flag_still_keeps_clan() -> None:
    rewritten = prepare_kill_and_edit_prompt(
        _EPIC_ROOT_PROMPT,
        "sase-pw.1--plan",
        family_name="sase-pw.1",
        role_suffix="--plan",
        phase_bead_id="sase-pw.1",
    )
    assert rewritten == _EPIC_ROOT_RELAUNCH


def test_prepare_kill_and_edit_prompt_plain_family_root_keeps_prompt() -> None:
    rewritten = prepare_kill_and_edit_prompt(
        "#gh:gh_sase-org__sase #plan",
        "06d--plan",
        family_name="06d",
        role_suffix="--plan",
        is_family_root=True,
    )
    assert rewritten == "#gh:gh_sase-org__sase #plan"
    assert "family=" not in rewritten


def test_prepare_kill_and_edit_prompt_keeps_prompt_without_identity() -> None:
    assert prepare_kill_and_edit_prompt("Do work", None) == "Do work"


def test_prepare_kill_and_edit_prompt_refuses_self_attaching_family() -> None:
    with pytest.raises(KillAndEditPromptError, match="attaches the agent to itself"):
        prepare_kill_and_edit_prompt(
            "Do work",
            "sase-pw.1",
            family_name="sase-pw.1",
            role_suffix="--code",
        )


@pytest.mark.parametrize(
    ("raw_prompt", "kwargs", "expected"),
    [
        (
            "%id:sase-8u.4.2\n%auto\nDo work",
            {
                "agent_name": "sase-8u.4.2--code",
                "family_name": "sase-8u.4.2",
                "role_suffix": "--code",
            },
            "%id(!code, family=sase-8u.4.2)\n%auto\nDo work",
        ),
        (
            "Do work",
            {
                "agent_name": "sase-8u.4.2--code",
                "family_name": "sase-8u.4.2",
                "role_suffix": "--code",
                "phase_bead_id": "sase-8u.4.2",
            },
            "%id(!code, family=sase-8u.4.2, bead=sase-8u.4.2)\nDo work",
        ),
        (
            "%id(worker, clan=research, bead=kept)\nDo work",
            {
                "agent_name": "athena.research.worker--reviewer",
                "family_name": "athena.research.worker",
                "role_suffix": "--reviewer",
                "phase_bead_id": "ignored",
            },
            "%id(!reviewer, family=research.worker, bead=kept)\nDo work",
        ),
        (
            "%clan(research, tribe=review)\n%id:research.worker\nDo work",
            {
                "agent_name": "research.worker--commit",
                "family_name": "research.worker",
                "role_suffix": "--commit",
            },
            "%id(!commit, family=research.worker)\nDo work",
        ),
    ],
)
def test_prepare_kill_and_edit_prompt_restarts_exact_family_member(
    raw_prompt: str,
    kwargs: dict[str, str],
    expected: str,
) -> None:
    call_kwargs = dict(kwargs)
    agent_name = call_kwargs.pop("agent_name")
    assert (
        prepare_kill_and_edit_prompt(raw_prompt, agent_name, **call_kwargs) == expected
    )


@pytest.mark.parametrize("agent_name", ["foo", None])
def test_prepare_kill_and_edit_prompt_keeps_bare_id(agent_name: str | None) -> None:
    assert prepare_kill_and_edit_prompt("%id\nDo work", agent_name) == "%id\nDo work"


@pytest.mark.parametrize(
    "agent_name",
    ["06y", "bbugyi200.athena.06y", None],
)
def test_prepare_kill_and_edit_prompt_keeps_06y_unnamed_prompt(
    agent_name: str | None,
) -> None:
    assert prepare_kill_and_edit_prompt(_06Y_PROMPT, agent_name) == _06Y_PROMPT


def test_prepare_kill_and_edit_prompt_keeps_fenced_only_id() -> None:
    prompt = "```\n%id:fenced\n```\nDo work"
    assert prepare_kill_and_edit_prompt(prompt, "foo") == prompt


def test_prepare_kill_and_edit_prompt_tolerates_unparseable_prompt_without_id() -> None:
    prompt = "%model:@no_such_alias\nDo work"
    assert prepare_kill_and_edit_prompt(prompt, "foo") == prompt
