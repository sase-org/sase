"""Real-git fixtures for VCS-backed (byte-free) ``ArtifactFile`` rows.

Shared by any test that needs to prove a code path materializes real bytes
out of a committed file rather than mocking ``materialize_artifact_file``.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from sase.artifact_ref_models import ArtifactRefRepository
from sase.core.artifact_file_types import ArtifactFile, ArtifactFileKind


def git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def vcs_row(
    tmp_path: Path,
    *,
    relpath: str = "docs/report.md",
    kind: ArtifactFileKind = "markdown",
    label: str = "Tracked report",
) -> tuple[Path, ArtifactFile, str]:
    """Commit a file into a scratch repo and return a matching byte-free row."""

    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init")
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "config", "user.name", "Test")
    source = repo / relpath
    source.parent.mkdir(parents=True, exist_ok=True)
    content = "# exact report\n"
    source.write_text(content, encoding="utf-8")
    git(repo, "add", relpath)
    git(repo, "commit", "-m", "add report")
    row = ArtifactFile(
        id="default:vcs",
        label=label,
        kind=kind,
        path=None,
        source_path=str(source),
        workspace_dir=str(repo),
        sha256=hashlib.sha256(content.encode()).hexdigest(),
        size_bytes=len(content.encode()),
        mime_type="text/markdown",
        vcs_repo="sase",
        vcs_sha=git(repo, "rev-parse", "HEAD"),
        vcs_relpath=relpath,
    )
    return repo, row, content


def install_materialization_context(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    repo: Path,
) -> None:
    """Point the shared launch/materialization context at a scratch repo."""

    repository = ArtifactRefRepository(
        "sase",
        checkout_path=repo,
        checkout_paths=(repo,),
    )
    context = SimpleNamespace(repositories=(repository,))
    monkeypatch.setattr(
        "sase.artifact_ref_context.launch_artifact_ref_context",
        lambda **_kwargs: context,
    )
    monkeypatch.setattr(
        "sase.core.artifact_file_vcs.default_artifact_files_root",
        lambda: tmp_path / "artifacts",
    )


__all__ = ["git", "install_materialization_context", "vcs_row"]
