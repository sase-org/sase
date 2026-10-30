"""Internal stage/adopt/cleanup transaction for monitor starts.

Public CLI stays on the immediate path. These tests call the staging
entries directly and keep existing ``start_monitor`` behavior unchanged.
"""

from __future__ import annotations

import json
from hashlib import sha256
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from sase.agent.staged_handoff import STAGED_HANDOFF_FILENAME, read_staged_handoff
from sase.core.staged_handoff import staged_monitor_launch_payload_schema_version
from sase.core.tool_run import tool_run_show
from sase.core.continuation_facade import seal_conditional_completion
from sase.core.continuation_wire import CONTINUATION_WIRE_SCHEMA_VERSION
from sase.finalizers.prepare import (
    bind_prepared_completion,
    load_prepared_completion,
    persist_prepared_completion,
)
from sase.finalizers.declaration import FinalizerDeclarationError
from sase.monitor.models import MonitorAlreadyRunningError, MonitorError
from sase.monitor.start import StartMonitorRequest, start_monitor
from sase.monitor.start_stage import (
    _load_staged_monitor_launch_payload,
    cleanup_staged_monitor,
    launch_from_persisted_payload,
    stage_monitor,
)
from sase.monitor.staged_owner import launch_payload_path
from sase.procs.submission import ProcSubmitError
from sase.running_field import WorkspaceClaim
from sase.tool.owner import observe_owner_fact
from tests.monitor._fixtures import (
    make_starter_agent,
    patch_project_records,
    record_from_disk,
    register_workspace_checkout,
    wait_for_done,
    write_project_file,
)
from tests.monitor._join_helpers import reserve_detached_run


SANDBOX_CATALOG = """\
tools:
  check:
    argv: ["true"]
    description: sandbox verify probe
    stages: none
    inputs: []
    env: []
    args: deny
    fingerprint:
      repos: []
      toolchain: {}
"""


def _read_reservations(artifacts_dir: str | Path) -> dict[str, Any]:
    path = (
        Path(artifacts_dir)
        / "continuation"
        / "completion_intents"
        / "reservations.json"
    )
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))["reservations"]


@pytest.fixture(autouse=True)
def _sandbox_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    monkeypatch.delenv("SASE_AGENT_NAME", raising=False)
    monkeypatch.delenv("SASE_NATIVE_HELPER", raising=False)
    monkeypatch.delenv("SASE_FINALIZER_OWNED_TURN", raising=False)


def _sandbox_project(tmp_path: Path, name: str = "proj") -> Path:
    root = tmp_path / name
    (root / ".git").mkdir(parents=True)
    sase_dir = root / "sase"
    sase_dir.mkdir(parents=True)
    (sase_dir / "sase.yml").write_text(SANDBOX_CATALOG, encoding="utf-8")
    return root


def _request(
    tmp_path: Path,
    *,
    command: str = "true",
    cwd: str | None = None,
    join_run_id: str | None = None,
    profile: str | None = None,
    completion_ref: str | None = None,
    checkpoint_ref: str | None = None,
    checkpoint_document: dict[str, object] | None = None,
) -> StartMonitorRequest:
    return StartMonitorRequest(
        command=command,
        reason="verify staging",
        timeout_seconds=30.0,
        cwd=cwd or str(tmp_path),
        project_name="proj",
        start_status="MONITORING",
        stop_status="MONITORED",
        lane="acme",
        join_run_id=join_run_id,
        profile=profile,
        completion_ref=completion_ref,
        checkpoint_ref=checkpoint_ref,
        checkpoint_document=checkpoint_document,
    )


def _sealed_intent(command: list[str]) -> dict[str, Any]:
    def digest(label: str) -> str:
        return sha256(label.encode()).hexdigest()

    context_digest = digest("context")
    plan_digest = digest("plan")
    return seal_conditional_completion(
        {
            "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
            "creator": {
                "project": "sase",
                "run_id": "run-1",
                "agent_name": "acme",
            },
            "context": {
                "run_id": "run-1",
                "agent_id": "acme",
                "turn_nonce": "nonce-1",
                "plan_digest": plan_digest,
                "context_digest": context_digest,
                "obligation_ids": ["repo-main"],
            },
            "success_message": "Required checks passed.",
            "verification_command": command,
            "declaration": {
                "schema_version": 2,
                "context_digest": context_digest,
                "plan_digest": plan_digest,
                "payloads": [
                    {
                        "instance_id": "commit",
                        "payload": {
                            "repositories": [
                                {
                                    "repo_id": "repo-main",
                                    "action": "commit",
                                    "message": "fix: finish the change",
                                }
                            ],
                            "deferrals": [],
                        },
                    }
                ],
            },
            "observations": [
                {
                    "repo_id": "repo-main",
                    "kind": "main",
                    "name": "main",
                    "head": digest("head"),
                    "head_tree": digest("head-tree"),
                    "index_tree": digest("index-tree"),
                    "complete": True,
                    "paths": [
                        {
                            "path": "src/app.py",
                            "kind": "file",
                            "protected": False,
                            "foreign": False,
                        }
                    ],
                }
            ],
            "executors": [
                {
                    "instance_id": "commit",
                    "provider_ref": "builtin@commit",
                    "headless": True,
                    "durable_replay": True,
                    "requires_model": False,
                }
            ],
        }
    )


