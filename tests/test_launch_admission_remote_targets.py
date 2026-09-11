"""Approved admission preserves workspace refs and remote dispatch targeting."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from sase.agent.launch_admission import dispatch_typed_launch_request
from sase.agent.launch_admission_runtime import dispatch_agent_unit
from sase.agent.launch_cwd_common import _KnownProjectVcsLaunchRef
from sase.core.agent_launch_facade import (
    agent_unit_dispatch_prompt,
    plan_typed_launch_units,
)
from sase.core.agent_launch_wire import (
    AgentUnitWire,
    agent_launch_wire_to_json_dict,
)
from sase.dispatch.launch import (
    RemoteDispatchLaunchError,
    _RemoteDispatchLaunchResult,
)
from sase.feature_flags import override_flags
from tests._launch_admission_helpers import agent_result


INCIDENT_PROMPT = (
    "%dispatch:apollo\n"
    "%id:sase-xe-live-dismiss-6614\n"
    "#gh:sase\n"
    "Observe the Apollo Agents pane and report honest last-observed status."
)


def _known_sase(tmp_path: Path) -> _KnownProjectVcsLaunchRef:
    workspace = tmp_path / "sase-checkout"
    workspace.mkdir(exist_ok=True)
    return _KnownProjectVcsLaunchRef(
        workflow_type="gh",
        ref="gh_sase-org__sase",
        workspace_dir=str(workspace),
        project_file=str(tmp_path / "sase.sase"),
    )


def _settled_result(*, target: str, operation_id: str, agent_id: str) -> Any:
    receipt = {
        "schema_version": 1,
        "key": {
            "schema_version": 1,
            "controller_id": "source-install",
            "operation_id": operation_id,
        },
        "state": "settled",
        "logical_locator": {
            "schema_version": 1,
            "project": {
                "schema_version": 1,
                "origin": {
                    "schema_version": 1,
                    "installation_id": "apollo-install",
                },
                "project_id": "gh_sase-org__sase",
            },
            "agent_id": agent_id,
            "family_id": None,
        },
        "instance_locator": {"run_id": "run-1"},
        "message": "launched",
    }
    return _RemoteDispatchLaunchResult(
        target=target,
        prompt="observe",
        message=f"Dispatched launch to {target} (settled)",
        payload={
            "count": 0,
            "dispatch": {
                "target": target,
                "operation_key": receipt["key"],
                "state": "settled",
                "source_status": "settled",
                "receipt": receipt,
            },
        },
    )


def test_typed_plan_keeps_incident_workspace_and_dispatch() -> None:
    pytest.importorskip("sase_core_rs")
    with override_flags(typed_launch_units=True):
        plan = plan_typed_launch_units(
            INCIDENT_PROMPT,
            selected_project="gh_sase-org__sase",
        )
    agent = plan.units[0].payload
    assert isinstance(agent, AgentUnitWire)
    assert agent.dispatch_target == "apollo"
    assert agent.workspace_provider == "gh"
    assert agent.workspace_reference == "#gh:sase"
    assert agent.identity == "sase-xe-live-dismiss-6614"
    assert "#gh:sase" not in agent.prompt
    assert "%dispatch" not in agent.prompt
    preview = "\n".join(plan.approval_preview)
    assert "workspace=#gh:sase" in preview
    assert "machine=apollo" in preview
    rebuilt = agent_unit_dispatch_prompt(agent)
    assert "%dispatch:apollo" in rebuilt
    assert "#gh:sase" in rebuilt
    assert "%id:sase-xe-live-dismiss-6614" in rebuilt


def test_typed_plan_keeps_distinct_workspace_refs() -> None:
    pytest.importorskip("sase_core_rs")
    prompt = "%id:one\n#gh:sase\nFirst\n---\n%id:two\n#git:dotfiles\nSecond"
    with override_flags(typed_launch_units=True):
        plan = plan_typed_launch_units(
            prompt,
            launch_kind="multi_prompt",
            selected_project="sase",
        )
    first = plan.units[0].payload
    second = plan.units[1].payload
    assert isinstance(first, AgentUnitWire)
    assert isinstance(second, AgentUnitWire)
    assert first.workspace_reference == "#gh:sase"
    assert second.workspace_reference == "#git:dotfiles"
    assert plan.selected_project == "sase"


def test_family_attach_does_not_inherit_plan_project_as_unit_ref() -> None:
    pytest.importorskip("sase_core_rs")
    with override_flags(typed_launch_units=True):
        plan = plan_typed_launch_units(
            "%id(reviewer, family=parent)\nReview",
            selected_project="sase",
        )
    agent = plan.units[0].payload
    assert isinstance(agent, AgentUnitWire)
    assert agent.family_attach_parent == "parent"
    assert agent.workspace_reference is None
    rebuilt = agent_unit_dispatch_prompt(agent)
    assert "#gh:" not in rebuilt
    assert "sase" not in rebuilt.split("\n")[0]


def test_approved_remote_unit_does_not_spawn_locally(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("sase_core_rs")
    known = _known_sase(tmp_path)
    monkeypatch.setattr(
        "sase.agent.launch_cwd_common.resolve_known_project_vcs_launch_ref",
        lambda prompt: known,
    )
    local_calls: list[str] = []
    remote_calls: list[dict[str, Any]] = []

    def fake_local(prompt: str, extra_env: dict[str, str] | None = None, **kwargs: Any):
        del extra_env, kwargs
        local_calls.append(prompt)
        return [agent_result(tmp_path, "local-fallback")]

    def fake_remote(query: str, *, payload: dict[str, Any], **kwargs: Any):
        del kwargs
        remote_calls.append(
            {"query": query, "payload": dict(payload), "cwd": str(Path.cwd())}
        )
        return _settled_result(
            target="apollo",
            operation_id=str(payload.get("request_id") or "op"),
            agent_id="sase-xe-live-dismiss-6614",
        )

    monkeypatch.setattr("sase.agent.launcher.launch_agents_from_cwd", fake_local)
    monkeypatch.setattr(
        "sase.dispatch.launch.maybe_dispatch_launch",
        fake_remote,
    )
    with override_flags(typed_launch_units=True):
        plan = plan_typed_launch_units(
            INCIDENT_PROMPT,
            selected_project="gh_sase-org__sase",
        )
    response_dir = tmp_path / "bundle"
    response_dir.mkdir()
    result = dispatch_typed_launch_request(
        response_dir,
        {
            "request_id": "launch-incident",
            "selected_project": "gh_sase-org__sase",
            "typed_plan": agent_launch_wire_to_json_dict(plan),
            "dispatch": {"cwd": str(tmp_path), "prompt": INCIDENT_PROMPT},
        },
        spawn_coordinator=False,
    )
    assert local_calls == []
    assert len(remote_calls) == 1
    assert "%dispatch:apollo" in remote_calls[0]["query"]
    assert "#gh:sase" in remote_calls[0]["query"]
    assert remote_calls[0]["payload"]["project"] == "gh_sase-org__sase"
    assert remote_calls[0]["cwd"] == known.workspace_dir
    assert result.summary is not None
    assert result.summary.launched == 1
    assert result.unit_results[0].dispatch_target == "apollo"
    assert result.unit_results[0].workspace_reference == "#gh:sase"
    assert result.unit_results[0].identity == "sase-xe-live-dismiss-6614"
    assert result.unit_results[0].operation_key is not None
    receipt = json.loads(
        (response_dir / "launch_admission" / "receipt.json").read_text(encoding="utf-8")
    )
    assert receipt["units"][0]["dispatch_target"] == "apollo"


def test_mixed_local_and_remote_units_route_independently(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("sase_core_rs")
    known = _known_sase(tmp_path)
    monkeypatch.setattr(
        "sase.agent.launch_cwd_common.resolve_known_project_vcs_launch_ref",
        lambda prompt: known,
    )
    local_calls: list[str] = []
    remote_calls: list[str] = []

    def fake_local(prompt: str, extra_env: dict[str, str] | None = None, **kwargs: Any):
        del extra_env, kwargs
        local_calls.append(prompt)
        return [agent_result(tmp_path, "local-reviewer")]

    def fake_remote(query: str, *, payload: dict[str, Any], **kwargs: Any):
        del payload, kwargs
        remote_calls.append(query)
        return _settled_result(
            target="apollo",
            operation_id="op-remote",
            agent_id="observer",
        )

    monkeypatch.setattr("sase.agent.launcher.launch_agents_from_cwd", fake_local)
    monkeypatch.setattr("sase.dispatch.launch.maybe_dispatch_launch", fake_remote)
    prompt = (
        "%dispatch:apollo\n%id:observer\n#gh:sase\nWatch\n---\n"
        "%id:local-reviewer\nDo local work"
    )
    with override_flags(typed_launch_units=True):
        plan = plan_typed_launch_units(
            prompt,
            launch_kind="multi_prompt",
            selected_project="gh_sase-org__sase",
        )
    response_dir = tmp_path / "bundle"
    response_dir.mkdir()
    dispatch_typed_launch_request(
        response_dir,
        {
            "request_id": "mixed",
            "selected_project": "gh_sase-org__sase",
            "typed_plan": agent_launch_wire_to_json_dict(plan),
            "dispatch": {"cwd": str(tmp_path), "prompt": prompt},
        },
        spawn_coordinator=False,
    )
    assert len(remote_calls) == 1
    assert len(local_calls) == 1
    assert "%dispatch:apollo" in remote_calls[0]
    assert "%dispatch" not in local_calls[0]


def test_offline_remote_target_does_not_fall_back_locally(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("sase_core_rs")
    known = _known_sase(tmp_path)
    monkeypatch.setattr(
        "sase.agent.launch_cwd_common.resolve_known_project_vcs_launch_ref",
        lambda prompt: known,
    )
    local_calls: list[str] = []
    monkeypatch.setattr(
        "sase.agent.launcher.launch_agents_from_cwd",
        lambda prompt, **kwargs: local_calls.append(prompt) or [],
    )

    def fake_remote(query: str, *, payload: dict[str, Any], **kwargs: Any):
        del query, payload, kwargs
        raise RemoteDispatchLaunchError(
            "dispatch target 'apollo' is not enrolled in dispatch.machines"
        )

    monkeypatch.setattr("sase.dispatch.launch.maybe_dispatch_launch", fake_remote)
    with override_flags(typed_launch_units=True):
        plan = plan_typed_launch_units(
            INCIDENT_PROMPT,
            selected_project="gh_sase-org__sase",
        )
    response_dir = tmp_path / "bundle"
    response_dir.mkdir()
    result = dispatch_typed_launch_request(
        response_dir,
        {
            "request_id": "offline",
            "selected_project": "gh_sase-org__sase",
            "typed_plan": agent_launch_wire_to_json_dict(plan),
            "dispatch": {"cwd": str(tmp_path), "prompt": INCIDENT_PROMPT},
        },
        spawn_coordinator=False,
    )
    assert local_calls == []
    assert result.summary is not None
    assert result.summary.launch_errors == 1
    assert "not enrolled" in (result.unit_results[0].message or "")


def test_duplicate_remote_settlement_reuses_operation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("sase_core_rs")
    known = _known_sase(tmp_path)
    monkeypatch.setattr(
        "sase.agent.launch_cwd_common.resolve_known_project_vcs_launch_ref",
        lambda prompt: known,
    )
    keys: list[str] = []

    def fake_remote(query: str, *, payload: dict[str, Any], **kwargs: Any):
        del query, kwargs
        operation_id = str(payload.get("request_id") or "missing")
        keys.append(operation_id)
        return _settled_result(
            target="apollo",
            operation_id=operation_id,
            agent_id="sase-xe-live-dismiss-6614",
        )

    monkeypatch.setattr("sase.dispatch.launch.maybe_dispatch_launch", fake_remote)
    monkeypatch.setattr(
        "sase.agent.launcher.launch_agents_from_cwd",
        lambda *args, **kwargs: pytest.fail("local spawn"),
    )
    with override_flags(typed_launch_units=True):
        plan = plan_typed_launch_units(
            INCIDENT_PROMPT,
            selected_project="gh_sase-org__sase",
        )
    agent = plan.units[0]
    first = dispatch_agent_unit(
        agent,
        "f" * 64,
        selected_project="gh_sase-org__sase",
        source_cwd=str(tmp_path),
    )
    second = dispatch_agent_unit(
        agent,
        "f" * 64,
        selected_project="gh_sase-org__sase",
        source_cwd=str(tmp_path),
    )
    assert first[0] is True
    assert second[0] is True
    assert keys == ["f" * 64, "f" * 64]
    assert first[4]["operation_key"]["operation_id"] == "f" * 64
    assert second[4]["operation_key"]["operation_id"] == keys[0]


def test_uncertain_remote_receipt_is_inspectable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("sase_core_rs")
    known = _known_sase(tmp_path)
    monkeypatch.setattr(
        "sase.agent.launch_cwd_common.resolve_known_project_vcs_launch_ref",
        lambda prompt: known,
    )
    monkeypatch.setattr(
        "sase.agent.launcher.launch_agents_from_cwd",
        lambda *args, **kwargs: pytest.fail("local spawn"),
    )

    def fake_remote(query: str, *, payload: dict[str, Any], **kwargs: Any):
        del query, payload, kwargs
        raise RemoteDispatchLaunchError(
            "remote dispatch outcome is uncertain for apollo: lost reply"
        )

    monkeypatch.setattr("sase.dispatch.launch.maybe_dispatch_launch", fake_remote)
    with override_flags(typed_launch_units=True):
        plan = plan_typed_launch_units(
            INCIDENT_PROMPT,
            selected_project="gh_sase-org__sase",
        )
    ok, identity, message, spawned, extra = dispatch_agent_unit(
        plan.units[0],
        "a" * 64,
        selected_project="gh_sase-org__sase",
        source_cwd=str(tmp_path),
    )
    assert ok is True
    assert spawned == []
    assert extra["uncertain"] is True
    assert extra["dispatch_target"] == "apollo"
    assert "uncertain" in (message or "")
    assert identity


def test_unresolved_workspace_ref_refuses_home_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("sase_core_rs")
    monkeypatch.setattr(
        "sase.agent.launch_cwd_common.resolve_known_project_vcs_launch_ref",
        lambda prompt: None,
    )
    local_calls: list[str] = []
    monkeypatch.setattr(
        "sase.agent.launcher.launch_agents_from_cwd",
        lambda prompt, **kwargs: local_calls.append(prompt) or [],
    )
    monkeypatch.setattr(
        "sase.dispatch.launch.maybe_dispatch_launch",
        lambda *args, **kwargs: pytest.fail("should refuse before network"),
    )
    with override_flags(typed_launch_units=True):
        plan = plan_typed_launch_units(
            INCIDENT_PROMPT,
            selected_project="home",
        )
    ok, _identity, message, spawned, extra = dispatch_agent_unit(
        plan.units[0],
        "b" * 64,
        selected_project="home",
        source_cwd=str(tmp_path),
    )
    assert ok is False
    assert spawned == []
    assert local_calls == []
    assert "home fallback" in (message or "")
    assert extra["receipt_state"] == "unsent"


def test_source_refusal_does_not_spawn_locally(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("sase_core_rs")
    known = _known_sase(tmp_path)
    monkeypatch.setattr(
        "sase.agent.launch_cwd_common.resolve_known_project_vcs_launch_ref",
        lambda prompt: known,
    )
    local_calls: list[str] = []
    monkeypatch.setattr(
        "sase.agent.launcher.launch_agents_from_cwd",
        lambda prompt, **kwargs: local_calls.append(prompt) or [],
    )
    monkeypatch.setattr(
        "sase.dispatch.launch.maybe_dispatch_launch",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            RemoteDispatchLaunchError(
                "remote dispatch cannot use a dirty source checkout"
            )
        ),
    )
    with override_flags(typed_launch_units=True):
        plan = plan_typed_launch_units(
            INCIDENT_PROMPT,
            selected_project="gh_sase-org__sase",
        )
    ok, _identity, message, spawned, _extra = dispatch_agent_unit(
        plan.units[0],
        "c" * 64,
        selected_project="gh_sase-org__sase",
        source_cwd=str(tmp_path),
    )
    assert ok is False
    assert spawned == []
    assert local_calls == []
    assert "dirty source" in (message or "")
