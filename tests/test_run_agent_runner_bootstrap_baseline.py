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
from sase.axe import run_agent_runner, run_agent_runner_bootstrap
from sase.axe.run_agent_runner_bootstrap import _capture_commit_finalizer_baseline
from sase.axe.run_agent_runner_refresh import RUNNER_CODE_REFRESHED_ENV
from sase.llm_provider.commit_finalizer_baseline import (
    BASELINE_FILENAME,
    FINALIZER_BASELINE_FILENAME,
)


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
