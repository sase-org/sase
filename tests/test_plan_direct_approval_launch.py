"""Tests for the direct-approval coder launch ladder."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from sase.agent.launch_types import AgentLaunchResult
from sase.main.plan_direct_approval import (
    CoderPlacement,
    DirectApprovalPlan,
    DirectApprovalRequest,
)


def _plan(tmp_path: Path, *, mode: str = "session") -> DirectApprovalPlan:
    source = tmp_path / "work.md"
    source.write_text("# work\n", encoding="utf-8")
    placement = (
        CoderPlacement(
            mode="session",
            parent="0sk",
            member_name="0sk--2",
            agent_session="0sk",
        )
        if mode == "session"
        else CoderPlacement(mode="standalone", reason="no planner")
    )
    return DirectApprovalPlan(
        request=DirectApprovalRequest(selector=str(source), project="demo"),
        kind="tale",  # type: ignore[arg-type]
        source_path=source,
        location="proposal",  # type: ignore[arg-type]
        name="work",
        title="Work",
        size="small",
        project="demo",
        project_tag="+demo",
        planner="0sk",
        gate=None,
        placement=placement,
        model_directive="@small",
        bead=None,
        predicted_plan_ref="plan:202609/work.md",
        coder_prompt_preview="+demo %model:@small #coder(plan:202609/work.md)",
    )


def _result() -> AgentLaunchResult:
    return AgentLaunchResult(
        pid=1, workspace_num=10, workspace_dir="/ws/10", output_path="/tmp/out"
    )


@pytest.fixture(autouse=True)
def _owner(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "sase.config._owner.require_agent_owner_identity", lambda: object()
    )


def test_session_failure_then_standalone_success(tmp_path: Path) -> None:
    from sase.main.plan_direct_approval_launch import launch_coder_with_fallbacks

    plan = _plan(tmp_path, mode="session")
    calls: list[str] = []

    def _launch(prompt: str, local_plan: Path):
        calls.append(prompt)
        if len(calls) == 1:
            raise RuntimeError("session boom")
        return _result()

    with patch(
        "sase.main.plan_direct_approval_placement.resolve_bead", return_value=None
    ):
        outcome = launch_coder_with_fallbacks(
            plan, tmp_path / "work.md", "plan:202609/work.md", launch=_launch
        )
    assert len(calls) == 2
    assert "session=" in calls[0]
    assert "session=" not in calls[1]
    assert outcome.coder is not None
    assert outcome.placement is not None and outcome.placement.mode == "standalone"
    assert any("could not join agent session" in note for note in outcome.notes)


def test_fatal_project_tag_error_makes_one_call(tmp_path: Path) -> None:
    from sase.main.plan_direct_approval_launch import launch_coder_with_fallbacks
    from sase.project_tags.tags import ProjectTagError

    plan = _plan(tmp_path, mode="session")
    calls: list[str] = []

    def _launch(prompt: str, local_plan: Path):
        calls.append(prompt)
        raise ProjectTagError("bad tag")

    outcome = launch_coder_with_fallbacks(
        plan, tmp_path / "work.md", "plan:202609/work.md", launch=_launch
    )
    assert len(calls) == 1
    assert outcome.coder is None
    assert outcome.error == "bad tag"


def test_owner_precheck_failure_makes_zero_calls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.main.plan_direct_approval_launch import launch_coder_with_fallbacks

    monkeypatch.setattr(
        "sase.config._owner.require_agent_owner_identity",
        lambda: (_ for _ in ()).throw(RuntimeError("no owner")),
    )
    plan = _plan(tmp_path, mode="session")
    calls: list[str] = []

    def _launch(prompt: str, local_plan: Path):
        calls.append(prompt)
        return _result()

    outcome = launch_coder_with_fallbacks(
        plan, tmp_path / "work.md", "plan:202609/work.md", launch=_launch
    )
    assert calls == []
    assert outcome.coder is None
    assert outcome.error == "no owner"


def test_transient_retry_makes_one_extra_attempt(tmp_path: Path) -> None:
    from sase.main.plan_direct_approval_launch import launch_coder_with_fallbacks
    from sase.running_field import WorkspaceClaimError

    plan = _plan(tmp_path, mode="standalone")
    calls: list[str] = []

    def _launch(prompt: str, local_plan: Path):
        calls.append(prompt)
        if len(calls) == 1:
            raise WorkspaceClaimError("race", workspace_num=10)
        return _result()

    with patch("sase.main.plan_direct_approval_launch.time.sleep") as sleep:
        outcome = launch_coder_with_fallbacks(
            plan, tmp_path / "work.md", "plan:202609/work.md", launch=_launch
        )
    assert len(calls) == 2
    sleep.assert_called_once()
    assert outcome.coder is not None


def test_every_attempt_passes_plan_and_fallback_env(tmp_path: Path) -> None:
    from sase.main.plan_direct_approval_launch import launch_coder_once

    seen: list[dict[str, str]] = []

    def _fake_launch(prompt: str, extra_env=None, **kwargs):
        seen.append(dict(extra_env or {}))
        return [_result()]

    with patch(
        "sase.agent.launch_cwd.launch_agents_from_cwd", side_effect=_fake_launch
    ):
        launch_coder_once("+demo #coder(plan:202609/work.md)", tmp_path / "work.md")
    assert seen and seen[0].get("SASE_PLAN") == str(tmp_path / "work.md")
    assert seen[0].get("SASE_AGENT_PINNED_WORKSPACE_FALLBACK") == "pool"


def test_relocation_note_copied_from_result(tmp_path: Path) -> None:
    from sase.main.plan_direct_approval_launch import launch_coder_with_fallbacks

    plan = _plan(tmp_path, mode="standalone")

    def _launch(prompt: str, local_plan: Path):
        result = _result()
        result.workspace_relocation = (
            "pinned workspace #11 is claimed by x; launched in #13"
        )
        return result

    outcome = launch_coder_with_fallbacks(
        plan, tmp_path / "work.md", "plan:202609/work.md", launch=_launch
    )
    assert outcome.coder is not None
    assert any("pinned workspace #11" in note for note in outcome.notes)
