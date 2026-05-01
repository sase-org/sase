"""Tests for run_agent_exec workflow project selection."""

import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from sase.axe.run_agent_exec import (
    AgentExecContext,
    _AgentExecResult,
    _current_chat_agent_name,
    _finalize_loop,
    _resolve_workflow_project,
    _set_predicted_agent_chat_path,
    LoopState,
    run_execution_loop,
)
from sase.axe.run_agent_exec_retry import RetryTracker
from sase.axe.run_agent_runner_finalize import send_completion_notification


def _make_ctx(
    tmp_path: Path,
    *,
    is_home_mode: bool,
    project_name: str = "sase",
) -> AgentExecContext:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    return AgentExecContext(
        cl_name="test-cl",
        project_file=str(tmp_path / "project.gp"),
        workspace_dir=str(tmp_path),
        output_path=str(tmp_path / "output.log"),
        workspace_num=1,
        timestamp="20260408_120000",
        update_target="",
        project_name=project_name,
        is_home_mode=is_home_mode,
        artifacts_dir=str(artifacts),
        artifacts_timestamp="20260408_120000",
        vcs_tag=None,
        agent_name="agent",
        agent_model=None,
        agent_llm_provider=None,
        agent_vcs_provider=None,
        agent_hidden=False,
        agent_meta={},
        local_xprompts={},
    )


def test_resolve_workflow_project_non_home_mode_returns_project(tmp_path: Path) -> None:
    ctx = _make_ctx(tmp_path, is_home_mode=False, project_name="myproj")
    assert _resolve_workflow_project(ctx) == "myproj"


def test_resolve_workflow_project_home_mode_returns_none(tmp_path: Path) -> None:
    ctx = _make_ctx(tmp_path, is_home_mode=True, project_name="home")
    assert _resolve_workflow_project(ctx) is None


def test_run_execution_loop_home_mode_passes_none_project(tmp_path: Path) -> None:
    ctx = _make_ctx(tmp_path, is_home_mode=True, project_name="home")
    anon_workflow = SimpleNamespace(name="anon", xprompts={})
    final_result = _AgentExecResult(
        success=True,
        current_artifacts_dir=ctx.artifacts_dir,
    )

    with (
        patch("sase.history.chat.generate_chat_filename", return_value="test_chat"),
        patch(
            "sase.history.chat.get_chat_file_path",
            return_value="/tmp/test_chat.md",
        ),
        patch(
            "sase.xprompt.models.create_anonymous_workflow",
            return_value=anon_workflow,
        ),
        patch("sase.xprompt.workflow_runner.execute_workflow") as mock_execute,
        patch("sase.axe.run_agent_exec.was_killed", return_value=False),
        patch("sase.axe.run_agent_exec.reset_killed"),
        patch("sase.axe.run_agent_exec._finalize_loop", return_value=final_result),
    ):
        result = run_execution_loop(ctx, "prompt")

    assert result == final_result
    assert mock_execute.call_count == 1
    assert mock_execute.call_args.kwargs["project"] is None


def test_run_execution_loop_non_home_mode_passes_project(tmp_path: Path) -> None:
    ctx = _make_ctx(tmp_path, is_home_mode=False, project_name="sase")
    anon_workflow = SimpleNamespace(name="anon", xprompts={})
    final_result = _AgentExecResult(
        success=True,
        current_artifacts_dir=ctx.artifacts_dir,
    )

    with (
        patch("sase.history.chat.generate_chat_filename", return_value="test_chat"),
        patch(
            "sase.history.chat.get_chat_file_path",
            return_value="/tmp/test_chat.md",
        ),
        patch(
            "sase.xprompt.models.create_anonymous_workflow",
            return_value=anon_workflow,
        ),
        patch("sase.xprompt.workflow_runner.execute_workflow") as mock_execute,
        patch("sase.axe.run_agent_exec.was_killed", return_value=False),
        patch("sase.axe.run_agent_exec.reset_killed"),
        patch("sase.axe.run_agent_exec._finalize_loop", return_value=final_result),
    ):
        result = run_execution_loop(ctx, "prompt")

    assert result == final_result
    assert mock_execute.call_count == 1
    assert mock_execute.call_args.kwargs["project"] == "sase"


def test_current_chat_agent_name_uses_canonical_coder_suffix(tmp_path: Path) -> None:
    ctx = _make_ctx(tmp_path, is_home_mode=False)
    state = LoopState(
        current_prompt="implement",
        current_role_suffix=".coder",
        current_artifacts_dir=ctx.artifacts_dir,
        loop_outcome="completed",
        sdd_spec_path=None,
        original_prompt="implement",
        agent_step=2,
    )

    assert _current_chat_agent_name(ctx, state) == "agent.coder"


def test_predicted_chat_path_uses_current_phase_agent(
    tmp_path: Path,
    monkeypatch,
) -> None:
    ctx = _make_ctx(tmp_path, is_home_mode=False)
    state = LoopState(
        current_prompt="implement",
        current_role_suffix=".coder",
        current_artifacts_dir=ctx.artifacts_dir,
        loop_outcome="completed",
        sdd_spec_path=None,
        original_prompt="implement",
        agent_step=2,
    )

    captured: dict = {}

    def fake_generate(**kwargs):
        captured.update(kwargs)
        return "test-cl-ace_run-agent.coder-260408_120000"

    monkeypatch.setattr("sase.history.chat.generate_chat_filename", fake_generate)
    monkeypatch.setattr(
        "sase.history.chat.get_chat_file_path",
        lambda basename: f"/home/test/.sase/chats/{basename}.md",
    )

    _set_predicted_agent_chat_path(ctx, state)

    assert captured["agent"] == "agent.coder"
    assert "agent.coder" in os.environ["SASE_AGENT_CHAT_PATH"]


