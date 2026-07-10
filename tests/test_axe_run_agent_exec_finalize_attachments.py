"""Tests for run_agent_exec finalize attachment handling."""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from sase.attachments.markdown_pdf import MAX_MARKDOWN_PDF_ATTACHMENTS
from sase.attachments.markdown_pdf import MarkdownPdfProgressEvent
from sase.axe.image_attachments import MAX_COMPLETION_IMAGE_ATTACHMENTS
from sase.axe.run_agent_exec import AgentExecContext, LoopState, _finalize_loop
from sase.axe.run_agent_exec_finalize import _sdd_repo_scans
from sase.axe.run_agent_exec_retry import RetryTracker
from sase.axe.run_agent_runner_finalize import send_completion_notification
from sase.core.agent_artifact_facade import list_agent_artifacts
from sase.sdd.store import SddStore

from tests._axe_run_agent_exec_helpers import make_exec_ctx
from tests._axe_run_agent_exec_helpers import run_command
from tests._axe_run_agent_exec_helpers import write_markdown_sources


def test_finalize_loop_records_markdown_pdfs_images_and_notification_files(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    run_command(workspace, "git", "init")
    run_command(workspace, "git", "config", "user.email", "test@example.com")
    run_command(workspace, "git", "config", "user.name", "Test User")
    (workspace / "base.txt").write_text("base\n")
    run_command(workspace, "git", "add", ".")
    run_command(workspace, "git", "commit", "-m", "base")

    research = workspace / "sdd" / "research" / "example.md"
    notes = workspace / "docs" / "notes.md"
    image = workspace / "assets" / "diagram.png"
    video = workspace / "assets" / "demo.mp4"
    image_source = str(image.resolve())
    video_source = str(video.resolve())
    research.parent.mkdir(parents=True)
    notes.parent.mkdir()
    image.parent.mkdir()
    research.write_text("# Research\n")
    notes.write_text("# Notes\n")
    image.write_bytes(b"\x89PNG\r\n\x1a\n")
    video.write_bytes(b"mp4")

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
        patch(
            "sase.axe.run_agent_exec_finalize.save_chat_history",
            return_value=str(chat),
        ),
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
    assert result.image_paths == [image_source]
    assert result.video_paths == [video_source]

    done = json.loads((artifacts / "done.json").read_text())
    assert done["markdown_pdf_paths"] == expected_pdfs
    assert done["image_paths"] == [image_source]
    assert done["video_paths"] == [video_source]
    assert sorted(path.name for path in pdf_dir.glob("*.pdf")) == [
        "docs__notes.md.pdf",
        "sdd__research__example.md.pdf",
    ]
    assert json.loads((pdf_dir / "index.json").read_text()) == [
        {"source_path": str(notes.resolve()), "pdf_path": expected_pdfs[0]},
        {"source_path": str(research.resolve()), "pdf_path": expected_pdfs[1]},
    ]

    artifact_rows = list_agent_artifacts(artifacts)
    rows_by_source = {
        artifact.source_path: artifact
        for artifact in artifact_rows
        if artifact.source_path
    }
    assert rows_by_source[image_source].kind == "image"
    video_artifact = rows_by_source[video_source]
    assert video_artifact.kind == "file"
    assert video_artifact.explicit is False
    persisted_video_path = Path(video_artifact.path)
    assert persisted_video_path.is_file()

    video.unlink()
    artifact_rows_after_cleanup = list_agent_artifacts(artifacts)
    rows_after_cleanup = {
        artifact.source_path: artifact
        for artifact in artifact_rows_after_cleanup
        if artifact.source_path
    }
    assert rows_after_cleanup[video_source].path == str(persisted_video_path)
    assert Path(rows_after_cleanup[video_source].path).is_file()

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
            video_paths=result.video_paths,
            output_path=ctx.output_path,
            step_output=result.step_output,
            prompt=state.original_prompt,
            outcome=result.outcome,
        )

    assert notify.call_args.kwargs["extra_files"] == [
        str(chat),
        *expected_pdfs,
        image_source,
        video_source,
    ]


