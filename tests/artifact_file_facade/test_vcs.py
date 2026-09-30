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
from sase.core.artifact_file_vcs import (
    ArtifactFileRepositoryResolver,
    materialize_artifact_file,
)

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


def test_dedupe_tolerates_byte_free_row_with_incomplete_provenance() -> None:
    malformed = ArtifactFile(
        id="default:malformed",
        label="Malformed",
        kind="image",
        path=None,
        vcs_repo="sase",
        vcs_relpath="docs/malformed.png",
    )

    assert artifact_file_dedupe_key(malformed) == malformed.id
    assert dedupe_artifact_files([malformed]) == [malformed]


def _init_repo(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")


def _commit_file(repo: Path, relpath: str, content: bytes) -> str:
    target = repo / relpath
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    _git(repo, "add", relpath)
    _git(repo, "commit", "-m", f"add {relpath}")
    return _git(repo, "rev-parse", "HEAD")


def _isolate_cache(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    cache_root = tmp_path / "artifacts"
    monkeypatch.setattr(
        "sase.core.artifact_file_vcs.default_artifact_files_root",
        lambda: cache_root,
    )
    return cache_root


def _owner_repo(repo: Path, name: str = "research") -> ArtifactRefRepository:
    return ArtifactRefRepository(
        name,
        checkout_path=repo,
        checkout_paths=(repo,),
    )


def test_materialize_prefers_owning_project_over_caller_repositories(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo_a = tmp_path / "repo-a"
    repo_b = tmp_path / "repo-b"
    _init_repo(repo_a)
    _commit_file(repo_a, "other.txt", b"wrong project\n")
    _init_repo(repo_b)
    content = b"# owner project report\n"
    sha = _commit_file(repo_b, "docs/report.md", content)
    _isolate_cache(monkeypatch, tmp_path)

    row = ArtifactFile(
        id="default:vcs",
        label="Report",
        kind="markdown",
        path=None,
        sha256=hashlib.sha256(content).hexdigest(),
        size_bytes=len(content),
        mime_type="text/markdown",
        vcs_repo="research",
        vcs_sha=sha,
        vcs_relpath="docs/report.md",
        project="project-b",
    )
    caller_repositories = (_owner_repo(repo_a),)

    def fake_owner_repositories(*, project: str | None, workspace_num: int):  # type: ignore[no-untyped-def]
        assert project == "project-b"
        return (_owner_repo(repo_b),)

    monkeypatch.setattr(
        "sase.artifact_ref_context.artifact_ref_repositories",
        fake_owner_repositories,
    )

    resolved = materialize_artifact_file(row, repositories=caller_repositories)

    assert resolved is not None
    assert resolved.read_bytes() == content


def test_materialize_falls_back_when_owner_project_unknown(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    content = b"# fallback report\n"
    sha = _commit_file(repo, "docs/report.md", content)
    _isolate_cache(monkeypatch, tmp_path)

    row = ArtifactFile(
        id="default:vcs",
        label="Report",
        kind="markdown",
        path=None,
        sha256=hashlib.sha256(content).hexdigest(),
        size_bytes=len(content),
        mime_type="text/markdown",
        vcs_repo="research",
        vcs_sha=sha,
        vcs_relpath="docs/report.md",
        project="missing-project",
    )

    from sase._repo_inventory_models import RepoInventoryProjectNotFoundError

    def fake_missing(*, project: str | None, workspace_num: int):  # type: ignore[no-untyped-def]
        raise RepoInventoryProjectNotFoundError(f"project {project!r} not found")

    monkeypatch.setattr(
        "sase.artifact_ref_context.artifact_ref_repositories",
        fake_missing,
    )

    resolved = materialize_artifact_file(row, repositories=(_owner_repo(repo),))

    assert resolved is not None
    assert resolved.read_bytes() == content


def test_materialize_falls_back_when_owner_has_no_matching_repo(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    content = b"# caller report\n"
    sha = _commit_file(repo, "docs/report.md", content)
    _isolate_cache(monkeypatch, tmp_path)

    row = ArtifactFile(
        id="default:vcs",
        label="Report",
        kind="markdown",
        path=None,
        sha256=hashlib.sha256(content).hexdigest(),
        size_bytes=len(content),
        mime_type="text/markdown",
        vcs_repo="research",
        vcs_sha=sha,
        vcs_relpath="docs/report.md",
        project="project-b",
    )
    monkeypatch.setattr(
        "sase.artifact_ref_context.artifact_ref_repositories",
        lambda *, project, workspace_num: (_owner_repo(repo, name="other"),),
    )

    resolved = materialize_artifact_file(row, repositories=(_owner_repo(repo),))

    assert resolved is not None
    assert resolved.read_bytes() == content


def test_materialize_consults_cache_with_no_resolvable_repository(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    content = b"# cached report\n"
    sha = _commit_file(repo, "docs/report.md", content)
    _isolate_cache(monkeypatch, tmp_path)

    row = ArtifactFile(
        id="default:vcs",
        label="Report",
        kind="markdown",
        path=None,
        sha256=hashlib.sha256(content).hexdigest(),
        size_bytes=len(content),
        mime_type="text/markdown",
        vcs_repo="research",
        vcs_sha=sha,
        vcs_relpath="docs/report.md",
        project="project-b",
    )
    monkeypatch.setattr(
        "sase.artifact_ref_context.artifact_ref_repositories",
        lambda *, project, workspace_num: (),
    )

    first = materialize_artifact_file(row, repositories=(_owner_repo(repo),))
    assert first is not None
    assert first.read_bytes() == content

    seen: dict[str, object] = {}
    from sase.core import artifact_file_vcs as vcs_bridge

    real_require = vcs_bridge.require_rust_binding

    def spy_require(name: str):  # type: ignore[no-untyped-def]
        binding = real_require(name)

        def spy(payload: dict):  # type: ignore[no-untyped-def]
            seen["checkout_paths"] = list(payload.get("checkout_paths", []))
            return binding(payload)

        return spy

    monkeypatch.setattr("sase.core.artifact_file_vcs.require_rust_binding", spy_require)

    second = materialize_artifact_file(row, repositories=())
    assert second == first
    assert second.read_bytes() == content
    assert seen.get("checkout_paths") == []


def test_resolver_memoizes_owner_lookup_and_skips_lazy_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    content = b"# memo report\n"
    sha = _commit_file(repo, "docs/report.md", content)
    _isolate_cache(monkeypatch, tmp_path)

    def make_row() -> ArtifactFile:
        return ArtifactFile(
            id="default:vcs",
            label="Report",
            kind="markdown",
            path=None,
            sha256=hashlib.sha256(content).hexdigest(),
            size_bytes=len(content),
            mime_type="text/markdown",
            vcs_repo="research",
            vcs_sha=sha,
            vcs_relpath="docs/report.md",
            project="project-b",
        )

    calls: list[tuple[str | None, int]] = []

    def counting_lookup(*, project: str | None, workspace_num: int):  # type: ignore[no-untyped-def]
        calls.append((project, workspace_num))
        return (_owner_repo(repo),)

    monkeypatch.setattr(
        "sase.artifact_ref_context.artifact_ref_repositories",
        counting_lookup,
    )

    def fail_fallback():  # type: ignore[no-untyped-def]
        raise AssertionError("lazy fallback must not be evaluated")

    resolver = ArtifactFileRepositoryResolver(fallback=fail_fallback)
    first = materialize_artifact_file(make_row(), resolver=resolver)
    second = materialize_artifact_file(make_row(), resolver=resolver)

    assert first is not None
    assert second == first
    assert len(calls) == 1
    assert calls[0][0] == "project-b"
