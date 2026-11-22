"""Runner-side lean-wait handoff and return tests."""

from __future__ import annotations

import json
import os
import signal
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from sase.axe import (
    run_agent_lean_wait,
    run_agent_runner,
    run_agent_runner_lean_wait as lean_handoff,
    run_agent_runner_refresh as refresh,
)
from sase.axe.run_agent_runner_state import RunnerRunState
from sase.agent.multi_prompt_macros import read_local_macros_path
from sase.agent._user_kill_intent import write_user_kill_intent
from sase.bead.claims import (
    BeadClaimReleaseOutcome,
    write_bead_claim_marker,
)
from sase.env_contracts import (
    SASE_RUNNER_CODE_REFRESHED_ENV,
    SASE_RUNNER_LEAN_WAIT_ENV,
    SASE_RUNNER_LEAN_WAIT_RESULT_ENV,
    SASE_RUNNER_LEAN_WAIT_SPEC_ENV,
)
from sase.macro.models import Macro


def test_handoff_builds_contract_and_execs_waiter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prompt_file = tmp_path / "prompt.md"
    prompt_file.write_text("old prompt", encoding="utf-8")
    monkeypatch.delenv(SASE_RUNNER_LEAN_WAIT_ENV, raising=False)
    monkeypatch.delenv(SASE_RUNNER_LEAN_WAIT_SPEC_ENV, raising=False)
    monkeypatch.delenv(SASE_RUNNER_CODE_REFRESHED_ENV, raising=False)
    observed: dict[str, object] = {}

    def validate(spec: dict[str, object]) -> None:
        observed["spec"] = spec

    def exec_waiter(
        path: str,
        argv: list[str],
        *,
        before_exec: object,
    ) -> None:
        assert callable(before_exec) and before_exec()
        observed["exec"] = (path, argv)
        observed["env_spec"] = json.loads(os.environ[SASE_RUNNER_LEAN_WAIT_SPEC_ENV])
        observed["refreshed"] = os.environ[SASE_RUNNER_CODE_REFRESHED_ENV]

    with (
        patch(
            "sase.axe.run_agent_runner_lean_wait.importlib.util.find_spec",
            return_value=SimpleNamespace(origin=str(tmp_path / "waiter.py")),
        ),
        patch(
            "sase.axe.wait_checks_heartbeat.wait_checks_heartbeat_path",
            return_value=tmp_path / "heartbeat",
        ),
        patch(
            "sase.axe.run_agent_lean_wait.validate_lean_wait_spec",
            side_effect=validate,
        ),
        patch(
            "sase.axe.run_agent_runner_lean_wait.prepare_runner_exec_handoff",
            wraps=refresh.prepare_runner_exec_handoff,
        ) as prepare,
        patch(
            "sase.axe.run_agent_runner_lean_wait.execv_with_sigterm_mask",
            side_effect=exec_waiter,
        ),
        patch("sase.axe.run_agent_runner_lean_wait.was_killed", return_value=False),
        patch.object(lean_handoff.os, "name", "posix"),
        patch.object(lean_handoff.sys, "executable", "/venv/bin/python"),
        patch.object(lean_handoff.sys, "argv", ["runner.py", "--workspace-num", "7"]),
    ):
        handed_off = lean_handoff.try_handoff_to_lean_waiter(
            "dependency",
            None,
            100.0,
            artifacts_dir=str(tmp_path / "artifacts"),
            artifacts_timestamp="20261122010101",
            project_name="proj",
            prompt_file=str(prompt_file),
            submitted_prompt="%wait:dependency\nDo work\n",
            agent_name="builder.w0",
            local_macros=None,
            wait_beads=[],
        )

    assert handed_off is True
    assert observed["spec"] == observed["env_spec"]
    spec = observed["spec"]
    assert isinstance(spec, dict)
    assert spec["runner_argv"] == [
        "/venv/bin/python",
        "runner.py",
        "--workspace-num",
        "7",
    ]
    assert spec["heartbeat_path"] == str(tmp_path / "heartbeat")
    assert spec["mode"] == "dependency"
    assert spec["deadline_epoch"] is None
    assert observed["exec"] == (
        "/venv/bin/python",
        ["/venv/bin/python", str(tmp_path / "waiter.py"), "20261122010101"],
    )
    assert observed["refreshed"] == "1"
    assert prompt_file.read_text(encoding="utf-8") == "%wait:dependency\nDo work\n"
    prepare.assert_called_once()
    assert prepare.call_args.kwargs["local_macros_directory"] == str(
        tmp_path / "artifacts"
    )


