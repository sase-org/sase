"""Tests for run_agent_exec workflow project selection."""

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from sase.attachments.markdown_pdf import MAX_MARKDOWN_PDF_ATTACHMENTS
from sase.attachments.markdown_pdf import MarkdownPdfProgressEvent
from sase.axe.run_agent_exec import (
    AgentExecContext,
    _AgentExecResult,
    _finalize_loop,
    _publish_phase_env,
    _resolve_workflow_project,
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
        project_file=str(tmp_path / "project.sase"),
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

    research = workspace / "sdd" / "research" / "example.md"
    notes = workspace / "docs" / "notes.md"
    image = workspace / "assets" / "diagram.png"
    research.parent.mkdir(parents=True)
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

    def fake_render_markdown_pdf(src: Path, dest: Path, **kwargs) -> Path:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(f"%PDF {src.name}".encode())
        return dest

    ctx = AgentExecContext(
        cl_name="test-cl",
        project_file=str(tmp_path / "project.sase"),
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
        str(pdf_dir / "sdd__research__example.md.pdf"),
    ]
    assert result.markdown_pdf_paths == expected_pdfs
    assert result.image_paths == [str(image.resolve())]

    done = json.loads((artifacts / "done.json").read_text())
    assert done["markdown_pdf_paths"] == expected_pdfs
    assert done["image_paths"] == [str(image.resolve())]
    assert sorted(path.name for path in pdf_dir.glob("*.pdf")) == [
        "docs__notes.md.pdf",
        "sdd__research__example.md.pdf",
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


def test_finalize_loop_renders_markdown_pdfs_at_attachment_limit(
    tmp_path: Path,
) -> None:
    ctx = _make_ctx(tmp_path, is_home_mode=False)
    state = LoopState(
        current_prompt="create markdown",
        current_role_suffix="",
        current_artifacts_dir=ctx.artifacts_dir,
        loop_outcome="completed",
        sdd_spec_path=None,
        original_prompt="create markdown",
    )
    chat = tmp_path / "chat.md"
    sources = _write_markdown_sources(tmp_path, MAX_MARKDOWN_PDF_ATTACHMENTS)

    def fake_render_markdown_pdf(src: Path, dest: Path, **kwargs) -> Path:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(f"%PDF {src.name}".encode())
        return dest

    with (
        patch("sase.axe.run_agent_exec.save_chat_history", return_value=str(chat)),
        patch(
            "sase.axe.image_attachments.collect_agent_markdown_paths",
            return_value=sources,
        ),
        patch(
            "sase.attachments.markdown_pdf.render_markdown_pdf",
            side_effect=fake_render_markdown_pdf,
        ) as render,
    ):
        result = _finalize_loop(
            ctx,
            state,
            RetryTracker(retry_cfg=None),
            SimpleNamespace(response_text="done"),
        )

    assert render.call_count == MAX_MARKDOWN_PDF_ATTACHMENTS
    assert len(result.markdown_pdf_paths) == MAX_MARKDOWN_PDF_ATTACHMENTS
    assert result.markdown_source_count == MAX_MARKDOWN_PDF_ATTACHMENTS


def test_finalize_loop_skips_markdown_pdfs_above_attachment_limit(
    tmp_path: Path,
) -> None:
    ctx = _make_ctx(tmp_path, is_home_mode=False)
    state = LoopState(
        current_prompt="create many markdown files",
        current_role_suffix="",
        current_artifacts_dir=ctx.artifacts_dir,
        loop_outcome="completed",
        sdd_spec_path=None,
        original_prompt="create many markdown files",
    )
    chat = tmp_path / "chat.md"
    sources = _write_markdown_sources(tmp_path, MAX_MARKDOWN_PDF_ATTACHMENTS + 1)

    with (
        patch("sase.axe.run_agent_exec.save_chat_history", return_value=str(chat)),
        patch(
            "sase.axe.image_attachments.collect_agent_markdown_paths",
            return_value=sources,
        ),
        patch("sase.attachments.markdown_pdf.render_markdown_pdf") as render,
    ):
        result = _finalize_loop(
            ctx,
            state,
            RetryTracker(retry_cfg=None),
            SimpleNamespace(response_text="done"),
        )

    render.assert_not_called()
    assert result.markdown_pdf_paths == []
    assert result.markdown_source_count == MAX_MARKDOWN_PDF_ATTACHMENTS + 1

    done = json.loads((Path(ctx.artifacts_dir) / "done.json").read_text())
    assert done["markdown_pdf_paths"] == []


def test_finalize_loop_prints_and_persists_markdown_pdf_progress(
    tmp_path: Path,
    capsys,
) -> None:
    ctx = _make_ctx(tmp_path, is_home_mode=False)
    artifacts = Path(ctx.artifacts_dir)
    (artifacts / "workflow_state.json").write_text(
        json.dumps(
            {
                "workflow_name": "run",
                "status": "running",
                "context": {"cl_name": "test-cl"},
                "steps": [],
            }
        )
    )
    source = tmp_path / "docs" / "note.md"
    source.parent.mkdir()
    source.write_text("# Note\n")
    state = LoopState(
        current_prompt="create markdown",
        current_role_suffix="",
        current_artifacts_dir=ctx.artifacts_dir,
        loop_outcome="completed",
        sdd_spec_path=None,
        original_prompt="create markdown",
    )
    chat = tmp_path / "chat.md"

    def fake_render_markdown_pdf(
        src: Path,
        dest: Path,
        *,
        progress=None,
        **kwargs,
    ) -> Path:
        if progress is not None:
            progress(
                MarkdownPdfProgressEvent(
                    stage="source_started",
                    source_path=str(src),
                    pdf_path=str(dest),
                )
            )
            progress(
                MarkdownPdfProgressEvent(
                    stage="engine_started",
                    source_path=str(src),
                    pdf_path=str(dest),
                    engine="wkhtmltopdf",
                )
            )
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"%PDF")
        if progress is not None:
            progress(
                MarkdownPdfProgressEvent(
                    stage="source_succeeded",
                    source_path=str(src),
                    pdf_path=str(dest),
                    engine="wkhtmltopdf",
                )
            )
        return dest

    with (
        patch("sase.axe.run_agent_exec.save_chat_history", return_value=str(chat)),
        patch(
            "sase.axe.image_attachments.collect_agent_markdown_paths",
            return_value=[str(source)],
        ),
        patch("sase.axe.image_attachments.collect_agent_image_paths", return_value=[]),
        patch(
            "sase.attachments.markdown_pdf.render_markdown_pdf",
            side_effect=fake_render_markdown_pdf,
        ),
    ):
        _finalize_loop(
            ctx,
            state,
            RetryTracker(retry_cfg=None),
            SimpleNamespace(response_text="done"),
        )

    output = capsys.readouterr().out
    assert "Preparing PDFs from Markdown... found 1, cap" in output
    assert "[PDF] 1/1 trying wkhtmltopdf: docs/note.md" in output
    workflow_state = json.loads((artifacts / "workflow_state.json").read_text())
    assert workflow_state["pdf_status"] == {
        "stage": "completed",
        "total": 1,
        "generated": 1,
        "skipped": 0,
        "cap": MAX_MARKDOWN_PDF_ATTACHMENTS,
        "active": False,
    }
    assert "activity" not in workflow_state


def test_finalize_loop_records_markdown_pdf_limit_reason(
    tmp_path: Path,
) -> None:
    ctx = _make_ctx(tmp_path, is_home_mode=False)
    artifacts = Path(ctx.artifacts_dir)
    (artifacts / "workflow_state.json").write_text(
        json.dumps({"workflow_name": "run", "status": "running", "steps": []})
    )
    state = LoopState(
        current_prompt="create many markdown files",
        current_role_suffix="",
        current_artifacts_dir=ctx.artifacts_dir,
        loop_outcome="completed",
        sdd_spec_path=None,
        original_prompt="create many markdown files",
    )
    sources = _write_markdown_sources(tmp_path, MAX_MARKDOWN_PDF_ATTACHMENTS + 1)

    with (
        patch(
            "sase.axe.run_agent_exec.save_chat_history",
            return_value=str(tmp_path / "chat.md"),
        ),
        patch(
            "sase.axe.image_attachments.collect_agent_markdown_paths",
            return_value=sources,
        ),
        patch("sase.axe.image_attachments.collect_agent_image_paths", return_value=[]),
    ):
        _finalize_loop(
            ctx,
            state,
            RetryTracker(retry_cfg=None),
            SimpleNamespace(response_text="done"),
        )

    workflow_state = json.loads((artifacts / "workflow_state.json").read_text())
    assert workflow_state["pdf_status"]["stage"] == "completed"
    assert workflow_state["pdf_status"]["skipped"] == MAX_MARKDOWN_PDF_ATTACHMENTS + 1
    assert workflow_state["pdf_status"]["reason"].startswith("over attachment limit")


def _write_markdown_sources(tmp_path: Path, count: int) -> list[str]:
    docs = tmp_path / "docs"
    docs.mkdir(exist_ok=True)
    sources = []
    for index in range(count):
        path = docs / f"note_{index:02d}.md"
        path.write_text(f"# Note {index}\n")
        sources.append(str(path))
    return sources


def _run(cwd: Path, *args: str) -> None:
    subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True)


