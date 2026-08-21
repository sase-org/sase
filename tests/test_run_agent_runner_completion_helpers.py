"""Tests for completion metadata and attachment discovery helpers."""

import json
import subprocess

from sase.axe.image_attachments import collect_agent_image_paths
from sase.axe.run_agent_phases import build_done_marker
from sase.axe.run_agent_runner_finalize import write_error_done_marker


def test_completed_done_marker_includes_markdown_pdf_paths(tmp_path):
    marker = build_done_marker(
        "test-cl",
        "/tmp/project.sase",
        "20260430120000",
        "20260430120000",
        1,
        "/tmp/workspace",
        "/tmp/output.log",
        "completed",
        agent_llm_provider="claude",
        agent_exec_llm_provider="fakey",
        markdown_pdf_paths=[str(tmp_path / "notes.pdf")],
        video_paths=[str(tmp_path / "demo.mp4")],
        finished_at=1_777_000_000.0,
    )

    assert marker["markdown_pdf_paths"] == [str(tmp_path / "notes.pdf")]
    assert marker["video_paths"] == [str(tmp_path / "demo.mp4")]
    assert marker["workspace_dir"] == "/tmp/workspace"
    assert marker["llm_provider"] == "claude"
    assert marker["exec_llm_provider"] == "fakey"
    assert marker["finished_at"] == 1_777_000_000.0


def test_completed_done_marker_defaults_empty_markdown_pdf_paths():
    marker = build_done_marker(
        "test-cl",
        "/tmp/project.sase",
        "20260430120000",
        "20260430120000",
        1,
        "/tmp/workspace",
        "/tmp/output.log",
        "completed",
    )

    assert marker["markdown_pdf_paths"] == []
    assert marker["video_paths"] == []


def test_failed_done_marker_copies_execution_provider_from_agent_meta(tmp_path):
    (tmp_path / "agent_meta.json").write_text(
        json.dumps({"exec_llm_provider": "fakey"}), encoding="utf-8"
    )

    write_error_done_marker(
        current_artifacts_dir=str(tmp_path),
        cl_name="test-cl",
        project_file="/tmp/project.sase",
        timestamp="20260430120000",
        artifacts_timestamp="20260430120000",
        workspace_num=1,
        workspace_dir="/tmp/workspace",
        output_path="/tmp/output.log",
        agent_name="test-agent",
        agent_model="opus",
        agent_llm_provider="claude",
        agent_vcs_provider="git",
        agent_hidden=False,
        error="provider failed",
        traceback_str="traceback",
    )

    marker = json.loads((tmp_path / "done.json").read_text())
    assert marker["llm_provider"] == "claude"
    assert marker["exec_llm_provider"] == "fakey"
    assert isinstance(marker["finished_at"], float)
    assert marker["finished_at"] > 1_700_000_000


def test_collect_agent_image_paths_from_working_tree(tmp_path):
    _run(tmp_path, "git", "init")
    _run(tmp_path, "git", "config", "user.email", "test@example.com")
    _run(tmp_path, "git", "config", "user.name", "Test User")
    (tmp_path / "existing.txt").write_text("base\n")
    (tmp_path / "changed.png").write_bytes(b"old")
    _run(tmp_path, "git", "add", ".")
    _run(tmp_path, "git", "commit", "-m", "base")

    (tmp_path / "changed.png").write_bytes(b"new")
    (tmp_path / "new.webp").write_bytes(b"webp")
    (tmp_path / "notes.txt").write_text("ignore\n")

    assert collect_agent_image_paths(str(tmp_path)) == [
        str((tmp_path / "changed.png").resolve()),
        str((tmp_path / "new.webp").resolve()),
    ]


def test_collect_agent_image_paths_ignores_deleted_missing_and_non_images(tmp_path):
    _run(tmp_path, "git", "init")
    _run(tmp_path, "git", "config", "user.email", "test@example.com")
    _run(tmp_path, "git", "config", "user.name", "Test User")
    (tmp_path / "deleted.gif").write_bytes(b"gif")
    (tmp_path / "notes.txt").write_text("base\n")
    _run(tmp_path, "git", "add", ".")
    _run(tmp_path, "git", "commit", "-m", "base")

    (tmp_path / "deleted.gif").unlink()
    (tmp_path / "notes.txt").write_text("changed\n")
    (tmp_path / "missing.jpg").write_bytes(b"jpg")
    diff_path = tmp_path / "proposal.diff"
    diff_path.write_text(
        "diff --git a/missing.jpg b/missing.jpg\n"
        "new file mode 100644\n"
        "+++ b/missing.jpg\n"
    )
    (tmp_path / "missing.jpg").unlink()

    assert collect_agent_image_paths(str(tmp_path), diff_path=str(diff_path)) == []


def test_collect_agent_image_paths_from_diff_file_when_tree_clean(tmp_path):
    image = tmp_path / "result.jpeg"
    image.write_bytes(b"jpeg")
    diff_path = tmp_path / "commit.diff"
    diff_path.write_text(
        "diff --git a/result.jpeg b/result.jpeg\n"
        "new file mode 100644\n"
        "--- /dev/null\n"
        "+++ b/result.jpeg\n"
    )

    assert collect_agent_image_paths(str(tmp_path), diff_path=str(diff_path)) == [
        str(image.resolve())
    ]


def test_collect_agent_image_paths_from_head_commit(tmp_path):
    _run(tmp_path, "git", "init")
    _run(tmp_path, "git", "config", "user.email", "test@example.com")
    _run(tmp_path, "git", "config", "user.name", "Test User")
    (tmp_path / "base.txt").write_text("base\n")
    _run(tmp_path, "git", "add", ".")
    _run(tmp_path, "git", "commit", "-m", "base")

    image = tmp_path / "committed.jpg"
    image.write_bytes(b"jpg")
    _run(tmp_path, "git", "add", ".")
    _run(tmp_path, "git", "commit", "-m", "add image")

    assert collect_agent_image_paths(str(tmp_path), include_head_commit=True) == [
        str(image.resolve())
    ]


def _run(cwd, *args):
    subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True)
