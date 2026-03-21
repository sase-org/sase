"""Tests for sdd.py - SDD file writing utilities."""

import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch

from sase.sdd import (
    _get_primary_workspace_dir,
    commit_sdd_files,
    get_sdd_dir,
    _init_beads,
    update_spec_with_qa,
    write_sdd_files,
)


# ---------------------------------------------------------------------------
# _get_primary_workspace_dir
# ---------------------------------------------------------------------------


def test_primary_workspace_dir_ws1() -> None:
    assert (
        _get_primary_workspace_dir("/home/user/myproject", 1) == "/home/user/myproject"
    )


def test_primary_workspace_dir_ws0() -> None:
    assert (
        _get_primary_workspace_dir("/home/user/myproject", 0) == "/home/user/myproject"
    )


def test_primary_workspace_dir_ws2() -> None:
    result = _get_primary_workspace_dir("/home/user/myproject_2", 2)
    assert result == "/home/user/myproject"


def test_primary_workspace_dir_ws3() -> None:
    result = _get_primary_workspace_dir("/home/user/myproject_3", 3)
    assert result == "/home/user/myproject"


def test_primary_workspace_dir_no_suffix() -> None:
    """If workspace dir doesn't end with _N suffix, return as-is."""
    result = _get_primary_workspace_dir("/home/user/myproject", 2)
    assert result == "/home/user/myproject"


def test_primary_workspace_dir_trailing_slash() -> None:
    result = _get_primary_workspace_dir("/home/user/myproject_2/", 2)
    assert result == "/home/user/myproject"


def test_primary_workspace_dir_prefers_project_workspace_dir() -> None:
    with (
        patch("sase.sdd.Path.home", return_value=Path("/home/user")),
        patch("sase.workspace_provider.get_workspace_name", return_value="myproject"),
        patch(
            "sase.workspace_provider.utils.parse_workspace_dir",
            return_value="/home/user/myproject",
        ),
    ):
        result = _get_primary_workspace_dir("/home/user/myproject_2", 1)
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
# _init_beads
# ---------------------------------------------------------------------------


def test_init_beads_creates_sdd_git_repo() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        with (
            patch("sase.sdd.subprocess.run") as mock_run,
            patch("sase.sdd.BeadProject.init") as mock_bead_init,
        ):
            mock_run.return_value = subprocess.CompletedProcess([], 0)
            result = _init_beads(tmpdir, 1)

        assert result == Path(tmpdir) / ".sase" / "sdd"
        assert result.is_dir()
        # Verify .gitignore was created
        sdd_dir = Path(tmpdir) / ".sase" / "sdd"
        gitignore = sdd_dir / ".gitignore"
        assert gitignore.exists()
        assert "beads/beads.db" in gitignore.read_text(encoding="utf-8")
        # Verify BeadProject.init was called with sdd_dir and non-VC dirname
        mock_bead_init.assert_called_once_with(sdd_dir, beads_dirname="beads")


def test_init_beads_idempotent() -> None:
    """Calling _init_beads twice should not error."""
    with tempfile.TemporaryDirectory() as tmpdir:
        sdd_dir = Path(tmpdir) / ".sase" / "sdd"
        sdd_dir.mkdir(parents=True)
        # Simulate existing git repo
        (sdd_dir / ".git").mkdir()
        # Simulate existing beads inside sdd_dir (non-VC uses "beads" without dot)
        (sdd_dir / "beads").mkdir()
        # Simulate existing .gitignore
        (sdd_dir / ".gitignore").write_text("beads/beads.db\n", encoding="utf-8")

        with patch("sase.sdd.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess([], 0)
            result = _init_beads(tmpdir, 1)
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
