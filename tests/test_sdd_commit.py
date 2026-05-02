"""Tests for committing SDD files."""

import subprocess
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from sase.axe.run_agent_exec_plan import _commit_sdd_files
from sase.sdd.files import commit_sdd_files


def test_commit_sdd_files() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        sdd_dir = Path(tmpdir)
        subprocess.run(["git", "init"], cwd=sdd_dir, check=True, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=sdd_dir,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=sdd_dir,
            check=True,
            capture_output=True,
        )

        (sdd_dir / "test.md").write_text("hello", encoding="utf-8")
        commit_sdd_files(sdd_dir, "Test commit")

        log = subprocess.run(
            ["git", "log", "--oneline"],
            cwd=sdd_dir,
            capture_output=True,
            text=True,
        )
        assert "Test commit" in log.stdout


def test_commit_sdd_files_no_changes() -> None:
    """No-op when there are no changes to commit."""
    with tempfile.TemporaryDirectory() as tmpdir:
        sdd_dir = Path(tmpdir)
        subprocess.run(["git", "init"], cwd=sdd_dir, check=True, capture_output=True)

        commit_sdd_files(sdd_dir, "Empty commit")

        log = subprocess.run(
            ["git", "log", "--oneline"],
            cwd=sdd_dir,
            capture_output=True,
            text=True,
        )
        assert log.stdout.strip() == ""


def test_commit_sdd_files_not_git_repo() -> None:
    """No-op if sdd_dir is not a git repo."""
    with tempfile.TemporaryDirectory() as tmpdir:
        sdd_dir = Path(tmpdir)
        commit_sdd_files(sdd_dir, "Should not error")


def test_commit_sdd_files_passes_tempfile_to_m() -> None:
    """_commit_sdd_files writes the message to a temp file and passes it to -M."""
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = tmpdir
        prompts = Path(ws) / "prompts" / "202603"
        plans = Path(ws) / "plans" / "202603"
        prompts.mkdir(parents=True)
        plans.mkdir(parents=True)
        (prompts / "my_plan.md").write_text("prompt", encoding="utf-8")
        (plans / "my_plan.md").write_text("plan", encoding="utf-8")

        captured_msg_content: list[str] = []

        def fake_run(
            cmd: list[str], **kwargs: object
        ) -> subprocess.CompletedProcess[str]:
            m_idx = cmd.index("-M")
            msg_path = Path(cmd[m_idx + 1])
            assert msg_path.is_file(), f"-M should point to a file, got: {msg_path}"
            captured_msg_content.append(msg_path.read_text(encoding="utf-8"))
            return subprocess.CompletedProcess(cmd, 0)

        with patch("sase.axe.run_agent_exec_plan.subprocess.run", side_effect=fake_run):
            _commit_sdd_files(ws, "my_plan")

        assert len(captured_msg_content) == 1
        assert captured_msg_content[0] == "chore: Add SDD prompt and plan for my_plan"


def test_commit_sdd_files_passes_f_flags() -> None:
    """_commit_sdd_files passes -f for each existing prompt/plan file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = tmpdir
        prompts = Path(ws) / "prompts" / "202603"
        plans = Path(ws) / "plans" / "202603"
        prompts.mkdir(parents=True)
        plans.mkdir(parents=True)
        prompt_file = prompts / "my_plan.md"
        plan_file = plans / "my_plan.md"
        prompt_file.write_text("prompt", encoding="utf-8")
        plan_file.write_text("plan", encoding="utf-8")

        captured_cmd: list[list[str]] = []

        def fake_run(
            cmd: list[str], **kwargs: object
        ) -> subprocess.CompletedProcess[str]:
            captured_cmd.append(list(cmd))
            return subprocess.CompletedProcess(cmd, 0)

        with patch("sase.axe.run_agent_exec_plan.subprocess.run", side_effect=fake_run):
            _commit_sdd_files(ws, "my_plan")

        cmd = captured_cmd[0]
        f_values = [cmd[i + 1] for i, v in enumerate(cmd) if v == "-f"]
        assert str(prompt_file) in f_values
        assert str(plan_file) in f_values


def test_commit_sdd_files_finds_canonical_sdd_paths() -> None:
    """_commit_sdd_files prefers version-controlled sdd/ paths."""
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = tmpdir
        prompts = Path(ws) / "sdd" / "prompts" / "202603"
        epics = Path(ws) / "sdd" / "epics" / "202603"
        prompts.mkdir(parents=True)
        epics.mkdir(parents=True)
        prompt_file = prompts / "my_epic.md"
        plan_file = epics / "my_epic.md"
        prompt_file.write_text("prompt", encoding="utf-8")
        plan_file.write_text("plan", encoding="utf-8")

        captured_cmd: list[list[str]] = []

        def fake_run(
            cmd: list[str], **kwargs: object
        ) -> subprocess.CompletedProcess[str]:
            captured_cmd.append(list(cmd))
            return subprocess.CompletedProcess(cmd, 0)

        with patch("sase.axe.run_agent_exec_plan.subprocess.run", side_effect=fake_run):
            _commit_sdd_files(ws, "my_epic", plan_kind="epics")

        f_values = [
            captured_cmd[0][i + 1] for i, v in enumerate(captured_cmd[0]) if v == "-f"
        ]
        assert str(prompt_file) in f_values
        assert str(plan_file) in f_values


def test_commit_sdd_files_prompt_only() -> None:
    """Only prompt file exists, so sase commit is invoked with one -f."""
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = tmpdir
        prompts = Path(ws) / "prompts" / "202603"
        prompts.mkdir(parents=True)
        (prompts / "only_prompt.md").write_text("prompt", encoding="utf-8")

        captured_cmd: list[list[str]] = []

        def fake_run(
            cmd: list[str], **kwargs: object
        ) -> subprocess.CompletedProcess[str]:
            captured_cmd.append(list(cmd))
            return subprocess.CompletedProcess(cmd, 0)

        with patch("sase.axe.run_agent_exec_plan.subprocess.run", side_effect=fake_run):
            _commit_sdd_files(ws, "only_prompt")

        assert len(captured_cmd) == 1
        cmd = captured_cmd[0]
        f_values = [cmd[i + 1] for i, v in enumerate(cmd) if v == "-f"]
        assert len(f_values) == 1


def test_commit_sdd_files_noop_no_files() -> None:
    """No-op when neither spec nor plan file exists."""
    with tempfile.TemporaryDirectory() as tmpdir:
        mock_run = MagicMock()
        with patch("sase.axe.run_agent_exec_plan.subprocess.run", mock_run):
            _commit_sdd_files(tmpdir, "nonexistent")
        mock_run.assert_not_called()


def test_commit_sdd_files_logs_failure() -> None:
    """Non-zero exit code from sase commit is logged."""
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = tmpdir
        prompts = Path(ws) / "prompts" / "202603"
        prompts.mkdir(parents=True)
        (prompts / "fail.md").write_text("prompt", encoding="utf-8")

        def fake_run(
            cmd: list[str], **kwargs: object
        ) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(cmd, 1, stderr="boom")

        with (
            patch("sase.axe.run_agent_exec_plan.subprocess.run", side_effect=fake_run),
            patch("sase.axe.run_agent_exec_plan.logger") as mock_logger,
        ):
            _commit_sdd_files(ws, "fail")

        mock_logger.warning.assert_called_once()
        assert (
            "exit 1"
            in mock_logger.warning.call_args[0][0]
            % mock_logger.warning.call_args[0][1:]
        )
