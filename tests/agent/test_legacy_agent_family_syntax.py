"""Unconditional coverage for the retired agent-family syntax aliases."""

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
from sase.main.parser_gate import register_gate_parser
from sase.notification_gates.model_turn import GateTurnNext
from sase.notification_gates.models import GateSpec
from sase.macro._exceptions import DirectiveError
from sase.macro._directive_edit_identity import set_prompt_name
from sase.macro.directives import extract_prompt_directives
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


def test_canonical_session_directive_passes_through() -> None:
    _, directives = extract_prompt_directives("%id(review, session=parent)\nDo work")

    assert directives.agent_session_attach_parent == "parent"
    assert directives.agent_session_attach_suffix == "review"


def test_legacy_directive_is_always_an_accepted_alias() -> None:
    _, directives = extract_prompt_directives("%id(review, family=parent)\nDo work")
    assert directives.agent_session_attach_parent == "parent"


def test_session_and_family_directives_cannot_be_combined() -> None:
    with pytest.raises(DirectiveError, match=r"cannot be combined; use only session="):
        extract_prompt_directives("%id(review, session=parent, family=other)\nDo work")


def test_prompt_identity_edits_emit_session_for_legacy_input() -> None:
    rewritten = set_prompt_name("%id(old, family=parent)\nDo work", "new")
    assert rewritten == "%id(new, session=parent)\nDo work"


def test_canonical_next_fork_passes_through() -> None:
    args = _gate_parser().parse_args(["gate", "create", "--next-fork", "session"])
    raw = custom_gate_spec(request_id="canonical-fork")
    raw["shell"] = {"next": {"fork": "session"}}
    spec = GateSpec.from_mapping(raw)

    assert args.next_fork == "session"
    assert spec.shell is not None
    assert spec.shell.next.fork == "session"


def test_legacy_next_fork_and_gate_spec_are_always_accepted_aliases() -> None:
    args = _gate_parser().parse_args(["gate", "create", "--next-fork", "family"])
    raw = custom_gate_spec(request_id="legacy-fork-on")
    raw["shell"] = {"next": {"fork": "family"}}
    spec = GateSpec.from_mapping(raw)
    assert args.next_fork == "session"
    assert spec.shell is not None
    assert spec.shell.next.fork == "session"


def test_gate_help_lists_only_canonical_next_fork_value(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit):
        _gate_parser().parse_args(["gate", "create", "--help"])
    help_text = capsys.readouterr().out

    assert "--next-fork {session,turn,none}" in help_text
    assert "--next-fork {family,shell,none}" not in help_text
    assert "--next-fork {session,shell,none}" not in help_text


def test_durable_legacy_gate_fork_loads() -> None:
    policy = GateTurnNext.from_mapping({"fork": "family"}, target="shell.next")

    assert policy.fork == "session"


def test_attach_env_writer_prefers_canonical_and_loader_reads_legacy() -> None:
    plan = _attach_plan()
    written = agent_session_attach_env(plan)
    assert written[AGENT_SESSION_ATTACH_ENV]
    assert LEGACY_AGENT_FAMILY_ATTACH_ENV not in written

    legacy = {LEGACY_AGENT_FAMILY_ATTACH_ENV: json.dumps(asdict(plan))}
    assert load_agent_session_attach_plan_from_env(legacy) == plan
    assert load_agent_session_attach_plan_from_env(written) == plan


def _agents_profile() -> object:
    from sase.ace.query_profile.pane_registry import compiled_profile_for_builtin_pane

    profile = compiled_profile_for_builtin_pane("agents")
    assert profile is not None
    return profile


def test_canonical_session_query_terms_pass_through() -> None:
    from sase.agent.legacy_agent_family_syntax import (
        normalize_agent_session_query_text,
    )

    profile = _agents_profile()
    assert (
        normalize_agent_session_query_text('session:"research.12"', profile)
        == 'session:"research.12"'
    )
    assert (
        normalize_agent_session_query_text("session:research.12", profile)
        == "session:research.12"
    )
    assert normalize_agent_session_query_text("kind:session", profile) == "kind:session"


def test_legacy_query_terms_are_always_accepted_aliases() -> None:
    from sase.agent.legacy_agent_family_syntax import (
        normalize_agent_session_query_text,
    )

    profile = _agents_profile()
    assert (
        normalize_agent_session_query_text('family:"research.12"', profile)
        == "session:research.12"
    )
    assert normalize_agent_session_query_text("kind:family", profile) == "kind:session"
    assert (
        normalize_agent_session_query_text(
            'family:"research.12" AND NOT kind:workflow-child', profile
        )
        == "session:research.12 AND NOT kind:workflow-child"
    )


def test_legacy_query_alias_preserves_host_limit_token() -> None:
    from sase.agent.legacy_agent_family_syntax import (
        normalize_agent_session_query_text,
    )

    profile = _agents_profile()
    assert (
        normalize_agent_session_query_text("family:x limit:5", profile)
        == "session:x limit:5"
    )
    assert (
        normalize_agent_session_query_text("kind:family limit:0", profile)
        == "kind:session limit:0"
    )


def test_canonical_query_text_passes_through_untouched() -> None:
    from sase.agent.legacy_agent_family_syntax import (
        normalize_agent_session_query_text,
    )

    profile = _agents_profile()
    assert normalize_agent_session_query_text("", profile) == ""
    assert normalize_agent_session_query_text("limit:5", profile) == "limit:5"
    assert normalize_agent_session_query_text("name:family", profile) == "name:family"


def test_agent_query_completion_and_hints_show_only_session() -> None:
    profile = _agents_profile()
    assert "session" in profile.filterable_fields()
    assert "family" not in profile.filterable_fields()