def _stage_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    cwd: str | None = None,
    workspace_num: int = 3,
    workspace_dir: str | None = None,
    starter_workspace_dir: str | None = None,
    starter_name: str = "acme",
    agent_session: str | None = "acme",
) -> list[str]:
    write_project_file(
        "proj",
        workspace_dir=workspace_dir,
        running_claims=[
            WorkspaceClaim(workspace_num, "ace-run", "acme", pid=os.getpid())
        ],
    )
    starter_meta: dict[str, object] = {
        "model": "claude-sonnet-5",
        "workspace_dir": starter_workspace_dir or workspace_dir or cwd or str(tmp_path),
        "workspace_num": workspace_num,
        "pid": os.getpid(),
        "cl_name": "acme",
    }
    if agent_session is not None:
        starter_meta["agent_session"] = agent_session
    if starter_name != "acme" and agent_session is not None:
        starter_meta.update(
            workflow_name=agent_session,
            role_suffix="--1",
            agent_session_role="member",
        )
    starter_dir = make_starter_agent(
        "proj", "20260812120000", starter_name, **starter_meta
    )
    monkeypatch.setenv("SASE_AGENT", "1")
    monkeypatch.setenv("SASE_AGENT_NAME", starter_name)
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", starter_dir)
    dirs = [starter_dir]
    patch_project_records(monkeypatch, dirs)
    return dirs


def test_staged_authored_checkpoint_survives_cli_file_removal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.continuation_capture import load_authored_checkpoint

    dirs = _stage_env(tmp_path, monkeypatch)
    source = tmp_path / "authored-checkpoint.yml"
    source.write_text(
        "objective: verify the staged change\nconstraints:\n  - keep the workspace\n",
        encoding="utf-8",
    )
    authored = load_authored_checkpoint(source)
    staged = stage_monitor(
        _request(
            tmp_path,
            checkpoint_ref=authored.content_ref,
            checkpoint_document=authored.payload,
        )
    )
    dirs.append(staged.record.artifacts_dir)
    source.write_text("objective: changed after staging\n", encoding="utf-8")
    source.unlink()

    payload = _load_staged_monitor_launch_payload(staged.record.artifacts_dir)
    claim = payload["workspace"]["claim_context"]
    frozen_ref = claim["checkpoint_content_ref"]
    frozen_path = Path(staged.record.artifacts_dir) / frozen_ref.removeprefix("local:")
    assert frozen_path.is_file()
    assert claim["checkpoint_content_required"] is True

    captured: dict[str, Any] = {}

    def fake_launch(context: Any, timer: Any) -> Any:
        del timer
        captured["request"] = context.request
        return staged.record

    monkeypatch.setattr("sase.monitor.start_stage.launch_monitor", fake_launch)
    launched = launch_from_persisted_payload(staged.record.artifacts_dir)

    assert launched.monitor_id == staged.record.monitor_id
    assert captured["request"].checkpoint_ref == authored.content_ref
    assert captured["request"].checkpoint_document == authored.payload


@pytest.mark.parametrize("damage", ["remove", "corrupt"])
def test_staged_authored_checkpoint_missing_or_corrupt_refuses_before_launch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    damage: str,
) -> None:
    from sase.continuation_capture import load_authored_checkpoint

    dirs = _stage_env(tmp_path, monkeypatch)
    source = tmp_path / "authored-checkpoint.yml"
    source.write_text("objective: preserve the stage\n", encoding="utf-8")
    authored = load_authored_checkpoint(source)
    staged = stage_monitor(
        _request(
            tmp_path,
            checkpoint_ref=authored.content_ref,
            checkpoint_document=authored.payload,
        )
    )
    dirs.append(staged.record.artifacts_dir)
    payload = _load_staged_monitor_launch_payload(staged.record.artifacts_dir)
    frozen_ref = payload["workspace"]["claim_context"]["checkpoint_content_ref"]
    frozen_path = Path(staged.record.artifacts_dir) / frozen_ref.removeprefix("local:")
    if damage == "remove":
        frozen_path.unlink()
    else:
        frozen_path.write_text("{broken json", encoding="utf-8")

    launched: list[bool] = []
    monkeypatch.setattr(
        "sase.monitor.start_stage.launch_monitor",
        lambda *_args, **_kwargs: launched.append(True),
    )
    with pytest.raises(MonitorError, match="staged authored checkpoint"):
        launch_from_persisted_payload(staged.record.artifacts_dir)
    assert launched == []


