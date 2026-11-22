"""Runner-side lean-wait handoff and return tests."""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from sase.axe import (
    run_agent_runner,
    run_agent_runner_lean_wait as lean_handoff,
    run_agent_runner_refresh as refresh,
)
from sase.axe.run_agent_runner_state import RunnerRunState
from sase.agent.multi_prompt_macros import read_local_macros_path
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

    def exec_waiter(path: str, argv: list[str]) -> None:
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


def test_execv_masks_sigterm_and_unblocks_after_failure() -> None:
    import signal

    from unittest.mock import Mock

    masks = Mock()
    with (
        patch.object(refresh.signal, "pthread_sigmask", side_effect=masks),
        patch.object(refresh.os, "execv", side_effect=OSError("exec failed")),
        pytest.raises(OSError, match="exec failed"),
    ):
        refresh.execv_with_sigterm_mask("python", ["python", "runner.py"])

    assert [call.args[0] for call in masks.call_args_list] == [
        signal.SIG_BLOCK,
        signal.SIG_UNBLOCK,
    ]


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
