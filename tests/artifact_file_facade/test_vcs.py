from __future__ import annotations

import hashlib
from pathlib import Path
import subprocess

import pytest

from sase.artifact_ref_models import ArtifactRefRepository
from sase.core.artifact_file_explicit import store_default_artifact_file
from sase.core.artifact_file_helpers import (
    artifact_file_dedupe_key,
    artifact_file_id,
    dedupe_artifact_files,
)
from sase.core.artifact_file_types import (
    ArtifactFile,
    ArtifactFileAssociation,
)
from sase.core.artifact_file_vcs import materialize_artifact_file

from .helpers import agent_dir


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _committed_file(tmp_path: Path) -> tuple[Path, Path, str, bytes]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    source = repo / "docs" / "report.md"
    source.parent.mkdir()
    content = b"# exact report\n"
    source.write_bytes(content)
    _git(repo, "add", "docs/report.md")
    _git(repo, "commit", "-m", "add report")
    return repo, source, _git(repo, "rev-parse", "HEAD"), content


def _vcs_row(*, sha: str, content: bytes) -> ArtifactFile:
    return ArtifactFile(
        id="default:vcs",
        label="Report",
        kind="markdown",
        path=None,
        sha256=hashlib.sha256(content).hexdigest(),
        size_bytes=len(content),
        mime_type="text/markdown",
        vcs_repo="sase",
        vcs_sha=sha,
        vcs_relpath="docs/report.md",
    )


def test_materialize_artifact_file_uses_verified_content_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, _source, sha, content = _committed_file(tmp_path)
    row = _vcs_row(sha=sha, content=content)
    cache_root = tmp_path / "artifacts"
    monkeypatch.setattr(
        "sase.core.artifact_file_vcs.default_artifact_files_root",
        lambda: cache_root,
    )
    repository = ArtifactRefRepository(
        "sase",
        checkout_path=repo,
        checkout_paths=(repo,),
    )

    first = materialize_artifact_file(row, repositories=(repository,))
    assert first is not None
    assert first.read_bytes() == content
    assert first.is_relative_to(cache_root / "vcs-cache")

    unavailable = ArtifactRefRepository("sase")
    second = materialize_artifact_file(row, repositories=(unavailable,))
    assert second == first
    assert second.read_bytes() == content


def test_store_default_reference_writes_no_artifact_bytes(tmp_path: Path) -> None:
    _repo, source, sha, content = _committed_file(tmp_path)
    root = tmp_path / "artifacts"

    row = store_default_artifact_file(
        source,
        agent_dir(tmp_path),
        artifact_files_root=root,
        vcs_repo="sase",
        vcs_sha=sha,
        vcs_relpath="docs/report.md",
        sha256=hashlib.sha256(content).hexdigest(),
        size_bytes=len(content),
        mime_type="text/markdown",
    )

    assert row is not None
    assert row.path is None
    assert row.is_vcs_backed
    assert not (root / "agents").exists()


def test_vcs_ids_and_dedupe_keys_are_stable_and_revision_specific() -> None:
    association = ArtifactFileAssociation("/agents/run", project="sase")
    first = _vcs_row(sha="a" * 40, content=b"first")
    second = _vcs_row(sha="b" * 40, content=b"second")
    first_id = artifact_file_id(
        "default",
        association,
        None,
        "Report",
        vcs_repo=first.vcs_repo,
        vcs_relpath=first.vcs_relpath,
        sha256=first.sha256,
    )
    repeated_id = artifact_file_id(
        "default",
        association,
        None,
        "Report",
        vcs_repo=first.vcs_repo,
        vcs_relpath=first.vcs_relpath,
        sha256=first.sha256,
    )
    second_id = artifact_file_id(
        "default",
        association,
        None,
        "Report",
        vcs_repo=second.vcs_repo,
        vcs_relpath=second.vcs_relpath,
        sha256=second.sha256,
    )

    assert first_id == repeated_id
    assert first_id != second_id
    duplicate = ArtifactFile(**{**first.__dict__, "id": "duplicate"})
    assert artifact_file_dedupe_key(first) == artifact_file_dedupe_key(duplicate)
    assert dedupe_artifact_files([first, duplicate, second]) == [first, second]