@pytest.mark.parametrize(
    ("starter_name", "agent_session", "expected_starter"),
    [
        ("acme", None, "acme--0"),
        ("acme--1", "acme", "acme--1"),
    ],
)
def test_staged_monitor_adoption_saves_real_response_and_exact_starter_parent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    starter_name: str,
    agent_session: str | None,
    expected_starter: str,
) -> None:
    from dataclasses import replace

    from sase.agent.staged_handoff import (
        read_staged_handoff,
        write_staged_handoff_response,
    )
    from sase.axe.run_agent_exec import LoopState
    from sase.axe.run_agent_exec_finalize import finalize_loop
    from sase.axe.run_agent_exec_retry import RetryTracker
    from sase.axe.run_agent_exec_staged import (
        STAGED_HANDOFF_ADOPTERS,
        StagedInlineContinuation,
    )
    from tests._axe_run_agent_exec_helpers import make_exec_ctx

    dirs = _stage_env(
        tmp_path,
        monkeypatch,
        starter_name=starter_name,
        agent_session=agent_session,
    )
    starter_dir = Path(dirs[0])
    original_meta = json.loads((starter_dir / "agent_meta.json").read_text())
    staged = stage_monitor(_request(tmp_path))
    dirs.append(staged.record.artifacts_dir)
    handoff = read_staged_handoff(starter_dir)
    assert handoff is not None
    write_staged_handoff_response(
        str(handoff["staged_id"]),
        "The provider's real final response.",
        artifacts_dir=str(starter_dir),
    )

    ctx = replace(
        make_exec_ctx(tmp_path, is_home_mode=False),
        artifacts_dir=str(starter_dir),
        agent_name=starter_name,
        agent_meta=original_meta,
        project_name="proj",
    )
    state = LoopState(
        current_prompt="Run the staged verification.",
        current_role_suffix="",
        current_artifacts_dir=str(starter_dir),
        loop_outcome="completed",
        sdd_spec_path=None,
        original_prompt="Run the staged verification.",
    )
    captured: dict[str, Any] = {}

    def fake_launch(context: Any, timer: Any) -> Any:
        del timer
        captured["context"] = context
        assert not (starter_dir / "done.json").exists()
        return staged.record

    monkeypatch.setattr("sase.monitor.start_stage.launch_monitor", fake_launch)
    outcome = STAGED_HANDOFF_ADOPTERS["monitor"](
        handoff,
        json.loads((starter_dir / "agent_meta.json").read_text()),
        StagedInlineContinuation(ctx=ctx, state=state),
        "The provider's real final response.",
    )
    assert outcome.outcome == "monitored"

    starter_meta = json.loads((starter_dir / "agent_meta.json").read_text())
    assert starter_meta["name"] == expected_starter
    assert state.saved_chat_paths
    chat_path = Path(state.saved_chat_paths[-1][1])
    chat = chat_path.read_text(encoding="utf-8")
    assert "The provider's real final response." in chat
    assert "# Monitor handoff" in chat
    assert "verify staging" in chat
    assert starter_meta["chat_path"] == str(chat_path)

    delta_files = list(
        (starter_dir / "continuation" / "records" / "agent_delta").glob("*.json")
    )
    assert len(delta_files) == 1
    delta = json.loads(delta_files[0].read_text(encoding="utf-8"))
    assert delta["status"] == "completed"
    assert delta["final_response_ref"]
    assert delta["handoff_checkpoint_ref"]

    monitor_context = captured["context"]
    starter_node_id = starter_meta["continuation_node_id"]
    assert monitor_context.request.parent_node_ids == (starter_node_id,)
    member_meta = json.loads(
        (Path(staged.record.artifacts_dir) / "agent_meta.json").read_text()
    )
    assert member_meta["continuation_parent_node_ids"] == [starter_node_id]
    assert member_meta["monitor_starter_agent"] == expected_starter

    state.loop_outcome = "monitored"
    result = finalize_loop(ctx, state, RetryTracker(retry_cfg=None), None)
    done = json.loads((starter_dir / "done.json").read_text(encoding="utf-8"))
    assert result.outcome == "monitored"
    assert done["response_path"] == str(chat_path)
    assert done["continuation"]["node_id"] == starter_node_id


def test_staged_monitor_rejects_foreign_persisted_starter_before_launch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dataclasses import replace

    from sase.agent.staged_handoff import StagedHandoffError
    from sase.axe.run_agent_exec import LoopState
    from sase.axe.run_agent_exec_staged import (
        STAGED_HANDOFF_ADOPTERS,
        StagedInlineContinuation,
    )
    from tests._axe_run_agent_exec_helpers import make_exec_ctx

    dirs = _stage_env(tmp_path, monkeypatch)
    starter_dir = Path(dirs[0])
    original_meta = json.loads((starter_dir / "agent_meta.json").read_text())
    staged = stage_monitor(_request(tmp_path))
    dirs.append(staged.record.artifacts_dir)
    handoff = read_staged_handoff(starter_dir)
    assert handoff is not None

    ctx = replace(
        make_exec_ctx(tmp_path, is_home_mode=False),
        artifacts_dir=str(starter_dir),
        agent_name="acme",
        agent_meta=original_meta,
        project_name="proj",
    )
    state = LoopState(
        current_prompt="Run the staged verification.",
        current_role_suffix="",
        current_artifacts_dir=str(starter_dir),
        loop_outcome="completed",
        sdd_spec_path=None,
        original_prompt="Run the staged verification.",
    )
    foreign_metadata = json.loads((starter_dir / "agent_meta.json").read_text())
    foreign_metadata["name"] = "outsider--0"
    launches: list[bool] = []
    monkeypatch.setattr(
        "sase.monitor.start_stage.launch_from_persisted_payload",
        lambda *_args, **_kwargs: launches.append(True),
    )

    with pytest.raises(StagedHandoffError, match="persisted agent identity"):
        STAGED_HANDOFF_ADOPTERS["monitor"](
            handoff,
            foreign_metadata,
            StagedInlineContinuation(ctx=ctx, state=state),
            "The provider's real final response.",
        )

    assert launches == []
    member_meta = json.loads(
        (Path(staged.record.artifacts_dir) / "agent_meta.json").read_text()
    )
    assert member_meta["monitor_state"] == "staged"


