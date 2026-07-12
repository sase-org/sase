"""Tests for run_agent_exec finalize attachments from SDD repositories."""

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from sase.axe.run_agent_exec import AgentExecContext, LoopState, _finalize_loop
from sase.axe.run_agent_exec_finalize import _sdd_repo_scans
from sase.axe.run_agent_exec_retry import RetryTracker
from sase.axe.run_agent_runner_finalize import send_completion_notification
from sase.core.agent_artifact_facade import list_agent_artifacts
from sase.sdd.store import SddStore

from tests._axe_run_agent_exec_helpers import make_exec_ctx
from tests._axe_run_agent_exec_helpers import run_command


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
    assert separate_scan[0].exclude is not None
    assert separate_scan[0].exclude("plans/202607/prompts/foo.md") is True
    assert separate_scan[0].exclude("plans/202607/foo.md") is False

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

    plan = sdd_repo / "plans" / "202607" / "foo.md"
    prompt = sdd_repo / "plans" / "202607" / "prompts" / "foo.md"
    image = sdd_repo / "research" / "diagram.png"
    plan.parent.mkdir(parents=True)
    prompt.parent.mkdir()
    image.parent.mkdir()
    plan.write_text("# Plan\n")
    prompt.write_text("# Prompt snapshot\n")
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
        artifacts / "markdown_pdfs" / "sase__sdd__plans__202607__foo.md.pdf"
    )
    image_source = str(image.resolve())
    assert result.markdown_pdf_paths == [expected_pdf]
    assert result.image_paths == [image_source]

    done = json.loads((artifacts / "done.json").read_text())
    assert done["markdown_pdf_paths"] == [expected_pdf]
    assert done["image_paths"] == [image_source]
    assert json.loads((artifacts / "markdown_pdfs" / "index.json").read_text()) == [
        {"source_path": str(plan.resolve()), "pdf_path": expected_pdf}
    ]

    artifacts_by_source = {
        artifact.source_path: artifact
        for artifact in list_agent_artifacts(artifacts)
        if artifact.source_path
    }
    assert artifacts_by_source[str(plan.resolve())].kind == "pdf"
    assert str(prompt.resolve()) not in artifacts_by_source
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


def _git_stdout(cwd: Path, *args: str) -> str:
    result = subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True)
    return result.stdout.strip()