def test_finalize_loop_retains_images_omitted_from_completion_notification(
    tmp_path: Path,
) -> None:
    ctx = make_exec_ctx(tmp_path, is_home_mode=False)
    state = LoopState(
        current_prompt="create many images",
        current_role_suffix="",
        current_artifacts_dir=ctx.artifacts_dir,
        loop_outcome="completed",
        sdd_spec_path=None,
        original_prompt="create many images",
    )
    chat = tmp_path / "chat.md"
    image_dir = tmp_path / "images"
    image_dir.mkdir()
    image_paths = []
    for index in range(MAX_COMPLETION_IMAGE_ATTACHMENTS + 1):
        image = image_dir / f"screen_{index:02d}.png"
        image.write_bytes(b"png")
        image_paths.append(str(image))

    with (
        patch(
            "sase.axe.run_agent_exec_finalize.save_chat_history",
            return_value=str(chat),
        ),
        patch(
            "sase.axe.image_attachments.collect_agent_markdown_paths",
            return_value=[],
        ),
        patch(
            "sase.axe.image_attachments.collect_agent_image_paths",
            return_value=image_paths,
        ),
        patch(
            "sase.axe.image_attachments.collect_agent_video_paths",
            return_value=[],
        ),
    ):
        result = _finalize_loop(
            ctx,
            state,
            RetryTracker(retry_cfg=None),
            SimpleNamespace(response_text="done"),
        )

    assert result.image_paths == image_paths
    done = json.loads((Path(ctx.artifacts_dir) / "done.json").read_text())
    assert done["image_paths"] == image_paths
    artifact_image_sources = {
        artifact.source_path
        for artifact in list_agent_artifacts(ctx.artifacts_dir)
        if artifact.kind == "image"
    }
    assert artifact_image_sources == set(image_paths)

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
            current_artifacts_dir=result.current_artifacts_dir,
            markdown_pdf_paths=result.markdown_pdf_paths,
            image_paths=result.image_paths,
            video_paths=result.video_paths,
            output_path=ctx.output_path,
            step_output=result.step_output,
            prompt=state.original_prompt,
            outcome=result.outcome,
        )

    assert notify.call_args.kwargs["extra_files"] == [str(chat)]
    assert notify.call_args.kwargs["notes"][-1] == (
        f"Discovered {len(image_paths)} images; skipped image attachments because "
        f"the limit is {MAX_COMPLETION_IMAGE_ATTACHMENTS}."
    )


def test_sdd_repo_scans_pass_attribution_and_storage_policy(tmp_path: Path) -> None:
    ctx = make_exec_ctx(tmp_path, is_home_mode=False)
    ctx.agent_meta = {"sdd_base_sha": "context-base"}
    sdd_repo = tmp_path / "sdd"
    (sdd_repo / ".git").mkdir(parents=True)

    with patch(
        "sase.sdd.store.resolve_sdd_store",
        return_value=SddStore(
            storage="separate_repo",
            sdd_dir=sdd_repo,
            repo_root=sdd_repo,
        ),
    ):
        separate_scan = _sdd_repo_scans(ctx)

    assert len(separate_scan) == 1
    assert separate_scan[0].base_sha == "context-base"
    assert separate_scan[0].agent_name == "agent"
    assert separate_scan[0].include_working_tree is True

    ctx.agent_name = None
    ctx.agent_meta = {}
    (Path(ctx.artifacts_dir) / "agent_meta.json").write_text(
        json.dumps({"name": "transcript-agent", "sdd_base_sha": "transcript-base"})
    )
    with patch(
        "sase.sdd.store.resolve_sdd_store",
        return_value=SddStore(
            storage="local",
            sdd_dir=sdd_repo,
            repo_root=sdd_repo,
        ),
    ):
        local_scan = _sdd_repo_scans(ctx)

    assert len(local_scan) == 1
    assert local_scan[0].base_sha == "transcript-base"
    assert local_scan[0].agent_name == "transcript-agent"
    assert local_scan[0].include_working_tree is False


