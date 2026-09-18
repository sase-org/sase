"""Coverage for wiring the commit finalizer's dirty-path baseline capture
into the runner bootstrap phase (bead sase-lb.1.6) and its inheritance by
family-attach continuations (plan 202608/lane_baseline_inheritance.md)."""

from __future__ import annotations

from dataclasses import asdict
import json
import os
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import ANY, MagicMock, patch

import pytest

from sase.agent.family_attach import FAMILY_ATTACH_ENV, FamilyAttachLaunchPlan
from sase.agent.launch_hold import LAUNCH_HOLD_KEY_ENV
from sase.axe import run_agent_runner, run_agent_runner_bootstrap
from sase.axe.run_agent_runner_bootstrap import _capture_commit_finalizer_baseline
from sase.axe.run_agent_runner_refresh import RUNNER_CODE_REFRESHED_ENV
from sase.core.agent_hold_facade import list_agent_holds_without_liveness
from sase.core.agent_hold_types import PendingCapture
from sase.feature_flags import override_flags
from sase.llm_provider.commit_finalizer_baseline import (
    BASELINE_FILENAME,
    FINALIZER_BASELINE_FILENAME,
)
from sase.xprompt.hold_directive import HoldFields


def _runner_args(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        cl_name="bootstrap-baseline",
        project_file="/tmp/projects/sase/sase.sase",
        workspace_dir=str(tmp_path / "workspace"),
        output_path=str(tmp_path / "output.log"),
        workspace_num=7,
        workflow_name="ace(run)-260701_010202",
        prompt_file=str(tmp_path / "prompt.md"),
        timestamp="260701_010202",
        update_target="",
        project_name="sase",
        is_home_mode=False,
    )


def test_capture_commit_finalizer_baseline_delegates_to_resolved_project_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SASE_DISABLE_COMMIT_STOP_HOOK", raising=False)
    monkeypatch.setenv("SASE_ACTIVE_PROJECT_DIR", str(tmp_path))
    capture = MagicMock()
    monkeypatch.setattr(
        "sase.llm_provider.commit_finalizer_baseline.capture_dirty_baseline", capture
    )

    _capture_commit_finalizer_baseline(str(tmp_path / "artifacts"))

    capture.assert_called_once_with(str(tmp_path), str(tmp_path / "artifacts"))


def _family_attach_plan(*, parent_artifacts_dir: str) -> FamilyAttachLaunchPlan:
    return FamilyAttachLaunchPlan(
        parent_arg="research.worker",
        suffix_arg="reviewer",
        parent_name="research.worker--0",
        parent_base="research.worker",
        parent_timestamp="20260701010101",
        parent_artifacts_dir=parent_artifacts_dir,
        role_suffix="--reviewer",
        agent_name="research.worker--reviewer",
        agent_family_role="reviewer",
        parent_family_member_name="research.worker--0",
        parent_family_role_suffix="--0",
        parent_needs_rename=False,
        parent_project_name="sase",
    )