@pytest.mark.parametrize("fail_fix", [False, True])
def test_staged_monitor_waits_for_real_finalizer_controller(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fail_fix: bool,
) -> None:
    import os
    from dataclasses import replace

    from sase.agent.staged_handoff import write_staged_handoff_response
    from sase.axe.run_agent_exec import LoopState
    from sase.axe.run_agent_exec_staged import (
        StagedInlineContinuation,
        dispatch_completed_staged_handoff,
    )
    from sase.core.tool_run import tool_run_show
    from sase.finalizers.plan import resolve_and_persist_finalizer_plan
    from sase.macro.directives import PromptDirectives
    from tests._axe_run_agent_exec_helpers import make_exec_ctx
    from tests.finalizers_live_e2e_test_helpers import (
        command_instance,
        commit_instance,
        config_for,
        use_config,
    )
    from tests.finalizers_protocol_harness_test_helpers import (
        dirty_repo,
        prepare_agent_env,
        run_controller,
    )
    from tests.staged_handoff_acceptance_helpers import patch_dirty_for_settlement

    root = _sandbox_project(tmp_path)
    monkeypatch.setattr(
        "sase.monitor.start_prepare.get_monitor_tool_wrap", lambda: "verify"
    )
    dirs = _stage_env(
        tmp_path,
        monkeypatch,
        cwd=str(root),
        workspace_dir=str(root),
        starter_workspace_dir=str(root),
    )
    starter_dir = Path(dirs[0])
    prepare_agent_env(monkeypatch, starter_dir, root)
    monkeypatch.setenv("SASE_AGENT_TIMESTAMP", "20260812120000")
    monkeypatch.setenv("SASE_AGENT_NAME", "acme")

    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    events_path = tmp_path / "finalizer-events"
    fake_just = fake_bin / "just"
    fake_just.write_text(
        "#!/bin/sh\n"
        'printf \'%s\\n\' "$1" >> "$SASE_FINALIZER_EVENTS"\n'
        '[ "${SASE_FINALIZER_FAIL:-}" != "$1" ]\n',
        encoding="utf-8",
    )
    fake_just.chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake_bin}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("SASE_FINALIZER_EVENTS", str(events_path))
    if fail_fix:
        monkeypatch.setenv("SASE_FINALIZER_FAIL", "fix")
    else:
        monkeypatch.delenv("SASE_FINALIZER_FAIL", raising=False)

    def observed_command(
        instance_id: str,
        command: list[str],
        *,
        after: tuple[str, ...] = (),
    ) -> Any:
        instance = command_instance(instance_id, command, after=after)
        return replace(
            instance,
            config={
                **instance.config,
                "env": ["SASE_FINALIZER_EVENTS", "SASE_FINALIZER_FAIL"],
            },
        )

    config = config_for(
        {
            "fix": observed_command("fix", ["just", "fix"]),
            "commit": replace(commit_instance(), after=("fix",), refusal="defer"),
            "audit": observed_command("audit", ["just", "audit"], after=("commit",)),
        },
        ("fix", "commit", "audit"),
    )
    use_config(monkeypatch, config)
    dirty = {"repos": (dirty_repo(root),)}
    patch_dirty_for_settlement(monkeypatch, root, dirty)

    staged = stage_monitor(
        _request(
            tmp_path,
            cwd=str(root),
            profile="verify",
        )
    )
    dirs.append(staged.record.artifacts_dir)
    write_staged_handoff_response(
        staged.staged_id,
        "The provider's real final response.",
        artifacts_dir=str(starter_dir),
    )
    resolve_and_persist_finalizer_plan(
        PromptDirectives(), artifacts_dir=str(starter_dir)
    )

    original_meta = json.loads((starter_dir / "agent_meta.json").read_text())
    ctx = replace(
        make_exec_ctx(tmp_path, is_home_mode=False),
        artifacts_dir=str(starter_dir),
        agent_name="acme",
        agent_meta=original_meta,
        project_name="proj",
    )
    state = LoopState(
        current_prompt="Run the staged verification.",
        current_role_suffix="",
        current_artifacts_dir=str(starter_dir),
        loop_outcome="completed",
        sdd_spec_path=None,
        original_prompt="Run the staged verification.",
    )
    continuation = StagedInlineContinuation(ctx=ctx, state=state)
    launches: list[str] = []

    def fake_launch(context: Any, timer: Any) -> Any:
        del timer
        assert events_path.read_text(encoding="utf-8").splitlines() == (
            ["fix"] if fail_fix else ["fix", "audit"]
        )
        launches.append("launch")
        return staged.record

    monkeypatch.setattr("sase.monitor.start_stage.launch_monitor", fake_launch)

    if fail_fix:
        with pytest.raises(RuntimeError, match="failed on attempt"):
            run_controller(starter_dir)
        assert events_path.read_text(encoding="utf-8").splitlines() == ["fix"]
    else:
        result = run_controller(starter_dir)
        assert result.content == "done"
        assert events_path.read_text(encoding="utf-8").splitlines() == [
            "fix",
            "audit",
        ]
        accepted = json.loads(
            (starter_dir / "final_submission.json").read_text(encoding="utf-8")
        )
        assert accepted["synthesized"]["kind"] == "handoff_carry"
        assert accepted["synthesized"]["source"] == "host"

    dispatch = dispatch_completed_staged_handoff(str(starter_dir), continuation)

    if fail_fix:
        assert dispatch is not None and not dispatch.adopted
        assert launches == []
        member_meta = json.loads(
            (Path(staged.record.artifacts_dir) / "agent_meta.json").read_text()
        )
        assert member_meta["monitor_stage_held"] is True
        shown = tool_run_show(staged.record.tool_run_id or "")["run"]
        assert shown["state"] != "created"
        assert shown.get("proc") is None
    else:
        assert dispatch is not None and dispatch.adopted
        assert launches == ["launch"]