def test_exec_failure_restores_prompt_environment_and_spec(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prompt_file = tmp_path / "prompt.md"
    prompt_file.write_text("old prompt", encoding="utf-8")
    monkeypatch.setenv(SASE_RUNNER_LEAN_WAIT_SPEC_ENV, "old-spec")
    monkeypatch.delenv(SASE_RUNNER_CODE_REFRESHED_ENV, raising=False)
    monkeypatch.delenv(SASE_RUNNER_LEAN_WAIT_ENV, raising=False)

    with (
        patch(
            "sase.axe.run_agent_runner_lean_wait.importlib.util.find_spec",
            return_value=SimpleNamespace(origin=str(tmp_path / "waiter.py")),
        ),
        patch(
            "sase.axe.wait_checks_heartbeat.wait_checks_heartbeat_path",
            return_value=tmp_path / "heartbeat",
        ),
        patch("sase.axe.run_agent_lean_wait.validate_lean_wait_spec"),
        patch(
            "sase.axe.run_agent_runner_lean_wait.execv_with_sigterm_mask",
            side_effect=OSError("exec denied"),
        ),
        patch.object(lean_handoff.os, "name", "posix"),
    ):
        handed_off = lean_handoff.try_handoff_to_lean_waiter(
            "until",
            200.0,
            100.0,
            artifacts_dir=str(tmp_path / "artifacts"),
            artifacts_timestamp="20261122010101",
            project_name=None,
            prompt_file=str(prompt_file),
            submitted_prompt="new prompt",
            agent_name=None,
            local_macros=None,
            wait_beads=[],
        )

    assert handed_off is False
    assert prompt_file.read_text(encoding="utf-8") == "old prompt"
    assert os.environ[SASE_RUNNER_LEAN_WAIT_SPEC_ENV] == "old-spec"
    assert SASE_RUNNER_CODE_REFRESHED_ENV not in os.environ


def test_prepared_macros_live_under_durable_artifacts_and_rollback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prompt_file = tmp_path / "managed-tmp" / "prompt.md"
    prompt_file.parent.mkdir()
    prompt_file.write_text("old prompt", encoding="utf-8")
    artifacts = tmp_path / "artifacts"
    monkeypatch.delenv("SASE_AGENT_LOCAL_MACROS", raising=False)
    monkeypatch.delenv(SASE_RUNNER_CODE_REFRESHED_ENV, raising=False)

    prepared = refresh.prepare_runner_exec_handoff(
        prompt_file=str(prompt_file),
        submitted_prompt="new prompt",
        local_macros={"local": Macro(name="local", content="body")},
        local_macros_directory=str(artifacts),
    )

    assert prepared is not None
    macros_path = read_local_macros_path(os.environ)
    assert macros_path is not None
    assert Path(macros_path).parent == artifacts
    assert (
        json.loads(Path(macros_path).read_text(encoding="utf-8"))["local"]["content"]
        == "body"
    )
    assert prompt_file.read_text(encoding="utf-8") == "new prompt"

    prepared.rollback()

    assert prompt_file.read_text(encoding="utf-8") == "old prompt"
    assert read_local_macros_path(os.environ) is None
    assert not Path(macros_path).exists()
    assert SASE_RUNNER_CODE_REFRESHED_ENV not in os.environ


def test_return_bootstraps_from_durable_prompt_and_macros_after_tmp_expiry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.agent.multi_prompt_macros import deserialize_local_macros
    from sase.axe.run_agent_runner_bootstrap import _load_submitted_prompt
    from sase.axe.run_agent_runner_setup import write_submitted_prompt_artifact

    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    prompt_file = tmp_path / "managed-tmp" / "prompt.md"
    prompt_file.parent.mkdir()
    submitted = "%wait:dependency\n#_local finish the task\n"
    write_submitted_prompt_artifact(str(artifacts), submitted)
    monkeypatch.delenv(SASE_RUNNER_CODE_REFRESHED_ENV, raising=False)
    monkeypatch.delenv("SASE_AGENT_LOCAL_MACROS", raising=False)

    prepared = refresh.prepare_runner_exec_handoff(
        prompt_file=str(prompt_file),
        submitted_prompt=submitted,
        local_macros={"_local": Macro(name="_local", content="durable body")},
        local_macros_directory=str(artifacts),
    )
    assert prepared is not None
    prompt_file.unlink()
    monkeypatch.setenv(SASE_RUNNER_CODE_REFRESHED_ENV, "1")
    state = RunnerRunState(
        cl_name="durable-return",
        project_file=str(tmp_path / "project.sase"),
        prompt_file=str(prompt_file),
        output_path=str(tmp_path / "output.log"),
        workflow_name="ace(run)-20261122010101",
        timestamp="20261122010101",
        update_target="",
        is_home_mode=False,
        workspace_dir=str(tmp_path / "workspace"),
        workspace_num=7,
        project_name="proj",
        artifacts_timestamp="20261122010101",
        artifacts_dir=str(artifacts),
    )

    _load_submitted_prompt(state)

    macros_path = read_local_macros_path(os.environ)
    assert state.prompt == state.submitted_prompt == submitted
    assert macros_path is not None
    assert Path(macros_path).parent == artifacts
    assert deserialize_local_macros(macros_path)["_local"].content == "durable body"


def test_execv_masks_sigterm_and_unblocks_after_failure() -> None:
    import signal

    from unittest.mock import Mock

    masks = Mock(return_value=set())
    with (
        patch.object(refresh.signal, "pthread_sigmask", side_effect=masks),
        patch.object(refresh.os, "execv", side_effect=OSError("exec failed")),
        pytest.raises(OSError, match="exec failed"),
    ):
        refresh.execv_with_sigterm_mask("python", ["python", "runner.py"])

    assert [call.args[0] for call in masks.call_args_list] == [
        signal.SIG_BLOCK,
        signal.SIG_SETMASK,
    ]


def test_handled_kill_during_forward_handoff_rolls_back_all_staged_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.agent.multi_prompt_macros import LOCAL_MACROS_ENV

    prompt_file = tmp_path / "managed-tmp" / "prompt.md"
    prompt_file.parent.mkdir()
    prompt_file.write_text("old prompt", encoding="utf-8")
    prior_macros = tmp_path / "prior-macros.json"
    prior_macros.write_text("{}", encoding="utf-8")
    monkeypatch.setenv(LOCAL_MACROS_ENV, str(prior_macros))
    monkeypatch.setenv(SASE_RUNNER_LEAN_WAIT_SPEC_ENV, "old-spec")
    monkeypatch.setenv(SASE_RUNNER_CODE_REFRESHED_ENV, "old-refresh")
    monkeypatch.delenv("SASE_AGENT_PLANNED_NAME", raising=False)

    with (
        patch(
            "sase.axe.run_agent_runner_lean_wait.importlib.util.find_spec",
            return_value=SimpleNamespace(origin=str(tmp_path / "waiter.py")),
        ),
        patch(
            "sase.axe.wait_checks_heartbeat.wait_checks_heartbeat_path",
            return_value=tmp_path / "heartbeat",
        ),
        patch("sase.axe.run_agent_lean_wait.validate_lean_wait_spec"),
        patch(
            "sase.axe.run_agent_runner_lean_wait.prepare_runner_exec_handoff",
            wraps=refresh.prepare_runner_exec_handoff,
        ) as prepare,
        patch.object(refresh.os, "execv") as execv,
        patch("sase.axe.run_agent_runner_lean_wait.was_killed", return_value=True),
        patch.object(lean_handoff.os, "name", "posix"),
    ):
        handed_off = lean_handoff.try_handoff_to_lean_waiter(
            "dependency",
            None,
            100.0,
            artifacts_dir=str(tmp_path / "artifacts"),
            artifacts_timestamp="20261122010101",
            project_name="proj",
            prompt_file=str(prompt_file),
            submitted_prompt="new prompt",
            agent_name="builder.w0",
            local_macros={"local": Macro(name="local", content="body")},
            wait_beads=[],
        )

    assert handed_off is False
    execv.assert_not_called()
    prepare.assert_called_once()
    assert prompt_file.read_text(encoding="utf-8") == "old prompt"
    assert read_local_macros_path(os.environ) == str(prior_macros)
    assert os.environ[SASE_RUNNER_LEAN_WAIT_SPEC_ENV] == "old-spec"
    assert os.environ[SASE_RUNNER_CODE_REFRESHED_ENV] == "old-refresh"
    assert "SASE_AGENT_PLANNED_NAME" not in os.environ
    staged_macros = list((tmp_path / "artifacts").glob("*.json"))
    assert staged_macros == []


def test_handled_kill_after_release_selection_is_serialized_as_killed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw_spec = {
        "version": 1,
        "artifacts_dir": str(tmp_path),
        "project_name": None,
        "runner_argv": ["python", "runner.py"],
        "mode": "dependency",
        "deadline_epoch": None,
        "heartbeat_path": None,
        "bead_sync_hint": False,
        "bead_sync_role": "beads",
        "blocked_since": 100.0,
        "handed_off_at": 101.0,
    }
    spec = run_agent_lean_wait.validate_lean_wait_spec(raw_spec)
    sigterm = run_agent_lean_wait._SigtermFlag()
    sigterm._handle(signal.SIGTERM, None)
    released = {
        "version": 1,
        "outcome": "released",
        "artifacts_dir": str(tmp_path),
        "release_source": "ready_json",
        "dependencies_satisfied_at": 99.0,
        "released_at": 101.0,
        "killed_at": None,
    }
    captured: dict[str, object] = {}

    def fail_exec(_path: str, _argv: list[str], env: dict[str, str]) -> None:
        captured.update(json.loads(env[SASE_RUNNER_LEAN_WAIT_RESULT_ENV]))
        raise OSError("exec denied")

    monkeypatch.setenv(SASE_RUNNER_LEAN_WAIT_SPEC_ENV, "spec")
    monkeypatch.setenv(SASE_RUNNER_LEAN_WAIT_RESULT_ENV, "stale")
    monkeypatch.setattr(run_agent_lean_wait, "EXEC_RETRIES", 0)
    with patch.object(run_agent_lean_wait.os, "execve", side_effect=fail_exec):
        run_agent_lean_wait._exec_back(spec, released, sigterm)

    assert captured["outcome"] == "killed"
    assert captured["killed_at"] == sigterm.killed_at
    assert captured["release_source"] is None
    assert captured["released_at"] is None
    assert captured["dependencies_satisfied_at"] is None


def test_diagnostic_override_skips_handoff(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(SASE_RUNNER_LEAN_WAIT_ENV, "0")
    with patch(
        "sase.axe.run_agent_runner_lean_wait.importlib.util.find_spec"
    ) as find_spec:
        result = lean_handoff.try_handoff_to_lean_waiter(
            "dependency",
            None,
            100.0,
            artifacts_dir=str(tmp_path),
            artifacts_timestamp="20261122010101",
            project_name="proj",
            prompt_file=str(tmp_path / "prompt.md"),
            submitted_prompt="prompt",
            agent_name=None,
            local_macros=None,
            wait_beads=[],
        )
    assert result is False
    find_spec.assert_not_called()


@pytest.mark.parametrize(
    ("outcome", "source", "killed_at"),
    [("released", "ready_json", None), ("killed", None, 120.0)],
)
def test_consume_lean_wait_result_pops_and_checks_one_shot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    outcome: str,
    source: str | None,
    killed_at: float | None,
) -> None:
    result = {
        "version": 1,
        "outcome": outcome,
        "artifacts_dir": str(tmp_path),
        "release_source": source,
        "dependencies_satisfied_at": None,
        "released_at": None,
        "killed_at": killed_at,
    }
    monkeypatch.setenv(SASE_RUNNER_LEAN_WAIT_RESULT_ENV, json.dumps(result))
    assert lean_handoff.consume_lean_wait_result(str(tmp_path)) == result
    assert SASE_RUNNER_LEAN_WAIT_RESULT_ENV not in os.environ


def test_killed_return_restores_durable_state_and_cleans_markers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "agent_meta.json").write_text(
        json.dumps(
            {
                "name": "phase.w0",
                "model": "@small",
                "llm_provider": "codex",
                "vcs_provider": "git",
                "hidden": True,
            }
        ),
        encoding="utf-8",
    )
    (artifacts / "submitted_prompt.md").write_text("submitted", encoding="utf-8")
    (artifacts / "bead_claim.json").write_text(
        json.dumps(
            {
                "bead_id": "tailnet-1e.8.1.3",
                "agent_name": "phase.w0",
                "project_name": "tailnet",
            }
        ),
        encoding="utf-8",
    )
    (artifacts / "waiting.json").write_text("{}", encoding="utf-8")
    (artifacts / "ready.json").write_text("{}", encoding="utf-8")
    state = RunnerRunState(
        cl_name="work",
        project_file=str(tmp_path / "project.yml"),
        prompt_file=str(tmp_path / "prompt.md"),
        output_path=str(tmp_path / "output.txt"),
        workflow_name="agent",
        timestamp="20261122010101",
        update_target="",
        is_home_mode=False,
        workspace_dir=str(tmp_path / "workspace"),
        workspace_num=7,
        project_name="tailnet",
        artifacts_timestamp="20261122010101",
        artifacts_dir=str(artifacts),
    )
    released: dict[str, object] = {}
    monkeypatch.delenv(SASE_RUNNER_CODE_REFRESHED_ENV, raising=False)

    with (
        patch.object(run_agent_runner, "mark_killed") as mark_killed,
        patch.object(run_agent_runner, "release_workspace_claim") as release_claim,
        patch.object(
            run_agent_runner,
            "update_agent_artifact_index_for_marker_mutation",
            side_effect=lambda path: released.setdefault("indexed", str(path)),
        ),
    ):
        run_agent_runner._restore_killed_lean_wait_state(
            state,
            {
                "killed_at": 120.0,
                "artifacts_dir": str(artifacts),
                "outcome": "killed",
            },
        )

    assert state.agent_name == "phase.w0"
    assert state.agent_model == "@small"
    assert state.agent_llm_provider == "codex"
    assert state.agent_vcs_provider == "git"
    assert state.agent_hidden is True
    assert state.held_bead_claim is not None
    assert state.held_bead_claim.bead_id == "tailnet-1e.8.1.3"
    assert state.prompt == state.submitted_prompt == "submitted"
    assert not (artifacts / "waiting.json").exists()
    assert not (artifacts / "ready.json").exists()
    mark_killed.assert_called_once_with(at=120.0)
    release_claim.assert_called_once()
    assert released["indexed"] == str(artifacts)