def test_capture_commit_finalizer_baseline_inherits_parent_baseline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A family-attach continuation copies its parent's baseline byte-for-byte
    instead of capturing a fresh one."""
    monkeypatch.delenv("SASE_DISABLE_COMMIT_STOP_HOOK", raising=False)
    parent_dir = tmp_path / "parent"
    parent_dir.mkdir()
    baseline_payload = '{"repo": {"file.txt": ["M", "abc123"]}}\n'
    (parent_dir / BASELINE_FILENAME).write_text(baseline_payload, encoding="utf-8")
    plan = _family_attach_plan(parent_artifacts_dir=str(parent_dir))
    monkeypatch.setenv(FAMILY_ATTACH_ENV, json.dumps(asdict(plan)))
    capture = MagicMock()
    monkeypatch.setattr(
        "sase.llm_provider.commit_finalizer_baseline.capture_dirty_baseline", capture
    )
    artifacts_dir = tmp_path / "artifacts"

    _capture_commit_finalizer_baseline(str(artifacts_dir))

    capture.assert_not_called()
    assert (artifacts_dir / BASELINE_FILENAME).read_text(
        encoding="utf-8"
    ) == baseline_payload


def test_capture_commit_finalizer_baseline_inherits_parent_finalizer_baseline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SASE_DISABLE_COMMIT_STOP_HOOK", raising=False)
    parent_dir = tmp_path / "parent"
    parent_dir.mkdir()
    baseline_payload = json.dumps(
        {
            "schema_version": 1,
            "repositories": [
                {
                    "repo_id": "sdd:research",
                    "path": "/repos/research",
                    "kind": "sdd",
                    "name": "research",
                    "scope": "run_start",
                    "captured_at": "2026-08-25T11:00:00+00:00",
                    "fingerprints": {},
                }
            ],
        },
        sort_keys=True,
    )
    (parent_dir / FINALIZER_BASELINE_FILENAME).write_text(
        baseline_payload,
        encoding="utf-8",
    )
    plan = _family_attach_plan(parent_artifacts_dir=str(parent_dir))
    monkeypatch.setenv(FAMILY_ATTACH_ENV, json.dumps(asdict(plan)))
    capture = MagicMock()
    monkeypatch.setattr(
        "sase.llm_provider.commit_finalizer_baseline.capture_dirty_baseline", capture
    )
    artifacts_dir = tmp_path / "artifacts"

    _capture_commit_finalizer_baseline(str(artifacts_dir))

    capture.assert_not_called()
    assert (artifacts_dir / FINALIZER_BASELINE_FILENAME).read_text(
        encoding="utf-8"
    ) == baseline_payload


def test_capture_commit_finalizer_baseline_falls_back_when_parent_has_no_baseline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SASE_DISABLE_COMMIT_STOP_HOOK", raising=False)
    parent_dir = tmp_path / "parent"
    parent_dir.mkdir()
    plan = _family_attach_plan(parent_artifacts_dir=str(parent_dir))
    monkeypatch.setenv(FAMILY_ATTACH_ENV, json.dumps(asdict(plan)))
    capture = MagicMock()
    monkeypatch.setattr(
        "sase.llm_provider.commit_finalizer_baseline.capture_dirty_baseline", capture
    )
    artifacts_dir = tmp_path / "artifacts"

    _capture_commit_finalizer_baseline(str(artifacts_dir))

    capture.assert_called_once_with(ANY, str(artifacts_dir))
    assert not (artifacts_dir / BASELINE_FILENAME).exists()


def test_capture_commit_finalizer_baseline_captures_fresh_without_family_attach_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SASE_DISABLE_COMMIT_STOP_HOOK", raising=False)
    monkeypatch.delenv(FAMILY_ATTACH_ENV, raising=False)
    monkeypatch.setenv("SASE_ACTIVE_PROJECT_DIR", str(tmp_path))
    capture = MagicMock()
    monkeypatch.setattr(
        "sase.llm_provider.commit_finalizer_baseline.capture_dirty_baseline", capture
    )

    _capture_commit_finalizer_baseline(str(tmp_path / "artifacts"))

    capture.assert_called_once_with(str(tmp_path), str(tmp_path / "artifacts"))


def test_capture_commit_finalizer_baseline_falls_back_on_malformed_family_attach_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SASE_DISABLE_COMMIT_STOP_HOOK", raising=False)
    monkeypatch.setenv(FAMILY_ATTACH_ENV, "not valid json")
    capture = MagicMock()
    monkeypatch.setattr(
        "sase.llm_provider.commit_finalizer_baseline.capture_dirty_baseline", capture
    )
    artifacts_dir = tmp_path / "artifacts"

    _capture_commit_finalizer_baseline(str(artifacts_dir))

    capture.assert_called_once_with(ANY, str(artifacts_dir))


def test_capture_commit_finalizer_baseline_falls_back_when_parent_baseline_unreadable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SASE_DISABLE_COMMIT_STOP_HOOK", raising=False)
    parent_dir = tmp_path / "parent"
    parent_dir.mkdir()
    baseline_path = parent_dir / BASELINE_FILENAME
    baseline_path.write_text('{"repo": {}}\n', encoding="utf-8")
    baseline_path.chmod(0)
    stack = ExitStack()
    stack.callback(baseline_path.chmod, 0o644)
    plan = _family_attach_plan(parent_artifacts_dir=str(parent_dir))
    monkeypatch.setenv(FAMILY_ATTACH_ENV, json.dumps(asdict(plan)))
    capture = MagicMock()
    monkeypatch.setattr(
        "sase.llm_provider.commit_finalizer_baseline.capture_dirty_baseline", capture
    )
    artifacts_dir = tmp_path / "artifacts"

    with stack:
        _capture_commit_finalizer_baseline(str(artifacts_dir))

    capture.assert_called_once_with(ANY, str(artifacts_dir))
    assert not (artifacts_dir / BASELINE_FILENAME).exists()


def test_bootstrap_pops_launch_hold_key_before_setup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(LAUNCH_HOLD_KEY_ENV, "launch:req/u1")
    state = run_agent_runner_bootstrap.RunnerRunState(
        cl_name="bootstrap-key",
        project_file="/tmp/projects/sase/sase.sase",
        prompt_file=str(tmp_path / "prompt.md"),
        output_path=str(tmp_path / "output.log"),
        workflow_name="ace(run)-260701_010202",
        timestamp="260701_010202",
        update_target="",
        is_home_mode=False,
        workspace_dir=str(tmp_path / "workspace"),
        workspace_num=7,
        project_name="sase",
        artifacts_timestamp="20260701_010202",
        artifacts_dir=str(tmp_path / "artifacts"),
    )

    with (
        patch.object(
            run_agent_runner_bootstrap,
            "install_workspace_release_sigterm_handler",
        ),
        patch.object(
            run_agent_runner_bootstrap,
            "setup_artifacts_directory",
            side_effect=RuntimeError("stop after pop"),
        ),
    ):
        with pytest.raises(RuntimeError, match="stop after pop"):
            run_agent_runner_bootstrap.bootstrap_agent_run(state)

    assert LAUNCH_HOLD_KEY_ENV not in os.environ


def test_bootstrap_arms_launch_hold_before_dependency_wait_claim(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(LAUNCH_HOLD_KEY_ENV, "launch:req/u1")
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    state = run_agent_runner_bootstrap.RunnerRunState(
        cl_name="bootstrap-hold",
        project_file="/tmp/projects/sase/sase.sase",
        prompt_file=str(tmp_path / "prompt.md"),
        output_path=str(tmp_path / "output.log"),
        workflow_name="ace(run)-260701_010202",
        timestamp="260701_010202",
        update_target="",
        is_home_mode=False,
        workspace_dir=str(tmp_path / "workspace"),
        workspace_num=7,
        project_name="sase",
        artifacts_timestamp="20260701_010202",
        artifacts_dir=str(artifacts_dir),
    )
    info = SimpleNamespace(
        name="bootstrap.agent",
        bead_id="sase-1",
        wait_names=["dependency"],
        wait_identity_deps=[],
        wait_fork_sources=[],
        wait_beads=[],
        wait_duration=None,
        wait_until=None,
        wait_runners=None,
        wait_priority=None,
        queue_weight_explicit=False,
        model=None,
        llm_provider=None,
        vcs_provider=None,
        hidden=False,
        hold=object(),
        meta={"agent_name": "bootstrap.agent"},
    )
    events: list[str] = []

    def load_prompt(current: object) -> None:
        current.prompt = "Do work"
        current.submitted_xprompt = "Do work"

    with (
        patch.object(
            run_agent_runner_bootstrap,
            "install_workspace_release_sigterm_handler",
        ),
        patch.object(
            run_agent_runner_bootstrap,
            "setup_artifacts_directory",
            return_value=("sase", "20260701010202", str(artifacts_dir)),
        ),
        patch.object(run_agent_runner_bootstrap, "_write_bootstrap_agent_meta"),
        patch.object(run_agent_runner_bootstrap, "_load_submitted_prompt", load_prompt),
        patch.object(run_agent_runner_bootstrap, "init_telemetry"),
        patch.object(run_agent_runner_bootstrap, "register_flush_on_exit"),
        patch.object(run_agent_runner_bootstrap, "print_agent_start_banner"),
        patch.object(
            run_agent_runner_bootstrap,
            "preprocess_prompt_xprompts",
            return_value=("Do work", None, "Do work"),
        ),
        patch.object(
            run_agent_runner_bootstrap,
            "load_retry_handoff_from_env",
            return_value=None,
        ),
        patch.object(run_agent_runner_bootstrap, "enter_agent_workspace"),
        patch.object(run_agent_runner_bootstrap, "_capture_commit_finalizer_baseline"),
        patch.object(
            run_agent_runner_bootstrap,
            "extract_directives_and_write_meta",
            return_value=info,
        ),
        patch.object(
            run_agent_runner_bootstrap,
            "arm_bootstrap_hold",
            side_effect=lambda *args: events.append("arm"),
        ) as arm,
        patch.object(
            run_agent_runner_bootstrap,
            "_force_reuse_bead_association_for_run",
            return_value=None,
        ),
        patch.object(
            run_agent_runner_bootstrap,
            "apply_retry_chain_to_meta",
            return_value=dict(info.meta),
        ),
        patch.object(
            run_agent_runner_bootstrap,
            "_claim_bead_before_wait",
            side_effect=lambda *args, **kwargs: events.append("claim"),
        ),
    ):
        bootstrap = run_agent_runner_bootstrap.bootstrap_agent_run(state)

    assert bootstrap.has_wait is True
    assert events == ["arm", "claim"]
    arm.assert_called_once_with(state, info, None, "launch:req/u1")
    assert LAUNCH_HOLD_KEY_ENV not in os.environ


def test_bootstrap_real_hold_exists_before_dependency_wait_claim(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("sase_core_rs")
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    monkeypatch.delenv(LAUNCH_HOLD_KEY_ENV, raising=False)
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    state = run_agent_runner_bootstrap.RunnerRunState(
        cl_name="bootstrap-hold",
        project_file="/tmp/projects/sase/sase.sase",
        prompt_file=str(tmp_path / "prompt.md"),
        output_path=str(tmp_path / "output.log"),
        workflow_name="ace(run)-260701_010202",
        timestamp="260701_010202",
        update_target="",
        is_home_mode=False,
        workspace_dir=str(tmp_path / "workspace"),
        workspace_num=7,
        project_name="sase",
        artifacts_timestamp="20260701_010202",
        artifacts_dir=str(artifacts_dir),
    )
    info = SimpleNamespace(
        name="bootstrap.agent",
        bead_id="sase-1",
        wait_names=["dependency"],
        wait_identity_deps=[],
        wait_fork_sources=[],
        wait_beads=[],
        wait_duration=None,
        wait_until=None,
        wait_runners=None,
        wait_priority=None,
        queue_weight_explicit=False,
        model=None,
        llm_provider=None,
        vcs_provider=None,
        hidden=False,
        hold=HoldFields(pending=True),
        meta={"agent_name": "bootstrap.agent"},
    )
    events: list[str] = []
    pending_dir = str(tmp_path / "waiting-agent")

    def load_prompt(current: object) -> None:
        current.prompt = "%wait:dependency %hold(pending)\nDo work"
        current.submitted_xprompt = current.prompt

    def extract_directives(*args: object, **kwargs: object) -> object:
        del args, kwargs
        (artifacts_dir / "agent_meta.json").write_text(
            json.dumps(
                {
                    "name": "bootstrap.agent",
                    "pid": os.getpid(),
                    "agent_family": "bootstrap",
                    "output_path": state.output_path,
                }
            ),
            encoding="utf-8",
        )
        return info

    def claim_before_wait(*args: object, **kwargs: object) -> None:
        del args, kwargs
        holds = list_agent_holds_without_liveness()
        assert [hold["armer"]["key"] for hold in holds] == ["agent:bootstrap.agent"]
        assert holds[0]["selectors"]["artifact_dirs"] == [pending_dir]
        events.append("claim")

    with (
        override_flags(agent_holds=True),
        patch.object(
            run_agent_runner_bootstrap,
            "install_workspace_release_sigterm_handler",
        ),
        patch.object(
            run_agent_runner_bootstrap,
            "setup_artifacts_directory",
            return_value=("sase", "20260701010202", str(artifacts_dir)),
        ),
        patch.object(run_agent_runner_bootstrap, "_load_submitted_prompt", load_prompt),
        patch.object(run_agent_runner_bootstrap, "init_telemetry"),
        patch.object(run_agent_runner_bootstrap, "register_flush_on_exit"),
        patch.object(run_agent_runner_bootstrap, "print_agent_start_banner"),
        patch.object(
            run_agent_runner_bootstrap,
            "preprocess_prompt_xprompts",
            return_value=("%wait:dependency %hold(pending)\nDo work", None, "Do work"),
        ),
        patch.object(
            run_agent_runner_bootstrap,
            "load_retry_handoff_from_env",
            return_value=None,
        ),
        patch.object(run_agent_runner_bootstrap, "enter_agent_workspace"),
        patch.object(run_agent_runner_bootstrap, "_capture_commit_finalizer_baseline"),
        patch.object(
            run_agent_runner_bootstrap,
            "extract_directives_and_write_meta",
            side_effect=extract_directives,
        ),
        patch(
            "sase.core.agent_hold_facade._capture_pending_targets",
            return_value=PendingCapture(
                artifact_dirs=(pending_dir,),
                waiting_count=1,
                queued_count=0,
                skipped_running_count=0,
            ),
        ),
        patch("sase.core.agent_hold_facade._project_for_cwd", return_value="sase"),
        patch.object(
            run_agent_runner_bootstrap,
            "_force_reuse_bead_association_for_run",
            return_value=None,
        ),
        patch.object(
            run_agent_runner_bootstrap,
            "apply_retry_chain_to_meta",
            return_value=dict(info.meta),
        ),
        patch.object(
            run_agent_runner_bootstrap,
            "_claim_bead_before_wait",
            side_effect=claim_before_wait,
        ),
    ):
        bootstrap = run_agent_runner_bootstrap.bootstrap_agent_run(state)

    assert bootstrap.has_dependency_wait is True
    assert events == ["claim"]
    assert LAUNCH_HOLD_KEY_ENV not in os.environ


def test_bootstrap_captures_baseline_after_entering_the_real_workspace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``bootstrap_agent_run`` must capture the baseline for the workspace it
    actually entered, before directive extraction runs."""
    monkeypatch.delenv(RUNNER_CODE_REFRESHED_ENV, raising=False)
    monkeypatch.delenv("SASE_DISABLE_COMMIT_STOP_HOOK", raising=False)
    args = _runner_args(tmp_path)
    Path(args.workspace_dir).mkdir(parents=True)
    Path(args.prompt_file).write_text("Do work", encoding="utf-8")
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()

    calls: list[tuple[str, str]] = []

    def fake_capture(project_dir: str, artifacts_dir_arg: str) -> None:
        calls.append((project_dir, artifacts_dir_arg))

    # ``enter_agent_workspace`` chdirs into ``args.workspace_dir``, which
    # lives under ``tmp_path`` and is removed after the test; restore the
    # original cwd so later tests do not inherit a deleted directory.
    original_cwd = os.getcwd()
    stack = ExitStack()
    stack.callback(os.chdir, original_cwd)
    with stack:
        stack.enter_context(
            patch.object(run_agent_runner, "parse_runner_args", return_value=args)
        )
        stack.enter_context(
            patch.object(
                run_agent_runner_bootstrap, "install_workspace_release_sigterm_handler"
            )
        )
        stack.enter_context(
            patch.object(
                run_agent_runner_bootstrap,
                "setup_artifacts_directory",
                return_value=("sase", "20260701010202", str(artifacts_dir)),
            )
        )
        stack.enter_context(
            patch(
                "sase.axe.run_agent_runner_setup."
                "update_agent_artifact_index_for_marker_mutation"
            )
        )
        stack.enter_context(
            patch(
                "sase.axe.run_agent_runner_finalize."
                "update_agent_artifact_index_for_marker_mutation"
            )
        )
        stack.enter_context(patch.object(run_agent_runner_bootstrap, "init_telemetry"))
        stack.enter_context(
            patch.object(run_agent_runner_bootstrap, "register_flush_on_exit")
        )
        stack.enter_context(
            patch.object(run_agent_runner_bootstrap, "print_agent_start_banner")
        )
        stack.enter_context(
            patch.object(
                run_agent_runner, "format_agent_run_runtime", return_value="0s"
            )
        )
        stack.enter_context(patch.object(run_agent_runner, "record_completion_metrics"))
        stack.enter_context(patch.object(run_agent_runner, "finalize_runner_shutdown"))
        stack.enter_context(patch.object(run_agent_runner, "AGENT_KILLS"))
        stack.enter_context(
            patch(
                "sase.llm_provider.commit_finalizer_baseline.capture_dirty_baseline",
                side_effect=fake_capture,
            )
        )
        stack.enter_context(
            patch.object(
                run_agent_runner_bootstrap,
                "extract_directives_and_write_meta",
                side_effect=RuntimeError("stop after baseline capture"),
            )
        )

        with pytest.raises(SystemExit):
            run_agent_runner.main()

    assert len(calls) == 1
    project_dir, captured_artifacts_dir = calls[0]
    assert project_dir == args.workspace_dir
    assert captured_artifacts_dir == str(artifacts_dir)
    done = json.loads((artifacts_dir / "done.json").read_text(encoding="utf-8"))
    assert "stop after baseline capture" in done["error"]
