"""Shared helpers for Codex commit-stop fallback tests."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_REAL_POPEN = subprocess.Popen


def _run_real_subprocess(
    args: list[str],
    *,
    cwd: Path,
    capture_output: bool = False,
) -> subprocess.CompletedProcess[str]:
    current_popen = subprocess.Popen
    subprocess.Popen = _REAL_POPEN
    try:
        return subprocess.run(
            args,
            cwd=cwd,
            check=True,
            capture_output=capture_output,
            text=True,
        )
    finally:
        subprocess.Popen = current_popen


def init_dirty_project(repo: Path, relpath: str = "src/foo.py") -> Path:
    repo.mkdir(parents=True, exist_ok=True)
    _run_real_subprocess(["git", "init", "-q"], cwd=repo)
    _run_real_subprocess(["git", "config", "user.name", "SASE Test"], cwd=repo)
    _run_real_subprocess(
        ["git", "config", "user.email", "sase-test@example.invalid"],
        cwd=repo,
    )
    (repo / "README.md").write_text("fixture\n", encoding="utf-8")
    _run_real_subprocess(["git", "add", "README.md"], cwd=repo)
    _run_real_subprocess(["git", "commit", "-q", "-m", "initial"], cwd=repo)
    dirty = repo / relpath
    dirty.parent.mkdir(parents=True, exist_ok=True)
    dirty.write_text("dirty\n", encoding="utf-8")
    return dirty


def commit_all(repo: Path, message: str = "finalize dirty work") -> None:
    _run_real_subprocess(["git", "add", "-A"], cwd=repo)
    _run_real_subprocess(["git", "commit", "-q", "-m", message], cwd=repo)


def use_git_dirty_details(monkeypatch: pytest.MonkeyPatch) -> None:
    from sase.commit_instructions import build_commit_instruction_message
    from sase.llm_provider import commit_finalizer_git as finalizer_git

    def git_changed_files(project_dir: str) -> list[str]:
        result = _run_real_subprocess(
            ["git", "status", "--porcelain=v1", "--untracked-files=all"],
            cwd=Path(project_dir),
            capture_output=True,
        )
        return finalizer_git.changed_files_from_git_status(result.stdout)

    def git_head(repo_dir: str) -> str:
        try:
            result = _run_real_subprocess(
                ["git", "rev-parse", "HEAD"],
                cwd=Path(repo_dir),
                capture_output=True,
            )
        except subprocess.CalledProcessError:
            return "<unknown-head>"
        return result.stdout.strip() or "<unknown-head>"

    def build(project_dir: str) -> tuple[bool, list[str], str, str]:
        changed_files = git_changed_files(project_dir)
        if not changed_files:
            return (False, [], "", "")
        instruction = build_commit_instruction_message(
            "/sase_git_commit",
            os.environ.get("SASE_COMMIT_METHOD", ""),
            os.environ.get("SASE_BEAD_ID"),
        )
        details = (
            "Uncommitted changes detected:\n"
            + "\n".join(changed_files)
            + f"\n\n{instruction}"
        )
        return (True, changed_files, instruction, details)

    monkeypatch.setattr(
        "sase.llm_provider.commit_finalizer.build_commit_details",
        build,
    )
    monkeypatch.setattr(
        "sase.llm_provider.commit_finalizer_git_progress.git_head_commit_id",
        git_head,
    )


def isolate_fallback_markers(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Point fallback/native marker files into a tmp dir for the test."""
    marker_dir = tmp_path / "markers"
    project_dir = tmp_path / "project"
    marker_dir.mkdir()
    project_dir.mkdir()
    monkeypatch.setenv("SASE_TMPDIR", str(marker_dir))
    monkeypatch.setenv("CODEX_PROJECT_DIR", str(project_dir))


def set_sase_session(monkeypatch: pytest.MonkeyPatch, ts: str = "260511_120000") -> str:
    monkeypatch.setenv("SASE_AGENT_TIMESTAMP", ts)
    return ts


def start_fixture_codex_process(
    events: list[dict[str, object]],
) -> subprocess.Popen[str]:
    lines = [json.dumps(event) for event in events]
    script = f"import sys\nfor line in {lines!r}:\n    print(line, flush=True)\n"
    return subprocess.Popen(
        [sys.executable, "-c", script],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def codex_tool_turn_events(tool_id: str, reply: str) -> list[dict[str, object]]:
    return [
        {
            "type": "item.started",
            "item": {
                "id": tool_id,
                "type": "command_execution",
                "command": f"/bin/zsh -lc 'printf {tool_id}'",
                "aggregated_output": "",
                "exit_code": None,
                "status": "in_progress",
            },
        },
        {
            "type": "item.completed",
            "item": {
                "id": tool_id,
                "type": "command_execution",
                "command": f"/bin/zsh -lc 'printf {tool_id}'",
                "aggregated_output": f"{tool_id}\n",
                "exit_code": 0,
                "status": "completed",
            },
        },
        {
            "type": "item.completed",
            "item": {"id": f"msg_{tool_id}", "type": "agent_message", "text": reply},
        },
    ]