def test_finalize_loop_saves_coder_chat_with_phase_agent(tmp_path: Path) -> None:
    ctx = _make_ctx(tmp_path, is_home_mode=False)
    state = LoopState(
        current_prompt="implement",
        current_role_suffix=".coder",
        current_artifacts_dir=ctx.artifacts_dir,
        loop_outcome="completed",
        sdd_spec_path=None,
        original_prompt="implement",
        agent_step=2,
    )
    captured: dict = {}

    def fake_save_chat_history(**kwargs):
        captured.update(kwargs)
        return str(tmp_path / "chat.md")

    with patch(
        "sase.axe.run_agent_exec.save_chat_history", side_effect=fake_save_chat_history
    ):
        _finalize_loop(
            ctx,
            state,
            RetryTracker(retry_cfg=None),
            SimpleNamespace(response_text="done"),
        )

    assert captured["agent"] == "agent.coder"


def test_finalize_loop_records_markdown_pdfs_images_and_notification_files(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _run(workspace, "git", "init")
    _run(workspace, "git", "config", "user.email", "test@example.com")
    _run(workspace, "git", "config", "user.name", "Test User")
    (workspace / "base.txt").write_text("base\n")
    _run(workspace, "git", "add", ".")
    _run(workspace, "git", "commit", "-m", "base")

    research = workspace / "research" / "example.md"
    notes = workspace / "docs" / "notes.md"
    image = workspace / "assets" / "diagram.png"
    research.parent.mkdir()
    notes.parent.mkdir()
    image.parent.mkdir()
    research.write_text("# Research\n")
    notes.write_text("# Notes\n")
    image.write_bytes(b"\x89PNG\r\n\x1a\n")

    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "workflow_state.json").write_text(
        json.dumps(
            {
                "steps": [
                    {"output": {"summary": "created markdown and image attachments"}}
                ]
            }
        )
    )
    chat = tmp_path / "chat.md"

    def fake_render_markdown_pdf(src: Path, dest: Path) -> Path:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(f"%PDF {src.name}".encode())
        return dest

    ctx = AgentExecContext(
        cl_name="test-cl",
        project_file=str(tmp_path / "project.gp"),
        workspace_dir=str(workspace),
        output_path=str(tmp_path / "output.log"),
        workspace_num=1,
        timestamp="20260430120000",
        update_target="",
        project_name="test",
        is_home_mode=False,
        artifacts_dir=str(artifacts),
        artifacts_timestamp="20260430120000",
        vcs_tag=None,
        agent_name="agent",
        agent_model="model",
        agent_llm_provider="provider",
        agent_vcs_provider="git",
        agent_hidden=False,
        agent_meta={},
        local_xprompts={},
    )
    state = LoopState(
        current_prompt="create attachments",
        current_role_suffix="",
        current_artifacts_dir=str(artifacts),
        loop_outcome="completed",
        sdd_spec_path=None,
        original_prompt="create attachments",
    )

    with (
        patch("sase.axe.run_agent_exec.save_chat_history", return_value=str(chat)),
        patch(
            "sase.attachments.markdown_pdf.render_markdown_pdf",
            side_effect=fake_render_markdown_pdf,
        ),
    ):
        result = _finalize_loop(
            ctx,
            state,
            RetryTracker(retry_cfg=None),
            SimpleNamespace(response_text="done"),
        )

    pdf_dir = artifacts / "markdown_pdfs"
    expected_pdfs = [
        str(pdf_dir / "docs__notes.md.pdf"),
        str(pdf_dir / "research__example.md.pdf"),
    ]
    assert result.markdown_pdf_paths == expected_pdfs
    assert result.image_paths == [str(image.resolve())]

    done = json.loads((artifacts / "done.json").read_text())
    assert done["markdown_pdf_paths"] == expected_pdfs
    assert done["image_paths"] == [str(image.resolve())]
    assert sorted(path.name for path in pdf_dir.glob("*.pdf")) == [
        "docs__notes.md.pdf",
        "research__example.md.pdf",
    ]
    assert json.loads((pdf_dir / "index.json").read_text()) == [
        {"source_path": str(notes.resolve()), "pdf_path": expected_pdfs[0]},
        {"source_path": str(research.resolve()), "pdf_path": expected_pdfs[1]},
    ]

    with patch("sase.notifications.senders.notify_workflow_complete") as notify:
        send_completion_notification(
            cl_name=ctx.cl_name,
            artifacts_timestamp=ctx.artifacts_timestamp,
            workflow_name="ace-run",
            success=result.success,
            agent_hidden=ctx.agent_hidden,
            agent_name=ctx.agent_name,
            agent_model=ctx.agent_model,
            agent_llm_provider=ctx.agent_llm_provider,
            error_summary=None,
            error_report_path=None,
            saved_path=result.saved_path,
            diff_path=result.diff_path,
            markdown_pdf_paths=result.markdown_pdf_paths,
            image_paths=result.image_paths,
            output_path=ctx.output_path,
            step_output=result.step_output,
            prompt=state.original_prompt,
            outcome=result.outcome,
        )

    assert notify.call_args.kwargs["extra_files"] == [
        str(chat),
        *expected_pdfs,
        str(image.resolve()),
    ]


def _run(cwd: Path, *args: str) -> None:
    subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True)