def test_stage_persists_payload_and_reconstructs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dirs = _stage_env(tmp_path, monkeypatch)
    staged = stage_monitor(_request(tmp_path))
    dirs.append(staged.record.artifacts_dir)

    assert staged.replayed is False
    assert staged.record.monitor_state == "staged"
    assert staged.record.pid is None
    payload_path = launch_payload_path(staged.record.artifacts_dir)
    assert payload_path.is_file()
    loaded = _load_staged_monitor_launch_payload(staged.record.artifacts_dir)
    assert loaded["schema_version"] == staged_monitor_launch_payload_schema_version()
    assert loaded["staged_id"] == staged.staged_id
    assert loaded["monitor_id"] == staged.record.monitor_id
    assert loaded["cwd"] == str(tmp_path)
    assert loaded["workspace"]["mode"] == "inherit"
    disk = record_from_disk(staged.record.artifacts_dir)
    assert disk.agent_meta is not None
    assert disk.agent_meta.agent_session_turn is not None
    assert disk.agent_meta.agent_session_turn.state == "staged"
    handoff = read_staged_handoff(dirs[0])
    assert handoff is not None
    assert handoff["kind"] == "monitor"
    assert handoff["staged_id"] == staged.staged_id
    assert handoff["successor_workspace"] == "inherit"
    assert handoff["carry_allowed"] is True


def test_stage_blocks_lane_and_replays_identical_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dirs = _stage_env(tmp_path, monkeypatch)
    first = stage_monitor(_request(tmp_path, command="sleep 30"))
    dirs.append(first.record.artifacts_dir)

    with pytest.raises(MonitorAlreadyRunningError):
        stage_monitor(_request(tmp_path, command="true"))
    with pytest.raises(MonitorAlreadyRunningError):
        start_monitor(_request(tmp_path, command="true"))

    replayed = stage_monitor(_request(tmp_path, command="sleep 30"))
    assert replayed.replayed is True
    assert replayed.record.monitor_id == first.record.monitor_id
    assert replayed.staged_id == first.staged_id


def test_nested_cwd_and_explicit_lane_freeze_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_WORKSPACE_ROOT", str(tmp_path / "managed"))
    primary = tmp_path / "primary"
    primary.mkdir()
    workspace_dir = register_workspace_checkout(primary, 10)
    nested = Path(workspace_dir) / "sase" / "repos" / "external" / "gh" / "sase-core"
    nested.mkdir(parents=True)
    dirs = _stage_env(
        tmp_path,
        monkeypatch,
        cwd=str(nested),
        workspace_num=10,
        workspace_dir=str(primary),
        starter_workspace_dir=workspace_dir,
    )
    staged = stage_monitor(_request(tmp_path, cwd=str(nested)))
    dirs.append(staged.record.artifacts_dir)
    payload = _load_staged_monitor_launch_payload(staged.record.artifacts_dir)
    claim = payload["workspace"]["claim_context"]
    assert payload["cwd"] == str(nested)
    assert payload["lane"] == "acme"
    assert int(claim["workspace_num"]) == 10


