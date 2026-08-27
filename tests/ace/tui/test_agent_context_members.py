"""Tests for compact agent-family context member labels."""

from __future__ import annotations

from pathlib import Path

from sase.ace.tui.agent_context_members import build_context_members
from sase.ace.tui.models.agent import Agent
from tests.ace.tui.widgets._agent_display_helpers import make_agent


def _member(
    tmp_path: Path,
    name: str,
    *,
    role_suffix: str,
    agent_family_role: str,
    plan_chain_root: bool = False,
) -> Agent:
    artifacts_dir = tmp_path / name
    artifacts_dir.mkdir()
    return make_agent(
        cl_name="context-test",
        raw_suffix=name,
        artifacts_dir=str(artifacts_dir),
        agent_name=f"alpha{name}",
        role_suffix=role_suffix,
        agent_family_role=agent_family_role,
        plan_chain_root=plan_chain_root,
    )


def test_promoted_root_context_label_uses_suffix_token(tmp_path: Path) -> None:
    root = _member(
        tmp_path,
        "root",
        role_suffix="--0",
        agent_family_role="root",
        plan_chain_root=False,
    )
    followup = _member(
        tmp_path,
        "bar",
        role_suffix="--bar",
        agent_family_role="bar",
    )
    root.followup_agents = [followup]

    members = build_context_members(root)

    assert [member.label for member in members] == ["0", "bar"]


def test_historical_q_suffix_context_label_uses_suffix_token(tmp_path: Path) -> None:
    historical = _member(
        tmp_path,
        "historical",
        role_suffix="--q",
        agent_family_role="review",
    )

    members = build_context_members(historical)

    assert [member.label for member in members] == ["q"]
