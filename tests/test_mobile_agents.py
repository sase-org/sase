"""Tests for the read-only mobile agent bridge."""

from __future__ import annotations

import argparse
import base64
import io
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from sase.agent.running import RunningAgentInfo, _KillResult
from sase.integrations import mobile_agents
from sase.integrations.mobile_agents import (
    _kill_mobile_agent,
    _launch_mobile_image_agents,
    _launch_mobile_text_agents,
    _list_mobile_agents,
    _mobile_agent_resume_options,
    _retry_mobile_agent,
    handle_mobile_agent_bridge,
)
from sase.agent.launcher import AgentLaunchResult

_PNG_BYTES = b"\x89PNG\r\n\x1a\npayload"


def _image_request(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": 1,
        "prompt": "Review this screenshot",
        "original_filename": "screen.png",
        "content_type": "image/png",
        "byte_length": len(_PNG_BYTES),
        "base64_image": base64.b64encode(_PNG_BYTES).decode("ascii"),
        "device_id": "device/one",
        "name": "mobile.image",
        "dry_run": False,
    }
    payload.update(overrides)
    return payload


def _agent(
    tmp_path: Path,
    *,
    name: str | None = "alpha",
    status: str = "RUNNING",
    project: str = "sase",
) -> RunningAgentInfo:
    artifacts_dir = tmp_path / (name or "unnamed")
    artifacts_dir.mkdir(exist_ok=True)
    (artifacts_dir / "agent_meta.json").write_text(
        json.dumps(
            {
                "retry_of_timestamp": "20260506140000",
                "retry_attempt": 1,
                "parent_agent_name": "parent",
            }
        ),
        encoding="utf-8",
    )
    return RunningAgentInfo(
        name=name,
        project=project,
        pid=1234,
        model="gpt-5.5",
        provider="codex",
        workspace_num=100,
        duration="1m",
        approve=False,
        prompt="Line one\nLine two",
        status=status,
        started_at=datetime(2026, 5, 6, 14, 30, tzinfo=UTC),
        duration_seconds=60,
        artifacts_dir=str(artifacts_dir),
    )


def _known_project(tmp_path: Path, name: str = "sase") -> Path:
    workspace = tmp_path / "workspaces" / name
    workspace.mkdir(parents=True)
    project_dir = tmp_path / "projects" / name
    project_dir.mkdir(parents=True)
    project_file = project_dir / f"{name}.gp"
    project_file.write_text(f"WORKSPACE_DIR: {workspace}\n", encoding="utf-8")
    return workspace


def test_list_mobile_agents_projects_running_agent(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        mobile_agents,
        "list_running_agents",
        lambda: [_agent(tmp_path)],
    )

    payload = _list_mobile_agents({"schema_version": 1})

    assert payload["schema_version"] == 1
    assert payload["total_count"] == 1
    agent = payload["agents"][0]
    assert agent["name"] == "alpha"
    assert agent["status"] == "running"
    assert agent["pid"] == 1234
    assert agent["workspace_number"] == 100
    assert agent["prompt_snippet"] == "Line one Line two"
    assert agent["has_artifact_dir"] is True
    assert agent["actions"] == {
        "can_resume": True,
        "can_wait": True,
        "can_kill": True,
        "can_retry": True,
    }
    assert agent["retry_lineage"]["retry_of_timestamp"] == "20260506140000"
    assert agent["retry_lineage"]["retry_attempt"] == 1