def test_tool_run_id_is_stable_from_stage_to_launch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _sandbox_project(tmp_path)
    monkeypatch.setattr(
        "sase.monitor.start_prepare.get_monitor_tool_wrap", lambda: "verify"
    )
    dirs = _stage_env(tmp_path, monkeypatch, cwd=str(root), workspace_dir=str(root))
    staged = stage_monitor(
        _request(tmp_path, command="true", cwd=str(root), profile="verify")
    )
    dirs.append(staged.record.artifacts_dir)
    run_id = staged.record.tool_run_id
    assert run_id
    payload = _load_staged_monitor_launch_payload(staged.record.artifacts_dir)
    assert payload["resources"]["tool_run_id"] == run_id
    record = launch_from_persisted_payload(staged.record.artifacts_dir)
    try:
        assert record.tool_run_id == run_id
        assert record.monitor_state == "running"
        assert record.monitor_id == staged.record.monitor_id
    finally:
        wait_for_done(record.artifacts_dir, timeout=30.0)


def test_prepared_stage_reserves_without_binding_then_binds_at_spawn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dirs = _stage_env(tmp_path, monkeypatch)
    prepared = persist_prepared_completion(
        _sealed_intent(["just", "check"]), artifacts_dir=dirs[0]
    )

    staged = stage_monitor(
        _request(tmp_path, command="just check", completion_ref=prepared.intent_ref)
    )
    dirs.append(staged.record.artifacts_dir)
    intent = load_prepared_completion(prepared.intent_ref, artifacts_dir=dirs[0])
    assert intent["status"] == "prepared"

    payload = _load_staged_monitor_launch_payload(staged.record.artifacts_dir)
    reservation = payload["resources"]["prepared_reservation"]
    assert reservation == {
        "staged_id": staged.staged_id,
        "monitor_id": staged.record.monitor_id,
        "request_fingerprint": staged.record.request_fingerprint,
        "command": ["just", "check"],
    }
    handoff = read_staged_handoff(dirs[0])
    assert handoff is not None
    assert handoff["payload"]["prepared_reservation"] == reservation
    assert handoff["carry_allowed"] is False

    # A direct/immediate consumer cannot take an intent reserved for this stage.
    with pytest.raises(
        FinalizerDeclarationError, match="reserved for a staged monitor"
    ):
        bind_prepared_completion(
            prepared.intent_ref,
            monitor_id="monitor-competitor",
            command=["just", "check"],
            request_fingerprint="competitor-fingerprint",
            artifacts_dir=dirs[0],
        )

    fake_pid = os.getpid() + 10000

    def _fake_submit(
        *args: Any, after_spawn: Any, after_ack: Any, **kwargs: Any
    ) -> Any:
        del args, kwargs
        after_spawn(SimpleNamespace(pid=fake_pid))
        proc = SimpleNamespace(pid=fake_pid, supervisor_id="supervisor-fake")
        after_ack(proc)
        return proc

    monkeypatch.setattr("sase.monitor.start_launch.submit_proc_request", _fake_submit)
    monkeypatch.setattr(
        "sase.monitor.start_launch.claim_monitor_workspace",
        lambda *args, **kwargs: SimpleNamespace(
            result=SimpleNamespace(success=True), starter_claim=None
        ),
    )

    record = launch_from_persisted_payload(staged.record.artifacts_dir)
    assert record.monitor_state == "running"
    bound = load_prepared_completion(prepared.intent_ref, artifacts_dir=dirs[0])
    assert bound["status"] == "bound"
    assert bound["binding"]["monitor_id"] == staged.record.monitor_id
    assert bound["binding"]["bound_command"] == ["just", "check"]
    assert record.monitor_state == "running"


