"""Tests for SDD bead initialization."""

import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch

from sase.sdd.beads import init_beads


def testinit_beads_creates_sdd_git_repo() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        with (
            patch("sase.sdd.beads.subprocess.run") as mock_run,
            patch("sase.sdd.beads.BeadProject.init") as mock_bead_init,
            patch("sase.sdd.beads.commit_sdd_store_files") as mock_commit,
        ):
            mock_run.return_value = subprocess.CompletedProcess([], 0)
            result = init_beads(tmpdir, 1)

        assert result == Path(tmpdir) / ".sase" / "sdd"
        assert result.is_dir()
        sdd_dir = Path(tmpdir) / ".sase" / "sdd"
        gitignore = sdd_dir / ".gitignore"
        assert gitignore.exists()
        gitignore_text = gitignore.read_text(encoding="utf-8")
        assert "beads/beads.db\n" in gitignore_text
        assert "beads/beads.db-shm\n" in gitignore_text
        assert "beads/beads.db-wal\n" in gitignore_text
        mock_bead_init.assert_called_once_with(sdd_dir, beads_dirname="beads")
        args, kwargs = mock_commit.call_args
        assert args[0].sdd_dir == sdd_dir
        assert args[1] == "Initialize beads"
        assert kwargs == {
            "auto_commit_type": "beads",
            "paths": [gitignore, sdd_dir / "beads"],
        }


def testinit_beads_idempotent() -> None:
    """Calling init_beads twice should not error."""
    with tempfile.TemporaryDirectory() as tmpdir:
        sdd_dir = Path(tmpdir) / ".sase" / "sdd"
        sdd_dir.mkdir(parents=True)
        (sdd_dir / ".git").mkdir()
        (sdd_dir / "beads").mkdir()
        (sdd_dir / ".gitignore").write_text("beads/beads.db\n", encoding="utf-8")

        with (
            patch("sase.sdd.beads.subprocess.run") as mock_run,
            patch("sase.sdd.beads.commit_sdd_store_files") as mock_commit,
        ):
            mock_run.return_value = subprocess.CompletedProcess([], 0)
            result = init_beads(tmpdir, 1)
        assert result == sdd_dir
        gitignore_text = (sdd_dir / ".gitignore").read_text(encoding="utf-8")
        assert "beads/beads.db-shm\n" in gitignore_text
        assert "beads/beads.db-wal\n" in gitignore_text
        mock_commit.assert_called_once()


def test_cli_init_beads_vc_ensures_generated_sdd_first(tmp_path: Path) -> None:
    from sase.bead.cli_common import init_beads as cli_init_beads

    with (
        patch("sase.sdd.files.ensure_bare_git_sdd_initialized") as ensure_sdd,
        patch("sase.bead.cli_common.BeadProject.init") as bead_init,
    ):
        cli_init_beads(tmp_path, "sdd/beads")

    ensure_sdd.assert_called_once_with(tmp_path, commit=True, push=False)
    bead_init.assert_called_once_with(tmp_path, beads_dirname="sdd/beads")


def test_cli_init_beads_supports_repository_root_store(tmp_path: Path) -> None:
    from sase.bead.cli_common import init_beads as cli_init_beads
    from sase.bead.project import BEADS_DIRNAME_ROOT

    with (
        patch("subprocess.run") as git_init,
        patch("sase.bead.cli_common.BeadProject.init") as bead_init,
    ):
        cli_init_beads(tmp_path, BEADS_DIRNAME_ROOT)

    git_init.assert_called_once()
    assert (tmp_path / ".gitignore").read_text(encoding="utf-8") == (
        "beads.db\nbeads.db-shm\nbeads.db-wal\n.bead-mutation-lock.holder\n"
    )
    bead_init.assert_called_once_with(
        tmp_path,
        beads_dirname=BEADS_DIRNAME_ROOT,
    )