def test_list_mobile_agents_filters_and_limits(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    _known_project(tmp_path, "sase")
    monkeypatch.setattr(
        mobile_agents,
        "list_all_agents",
        lambda: [
            _agent(tmp_path, name="alpha", status="DONE", project="sase"),
            _agent(tmp_path, name="bravo", status="RUNNING", project="other"),
        ],
    )

    payload = _list_mobile_agents(
        {
            "include_recent": True,
            "status": "done",
            "project": "sase",
            "limit": 1,
        }
    )

    assert payload["total_count"] == 1
    assert [agent["name"] for agent in payload["agents"]] == ["alpha"]


def test_resume_options_use_native_resume_and_wait_syntax(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        mobile_agents,
        "list_all_agents",
        lambda: [_agent(tmp_path, name="alpha"), _agent(tmp_path, name="has space")],
    )

    payload = _mobile_agent_resume_options()

    assert payload["options"][0] == {
        "id": "alpha:resume",
        "agent_name": "alpha",
        "kind": "resume",
        "label": "Resume alpha",
        "prompt_text": "#resume:alpha\n",
        "direct_launch_supported": True,
    }
    assert payload["options"][1]["prompt_text"] == "%wait:alpha\n"
    assert payload["options"][2]["prompt_text"] == "#resume:`has space`\n"
    assert payload["options"][3]["prompt_text"] == "%wait:`has space`\n"


def test_bridge_handler_writes_compact_json(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        mobile_agents,
        "list_running_agents",
        lambda: [_agent(tmp_path)],
    )
    stdout = io.StringIO()

    code = handle_mobile_agent_bridge(
        argparse.Namespace(mobile_agent_bridge_subcommand="list-agents"),
        stdin=io.StringIO('{"schema_version":1}'),
        stdout=stdout,
    )

    assert code == 0
    assert json.loads(stdout.getvalue())["agents"][0]["name"] == "alpha"


def test_bridge_handler_rejects_malformed_json() -> None:
    stderr = io.StringIO()

    code = handle_mobile_agent_bridge(
        argparse.Namespace(mobile_agent_bridge_subcommand="list-agents"),
        stdin=io.StringIO("{"),
        stderr=stderr,
    )

    assert code == 2
    assert "invalid JSON request" in stderr.getvalue()


def test_launch_mobile_text_agents_normalizes_prompt_and_returns_slots(
    monkeypatch,
    tmp_path: Path,
) -> None:
    captured: list[str] = []
    monkeypatch.setenv("SASE_HOME", str(tmp_path))

    def fake_launch(prompt: str) -> list[AgentLaunchResult]:
        captured.append(prompt)
        return [
            AgentLaunchResult(
                pid=111,
                workspace_num=0,
                workspace_dir="/tmp/ws1",
                output_path="/tmp/out1",
                project_name="home",
                timestamp="260506_143000",
            ),
            AgentLaunchResult(
                pid=222,
                workspace_num=0,
                workspace_dir="/tmp/ws2",
                output_path="/tmp/out2",
                project_name="home",
                timestamp="260506_143001",
            ),
        ]

    monkeypatch.setattr(mobile_agents, "launch_agents_from_cwd", fake_launch)
    monkeypatch.setattr(
        "sase.xprompt._parsing._LAUNCH_XPROMPT_AT_REF_RE",
        None,
    )
    monkeypatch.setattr(
        "sase.workspace_provider.get_workflow_names",
        lambda: {"gh", "cd"},
    )

    payload = _launch_mobile_text_agents(
        {
            "schema_version": 1,
            "prompt": "#gh@sase Fix it",
            "request_id": "req-text-1",
            "name": "mobile.demo",
            "provider": "codex",
            "model": "gpt-5.5",
        }
    )

    assert captured == ["%name:mobile.demo\n%model:codex/gpt-5.5\n#gh:sase Fix it"]
    assert payload["primary"] == payload["slots"][0]
    assert payload["primary"]["name"] == "mobile.demo"
    assert [slot["status"] for slot in payload["slots"]] == ["launched", "launched"]
    assert payload["slots"][0]["artifact_dir"].endswith(
        "/.sase/projects/home/artifacts/ace-run/20260506143000"
    )
    contexts = (tmp_path / "mobile_gateway" / "agent_launch_contexts.jsonl").read_text(
        encoding="utf-8"
    )
    assert '"agent_name": "mobile.demo"' in contexts
    assert '"request_id": "req-text-1"' in contexts


def test_launch_mobile_text_agents_persists_known_project_context(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    workspace = _known_project(tmp_path, "sase")
    captured_cwds: list[str] = []

    def fake_launch(_prompt: str) -> list[AgentLaunchResult]:
        captured_cwds.append(str(Path.cwd()))
        return [
            AgentLaunchResult(
                pid=111,
                workspace_num=0,
                workspace_dir=str(workspace),
                output_path="/tmp/out",
                project_name="sase",
                timestamp="260506_143000",
            )
        ]

    monkeypatch.setattr(mobile_agents, "launch_agents_from_cwd", fake_launch)

    _launch_mobile_text_agents(
        {
            "schema_version": 1,
            "prompt": "Do work",
            "name": "mobile.project",
            "project": "sase",
            "device_id": "device/one",
        }
    )

    assert captured_cwds == [str(workspace)]
    rows = [
        json.loads(line)
        for line in (tmp_path / "mobile_gateway" / "agent_launch_contexts.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert rows[-1]["project"] == "sase"
    assert rows[-1]["project_context"]["context_id"] == "project:sase"
    assert rows[-1]["project_context"]["project_file"].endswith(
        "/projects/sase/sase.gp"
    )
    device_context = json.loads(
        (
            tmp_path / "mobile_gateway" / "device_project_contexts" / "device-one.json"
        ).read_text(encoding="utf-8")
    )
    assert device_context["project_context"]["context_id"] == "project:sase"


def test_launch_mobile_text_agents_rejects_path_project_context(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path))

    with pytest.raises(Exception, match="not a path"):
        _launch_mobile_text_agents(
            {
                "schema_version": 1,
                "prompt": "Do work",
                "project": "../sase",
            }
        )


def test_launch_mobile_text_agents_reports_validation_errors() -> None:
    stderr = io.StringIO()

    code = handle_mobile_agent_bridge(
        argparse.Namespace(mobile_agent_bridge_subcommand="launch-text"),
        stdin=io.StringIO('{"schema_version":1,"prompt":"   "}'),
        stderr=stderr,
    )

    assert code == 2
    assert "prompt must be a non-empty string" in stderr.getvalue()


def test_launch_mobile_text_dry_run_does_not_spawn(monkeypatch) -> None:
    def fail_launch(_prompt: str) -> list[AgentLaunchResult]:
        raise AssertionError("dry run should not launch")

    monkeypatch.setattr(mobile_agents, "launch_agents_from_cwd", fail_launch)

    payload = _launch_mobile_text_agents(
        {"schema_version": 1, "prompt": "%name:dry\nDo work", "dry_run": True}
    )

    assert payload["primary"] == {
        "slot_id": "0",
        "name": "dry",
        "status": "dry_run",
        "artifact_dir": None,
        "message": "launch request validated",
    }


def test_launch_mobile_image_agents_stores_upload_and_launches(
    monkeypatch, tmp_path: Path
) -> None:
    captured: list[str] = []
    monkeypatch.setenv("SASE_HOME", str(tmp_path))

    def fake_launch(prompt: str) -> list[AgentLaunchResult]:
        captured.append(prompt)
        return [
            AgentLaunchResult(
                pid=111,
                workspace_num=0,
                workspace_dir="/tmp/ws",
                output_path="/tmp/out",
                project_name="home",
                timestamp="260506_143000",
            )
        ]

    monkeypatch.setattr(mobile_agents, "launch_agents_from_cwd", fake_launch)

    payload = _launch_mobile_image_agents(_image_request(request_id="req-image-1"))

    assert payload["primary"]["status"] == "launched"
    stored_files = list(
        (tmp_path / "mobile_gateway" / "uploads" / "images" / "device-one").glob(
            "*.png"
        )
    )
    assert len(stored_files) == 1
    assert stored_files[0].read_bytes() == _PNG_BYTES
    assert "The image has been saved to:" in captured[0]
    assert str(stored_files[0]) in captured[0]
    assert "%name:mobile.image" in captured[0]
    contexts = (tmp_path / "mobile_gateway" / "agent_launch_contexts.jsonl").read_text(
        encoding="utf-8"
    )
    assert '"request_id": "req-image-1"' in contexts


def test_launch_mobile_image_rejects_invalid_base64_without_file(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    stderr = io.StringIO()

    code = handle_mobile_agent_bridge(
        argparse.Namespace(mobile_agent_bridge_subcommand="launch-image"),
        stdin=io.StringIO(json.dumps(_image_request(base64_image="not base64!!!"))),
        stderr=stderr,
    )

    assert code == 3
    assert "invalid base64 image data" in stderr.getvalue()
    assert not (tmp_path / "mobile_gateway" / "uploads").exists()


def test_launch_mobile_image_rejects_extension_content_type_mismatch(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    stderr = io.StringIO()

    code = handle_mobile_agent_bridge(
        argparse.Namespace(mobile_agent_bridge_subcommand="launch-image"),
        stdin=io.StringIO(
            json.dumps(
                _image_request(
                    original_filename="screen.jpg",
                    content_type="image/png",
                )
            )
        ),
        stderr=stderr,
    )

    assert code == 3
    assert "image extension does not match content type" in stderr.getvalue()


def test_launch_mobile_image_rejects_oversize_before_write(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    stderr = io.StringIO()

    code = handle_mobile_agent_bridge(
        argparse.Namespace(mobile_agent_bridge_subcommand="launch-image"),
        stdin=io.StringIO(json.dumps(_image_request(byte_length=10 * 1024 * 1024 + 1))),
        stderr=stderr,
    )

    assert code == 3
    assert "image upload exceeds maximum size" in stderr.getvalue()
    assert not (tmp_path / "mobile_gateway" / "uploads").exists()


def test_launch_mobile_image_path_traversal_filename_is_not_used(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    monkeypatch.setattr(
        mobile_agents,
        "launch_agents_from_cwd",
        lambda _prompt: [
            AgentLaunchResult(
                pid=111,
                workspace_num=0,
                workspace_dir="/tmp/ws",
                output_path="/tmp/out",
                project_name="home",
                timestamp="260506_143000",
            )
        ],
    )

    _launch_mobile_image_agents(
        _image_request(original_filename="../../caller-name.png")
    )

    stored_files = list(
        (tmp_path / "mobile_gateway" / "uploads" / "images" / "device-one").glob(
            "*.png"
        )
    )
    assert len(stored_files) == 1
    assert stored_files[0].name != "caller-name.png"
    assert not (tmp_path / "caller-name.png").exists()


def test_launch_mobile_image_keeps_stored_file_when_launch_fails(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path))

    def fail_launch(_prompt: str) -> list[AgentLaunchResult]:
        raise RuntimeError("launch boom")

    monkeypatch.setattr(mobile_agents, "launch_agents_from_cwd", fail_launch)

    with pytest.raises(Exception, match="launch boom"):
        _launch_mobile_image_agents(_image_request())

    stored_files = list(
        (tmp_path / "mobile_gateway" / "uploads" / "images" / "device-one").glob(
            "*.png"
        )
    )
    assert len(stored_files) == 1


def test_kill_mobile_agent_returns_result_and_persists_context(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    agent = _agent(tmp_path, name="alpha")
    monkeypatch.setattr(mobile_agents, "list_all_agents", lambda: [agent])
    monkeypatch.setattr(
        mobile_agents,
        "kill_named_agent",
        lambda name, *, exact_name: _KillResult(
            True,
            f"Killed agent '{name}' (PID 1234)",
            status="killed",
            pid=1234,
            changed=True,
            artifacts_dir=agent.artifacts_dir,
            project="sase",
            timestamp="20260506143000",
        ),
    )

    payload = _kill_mobile_agent(
        {
            "schema_version": 1,
            "name": "alpha",
            "reason": "mobile",
            "device_id": "device_123",
        }
    )

    assert payload == {
        "schema_version": 1,
        "name": "alpha",
        "status": "killed",
        "pid": 1234,
        "changed": True,
        "message": "Killed agent 'alpha' (PID 1234)",
    }
    context_path = tmp_path / "mobile_gateway" / "agent_kill_contexts" / "alpha.json"
    context = json.loads(context_path.read_text(encoding="utf-8"))
    assert context["agent_name"] == "alpha"
    assert context["artifact_dir"] == agent.artifacts_dir
    assert context["project"] == "sase"
    assert context["raw_prompt"] == "Line one\nLine two"
    assert context["killed_pid"] == 1234
    assert context["device_id"] == "device_123"


@pytest.mark.parametrize(
    ("result", "expected_code", "expected_message"),
    [
        (
            _KillResult(
                False,
                "No agent found with name 'missing'",
                reason="not_found",
            ),
            4,
            "No agent found",
        ),
        (
            _KillResult(
                False,
                "Agent 'done' already completed",
                reason="already_completed",
            ),
            5,
            "already completed",
        ),
        (
            _KillResult(
                False,
                "Could not find PID for agent 'stale'",
                reason="missing_pid",
            ),
            5,
            "Could not find PID",
        ),
        (
            _KillResult(
                False,
                "Permission denied killing agent 'alpha' (PID 1234)",
                reason="permission_denied",
            ),
            6,
            "Permission denied",
        ),
    ],
)
def test_kill_mobile_agent_maps_lifecycle_errors(
    monkeypatch,
    result: _KillResult,
    expected_code: int,
    expected_message: str,
) -> None:
    monkeypatch.setattr(mobile_agents, "kill_named_agent", lambda *_a, **_k: result)
    stderr = io.StringIO()

    code = handle_mobile_agent_bridge(
        argparse.Namespace(mobile_agent_bridge_subcommand="kill-agent"),
        stdin=io.StringIO('{"schema_version":1,"name":"alpha"}'),
        stderr=stderr,
    )

    assert code == expected_code
    assert expected_message in stderr.getvalue()


def test_retry_mobile_agent_prefers_artifact_prompt_and_allocates_name(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    monkeypatch.setattr(mobile_agents, "list_all_agents", lambda: [])
    artifact_dir = tmp_path / "projects" / "sase" / "artifacts" / "ace-run" / "ts1"
    artifact_dir.mkdir(parents=True)
    (artifact_dir / "raw_xprompt.md").write_text(
        "%name:alpha\nDo work", encoding="utf-8"
    )
    store = tmp_path / "mobile_gateway" / "agent_launch_contexts.jsonl"
    store.parent.mkdir(parents=True)
    store.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "agent_name": "alpha",
                "artifact_dir": str(artifact_dir),
                "artifacts_timestamp": "ts1",
                "project": "sase",
                "prompt_snapshot": "fallback prompt",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    captured: list[str] = []

    def fake_launch(prompt: str) -> list[AgentLaunchResult]:
        captured.append(prompt)
        return [
            AgentLaunchResult(
                pid=333,
                workspace_num=0,
                workspace_dir="/tmp/ws",
                output_path="/tmp/out",
                project_name="sase",
                timestamp="260506_150000",
            )
        ]

    monkeypatch.setattr(mobile_agents, "launch_agents_from_cwd", fake_launch)
    monkeypatch.setattr(mobile_agents, "allocate_retry_name", lambda _name: "alpha.1")

    payload = _retry_mobile_agent(
        {"schema_version": 1, "name": "alpha", "request_id": "req-retry-1"}
    )

    assert captured == ["%name:alpha.1\nDo work"]
    assert payload["source_agent"] == "alpha"
    assert payload["launch"]["primary"]["name"] == "alpha.1"
    contexts = store.read_text(encoding="utf-8")
    assert '"agent_name": "alpha.1"' in contexts
    assert '"source_agent_name": "alpha"' in contexts
    assert '"request_id": "req-retry-1"' in contexts


def test_retry_mobile_agent_falls_back_to_mobile_kill_context(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    monkeypatch.setattr(mobile_agents, "list_all_agents", lambda: [])
    context_dir = tmp_path / "mobile_gateway" / "agent_kill_contexts"
    context_dir.mkdir(parents=True)
    (context_dir / "killed.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "agent_name": "killed",
                "raw_prompt": "Do killed work",
            }
        ),
        encoding="utf-8",
    )
    captured: list[str] = []
    monkeypatch.setattr(mobile_agents, "allocate_retry_name", lambda _name: "killed.1")
    monkeypatch.setattr(
        mobile_agents,
        "launch_agents_from_cwd",
        lambda prompt: (
            captured.append(prompt)
            or [
                AgentLaunchResult(
                    pid=334,
                    workspace_num=0,
                    workspace_dir="/tmp/ws",
                    output_path="/tmp/out",
                    project_name="sase",
                    timestamp="260506_150001",
                )
            ]
        ),
    )

    payload = _retry_mobile_agent({"schema_version": 1, "name": "killed"})

    assert captured == ["%name:killed.1\nDo killed work"]
    assert payload["source_agent"] == "killed"


def test_retry_mobile_agent_missing_context_returns_not_found(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    monkeypatch.setattr(mobile_agents, "list_all_agents", lambda: [])
    stderr = io.StringIO()

    code = handle_mobile_agent_bridge(
        argparse.Namespace(mobile_agent_bridge_subcommand="retry-agent"),
        stdin=io.StringIO('{"schema_version":1,"name":"missing"}'),
        stderr=stderr,
    )

    assert code == 4
    assert "No retry context found" in stderr.getvalue()


def test_mobile_agent_bridge_smoke_launch_list_kill_retry_and_image(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    monkeypatch.setattr(mobile_agents, "allocate_retry_name", lambda name: f"{name}.1")
    launched_prompts: list[str] = []
    running_names: list[str] = []

    def fake_launch(prompt: str) -> list[AgentLaunchResult]:
        launched_prompts.append(prompt)
        name = (
            mobile_agents._planned_name_for_prompt(prompt)
            or f"agent-{len(running_names)}"
        )
        running_names.append(name)
        return [
            AgentLaunchResult(
                pid=4000 + len(running_names),
                workspace_num=0,
                workspace_dir="/tmp/ws",
                output_path="/tmp/out",
                project_name="home",
                timestamp=f"260506_16000{len(running_names)}",
            )
        ]

    def fake_running() -> list[RunningAgentInfo]:
        return [_agent(tmp_path, name=name, project="home") for name in running_names]

    def fake_kill(name: str, *, exact_name: bool) -> _KillResult:
        if name in running_names:
            running_names.remove(name)
        return _KillResult(
            True,
            f"Killed agent '{name}' (PID 4001)",
            status="killed",
            pid=4001,
            changed=True,
            artifacts_dir=str(tmp_path / name),
            project="home",
            timestamp="20260506160001",
        )

    monkeypatch.setattr(mobile_agents, "launch_agents_from_cwd", fake_launch)
    monkeypatch.setattr(mobile_agents, "list_running_agents", fake_running)
    monkeypatch.setattr(mobile_agents, "list_all_agents", fake_running)
    monkeypatch.setattr(mobile_agents, "kill_named_agent", fake_kill)

    launch = _launch_mobile_text_agents(
        {
            "schema_version": 1,
            "prompt": "Do smoke work",
            "name": "smoke.text",
            "device_id": "device-one",
        }
    )
    listed = _list_mobile_agents({"schema_version": 1, "device_id": "device-one"})
    killed = _kill_mobile_agent(
        {"schema_version": 1, "name": "smoke.text", "device_id": "device-one"}
    )
    retry = _retry_mobile_agent(
        {"schema_version": 1, "name": "smoke.text", "device_id": "device-one"}
    )
    image = _launch_mobile_image_agents(_image_request(name="smoke.image"))

    assert launch["primary"]["name"] == "smoke.text"
    assert [agent["name"] for agent in listed["agents"]] == ["smoke.text"]
    assert killed["changed"] is True
    assert retry["launch"]["primary"]["name"] == "smoke.text.1"
    assert image["primary"]["name"] == "smoke.image"
    assert "The image has been saved to:" in launched_prompts[-1]
    assert list(
        (tmp_path / "mobile_gateway" / "uploads" / "images" / "device-one").glob(
            "*.png"
        )
    )
