"""Both-state coverage for the retired agent-family syntax flag."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json

import pytest

from sase.agent._agent_session_attach_types import (
    AGENT_SESSION_ATTACH_ENV,
    LEGACY_AGENT_FAMILY_ATTACH_ENV,
    AgentSessionAttachLaunchPlan,
)
from sase.agent.agent_session_attach import load_agent_session_attach_plan_from_env
from sase.agent.detached_child import agent_session_attach_env
from sase.feature_flags import override_flags
from sase.main.parser_gate import register_gate_parser
from sase.notification_gates.model_shell import GateShellNext
from sase.notification_gates.models import GateError, GateSpec
from sase.xprompt._exceptions import DirectiveError
from sase.xprompt._directive_edit_identity import set_prompt_name
from sase.xprompt.directives import extract_prompt_directives
from tests._notification_gates_fixtures import custom_gate_spec


def _attach_plan() -> AgentSessionAttachLaunchPlan:
    return AgentSessionAttachLaunchPlan(
        parent_arg="parent",
        suffix_arg="review",
        parent_name="parent--0",
        parent_base="parent",
        parent_timestamp="20260924120000",
        parent_artifacts_dir="/tmp/parent",
        role_suffix="--review",
        agent_name="parent--review",
        agent_session_role="review",
        parent_agent_session_member_name="parent--0",
        parent_agent_session_role_suffix="--0",
        parent_needs_rename=False,
        parent_project_name="sase",
    )


def _gate_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    register_gate_parser(parser.add_subparsers(dest="command"))
    return parser


@pytest.mark.parametrize("enabled", [False, True])
def test_canonical_session_directive_works_in_both_flag_states(enabled: bool) -> None:
    with override_flags(legacy_agent_family_syntax=enabled):
        _, directives = extract_prompt_directives(
            "%id(review, session=parent)\nDo work"
        )

    assert directives.agent_session_attach_parent == "parent"
    assert directives.agent_session_attach_suffix == "review"


def test_legacy_directive_is_an_enabled_alias_and_disabled_error() -> None:
    with override_flags(legacy_agent_family_syntax=True):
        _, directives = extract_prompt_directives("%id(review, family=parent)\nDo work")
    assert directives.agent_session_attach_parent == "parent"

    with override_flags(legacy_agent_family_syntax=False):
        with pytest.raises(DirectiveError, match=r"family= is retired; use session="):
            extract_prompt_directives("%id(review, family=parent)\nDo work")


def test_session_and_family_directives_cannot_be_combined() -> None:
    with override_flags(legacy_agent_family_syntax=True):
        with pytest.raises(
            DirectiveError, match=r"cannot be combined; use only session="
        ):
            extract_prompt_directives(
                "%id(review, session=parent, family=other)\nDo work"
            )


def test_prompt_identity_edits_emit_session_and_reject_disabled_legacy_input() -> None:
    with override_flags(legacy_agent_family_syntax=True):
        rewritten = set_prompt_name("%id(old, family=parent)\nDo work", "new")
    assert rewritten == "%id(new, session=parent)\nDo work"

    with override_flags(legacy_agent_family_syntax=False):
        with pytest.raises(ValueError, match=r"family= is retired; use session="):
            set_prompt_name("%id(old, family=parent)\nDo work", "new")


@pytest.mark.parametrize("enabled", [False, True])
def test_canonical_next_fork_works_in_both_flag_states(enabled: bool) -> None:
    with override_flags(legacy_agent_family_syntax=enabled):
        args = _gate_parser().parse_args(["gate", "create", "--next-fork", "session"])
        raw = custom_gate_spec(request_id=f"canonical-fork-{enabled}")
        raw["shell"] = {"next": {"fork": "session"}}
        spec = GateSpec.from_mapping(raw)

    assert args.next_fork == "session"
    assert spec.shell is not None
    assert spec.shell.next.fork == "session"


def test_legacy_next_fork_and_gate_spec_follow_the_flag(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with override_flags(legacy_agent_family_syntax=True):
        args = _gate_parser().parse_args(["gate", "create", "--next-fork", "family"])
        raw = custom_gate_spec(request_id="legacy-fork-on")
        raw["shell"] = {"next": {"fork": "family"}}
        spec = GateSpec.from_mapping(raw)
    assert args.next_fork == "session"
    assert spec.shell is not None
    assert spec.shell.next.fork == "session"

    with override_flags(legacy_agent_family_syntax=False):
        with pytest.raises(SystemExit):
            _gate_parser().parse_args(["gate", "create", "--next-fork", "family"])
        raw = custom_gate_spec(request_id="legacy-fork-off")
        raw["shell"] = {"next": {"fork": "family"}}
        with pytest.raises(GateError, match=r'"fork": "family" is retired'):
            GateSpec.from_mapping(raw)
    assert '"fork": "session"' in capsys.readouterr().err


def test_gate_help_lists_only_canonical_next_fork_value(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit):
        _gate_parser().parse_args(["gate", "create", "--help"])
    help_text = capsys.readouterr().out

    assert "--next-fork {session,shell,none}" in help_text
    assert "--next-fork {family,shell,none}" not in help_text


def test_durable_legacy_gate_fork_loads_when_the_flag_is_off() -> None:
    with override_flags(legacy_agent_family_syntax=False):
        policy = GateShellNext.from_mapping({"fork": "family"}, target="shell.next")

    assert policy.fork == "session"


def test_attach_env_writer_and_loader_follow_the_flag() -> None:
    plan = _attach_plan()
    written = agent_session_attach_env(plan)
    assert written[AGENT_SESSION_ATTACH_ENV]
    assert LEGACY_AGENT_FAMILY_ATTACH_ENV not in written

    legacy = {LEGACY_AGENT_FAMILY_ATTACH_ENV: json.dumps(asdict(plan))}
    with override_flags(legacy_agent_family_syntax=True):
        assert load_agent_session_attach_plan_from_env(legacy) == plan
    with override_flags(legacy_agent_family_syntax=False):
        assert load_agent_session_attach_plan_from_env(legacy) is None
        assert load_agent_session_attach_plan_from_env(written) == plan
