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
            patch("sase.sdd.beads.commit_sdd_files") as mock_commit,
        ):
            mock_run.return_value = subprocess.CompletedProcess([], 0)
            result = init_beads(tmpdir, 1)

        assert result == Path(tmpdir) / ".sase" / "sdd"
        assert result.is_dir()
        sdd_dir = Path(tmpdir) / ".sase" / "sdd"
        gitignore = sdd_dir / ".gitignore"
        assert gitignore.exists()
        assert "beads/beads.db" in gitignore.read_text(encoding="utf-8")
        mock_bead_init.assert_called_once_with(sdd_dir, beads_dirname="beads")
        mock_commit.assert_called_once_with(
            sdd_dir,
            "Initialize beads",
            auto_commit_type="beads",
            paths=[gitignore, sdd_dir / "beads"],
        )


def testinit_beads_idempotent() -> None:
    """Calling init_beads twice should not error."""
    with tempfile.TemporaryDirectory() as tmpdir:
        sdd_dir = Path(tmpdir) / ".sase" / "sdd"
        sdd_dir.mkdir(parents=True)
        (sdd_dir / ".git").mkdir()
        (sdd_dir / "beads").mkdir()
        (sdd_dir / ".gitignore").write_text("beads/beads.db\n", encoding="utf-8")

        with patch("sase.sdd.beads.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess([], 0)
            result = init_beads(tmpdir, 1)
        assert result == sdd_dir
