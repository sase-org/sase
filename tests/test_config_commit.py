"""Tests for the shared Config TUI commit-offer helper."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from sase.ace.tui.modals.config_commit import (
    ConfigCommitOffer,
    build_config_commit_offer,
)


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.email=test@example.com",
            "-c",
            "user.name=Test",
            *args,
        ],
        capture_output=True,
        text=True,
        check=True,
    )


def _init_repo(repo: Path) -> None:
    repo.mkdir(parents=True)
    _git(repo, "init", "-q")


def test_build_config_commit_offer_for_dirty_config_file(tmp_path: Path) -> None:
    repo = tmp_path / "config"
    _init_repo(repo)
    target = repo / "sase.yml"
    target.write_text("timezone: America/New_York\n", encoding="utf-8")

    offer = build_config_commit_offer(
        str(target),
        subject="chore: Update config timezone",
    )

    assert offer is not None
    assert offer.git_root == str(repo)
    assert offer.file_path == str(target)
    assert offer.rel_path == "sase.yml"


def test_build_config_commit_offer_for_dirty_chezmoi_source(tmp_path: Path) -> None:
    repo = tmp_path / "chezmoi"
    _init_repo(repo)
    source = repo / "home" / "dot_config" / "sase" / "sase.yml"
    source.parent.mkdir(parents=True)
    source.write_text("timezone: America/New_York\n", encoding="utf-8")

    offer = build_config_commit_offer(
        str(source),
        subject="chore: Update config timezone",
    )

    assert isinstance(offer, ConfigCommitOffer)
    assert offer.git_root == str(repo)
    assert offer.file_path == str(source)
    assert offer.rel_path == "home/dot_config/sase/sase.yml"
    assert offer.message.startswith("chore: Update config timezone")
    assert "SASE_TYPE=config" in offer.message


def test_build_config_commit_offer_skips_clean_target(tmp_path: Path) -> None:
    repo = tmp_path / "config"
    _init_repo(repo)
    target = repo / "sase.yml"
    target.write_text("timezone: UTC\n", encoding="utf-8")
    _git(repo, "add", "sase.yml")
    _git(repo, "commit", "-q", "-m", "init")

    assert (
        build_config_commit_offer(
            str(target),
            subject="chore: Update config timezone",
        )
        is None
    )


def test_build_config_commit_offer_skips_non_git_target(tmp_path: Path) -> None:
    target = tmp_path / "loose" / "sase.yml"
    target.parent.mkdir()
    target.write_text("timezone: UTC\n", encoding="utf-8")

    assert (
        build_config_commit_offer(
            str(target),
            subject="chore: Update config timezone",
        )
        is None
    )


def test_build_config_commit_offer_skips_git_inspection_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_git_root(_path: str) -> str | None:
        raise OSError("git unavailable")

    monkeypatch.setattr(
        "sase.ace.tui.modals.xprompt_browser_helpers.get_git_root",
        fail_git_root,
    )

    assert (
        build_config_commit_offer(
            "/tmp/sase.yml",
            subject="chore: Update config timezone",
        )
        is None
    )