def test_publish_phase_env_sets_both_vars_to_phase(tmp_path: Path, monkeypatch) -> None:
    """The helper publishes the current phase's artifacts dir + 14-digit timestamp."""
    monkeypatch.delenv("SASE_AGENT_TIMESTAMP", raising=False)
    monkeypatch.delenv("SASE_ARTIFACTS_DIR", raising=False)
    monkeypatch.setenv("SASE_AGENT_ROOT_TIMESTAMP", "20260501090000")

    phase_dir = tmp_path / "20260501123045"
    phase_dir.mkdir()
    _publish_phase_env(str(phase_dir))

    import os as _os

    assert _os.environ["SASE_ARTIFACTS_DIR"] == str(phase_dir)
    assert _os.environ["SASE_AGENT_TIMESTAMP"] == "20260501123045"
    assert _os.environ["SASE_AGENT_ROOT_TIMESTAMP"] == "20260501090000"


def test_run_execution_loop_publishes_phase_timestamp(
    tmp_path: Path, monkeypatch
) -> None:
    """When the loop runs, SASE_AGENT_TIMESTAMP is set to the current phase's
    14-digit timestamp (matching the agent row's raw_suffix), not the original
    launch timestamp inherited from the parent runner. This is the bug from
    followup_plan_notification_routing.md: PlanApproval / UserQuestion
    notifications emitted from a followup were carrying the original launch
    timestamp, and the TUI router silently dropped them on the floor.
    """
    monkeypatch.setenv("SASE_AGENT_TIMESTAMP", "260408_120000")
    monkeypatch.delenv("SASE_AGENT_ROOT_TIMESTAMP", raising=False)

    artifacts = tmp_path / "20260408120000"
    artifacts.mkdir()
    ctx = AgentExecContext(
        cl_name="test-cl",
        project_file=str(tmp_path / "project.sase"),
        workspace_dir=str(tmp_path),
        output_path=str(tmp_path / "output.log"),
        workspace_num=1,
        timestamp="20260408_120000",
        update_target="",
        project_name="sase",
        is_home_mode=False,
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
    anon_workflow = SimpleNamespace(name="anon", xprompts={})
    final_result = _AgentExecResult(success=True, current_artifacts_dir=str(artifacts))
    observed_timestamp: dict[str, str] = {}
    observed_root_timestamp: dict[str, str] = {}

    def _capture_env(*_args, **_kwargs):
        import os as _os

        observed_timestamp["value"] = _os.environ.get("SASE_AGENT_TIMESTAMP", "")
        observed_root_timestamp["value"] = _os.environ.get(
            "SASE_AGENT_ROOT_TIMESTAMP", ""
        )
        return SimpleNamespace(response_text="")

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
        patch(
            "sase.xprompt.workflow_runner.execute_workflow",
            side_effect=_capture_env,
        ),
        patch("sase.axe.run_agent_exec.was_killed", return_value=False),
        patch("sase.axe.run_agent_exec.reset_killed"),
        patch("sase.axe.run_agent_exec._finalize_loop", return_value=final_result),
    ):
        run_execution_loop(ctx, "prompt")

    # The phase timestamp must match the artifacts dir basename (14-digit),
    # NOT the inherited YYmmdd_HHMMSS launch-time value.
    assert observed_timestamp["value"] == "20260408120000"
    assert observed_root_timestamp["value"] == "20260408120000"


