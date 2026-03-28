"""Tests for sdd/ subpackage - SDD file writing utilities."""

import os
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from sase.axe.run_agent_exec_plan import _commit_sdd_files
from sase.sdd.beads import init_beads
from sase.sdd.files import (
    get_primary_workspace_dir,
    commit_sdd_files,
    get_sdd_dir,
    update_spec_with_qa,
    write_sdd_files,
)


# ---------------------------------------------------------------------------
# get_primary_workspace_dir
# ---------------------------------------------------------------------------


def test_primary_workspace_dir_ws1() -> None:
    assert (
        get_primary_workspace_dir("/home/user/myproject", 1) == "/home/user/myproject"
    )


def test_primary_workspace_dir_ws0() -> None:
    assert (
        get_primary_workspace_dir("/home/user/myproject", 0) == "/home/user/myproject"
    )


def test_primary_workspace_dir_ws2() -> None:
    result = get_primary_workspace_dir("/home/user/myproject_2", 2)
    assert result == "/home/user/myproject"


def test_primary_workspace_dir_ws3() -> None:
    result = get_primary_workspace_dir("/home/user/myproject_3", 3)
    assert result == "/home/user/myproject"


def test_primary_workspace_dir_suffix_in_parent_component() -> None:
    """Suffix in a parent path component, not the final one."""
    result = get_primary_workspace_dir("/google/src/cloud/bbugyi/pat_102/google3", 102)
    assert result == "/google/src/cloud/bbugyi/pat/google3"


def test_primary_workspace_dir_no_suffix() -> None:
    """If workspace dir doesn't end with _N suffix, return as-is."""
    result = get_primary_workspace_dir("/home/user/myproject", 2)
    assert result == "/home/user/myproject"


def test_primary_workspace_dir_trailing_slash() -> None:
    result = get_primary_workspace_dir("/home/user/myproject_2/", 2)
    assert result == "/home/user/myproject"


def test_primary_workspace_dir_prefers_project_workspace_dir() -> None:
    with (
        patch("sase.sdd.files.Path.home", return_value=Path("/home/user")),
        patch("sase.workspace_provider.get_workspace_name", return_value="myproject"),
        patch(
            "sase.workspace_provider.utils.parse_workspace_dir",
            return_value="/home/user/myproject",
        ),
    ):
        result = get_primary_workspace_dir("/home/user/myproject_2", 1)
    assert result == "/home/user/myproject"


# ---------------------------------------------------------------------------
# get_sdd_dir
# ---------------------------------------------------------------------------


def test_get_sdd_dir_version_controlled() -> None:
    result = get_sdd_dir("/home/user/project", 1, version_controlled=True)
    assert result == Path("/home/user/project")


def test_get_sdd_dir_not_version_controlled() -> None:
    result = get_sdd_dir("/home/user/project", 1, version_controlled=False)
    assert result == Path("/home/user/project/.sase/sdd")


def test_get_sdd_dir_not_version_controlled_ws2() -> None:
    result = get_sdd_dir("/home/user/project_2", 2, version_controlled=False)
    assert result == Path("/home/user/project/.sase/sdd")


def test_get_sdd_dir_not_version_controlled_suffix_in_parent() -> None:
    result = get_sdd_dir(
        "/google/src/cloud/bbugyi/pat_102/google3", 102, version_controlled=False
    )
    assert result == Path("/google/src/cloud/bbugyi/pat/google3/.sase/sdd")


# ---------------------------------------------------------------------------
# write_sdd_files
# ---------------------------------------------------------------------------


def test_write_sdd_files() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        sdd_dir = Path(tmpdir)
        plan_file = sdd_dir / "source_plan.yaml"
        plan_file.write_text("steps:\n  - do stuff\n", encoding="utf-8")

        spec_path, plan_path = write_sdd_files(
            sdd_dir, "my_plan", "# My Spec\nDetails here", str(plan_file)
        )

        assert spec_path.exists()
        assert plan_path.exists()
        assert spec_path.read_text(encoding="utf-8") == "# My Spec\nDetails here"
        plan_text = plan_path.read_text(encoding="utf-8")
        assert plan_text.startswith("---\ncreate_time:")
        assert "steps:" in plan_text


def test_write_sdd_files_missing_plan() -> None:
    """If source plan file doesn't exist, plan_path is not written."""
    with tempfile.TemporaryDirectory() as tmpdir:
        sdd_dir = Path(tmpdir)
        spec_path, plan_path = write_sdd_files(
            sdd_dir, "my_plan", "spec content", "/nonexistent/plan.yaml"
        )
        assert spec_path.exists()
        assert not plan_path.exists()


def test_write_sdd_files_creates_dirs() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        sdd_dir = Path(tmpdir) / "nested" / "sdd"
        plan_file = Path(tmpdir) / "plan.yaml"
        plan_file.write_text("plan", encoding="utf-8")

        write_sdd_files(sdd_dir, "test", "spec", str(plan_file))
        assert (sdd_dir / "specs").is_dir()
        assert (sdd_dir / "plans").is_dir()


# ---------------------------------------------------------------------------
# update_spec_with_qa
# ---------------------------------------------------------------------------


def test_update_spec_with_qa() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        spec_path = Path(tmpdir) / "spec.md"
        spec_path.write_text("# Spec\nOriginal content", encoding="utf-8")

        update_spec_with_qa(spec_path, "## Q&A\nQ: Why?\nA: Because.")

        content = spec_path.read_text(encoding="utf-8")
        assert "Original content" in content
        assert "## Q&A" in content
        assert "Q: Why?" in content


def test_update_spec_with_qa_missing_file() -> None:
    """No-op if spec file doesn't exist."""
    update_spec_with_qa(Path("/nonexistent/spec.md"), "qa content")
    # Should not raise