def test_prepared_stage_rejects_wrong_command_before_publish(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dirs = _stage_env(tmp_path, monkeypatch)
    prepared = persist_prepared_completion(
        _sealed_intent(["just", "check"]), artifacts_dir=dirs[0]
    )

    with pytest.raises(MonitorError, match="does not match"):
        stage_monitor(
            _request(
                tmp_path,
                command="just check-full",
                completion_ref=prepared.intent_ref,
            )
        )

    assert (
        load_prepared_completion(prepared.intent_ref, artifacts_dir=dirs[0])["status"]
        == "prepared"
    )
    assert _read_reservations(dirs[0]) == {}
    assert read_staged_handoff(dirs[0]) is None


def test_prepared_stage_ack_failure_rolls_back_binding_and_reservation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dirs = _stage_env(tmp_path, monkeypatch)
    prepared = persist_prepared_completion(
        _sealed_intent(["just", "check"]), artifacts_dir=dirs[0]
    )
    staged = stage_monitor(
        _request(tmp_path, command="just check", completion_ref=prepared.intent_ref)
    )
    dirs.append(staged.record.artifacts_dir)

    def _fail_submit(*args: Any, **kwargs: Any) -> Any:
        del args, kwargs
        raise ProcSubmitError("ack failed")

    monkeypatch.setattr("sase.monitor.start_launch.submit_proc_request", _fail_submit)
    with pytest.raises(MonitorError, match="ack failed"):
        launch_from_persisted_payload(staged.record.artifacts_dir)

    assert (
        load_prepared_completion(prepared.intent_ref, artifacts_dir=dirs[0])["status"]
        == "prepared"
    )
    assert _read_reservations(dirs[0]) == {}


@pytest.mark.parametrize("resource", ["owned", "joined", "prepared"])
def test_failed_finalization_releases_monitor_resources_and_keeps_stage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, resource: str
) -> None:
    from unittest.mock import Mock

    from sase.axe.run_agent_exec_staged import (
        StagedInlineContinuation,
        dispatch_completed_staged_handoff,
    )
    from sase.monitor.staged_owner import read_staged_owner_index
    from tests.staged_handoff_acceptance_helpers import make_continuation

    root = _sandbox_project(tmp_path)
    if resource == "prepared":
        (root / "sase" / "sase.yml").write_text(
            SANDBOX_CATALOG.replace('["true"]', '["just", "check"]'),
            encoding="utf-8",
        )
    monkeypatch.setattr(
        "sase.monitor.start_prepare.get_monitor_tool_wrap", lambda: "verify"
    )
    dirs = _stage_env(tmp_path, monkeypatch, cwd=str(root), workspace_dir=str(root))
    joined_run = (
        reserve_detached_run("--", "true", agent="acme")
        if resource == "joined"
        else None
    )
    prepared = (
        persist_prepared_completion(
            _sealed_intent(["just", "check"]), artifacts_dir=dirs[0]
        )
        if resource == "prepared"
        else None
    )
    staged = stage_monitor(
        _request(
            tmp_path,
            cwd=str(root),
            command="just check" if prepared else "true",
            join_run_id=joined_run,
            profile="verify" if resource != "joined" else None,
            completion_ref=prepared.intent_ref if prepared else None,
        )
    )
    dirs.append(staged.record.artifacts_dir)
    starter = Path(dirs[0])
    before = read_staged_handoff(dirs[0])
    (starter / "finalizer_result.json").write_text(
        json.dumps({"status": "failed", "instances": []}), encoding="utf-8"
    )
    submit = Mock(side_effect=AssertionError("held monitor must not launch"))
    monkeypatch.setattr("sase.monitor.start_launch.submit_proc_request", submit)
    continuation = StagedInlineContinuation(*make_continuation(tmp_path, starter))

    result = dispatch_completed_staged_handoff(dirs[0], continuation)

    assert result is not None and not result.adopted
    submit.assert_not_called()
    assert read_staged_handoff(dirs[0]) == before
    meta = json.loads(
        (Path(staged.record.artifacts_dir) / "agent_meta.json").read_text()
    )
    assert meta.get("monitor_stage_held") is True
    assert read_staged_owner_index(staged.record.monitor_id) is None
    shown = tool_run_show(staged.record.tool_run_id)["run"]
    if resource == "joined":
        assert shown["state"] == "created"
        assert "staged_join_reservation" not in shown
        assert "join" not in shown
    else:
        assert shown["state"] != "created"
        assert shown.get("proc") is None
    if prepared:
        assert _read_reservations(dirs[0]) == {}
        assert (
            load_prepared_completion(prepared.intent_ref, artifacts_dir=dirs[0])[
                "status"
            ]
            == "prepared"
        )

    # Repeated failure processing must retain the recovery evidence too.
    again = dispatch_completed_staged_handoff(dirs[0], continuation)
    assert again is not None and not again.adopted
    assert read_staged_handoff(dirs[0]) == before


@pytest.mark.parametrize(
    ("starter_name", "agent_session", "expected_starter"),
    [
        ("acme", None, "acme--0"),
        ("acme--1", "acme", "acme--1"),
    ],
)
def test_reserved_join_that_settles_before_adoption_is_consumed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    starter_name: str,
    agent_session: str | None,
    expected_starter: str,
) -> None:
    from tests.monitor._join_helpers import settle_detached_run

    dirs = _stage_env(
        tmp_path,
        monkeypatch,
        starter_name=starter_name,
        agent_session=agent_session,
    )
    run_id = reserve_detached_run("--", "true", agent=starter_name)
    staged = stage_monitor(_request(tmp_path, join_run_id=run_id))
    dirs.append(staged.record.artifacts_dir)
    starter_meta = json.loads((Path(dirs[0]) / "agent_meta.json").read_text())
    assert starter_meta["name"] == expected_starter
    settle_detached_run(
        run_id,
        state="succeeded",
        exit_code=0,
        terminal_cause="exited",
    )

    record = launch_from_persisted_payload(staged.record.artifacts_dir)
    assert tool_run_show(run_id)["run"]["join"]["id"] == record.monitor_id
    assert record.tool_run_id == run_id
    done = wait_for_done(record.artifacts_dir, timeout=30.0)
    assert done["monitor_state"] == "completed"