def test_finalize_loop_restores_original_agent_timestamp(
    tmp_path: Path, monkeypatch
) -> None:
    """_finalize_loop restores SASE_AGENT_TIMESTAMP to its pre-loop value so
    post-loop callers (e.g. commit stop hook session-dedup keys) keep their
    original semantics.
    """
    monkeypatch.setenv("SASE_AGENT_TIMESTAMP", "260408_120000")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", "/should/be/cleared")
    monkeypatch.setenv("SASE_AGENT_ROOT_TIMESTAMP", "20260408120000")

    ctx = _make_ctx(tmp_path, is_home_mode=True, project_name="home")
    state = LoopState(
        current_prompt="prompt",
        current_role_suffix="",
        current_artifacts_dir=ctx.artifacts_dir,
        loop_outcome="completed",
        sdd_spec_path=None,
        original_prompt="prompt",
        original_agent_timestamp="260408_120000",
    )
    chat = tmp_path / "chat.md"

    # Pretend the phase env got rewritten by _publish_phase_env earlier in the loop.
    import os as _os

    _os.environ["SASE_AGENT_TIMESTAMP"] = "20260408120000"
    _os.environ["SASE_AGENT_ROOT_TIMESTAMP"] = "20260408120000"

    with (
        patch("sase.axe.run_agent_exec.save_chat_history", return_value=str(chat)),
        patch(
            "sase.axe.image_attachments.collect_agent_markdown_paths",
            return_value=[],
        ),
        patch("sase.axe.image_attachments.collect_agent_image_paths", return_value=[]),
    ):
        _finalize_loop(
            ctx,
            state,
            RetryTracker(retry_cfg=None),
            SimpleNamespace(response_text="done"),
        )

    assert _os.environ.get("SASE_AGENT_TIMESTAMP") == "260408_120000"
    assert "SASE_ARTIFACTS_DIR" not in _os.environ
    assert "SASE_AGENT_ROOT_TIMESTAMP" not in _os.environ