@pytest.mark.parametrize("hijack", [False, True], ids=["kill", "hijack"])
def test_main_finishes_killed_lean_return_without_bootstrap_or_launch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    hijack: bool,
) -> None:
    from sase.agent import scope_sweep

    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    output_path = tmp_path / "output.log"
    state = RunnerRunState(
        cl_name="lean-wait-child",
        project_file=str(tmp_path / "project.sase"),
        prompt_file=str(tmp_path / "managed-tmp" / "prompt.md"),
        output_path=str(output_path),
        workflow_name="ace(run)-20261122010101",
        timestamp="20261122010101",
        update_target="",
        is_home_mode=False,
        workspace_dir=str(tmp_path / "workspace"),
        workspace_num=7,
        project_name="proj",
        artifacts_timestamp="20261122010101",
        artifacts_dir=str(artifacts),
    )
    meta = {
        "name": "worker.w0",
        "model": "@small",
        "llm_provider": "codex",
        "vcs_provider": "git",
        "hidden": False,
        "pid": os.getpid(),
    }
    (artifacts / "agent_meta.json").write_text(json.dumps(meta), encoding="utf-8")
    (artifacts / "submitted_prompt.md").write_text("submitted prompt", encoding="utf-8")
    write_bead_claim_marker(
        artifacts,
        project_name="proj",
        bead_id="proj-1.2",
        agent_name="worker.w0",
    )
    (artifacts / "waiting.json").write_text("{}", encoding="utf-8")
    (artifacts / "ready.json").write_text("{}", encoding="utf-8")
    if hijack:
        assert (
            write_user_kill_intent(
                artifacts,
                pid=os.getpid(),
                source="test",
                mode="hijack",
                hijack_id="hijack-test",
                custody_pid=os.getpid(),
            )
            is not None
        )

    result = {
        "version": 1,
        "outcome": "killed",
        "artifacts_dir": str(artifacts),
        "release_source": None,
        "dependencies_satisfied_at": None,
        "released_at": None,
        "killed_at": 123.5,
    }
    monkeypatch.setenv(SASE_RUNNER_LEAN_WAIT_RESULT_ENV, json.dumps(result))
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts))
    monkeypatch.delenv("SASE_AGENT_AUTO_DISMISS", raising=False)

    released_workspaces: list[tuple[object, ...]] = []
    held_workspaces: list[tuple[object, ...]] = []
    shutdown_states: list[object] = []
    real_finalize = run_agent_runner.finalize_runner_shutdown

    def capture_finalize(**kwargs: object) -> None:
        shutdown_states.append(kwargs["state"])
        real_finalize(**kwargs)  # type: ignore[arg-type]

    kill_started = time.monotonic()
    with (
        patch.object(run_agent_runner, "_defer_start_across_code_swap"),
        patch.object(run_agent_runner, "install_sigterm_handler"),
        patch.object(run_agent_runner, "_build_run_state", return_value=state),
        patch.object(run_agent_runner, "_run_agent") as run_agent,
        patch.object(run_agent_runner, "launch_agent_run") as launch,
        patch.object(run_agent_runner, "record_kill_provenance") as record_kill_mock,
        patch.object(
            run_agent_runner,
            "finalize_runner_shutdown",
            side_effect=capture_finalize,
        ),
        patch.object(scope_sweep, "sweep_own_agent_scope"),
        patch(
            "sase.running_field.release_workspace",
            side_effect=lambda *args, **kwargs: released_workspaces.append(args),
        ),
        patch(
            "sase.running_field.hold_workspace_claim",
            side_effect=lambda *args, **kwargs: (
                held_workspaces.append(args) or SimpleNamespace(success=True)
            ),
        ),
        patch("sase.workspace_provider.occupant.clear_occupant_record"),
        patch(
            "sase.bead.claims.release_bead_claim_for_agent",
            return_value=BeadClaimReleaseOutcome.RELEASED,
        ),
    ):
        try:
            with pytest.raises(SystemExit) as exc_info:
                run_agent_runner.main()
        finally:
            from sase.axe.runner_signals import reset_killed

            reset_killed()
    cleanup_latency = time.monotonic() - kill_started

    assert exc_info.value.code == 128 + signal.SIGTERM
    assert cleanup_latency < 6, f"kill cleanup took {cleanup_latency:.3f}s"
    run_agent.assert_not_called()
    launch.assert_not_called()
    assert len(shutdown_states) == 1
    assert shutdown_states[0].exec_outcome == ("hijacked" if hijack else "killed")
    assert shutdown_states[0].suppress_completion_notification is True
    record_kill_mock.assert_called_once_with(str(artifacts), None, kill_time=123.5)
    assert not (artifacts / "waiting.json").exists()
    assert not (artifacts / "ready.json").exists()
    if hijack:
        assert released_workspaces == []
        assert len(held_workspaces) == 1
        assert (
            json.loads((artifacts / "done.json").read_text(encoding="utf-8"))["outcome"]
            == "hijacked"
        )
        assert (artifacts / "bead_claim.json").is_file()
    else:
        assert released_workspaces
        assert held_workspaces == []
        assert not (artifacts / "done.json").exists()
        assert not (artifacts / "bead_claim.json").exists()