def test_finalize_loop_discovers_committed_separate_sdd_artifacts(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    sdd_repo = workspace / ".sase" / "sdd"
    sdd_repo.mkdir(parents=True)
    run_command(sdd_repo, "git", "init")
    run_command(sdd_repo, "git", "config", "user.email", "test@example.com")
    run_command(sdd_repo, "git", "config", "user.name", "Test User")
    (sdd_repo / "README.md").write_text("# SDD\n")
    run_command(sdd_repo, "git", "add", ".")
    run_command(sdd_repo, "git", "commit", "-m", "base")
    base_sha = _git_stdout(sdd_repo, "git", "rev-parse", "HEAD")

    research = sdd_repo / "research" / "example.md"
    image = sdd_repo / "research" / "diagram.png"
    research.parent.mkdir()
    research.write_text("# Research\n")
    image.write_bytes(b"\x89PNG\r\n\x1a\n")
    run_command(sdd_repo, "git", "add", ".")
    run_command(
        sdd_repo,
        "git",
        "commit",
        "-m",
        "agent research\n\nSASE_AGENT=agent",
    )

    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "workflow_state.json").write_text(
        json.dumps({"workflow_name": "run", "status": "running", "steps": []})
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
        agent_meta={"sdd_base_sha": base_sha},
        local_xprompts={},
    )
    state = LoopState(
        current_prompt="create SDD attachments",
        current_role_suffix="",
        current_artifacts_dir=str(artifacts),
        loop_outcome="completed",
        sdd_spec_path=None,
        original_prompt="create SDD attachments",
    )

    with (
        patch(
            "sase.axe.run_agent_exec_finalize.save_chat_history",
            return_value=str(chat),
        ),
        patch(
            "sase.sdd.store.resolve_sdd_store",
            return_value=SddStore(
                storage="separate_repo",
                sdd_dir=sdd_repo,
                repo_root=sdd_repo,
            ),
        ),
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

    expected_pdf = str(
        artifacts / "markdown_pdfs" / "sase__sdd__research__example.md.pdf"
    )
    image_source = str(image.resolve())
    assert result.markdown_pdf_paths == [expected_pdf]
    assert result.image_paths == [image_source]

    done = json.loads((artifacts / "done.json").read_text())
    assert done["markdown_pdf_paths"] == [expected_pdf]
    assert done["image_paths"] == [image_source]
    assert json.loads((artifacts / "markdown_pdfs" / "index.json").read_text()) == [
        {"source_path": str(research.resolve()), "pdf_path": expected_pdf}
    ]

    artifacts_by_source = {
        artifact.source_path: artifact
        for artifact in list_agent_artifacts(artifacts)
        if artifact.source_path
    }
    assert artifacts_by_source[str(research.resolve())].kind == "pdf"
    assert artifacts_by_source[image_source].kind == "image"

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
            video_paths=result.video_paths,
            output_path=ctx.output_path,
            step_output=result.step_output,
            prompt=state.original_prompt,
            outcome=result.outcome,
        )

    assert notify.call_args.kwargs["extra_files"] == [
        str(chat),
        expected_pdf,
        image_source,
    ]


def test_finalize_loop_renders_markdown_pdfs_at_attachment_limit(
    tmp_path: Path,
) -> None:
    ctx = make_exec_ctx(tmp_path, is_home_mode=False)
    state = LoopState(
        current_prompt="create markdown",
        current_role_suffix="",
        current_artifacts_dir=ctx.artifacts_dir,
        loop_outcome="completed",
        sdd_spec_path=None,
        original_prompt="create markdown",
    )
    chat = tmp_path / "chat.md"
    sources = write_markdown_sources(tmp_path, MAX_MARKDOWN_PDF_ATTACHMENTS)

    def fake_render_markdown_pdf(src: Path, dest: Path, **kwargs) -> Path:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(f"%PDF {src.name}".encode())
        return dest

    with (
        patch(
            "sase.axe.run_agent_exec_finalize.save_chat_history",
            return_value=str(chat),
        ),
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
    ctx = make_exec_ctx(tmp_path, is_home_mode=False)
    state = LoopState(
        current_prompt="create many markdown files",
        current_role_suffix="",
        current_artifacts_dir=ctx.artifacts_dir,
        loop_outcome="completed",
        sdd_spec_path=None,
        original_prompt="create many markdown files",
    )
    chat = tmp_path / "chat.md"
    sources = write_markdown_sources(tmp_path, MAX_MARKDOWN_PDF_ATTACHMENTS + 1)

    with (
        patch(
            "sase.axe.run_agent_exec_finalize.save_chat_history",
            return_value=str(chat),
        ),
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
    ctx = make_exec_ctx(tmp_path, is_home_mode=False)
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
        patch(
            "sase.axe.run_agent_exec_finalize.save_chat_history",
            return_value=str(chat),
        ),
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
    ctx = make_exec_ctx(tmp_path, is_home_mode=False)
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
    sources = write_markdown_sources(tmp_path, MAX_MARKDOWN_PDF_ATTACHMENTS + 1)

    with (
        patch(
            "sase.axe.run_agent_exec_finalize.save_chat_history",
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


def _git_stdout(cwd: Path, *args: str) -> str:
    import subprocess

    result = subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True)
    return result.stdout.strip()
