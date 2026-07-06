from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from sase.agent.family_attach import (
    _FamilyAttachDirective,
    _FamilyAttachError,
    _extract_family_attach_directive,
    _resolve_family_attach_plan,
)
from sase.agent.launch_validation import validate_launch_name_requests
from sase.agent.multi_prompt_reference_directives import extract_static_name_directive
from sase.plan_chain import agent_family_role_for_suffix, is_plan_chain_artifact_meta
from sase.xprompt._exceptions import DirectiveError
from sase.xprompt.directives import extract_prompt_directives


def test_name_directive_family_attach_form_parses_and_strips() -> None:
    cleaned, directives = extract_prompt_directives("%n(foo, reviewer)\nDo work")

    assert cleaned == "Do work"
    assert directives.name is None
    assert directives.family_attach_parent == "foo"
    assert directives.family_attach_suffix == "reviewer"


def test_name_directive_single_positional_keeps_plain_name_behavior() -> None:
    cleaned, directives = extract_prompt_directives("%n(foo)\nDo work")

    assert cleaned == "Do work"
    assert directives.name == "foo"
    assert directives.family_attach_parent is None


def test_name_directive_rejects_extra_positionals_and_keywords() -> None:
    with pytest.raises(DirectiveError, match="at most two positional"):
        extract_prompt_directives("%n(foo, reviewer, extra)\nDo work")

    with pytest.raises(DirectiveError, match="Unsupported keyword"):
        extract_prompt_directives("%n(foo, run_status=DONE)\nDo work")


def test_name_directive_rejects_legacy_family_suffix_spellings() -> None:
    with pytest.raises(DirectiveError, match="without a family separator"):
        extract_prompt_directives("%n(foo, .reviewer)\nDo work")

    with pytest.raises(DirectiveError, match="without a family separator"):
        extract_prompt_directives("%n(foo, -reviewer)\nDo work")


def test_prelaunch_name_helpers_ignore_family_attach_form() -> None:
    prompt = "%n(foo, reviewer)\nDo work"

    assert extract_static_name_directive(prompt) is None
    validate_launch_name_requests([prompt])


def test_extract_family_attach_directive() -> None:
    directive = _extract_family_attach_directive("%model:codex/gpt-5\n%n(foo, @)")

    assert directive == _FamilyAttachDirective(parent="foo", suffix="@")


def test_custom_family_role_classifies_plan_chain_metadata() -> None:
    meta = {
        "name": "foo--reviewer",
        "workflow_name": "foo",
        "role_suffix": "--reviewer",
        "agent_family_role": "reviewer",
    }

    assert agent_family_role_for_suffix("--reviewer", agent_family_role="reviewer") == (
        "reviewer"
    )
    assert is_plan_chain_artifact_meta(meta)


def test_family_attach_collision_message_suggests_auto_suffix() -> None:
    from sase.agent.family_attach import _ensure_family_name_available

    with patch("sase.agent.names.get_reserved_agent_names", return_value={"foo--bar"}):
        with pytest.raises(_FamilyAttachError, match=r"%n\(foo, @\)"):
            _ensure_family_name_available(
                "foo--bar",
                _FamilyAttachDirective(parent="foo", suffix="bar"),
            )


def test_family_attach_resolution_error_mentions_running_parent() -> None:
    from sase.agent.family_attach import _resolution_error_message

    message = _resolution_error_message(
        _FamilyAttachDirective(parent="foo", suffix="reviewer"),
        {
            "kind": "running",
            "candidates": [
                {
                    "name": "foo",
                    "timestamp": "20260701010101",
                    "artifact_dir": str(Path("/tmp/foo")),
                }
            ],
        },
        "sase",
    )

    assert "still running" in message
    assert "Wait for it to finish" in message


def test_family_attach_running_parent_builds_queued_plan(monkeypatch) -> None:
    meta = SimpleNamespace(
        name="foo",
        workflow_name="foo",
        agent_family=None,
        role_suffix=None,
        workspace_dir="/tmp/sase_7",
        workspace_num=7,
        cl_name="feature",
        changespec_name=None,
        parent_timestamp=None,
        sdd_plan_path=None,
        plan_path=None,
    )
    record = SimpleNamespace(
        agent_meta=meta,
        project_name="sase",
        artifact_dir="/tmp/artifacts/foo",
        timestamp="20260701010101",
        has_done_marker=False,
        done=None,
        workflow_state=None,
        running=SimpleNamespace(cl_name="feature"),
        plan_path=None,
    )
    monkeypatch.setattr(
        "sase.agent.family_attach._agent_family_snapshot",
        lambda _project_name: SimpleNamespace(records=[record]),
    )
    monkeypatch.setattr(
        "sase.agent.family_attach._dismissed_identity_dicts",
        lambda: [],
    )
    monkeypatch.setattr(
        "sase.agent.family_attach._resolve_binding",
        lambda: (
            lambda request: {
                "kind": "running",
                "parent": request["candidates"][0],
                "candidates": [request["candidates"][0]],
            }
        ),
    )
    monkeypatch.setattr(
        "sase.agent.names.get_reserved_agent_names",
        lambda: set(),
    )

    plan = _resolve_family_attach_plan(
        _FamilyAttachDirective(parent="foo", suffix="reviewer"),
        project_name="sase",
    )

    assert plan.parent_is_running is True
    assert plan.parent_project_name == "sase"
    assert plan.parent_timestamp == "20260701010101"
    assert plan.agent_name == "foo--reviewer"
    assert plan.parent_workspace_num == 7