# ---------------------------------------------------------------------------
# init_beads
# ---------------------------------------------------------------------------


def testinit_beads_creates_sdd_git_repo() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        with (
            patch("sase.sdd.beads.subprocess.run") as mock_run,
            patch("sase.sdd.beads.BeadProject.init") as mock_bead_init,
        ):
            mock_run.return_value = subprocess.CompletedProcess([], 0)
            result = init_beads(tmpdir, 1)

        assert result == Path(tmpdir) / ".sase" / "sdd"
        assert result.is_dir()
        # Verify .gitignore was created
        sdd_dir = Path(tmpdir) / ".sase" / "sdd"
        gitignore = sdd_dir / ".gitignore"
        assert gitignore.exists()
        assert "beads/beads.db" in gitignore.read_text(encoding="utf-8")
        # Verify BeadProject.init was called with sdd_dir and non-VC dirname
        mock_bead_init.assert_called_once_with(sdd_dir, beads_dirname="beads")


def testinit_beads_idempotent() -> None:
    """Calling init_beads twice should not error."""
    with tempfile.TemporaryDirectory() as tmpdir:
        sdd_dir = Path(tmpdir) / ".sase" / "sdd"
        sdd_dir.mkdir(parents=True)
        # Simulate existing git repo
        (sdd_dir / ".git").mkdir()
        # Simulate existing beads inside sdd_dir (non-VC uses "beads" without dot)
        (sdd_dir / "beads").mkdir()
        # Simulate existing .gitignore
        (sdd_dir / ".gitignore").write_text("beads/beads.db\n", encoding="utf-8")

        with patch("sase.sdd.beads.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess([], 0)
            result = init_beads(tmpdir, 1)
        assert result == sdd_dir


# ---------------------------------------------------------------------------
# commit_sdd_files
# ---------------------------------------------------------------------------


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

        # Write a file and commit it
        (sdd_dir / "test.md").write_text("hello", encoding="utf-8")
        commit_sdd_files(sdd_dir, "Test commit")

        # Verify commit exists
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

        # Call with no files — should not error or create empty commit
        commit_sdd_files(sdd_dir, "Empty commit")

        log = subprocess.run(
            ["git", "log", "--oneline"],
            cwd=sdd_dir,
            capture_output=True,
            text=True,
        )
        # No commits should exist
        assert log.stdout.strip() == ""


def test_commit_sdd_files_not_git_repo() -> None:
    """No-op if sdd_dir is not a git repo."""
    with tempfile.TemporaryDirectory() as tmpdir:
        sdd_dir = Path(tmpdir)
        commit_sdd_files(sdd_dir, "Should not error")
        # Should not raise


# ---------------------------------------------------------------------------
# _commit_sdd_files (run_agent_exec_plan)
# ---------------------------------------------------------------------------


def test_commit_sdd_files_passes_tempfile_to_m() -> None:
    """_commit_sdd_files writes the message to a temp file and passes its path to -m."""
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = tmpdir
        specs = Path(ws) / "specs"
        plans = Path(ws) / "plans"
        specs.mkdir()
        plans.mkdir()
        (specs / "my_plan.md").write_text("spec", encoding="utf-8")
        (plans / "my_plan.md").write_text("plan", encoding="utf-8")

        captured_msg_content: list[str] = []

        def fake_run(
            cmd: list[str], **kwargs: object
        ) -> subprocess.CompletedProcess[str]:
            # Find -m arg and read the file it points to
            m_idx = cmd.index("-m")
            msg_path = cmd[m_idx + 1]
            assert os.path.isfile(msg_path), (
                f"-m should point to a file, got: {msg_path}"
            )
            with open(msg_path, encoding="utf-8") as f:
                captured_msg_content.append(f.read())
            return subprocess.CompletedProcess(cmd, 0)

        with patch("sase.axe.run_agent_exec_plan.subprocess.run", side_effect=fake_run):
            _commit_sdd_files(ws, "my_plan")

        assert len(captured_msg_content) == 1
        assert captured_msg_content[0] == "chore: Add SDD spec and plan for my_plan"


def test_commit_sdd_files_passes_f_flags() -> None:
    """_commit_sdd_files passes -f for each existing spec/plan file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = tmpdir
        specs = Path(ws) / "specs"
        plans = Path(ws) / "plans"
        specs.mkdir()
        plans.mkdir()
        spec_file = specs / "my_plan.md"
        plan_file = plans / "my_plan.md"
        spec_file.write_text("spec", encoding="utf-8")
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
        # Collect all -f values
        f_values = [cmd[i + 1] for i, v in enumerate(cmd) if v == "-f"]
        assert str(spec_file) in f_values
        assert str(plan_file) in f_values


def test_commit_sdd_files_spec_only() -> None:
    """Only spec file exists — should still invoke sase commit with one -f."""
    with tempfile.TemporaryDirectory() as tmpdir:
        ws = tmpdir
        specs = Path(ws) / "specs"
        specs.mkdir()
        (specs / "only_spec.md").write_text("spec", encoding="utf-8")

        captured_cmd: list[list[str]] = []

        def fake_run(
            cmd: list[str], **kwargs: object
        ) -> subprocess.CompletedProcess[str]:
            captured_cmd.append(list(cmd))
            return subprocess.CompletedProcess(cmd, 0)

        with patch("sase.axe.run_agent_exec_plan.subprocess.run", side_effect=fake_run):
            _commit_sdd_files(ws, "only_spec")

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
        specs = Path(ws) / "specs"
        specs.mkdir()
        (specs / "fail.md").write_text("spec", encoding="utf-8")

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