def test_launcher_exit_keeps_pending_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.tool.liveness import reconcile_unsettled_tool_runs

    root = _sandbox_project(tmp_path)
    monkeypatch.setattr(
        "sase.monitor.start_prepare.get_monitor_tool_wrap", lambda: "verify"
    )
    dirs = _stage_env(tmp_path, monkeypatch, cwd=str(root), workspace_dir=str(root))
    staged = stage_monitor(
        _request(tmp_path, command="true", cwd=str(root), profile="verify")
    )
    dirs.append(staged.record.artifacts_dir)
    run_id = staged.record.tool_run_id
    assert run_id
    shown = tool_run_show(run_id)["run"]
    fact = observe_owner_fact(shown)
    assert fact is not None
    assert fact["state"] == "pending"
    reconcile_unsettled_tool_runs()
    after = tool_run_show(run_id)["run"]
    assert after["state"] == "created"
    assert after.get("terminal_cause") != "launch_failed"
    cleanup_staged_monitor(staged.record.artifacts_dir)


def test_ack_failure_rolls_back_staged_launch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dirs = _stage_env(tmp_path, monkeypatch)
    staged = stage_monitor(_request(tmp_path))
    dirs.append(staged.record.artifacts_dir)

    def _fail_submit(*args: Any, **kwargs: Any) -> Any:
        del args, kwargs
        raise ProcSubmitError("ack failed")

    monkeypatch.setattr("sase.monitor.start_launch.submit_proc_request", _fail_submit)
    with pytest.raises(MonitorError, match="ack failed"):
        launch_from_persisted_payload(staged.record.artifacts_dir)
    meta = json.loads(
        (Path(staged.record.artifacts_dir) / "agent_meta.json").read_text()
    )
    assert meta["monitor_state"] == "failed"
    assert meta.get("monitor_stage_held") is True
    assert read_staged_handoff(dirs[0]) is not None
    assert (Path(staged.record.artifacts_dir) / "done.json").is_file()


def test_cleanup_at_resource_boundaries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dirs = _stage_env(tmp_path, monkeypatch)
    bare = stage_monitor(_request(tmp_path, command="true"))
    dirs.append(bare.record.artifacts_dir)
    starter = dirs[0]
    result = cleanup_staged_monitor(bare.record.artifacts_dir)
    assert result.held is False
    assert result.member_state == "failed"
    assert result.settled_tool_run_id is None
    assert not (Path(starter) / STAGED_HANDOFF_FILENAME).exists()
    again = cleanup_staged_monitor(bare.record.artifacts_dir)
    assert again.member_state in {"failed", "staged"}


def test_cleanup_releases_staged_join_without_stopping_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dirs = _stage_env(tmp_path, monkeypatch)
    run_id = reserve_detached_run("--", "true", agent="acme")
    staged = stage_monitor(_request(tmp_path, join_run_id=run_id))
    dirs.append(staged.record.artifacts_dir)
    assert staged.record.tool_run_id == run_id
    result = cleanup_staged_monitor(staged.record.artifacts_dir)
    assert result.released_join is True
    assert result.settled_tool_run_id is None
    shown = tool_run_show(run_id)["run"]
    assert shown["state"] == "created"


def test_held_cleanup_keeps_outer_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _sandbox_project(tmp_path)
    monkeypatch.setattr(
        "sase.monitor.start_prepare.get_monitor_tool_wrap", lambda: "verify"
    )
    dirs = _stage_env(tmp_path, monkeypatch, cwd=str(root), workspace_dir=str(root))
    staged = stage_monitor(
        _request(tmp_path, command="true", cwd=str(root), profile="verify")
    )
    dirs.append(staged.record.artifacts_dir)
    run_id = staged.record.tool_run_id
    result = cleanup_staged_monitor(staged.record.artifacts_dir, held=True)
    assert result.held is True
    assert result.settled_tool_run_id == run_id
    assert (Path(dirs[0]) / STAGED_HANDOFF_FILENAME).is_file()
    meta = json.loads(
        (Path(staged.record.artifacts_dir) / "agent_meta.json").read_text()
    )
    assert meta["monitor_state"] == "staged"
    assert meta.get("monitor_stage_held") is True
    shown = tool_run_show(run_id)["run"]
    assert shown["state"] != "created"
    with pytest.raises(MonitorError, match="canceled run"):
        launch_from_persisted_payload(staged.record.artifacts_dir)


def test_launch_from_persisted_payload_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dirs = _stage_env(tmp_path, monkeypatch)
    staged = stage_monitor(_request(tmp_path))
    dirs.append(staged.record.artifacts_dir)
    record = launch_from_persisted_payload(staged.record.artifacts_dir)
    try:
        assert record.monitor_state == "running"
        assert record.pid is not None
        done = wait_for_done(record.artifacts_dir, timeout=30.0)
        assert done["monitor_state"] == "completed"
    except Exception:
        wait_for_done(record.artifacts_dir, timeout=10.0)
        raise


def test_immediate_start_still_launches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stage_env(tmp_path, monkeypatch)
    record = start_monitor(_request(tmp_path))
    try:
        assert record.monitor_state == "running"
        done = wait_for_done(record.artifacts_dir, timeout=30.0)
        assert done["monitor_state"] == "completed"
    except Exception:
        wait_for_done(record.artifacts_dir, timeout=10.0)
        raise
