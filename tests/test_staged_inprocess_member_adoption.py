"""Focused adoption tests for in-process staged successors."""

from __future__ import annotations

import pytest

from sase.agent.staged_handoff import StagedHandoffError
from sase.axe._run_agent_exec_staged_shared import StagedInlineContinuation
from sase.axe.run_agent_exec_staged_adopters import (
    _is_current_in_process_member,
    _runner_ctx_from_approval_context,
    _runner_ctx_from_metadata,
    _runner_ctx_from_monitor_metadata,
)

from tests._axe_run_agent_exec_plan_helpers import make_ctx, make_state


def _continuation(tmp_path, *, base: str = "test_agent", suffix: str = "--1"):
    ctx = make_ctx(tmp_path)
    import dataclasses

    ctx = dataclasses.replace(ctx, agent_name=base)
    state = make_state(tmp_path)
    state.current_role_suffix = suffix
    return StagedInlineContinuation(ctx=ctx, state=state)


def _member_meta(base: str = "test_agent", suffix: str = "--1") -> dict:
    return {
        "name": f"{base}{suffix}",
        "agent_session": base,
        "workflow_name": base,
        "model": "fakey-large",
        "llm_provider": "fakey",
        "vcs_provider": "github",
    }


def test_in_process_member_accepted_for_pipe(tmp_path) -> None:
    cont = _continuation(tmp_path)
    meta = _member_meta()
    assert _is_current_in_process_member(cont, meta) is True
    ctx = _runner_ctx_from_metadata(cont, meta)
    assert ctx.agent_name == "test_agent"
    assert ctx.agent_meta == meta
    assert ctx.agent_model == "fakey-large"


def test_in_process_member_accepted_for_gate(tmp_path) -> None:
    cont = _continuation(tmp_path)
    meta = _member_meta()
    ctx = _runner_ctx_from_metadata(cont, meta)
    assert ctx.agent_name == "test_agent"


def test_in_process_member_accepted_for_monitor(tmp_path) -> None:
    cont = _continuation(tmp_path)
    meta = _member_meta()
    ctx = _runner_ctx_from_monitor_metadata(cont, meta)
    assert ctx.agent_name == "test_agent"
    assert ctx.agent_meta == meta


def test_in_process_member_accepted_for_plan_via_approval_context(tmp_path) -> None:
    cont = _continuation(tmp_path)
    meta = _member_meta()
    approval = {
        "execution": {
            "agent_name": "test_agent",
            "project_name": "test_proj",
            "cl_name": "test",
        }
    }
    ctx = _runner_ctx_from_approval_context(cont, meta, approval)
    assert ctx.agent_name == "test_agent"
    assert ctx.agent_meta == meta


def test_approval_context_naming_member_is_normalized_to_base(tmp_path) -> None:
    cont = _continuation(tmp_path)
    meta = _member_meta()
    approval = {
        "execution": {
            "agent_name": "test_agent--1",
            "project_name": "test_proj",
        }
    }
    ctx = _runner_ctx_from_approval_context(cont, meta, approval)
    assert ctx.agent_name == "test_agent"


def test_foreign_identity_rejected(tmp_path) -> None:
    cont = _continuation(tmp_path)
    meta = dict(_member_meta())
    meta["name"] = "other-agent"
    meta["agent_session"] = "other-agent"
    assert _is_current_in_process_member(cont, meta) is False
    with pytest.raises(StagedHandoffError, match="persisted agent identity"):
        _runner_ctx_from_metadata(cont, meta)


def test_root_promotion_still_accepted(tmp_path) -> None:
    import dataclasses

    ctx = make_ctx(tmp_path)
    ctx = dataclasses.replace(ctx, agent_name="base-agent")
    state = make_state(tmp_path)
    state.current_role_suffix = ""
    cont = StagedInlineContinuation(ctx=ctx, state=state)
    meta = {
        "name": "base-agent--0",
        "agent_session": "base-agent",
        "workflow_name": "base-agent",
        "role_suffix": "--0",
        "agent_session_role": "root",
    }
    # Seed the runner's own meta so the promotion check sees the base identity.
    ctx = dataclasses.replace(ctx, agent_meta={"name": "base-agent"})
    cont = StagedInlineContinuation(ctx=ctx, state=state)
    out = _runner_ctx_from_monitor_metadata(cont, meta)
    assert out.agent_name == "base-agent--0"
