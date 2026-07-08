"""Tests for SDD bead initialization."""

import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.sdd.beads import get_effective_sdd_config, init_beads


def test_effective_sdd_config_treats_bare_git_as_version_controlled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "sase.sdd.store.load_merged_config",
        lambda: {"sdd": {"storage": "auto", "version_controlled": False}},
    )
    monkeypatch.setattr("sase.vcs_provider.detect_vcs", lambda cwd: "bare_git")
    monkeypatch.setattr(
        "sase.workspace_provider.get_sdd_storage_policy_by_vcs",
        lambda vcs_name: "in_tree" if vcs_name == "bare_git" else None,
    )

    assert get_effective_sdd_config(tmp_path) is True


@pytest.mark.parametrize("detected", ["github", "hg", None])
def test_effective_sdd_config_keeps_false_for_non_bare_providers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, detected: str | None
) -> None:
    monkeypatch.setattr(
        "sase.sdd.store.load_merged_config",
        lambda: {"sdd": {"storage": "auto", "version_controlled": False}},
    )
    monkeypatch.setattr("sase.vcs_provider.detect_vcs", lambda cwd: detected)
    monkeypatch.setattr(
        "sase.workspace_provider.get_sdd_storage_policy_by_vcs",
        lambda vcs_name: None,
    )

    assert get_effective_sdd_config(tmp_path) is False


def test_effective_sdd_config_falls_back_to_config_on_detection_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "sase.sdd.store.load_merged_config",
        lambda: {"sdd": {"storage": "auto", "version_controlled": False}},
    )

    def fail(_cwd: str) -> str:
        raise RuntimeError("detection failed")

    monkeypatch.setattr("sase.vcs_provider.detect_vcs", fail)

    assert get_effective_sdd_config(tmp_path) is False


def test_effective_sdd_config_uses_explicit_workspace_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "workspace"
    elsewhere = tmp_path / "elsewhere"
    workspace.mkdir()
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    monkeypatch.setattr(
        "sase.sdd.store.load_merged_config",
        lambda: {"sdd": {"storage": "auto", "version_controlled": False}},
    )

    def detect(cwd: str) -> str | None:
        return "bare_git" if Path(cwd) == workspace else None

    monkeypatch.setattr("sase.vcs_provider.detect_vcs", detect)
    monkeypatch.setattr(
        "sase.workspace_provider.get_sdd_storage_policy_by_vcs",
        lambda vcs_name: "in_tree" if vcs_name == "bare_git" else None,
    )

    assert get_effective_sdd_config(workspace) is True


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


def test_cli_init_beads_vc_ensures_generated_sdd_first(tmp_path: Path) -> None:
    from sase.bead.cli_common import init_beads as cli_init_beads

    with (
        patch("sase.sdd.files.ensure_bare_git_sdd_initialized") as ensure_sdd,
        patch("sase.bead.cli_common.BeadProject.init") as bead_init,
    ):
        cli_init_beads(tmp_path, "sdd/beads")

    ensure_sdd.assert_called_once_with(tmp_path, commit=True, push=False)
    bead_init.assert_called_once_with(tmp_path, beads_dirname="sdd/beads")
