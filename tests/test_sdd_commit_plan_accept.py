"""Tests for committing SDD files during plan acceptance."""

import subprocess
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from sase.axe.run_agent_exec_plan_accept import _commit_sdd_files


def test_commit_sdd_files_passes_tempfile_to_m() -> None:
    """_commit_sdd_files writes the message to a temp file and passes it to -M."""
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = tmpdir
        plans = Path(ws) / "plans" / "202603"
        plans.mkdir(parents=True)
        (plans / "my_plan.md").write_text("plan", encoding="utf-8")

        captured_msg_content: list[str] = []
        captured_msg_paths: list[Path] = []

        def fake_run(
            cmd: list[str], **kwargs: object
        ) -> subprocess.CompletedProcess[str]:
            m_idx = cmd.index("-M")
            msg_path = Path(cmd[m_idx + 1])
            assert msg_path.is_file(), f"-M should point to a file, got: {msg_path}"
            captured_msg_content.append(msg_path.read_text(encoding="utf-8"))
            captured_msg_paths.append(msg_path)
            return subprocess.CompletedProcess(cmd, 0)

        with patch(
            "sase.axe.run_agent_exec_plan_accept.subprocess.run", side_effect=fake_run
        ):
            assert _commit_sdd_files(ws, "my_plan") is True

        assert len(captured_msg_content) == 1
        assert captured_msg_paths
        assert not captured_msg_paths[0].exists()
        assert (
            captured_msg_content[0]
            == "chore: Add SDD plan for my_plan\n\nSASE_TYPE=sdd"
        )


def test_commit_sdd_files_passes_f_flag_only_for_plan() -> None:
    """_commit_sdd_files ignores retired plans-store prompt snapshots."""
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

        with patch(
            "sase.axe.run_agent_exec_plan_accept.subprocess.run", side_effect=fake_run
        ):
            assert _commit_sdd_files(ws, "my_plan") is True

        cmd = captured_cmd[0]
        f_values = [cmd[i + 1] for i, v in enumerate(cmd) if v == "-f"]
        assert str(prompt_file) not in f_values
        assert str(plan_file) in f_values


def test_commit_sdd_files_finds_canonical_sdd_paths() -> None:
    """_commit_sdd_files prefers version-controlled sdd/ paths."""
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = tmpdir
        prompts = Path(ws) / "sdd" / "prompts" / "202603"
        plans = Path(ws) / "sdd" / "plans" / "202603"
        prompts.mkdir(parents=True)
        plans.mkdir(parents=True)
        prompt_file = prompts / "my_epic.md"
        plan_file = plans / "my_epic.md"
        prompt_file.write_text("prompt", encoding="utf-8")
        plan_file.write_text("plan", encoding="utf-8")

        captured_cmd: list[list[str]] = []

        def fake_run(
            cmd: list[str], **kwargs: object
        ) -> subprocess.CompletedProcess[str]:
            captured_cmd.append(list(cmd))
            return subprocess.CompletedProcess(cmd, 0)

        with patch(
            "sase.axe.run_agent_exec_plan_accept.subprocess.run", side_effect=fake_run
        ):
            assert _commit_sdd_files(ws, "my_epic", plan_tier="epic") is True

        f_values = [
            captured_cmd[0][i + 1] for i, v in enumerate(captured_cmd[0]) if v == "-f"
        ]
        assert str(prompt_file) not in f_values
        assert str(plan_file) in f_values


def test_commit_sdd_files_retired_prompt_snapshot_only_is_noop() -> None:
    """A plans-store prompt snapshot is no longer a commit candidate."""
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = tmpdir
        prompts = Path(ws) / "prompts" / "202603"
        prompts.mkdir(parents=True)
        (prompts / "only_prompt.md").write_text("prompt", encoding="utf-8")

        mock_run = MagicMock()
        with patch("sase.axe.run_agent_exec_plan_accept.subprocess.run", mock_run):
            assert _commit_sdd_files(ws, "only_prompt") is True

        mock_run.assert_not_called()


def test_commit_sdd_files_noop_no_files() -> None:
    """No-op when neither spec nor plan file exists."""
    with tempfile.TemporaryDirectory() as tmpdir:
        mock_run = MagicMock()
        with patch("sase.axe.run_agent_exec_plan_accept.subprocess.run", mock_run):
            assert _commit_sdd_files(tmpdir, "nonexistent") is True
        mock_run.assert_not_called()


def test_commit_sdd_files_logs_failure() -> None:
    """Non-zero exit code from sase commit is logged."""
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = tmpdir
        plans = Path(ws) / "plans" / "202603"
        plans.mkdir(parents=True)
        (plans / "fail.md").write_text("plan", encoding="utf-8")
        captured_msg_paths: list[Path] = []

        def fake_run(
            cmd: list[str], **kwargs: object
        ) -> subprocess.CompletedProcess[str]:
            msg_path = Path(cmd[cmd.index("-M") + 1])
            assert msg_path.is_file()
            captured_msg_paths.append(msg_path)
            return subprocess.CompletedProcess(cmd, 1, stderr="boom")

        with (
            patch(
                "sase.axe.run_agent_exec_plan_accept.subprocess.run",
                side_effect=fake_run,
            ),
            patch("sase.axe.run_agent_exec_plan_accept.logger") as mock_logger,
        ):
            assert _commit_sdd_files(ws, "fail") is False

        mock_logger.warning.assert_called_once()
        assert captured_msg_paths
        assert not captured_msg_paths[0].exists()
        assert (
            "exit 1"
            in mock_logger.warning.call_args[0][0]
            % mock_logger.warning.call_args[0][1:]
        )