def test_finalize_loop_clears_agent_timestamp_when_unset_at_entry(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """If SASE_AGENT_TIMESTAMP wasn't set at loop entry, finalize clears it
    rather than leaking the per-phase value.
    """
    monkeypatch.delenv("SASE_AGENT_TIMESTAMP", raising=False)

    ctx = _make_ctx(tmp_path, is_home_mode=True, project_name="home")
    state = LoopState(
        current_prompt="prompt",
        current_role_suffix="",
        current_artifacts_dir=ctx.artifacts_dir,
        loop_outcome="completed",
        sdd_spec_path=None,
        original_prompt="prompt",
        original_agent_timestamp=None,
    )
    chat = tmp_path / "chat.md"

    import os as _os

    _os.environ["SASE_AGENT_TIMESTAMP"] = "20260408120000"
    _os.environ["SASE_AGENT_ROOT_TIMESTAMP"] = "20260408120000"

    with (
        patch("sase.axe.run_agent_exec.save_chat_history", return_value=str(chat)),
        patch(
            "sase.axe.image_attachments.collect_agent_markdown_paths",
            return_value=[],
        ),
        patch("sase.axe.image_attachments.collect_agent_image_paths", return_value=[]),
    ):
        _finalize_loop(
            ctx,
            state,
            RetryTracker(retry_cfg=None),
            SimpleNamespace(response_text="done"),
        )

    assert "SASE_AGENT_TIMESTAMP" not in _os.environ
    assert "SASE_AGENT_ROOT_TIMESTAMP" not in _os.environ
