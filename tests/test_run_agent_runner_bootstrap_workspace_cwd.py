"""Launch macro command substitutions use the assigned workspace cwd."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from sase.axe import run_agent_runner_bootstrap
from sase.axe.run_agent_runner_refresh import RUNNER_CODE_REFRESHED_ENV


class _StopAfterPrompt(Exception):
    pass


def _run_bootstrap_until_directive_extraction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    prompt: str,
    deferred: bool = False,
) -> tuple[str, list[str], list[str], Path, Path]:
    launch_dir = tmp_path / "launcher"
    workspace_dir = tmp_path / "workspace"
    artifacts_dir = tmp_path / "artifacts"
    macro_dir = launch_dir / "sase" / "macros"
    macro_dir.mkdir(parents=True)
    workspace_dir.mkdir()
    artifacts_dir.mkdir()
    (macro_dir / "cwd_probe.md").write_text(
        "---\nname: cwd_probe\n---\nPath: $(pwd)\n",
        encoding="utf-8",
    )
    (macro_dir / "cwd_arg.md").write_text(
        "---\nname: cwd_arg\ninput:\n  path:\n    type: text\n---\nPath: {{ path }}\n",
        encoding="utf-8",
    )
    prompt_file = tmp_path / "prompt.md"
    prompt_file.write_text(prompt, encoding="utf-8")
    state = run_agent_runner_bootstrap.RunnerRunState(
        cl_name="workspace-cwd",
        project_file=str(tmp_path / "projects" / "sase" / "sase.sase"),
        prompt_file=str(prompt_file),
        output_path=str(tmp_path / "output.log"),
        workflow_name="ace(run)-261119_010203",
        timestamp="261119_010203",
        update_target="",
        is_home_mode=False,
        workspace_dir=str(workspace_dir),
        workspace_num=7,
        project_name="sase",
        artifacts_timestamp="20261119_010203",
        artifacts_dir=str(artifacts_dir),
    )
    monkeypatch.chdir(launch_dir)
    monkeypatch.delenv("SASE_AGENT_LOCAL_MACROS", raising=False)
    monkeypatch.delenv("SASE_LAUNCH_SWARM_MACROS", raising=False)
    monkeypatch.delenv("SASE_AGENT_RETRY_HANDOFF", raising=False)
    monkeypatch.delenv(RUNNER_CODE_REFRESHED_ENV, raising=False)
    # This process-wide cache is otherwise shared by the separate bootstrap
    # scenarios, even though their cwd values differ.
    import sase.file_references as file_references

    monkeypatch.setattr(file_references, "_cmd_cache", {})
    if deferred:
        monkeypatch.setenv("SASE_AGENT_DEFERRED_WORKSPACE", "1")
    else:
        monkeypatch.delenv("SASE_AGENT_DEFERRED_WORKSPACE", raising=False)

    extracted_prompts: list[str] = []
    events: list[str] = []
    entered_workspaces: list[str] = []

    def enter_workspace(path: str, _workspace_num: int) -> None:
        events.append("enter")
        entered_workspaces.append(path)
        os.chdir(path)

    def capture_prompt(current_prompt: str, *_args: object, **_kwargs: object) -> None:
        extracted_prompts.append(current_prompt)
        raise _StopAfterPrompt

    def load_retry_handoff() -> None:
        events.append("retry")
        return None

    monkeypatch.setattr(
        run_agent_runner_bootstrap,
        "setup_artifacts_directory",
        lambda **_kwargs: ("sase", "20261119_010203", str(artifacts_dir)),
    )
    monkeypatch.setattr(
        run_agent_runner_bootstrap,
        "install_workspace_release_sigterm_handler",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        run_agent_runner_bootstrap,
        "_write_bootstrap_agent_meta",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr("sase.axe.agent_meta.read_live_agent_meta", lambda _path: {})
    monkeypatch.setattr(run_agent_runner_bootstrap, "init_telemetry", lambda: None)
    monkeypatch.setattr(
        run_agent_runner_bootstrap, "register_flush_on_exit", lambda **_kwargs: None
    )
    monkeypatch.setattr(
        run_agent_runner_bootstrap,
        "print_agent_start_banner",
        lambda **_kwargs: events.append("banner"),
    )
    monkeypatch.setattr(
        run_agent_runner_bootstrap, "enter_agent_workspace", enter_workspace
    )
    monkeypatch.setattr(
        run_agent_runner_bootstrap,
        "_capture_commit_finalizer_baseline",
        lambda *_args, **_kwargs: events.append("baseline"),
    )
    monkeypatch.setattr(
        run_agent_runner_bootstrap,
        "load_retry_handoff_from_env",
        load_retry_handoff,
    )
    monkeypatch.setattr(
        run_agent_runner_bootstrap, "extract_directives_and_write_meta", capture_prompt
    )
    monkeypatch.setattr(
        "sase.axe.runner_lifecycle_phase.mark_lifecycle_phase", lambda *_args: None
    )

    with pytest.raises(_StopAfterPrompt):
        run_agent_runner_bootstrap.bootstrap_agent_run(state)

    return extracted_prompts[0], events, entered_workspaces, launch_dir, workspace_dir


def test_assigned_workspace_macro_body_command_runs_in_workspace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expanded_prompt, events, entered_workspaces, _launch_dir, workspace_dir = (
        _run_bootstrap_until_directive_extraction(
            tmp_path,
            monkeypatch,
            prompt="#cwd_probe",
        )
    )

    assert f"Path: {workspace_dir}" in expanded_prompt
    assert events == ["banner", "enter", "retry", "baseline"]
    assert entered_workspaces == [str(workspace_dir)]


def test_assigned_workspace_macro_argument_command_runs_in_workspace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expanded_prompt, _events, entered_workspaces, _launch_dir, workspace_dir = (
        _run_bootstrap_until_directive_extraction(
            tmp_path,
            monkeypatch,
            prompt="#cwd_arg($(pwd))",
        )
    )

    assert f"Path: {workspace_dir}" in expanded_prompt
    assert entered_workspaces == [str(workspace_dir)]


def test_deferred_workspace_macro_command_keeps_launch_cwd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expanded_prompt, events, entered_workspaces, launch_dir, workspace_dir = (
        _run_bootstrap_until_directive_extraction(
            tmp_path,
            monkeypatch,
            prompt="#cwd_probe",
            deferred=True,
        )
    )

    assert f"Path: {launch_dir}" in expanded_prompt
    assert events == ["banner", "retry", "enter", "baseline"]
    assert entered_workspaces == [str(workspace_dir)]
