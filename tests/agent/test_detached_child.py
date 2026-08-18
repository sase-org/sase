"""Tests for the shared out-of-process family spawn primitive."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from sase.agent._family_attach_types import (
    FamilyAttachDirective,
    FamilyAttachLaunchPlan,
)
from sase.agent.detached_child import (
    family_attach_env,
    spawn_detached_child,
    spawn_family_successor,
)
from sase.agent.family_attach import load_family_attach_plan_from_env
from sase.agent.launch_types import AgentLaunchResult
from sase.workflows.utils import get_project_file_path


def _fake_plan(**overrides: Any) -> FamilyAttachLaunchPlan:
    defaults: dict[str, Any] = {
        "parent_arg": "acme",
        "suffix_arg": "@",
        "parent_name": "acme",
        "parent_base": "acme",
        "parent_timestamp": "20260812120000",
        "parent_artifacts_dir": "/tmp/acme",
        "role_suffix": "--1",
        "agent_name": "acme--1",
        "agent_family_role": "root",
        "parent_family_member_name": "acme--0",
        "parent_family_role_suffix": "--0",
        "parent_needs_rename": False,
        "parent_project_name": "proj",
    }
    defaults.update(overrides)
    return FamilyAttachLaunchPlan(**defaults)


def _fake_result(**overrides: Any) -> AgentLaunchResult:
    defaults: dict[str, Any] = {
        "pid": 999,
        "workspace_num": 3,
        "workspace_dir": "/tmp/ws",
        "output_path": "/tmp/ws.txt",
    }
    defaults.update(overrides)
    return AgentLaunchResult(**defaults)


class TestFamilyAttachEnv:
    def test_round_trips_through_load_family_attach_plan_from_env(self) -> None:
        plan = _fake_plan()

        env = family_attach_env(plan)

        assert env["SASE_INTERNAL_AGENT_NAME_BYPASS"] == "1"
        loaded = load_family_attach_plan_from_env(env)
        assert loaded is not None
        assert asdict(loaded) == asdict(plan)


class TestSpawnDetachedChild:
    def test_reserves_timestamp_derives_workflow_name_and_forwards_transfer_pid(
        self,
    ) -> None:
        captured: dict[str, Any] = {}

        def fake_spawn(**kwargs: Any) -> AgentLaunchResult:
            captured.update(kwargs)
            return _fake_result(timestamp=kwargs["timestamp"])

        result = spawn_detached_child(
            project_name="proj",
            prompt="do work",
            workspace_dir="/tmp/ws",
            workspace_num=3,
            cl_name="acme",
            transfer_from_pid=4242,
            project_file="/tmp/proj.sase",
            spawn_fn=fake_spawn,
        )

        assert captured["timestamp"] == result.timestamp
        assert captured["timestamp"]
        assert captured["workflow_name"] == f"ace(run)-{result.timestamp}"
        assert captured["retry_transfer_from_pid"] == 4242
        assert captured["project_file"] == "/tmp/proj.sase"
        assert captured["cl_name"] == "acme"
        assert captured["prompt"] == "do work"

    def test_derives_project_file_from_project_name_when_not_given(self) -> None:
        captured: dict[str, Any] = {}

        def fake_spawn(**kwargs: Any) -> AgentLaunchResult:
            captured.update(kwargs)
            return _fake_result(timestamp=kwargs["timestamp"])

        spawn_detached_child(
            project_name="proj",
            prompt="do work",
            workspace_dir="/tmp/ws",
            workspace_num=0,
            cl_name="acme",
            transfer_from_pid=None,
            spawn_fn=fake_spawn,
        )

        assert captured["project_file"] == get_project_file_path("proj")

    def test_forwards_extra_env_and_vcs_ref(self) -> None:
        captured: dict[str, Any] = {}

        def fake_spawn(**kwargs: Any) -> AgentLaunchResult:
            captured.update(kwargs)
            return _fake_result(timestamp=kwargs["timestamp"])

        spawn_detached_child(
            project_name="proj",
            prompt="do work",
            workspace_dir="/tmp/ws",
            workspace_num=1,
            cl_name="acme",
            transfer_from_pid=None,
            extra_env={"SOME_ENV": "1"},
            vcs_ref=("gh", "sase"),
            update_target="trunk",
            is_home_mode=True,
            spawn_fn=fake_spawn,
        )

        assert captured["extra_env"] == {"SOME_ENV": "1"}
        assert captured["vcs_ref"] == ("gh", "sase")
        assert captured["update_target"] == "trunk"
        assert captured["is_home_mode"] is True


class TestSpawnFamilySuccessor:
    def test_applies_overrides_layers_env_and_falls_back_to_the_plan_name(
        self,
    ) -> None:
        plan = _fake_plan()
        captured: dict[str, Any] = {}

        def fake_spawn(**kwargs: Any) -> AgentLaunchResult:
            captured.update(kwargs)
            return _fake_result(timestamp=kwargs["timestamp"])

        def fake_resolve(
            directive: FamilyAttachDirective, *, project_name: str
        ) -> FamilyAttachLaunchPlan:
            assert directive.parent == "acme"
            assert project_name == "proj"
            return plan

        result = spawn_family_successor(
            FamilyAttachDirective(parent="acme", suffix="@"),
            project_name="proj",
            prompt="do work",
            workspace_dir="/tmp/ws",
            workspace_num=3,
            transfer_from_pid=None,
            agent_family_role="feedback",
            resolve_plan=fake_resolve,
            spawn_fn=fake_spawn,
        )

        assert captured["cl_name"] == plan.agent_name
        assert captured["workspace_dir"] == "/tmp/ws"
        assert captured["workspace_num"] == 3
        env = captured["extra_env"]
        assert env["SASE_INTERNAL_AGENT_NAME_BYPASS"] == "1"
        launched_plan = load_family_attach_plan_from_env(env)
        assert launched_plan is not None
        assert launched_plan.parent_is_running is False
        assert launched_plan.agent_family_role == "feedback"
        assert launched_plan.parent_workspace_dir == "/tmp/ws"
        assert launched_plan.parent_workspace_num == 3
        # The subprocess result never reports its own name; the plan fills it in.
        assert result.agent_name == plan.agent_name

    def test_explicit_cl_name_overrides_the_plan_name(self) -> None:
        plan = _fake_plan()

        def fake_spawn(**kwargs: Any) -> AgentLaunchResult:
            return _fake_result(
                timestamp=kwargs["timestamp"], cl_name=kwargs["cl_name"]
            )

        result = spawn_family_successor(
            FamilyAttachDirective(parent="acme", suffix="@"),
            project_name="proj",
            prompt="do work",
            workspace_dir="/tmp/ws",
            workspace_num=3,
            transfer_from_pid=None,
            cl_name="explicit-branch",
            resolve_plan=lambda *_args, **_kwargs: plan,
            spawn_fn=fake_spawn,
        )

        assert result.cl_name == "explicit-branch"
