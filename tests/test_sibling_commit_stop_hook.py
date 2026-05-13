"""Subprocess tests for the repo-local sibling commit stop hook."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


HOOK = Path(__file__).resolve().parents[1] / "tools" / "sase_sibling_commit_stop_hook"
CODEX_FALLBACK_COMMAND = (
    '"${CODEX_PROJECT_DIR:-$PWD}"/tools/sase_sibling_commit_stop_hook'
)


def _run_hook(
    project_dir: Path,
    tmp_path: Path,
    *,
    timestamp: str = "260425_120000",
    codex: bool = False,
    qwen: bool = False,
    hook_input: dict[str, object] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = {
        "HOME": str(tmp_path / "home"),
        "PATH": os.environ["PATH"],
        "CODEX_PROJECT_DIR": str(project_dir),
        "SASE_AGENT_TIMESTAMP": timestamp,
        "SASE_TMPDIR": str(tmp_path / "sase_tmp"),
    }
    if codex:
        env["CODEX_THREAD_ID"] = "codex-test-thread"
    if qwen:
        # Qwen Code exports both QWEN_PROJECT_DIR and GEMINI_PROJECT_DIR; the
        # hook must classify the session as Qwen rather than Gemini.
        env["QWEN_PROJECT_DIR"] = str(project_dir)
        env["GEMINI_PROJECT_DIR"] = str(project_dir)

    Path(env["HOME"]).mkdir(parents=True, exist_ok=True)
    Path(env["SASE_TMPDIR"]).mkdir(parents=True, exist_ok=True)

    return subprocess.run(
        [str(HOOK)],
        cwd=project_dir,
        env=env,
        input=json.dumps(hook_input) if hook_input is not None else None,
        text=True,
        capture_output=True,
        check=False,
    )


def _run_configured_codex_fallback_command(
    project_dir: Path,
    tmp_path: Path,
    *,
    timestamp: str = "260425_120000",
) -> subprocess.CompletedProcess[str]:
    env = {
        "HOME": str(tmp_path / "home"),
        "PATH": os.environ["PATH"],
        "CODEX_THREAD_ID": "codex-test-thread",
        "SASE_AGENT_TIMESTAMP": timestamp,
        "SASE_TMPDIR": str(tmp_path / "sase_tmp"),
    }

    tools_dir = project_dir / "tools"
    tools_dir.mkdir()
    (tools_dir / "sase_sibling_commit_stop_hook").symlink_to(HOOK)
    Path(env["HOME"]).mkdir(parents=True, exist_ok=True)
    Path(env["SASE_TMPDIR"]).mkdir(parents=True, exist_ok=True)

    return subprocess.run(
        CODEX_FALLBACK_COMMAND,
        cwd=project_dir,
        env=env,
        text=True,
        capture_output=True,
        shell=True,
        check=False,
    )


def _make_project(tmp_path: Path) -> Path:
    project_dir = tmp_path / "sase"
    project_dir.mkdir()
    return project_dir


def _make_dirty_repo(path: Path) -> None:
    path.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    (path / "dirty.txt").write_text("dirty\n", encoding="utf-8")


def test_dirty_primary_sibling_repo_blocks(tmp_path: Path) -> None:
    project_dir = _make_project(tmp_path)
    _make_dirty_repo(tmp_path / "sase-telegram")

    result = _run_hook(project_dir, tmp_path)

    assert result.returncode == 2
    assert result.stdout == ""
    assert (
        "Uncommitted changes detected in sibling repo(s): ../sase-telegram"
        in result.stderr
    )
    assert "cd ../sase-telegram" in result.stderr
    assert "/sase_git_commit" in result.stderr
    assert "git status --short --branch" in result.stderr
    assert "git push" in result.stderr


def test_dirty_ephemeral_sibling_workspace_is_skipped(tmp_path: Path) -> None:
    project_dir = _make_project(tmp_path)
    _make_dirty_repo(tmp_path / "sase-telegram_100")

    result = _run_hook(project_dir, tmp_path)

    assert result.returncode == 0
    assert result.stdout == ""
    assert result.stderr == ""


def test_second_run_with_same_session_exits_cleanly(tmp_path: Path) -> None:
    project_dir = _make_project(tmp_path)
    _make_dirty_repo(tmp_path / "sase-telegram")
    timestamp = "260425_120001"

    first = _run_hook(project_dir, tmp_path, timestamp=timestamp)
    second = _run_hook(project_dir, tmp_path, timestamp=timestamp)

    assert first.returncode == 2
    assert "../sase-telegram" in first.stderr
    assert second.returncode == 0
    assert second.stdout == ""
    assert second.stderr == ""


def test_codex_json_reason_includes_actionable_sibling_details(
    tmp_path: Path,
) -> None:
    project_dir = _make_project(tmp_path)
    _make_dirty_repo(tmp_path / "sase-telegram")

    result = _run_hook(project_dir, tmp_path, codex=True)

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["decision"] == "block"
    assert (
        "Uncommitted changes detected in sibling repo(s): ../sase-telegram"
        in payload["reason"]
    )
    assert "cd ../sase-telegram" in payload["reason"]
    assert "/sase_git_commit" in payload["reason"]
    assert "git status --short --branch" in payload["reason"]
    assert "git push" in payload["reason"]
    assert payload["reason"] in result.stderr


def test_codex_fallback_command_blocks_without_codex_project_dir(
    tmp_path: Path,
) -> None:
    project_dir = _make_project(tmp_path)
    _make_dirty_repo(tmp_path / "sase-telegram")

    result = _run_configured_codex_fallback_command(project_dir, tmp_path)

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["decision"] == "block"
    assert (
        "Uncommitted changes detected in sibling repo(s): ../sase-telegram"
        in payload["reason"]
    )
    assert "cd ../sase-telegram" in payload["reason"]
    assert payload["reason"] in result.stderr


def test_qwen_json_reason_uses_deny_decision(tmp_path: Path) -> None:
    project_dir = _make_project(tmp_path)
    _make_dirty_repo(tmp_path / "sase-telegram")

    result = _run_hook(project_dir, tmp_path, qwen=True)

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["decision"] == "deny"
    assert (
        "Uncommitted changes detected in sibling repo(s): ../sase-telegram"
        in payload["reason"]
    )
    assert "/sase_git_commit" not in payload["reason"]


def test_qwen_stop_hook_active_skips_sibling_check(tmp_path: Path) -> None:
    project_dir = _make_project(tmp_path)
    _make_dirty_repo(tmp_path / "sase-telegram")

    result = _run_hook(
        project_dir,
        tmp_path,
        qwen=True,
        hook_input={"session_id": "nested", "stop_hook_active": True},
    )

    assert result.returncode == 0
    assert result.stdout == ""
    assert result.stderr == ""


def test_multiple_dirty_sibling_repos_lists_all_and_repeats_workflow(
    tmp_path: Path,
) -> None:
    project_dir = _make_project(tmp_path)
    _make_dirty_repo(tmp_path / "sase-alpha")
    _make_dirty_repo(tmp_path / "sase-beta")

    result = _run_hook(project_dir, tmp_path)

    assert result.returncode == 2
    assert "../sase-alpha" in result.stderr
    assert "../sase-beta" in result.stderr
    assert "repeat this workflow for each listed repo" in result.stderr
    assert "cd ../sase-alpha" in result.stderr
