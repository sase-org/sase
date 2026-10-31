"""Prepared-completion reservation, bind-at-spawn, and finalizer wait."""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from sase.agent.staged_handoff import read_staged_handoff
from sase.finalizers.declaration import FinalizerDeclarationError
from sase.finalizers.prepare import (
    bind_prepared_completion,
    load_prepared_completion,
    persist_prepared_completion,
)
from sase.monitor.models import MonitorError
from sase.monitor.start_stage import (
    launch_from_persisted_payload,
    stage_monitor,
)
from sase.monitor.start_stage_adopt import _load_staged_monitor_launch_payload
from sase.procs.submission import ProcSubmitError

from ._start_stage import (
    read_reservations,
    sandbox_home as sandbox_home,
    sandbox_project,
    sealed_intent,
    stage_env,
    stage_request,
)

__all__ = [
    "test_prepared_stage_ack_failure_rolls_back_binding_and_reservation",
    "test_prepared_stage_rejects_wrong_command_before_publish",
    "test_prepared_stage_reserves_without_binding_then_binds_at_spawn",
    "test_staged_monitor_waits_for_real_finalizer_controller",
]


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

    root = sandbox_project(tmp_path)
    monkeypatch.setattr(
        "sase.monitor.start_prepare.get_monitor_tool_wrap", lambda: "verify"
    )
    dirs = stage_env(
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
        stage_request(
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

    monkeypatch.setattr("sase.monitor.start_stage_adopt.launch_monitor", fake_launch)

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


def test_prepared_stage_reserves_without_binding_then_binds_at_spawn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dirs = stage_env(tmp_path, monkeypatch)
    prepared = persist_prepared_completion(
        sealed_intent(["just", "check"]), artifacts_dir=dirs[0]
    )

    staged = stage_monitor(
        stage_request(
            tmp_path, command="just check", completion_ref=prepared.intent_ref
        )
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
    dirs = stage_env(tmp_path, monkeypatch)
    prepared = persist_prepared_completion(
        sealed_intent(["just", "check"]), artifacts_dir=dirs[0]
    )

    with pytest.raises(MonitorError, match="does not match"):
        stage_monitor(
            stage_request(
                tmp_path,
                command="just check-full",
                completion_ref=prepared.intent_ref,
            )
        )

    assert (
        load_prepared_completion(prepared.intent_ref, artifacts_dir=dirs[0])["status"]
        == "prepared"
    )
    assert read_reservations(dirs[0]) == {}
    assert read_staged_handoff(dirs[0]) is None


def test_prepared_stage_ack_failure_rolls_back_binding_and_reservation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dirs = stage_env(tmp_path, monkeypatch)
    prepared = persist_prepared_completion(
        sealed_intent(["just", "check"]), artifacts_dir=dirs[0]
    )
    staged = stage_monitor(
        stage_request(
            tmp_path, command="just check", completion_ref=prepared.intent_ref
        )
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
    assert read_reservations(dirs[0]) == {}
