from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from sase._repo_inventory_models import RepoCloneRecord, RepoInventory, RepoRecord
from sase.core.artifact_capture_policy import GitVcsProbe, VcsProbe
from sase.core.artifact_file_explicit import (
    read_artifact_file_index,
    write_artifact_file_index_unlocked,
)
from sase.core.artifact_file_protection import ProtectedArtifactIds
from sase.core.artifact_file_reclaim import (
    execute_artifact_file_reclaim,
    plan_artifact_file_reclaim,
)
from sase.core.artifact_file_trash import list_trashed_artifact_files
from sase.core.artifact_file_types import ArtifactFile
from sase.core.artifact_file_vcs import materialize_artifact_file
from tests._sdd_commit_helpers import init_test_git_repo


PROJECT = "proj"
WORKSPACE_NUM = 7


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        check=True,
        text=True,
    ).stdout.strip()


def _pushed_repo(tmp_path: Path) -> tuple[Path, Path]:
    bare = tmp_path / "remote.git"
    workspace = tmp_path / "workspace"
    subprocess.run(["git", "init", "--bare", "-q", str(bare)], check=True)
    _git(bare, "symbolic-ref", "HEAD", "refs/heads/main")
    init_test_git_repo(workspace)
    _git(workspace, "branch", "-M", "main")
    _git(workspace, "remote", "add", "origin", str(bare))
    return workspace, bare


def _push(repo: Path) -> None:
    _git(repo, "push", "-qu", "origin", "main")
    _git(repo, "remote", "set-head", "origin", "-a")


def _commit(repo: Path, relpath: str, content: bytes, message: str) -> tuple[str, str]:
    path = repo / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    _git(repo, "add", relpath)
    _git(repo, "commit", "-qm", message)
    return _git(repo, "rev-parse", "HEAD"), hashlib.sha256(content).hexdigest()


def _record(
    repo: Path,
    *,
    name: str = PROJECT,
    kind: str = "primary",
    workspace_path: Path | None = None,
    exists: bool = True,
) -> RepoRecord:
    selected_path = workspace_path or repo
    return RepoRecord(
        name=name,
        kind=kind,  # type: ignore[arg-type]
        project=PROJECT,
        project_key=PROJECT,
        path=str(repo),
        exists=exists,
        auto_clone=False,
        description=None,
        source="test",
        env_name=None,
        clones=(RepoCloneRecord(WORKSPACE_NUM, str(selected_path), exists),),
    )


def _artifact(
    stored_path: Path,
    source_path: Path,
    workspace: Path,
    digest: str,
    *,
    artifact_id: str = "default:111111111111111111111111",
    explicit: bool = False,
) -> ArtifactFile:
    return ArtifactFile(
        id=artifact_id,
        label="report",
        kind="file",
        path=str(stored_path),
        source_path=str(source_path),
        workspace_dir=str(workspace),
        created_at="2026-07-01T00:00:00Z",
        agent_artifacts_dir=str(
            workspace / ".sase" / "artifacts" / "run" / "20260701000000"
        ),
        project=PROJECT,
        workflow="run",
        raw_timestamp="20260701000000",
        agent_name="agent.one",
        explicit=explicit,
        sha256=digest,
        size_bytes=stored_path.stat().st_size,
        mime_type="text/plain",
    )


def _seed_index(
    tmp_path: Path,
    row: ArtifactFile,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    home = tmp_path / "home"
    monkeypatch.setenv("SASE_HOME", str(home))
    index = home / "artifacts" / "index.jsonl"
    index.parent.mkdir(parents=True)
    write_artifact_file_index_unlocked(index, [row])
    return index


def test_clean_pushed_file_reclaims_resolves_and_is_idempotent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, _bare = _pushed_repo(tmp_path)
    sha, digest = _commit(repo, "report.txt", b"durable\n", "seed")
    _push(repo)
    stored = tmp_path / "stored.txt"
    stored.write_bytes(b"durable\n")
    row = _artifact(stored, repo / "report.txt", repo, digest)
    index = _seed_index(tmp_path, row, monkeypatch)
    inventory = RepoInventory((_record(repo),))

    plan = plan_artifact_file_reclaim(index_path=index, inventory=inventory)

    assert len(plan.verified) == 1
    assert plan.verified[0].vcs_sha == sha
    assert plan.verified[0].vcs_relpath == "report.txt"
    assert plan.reclaimable_bytes == len(b"durable\n")
    assert plan.verified[0].new_id != row.id

    # Historical rows commonly outlive their numbered workspace source.
    (repo / "report.txt").unlink()

    result = execute_artifact_file_reclaim(plan, index_path=index)

    assert result.rows_reclaimed == 1
    assert result.reclaimed[0].old_id == row.id
    assert result.reclaimed[0].new_id != row.id
    assert not stored.exists()
    [replacement] = read_artifact_file_index(index)
    assert replacement.id == result.reclaimed[0].new_id
    assert replacement.path is None
    assert replacement.agent_name == row.agent_name
    assert (replacement.vcs_repo, replacement.vcs_sha, replacement.vcs_relpath) == (
        PROJECT,
        sha,
        "report.txt",
    )
    [trash] = list_trashed_artifact_files(index_path=index).entries
    assert trash.artifact_id == row.id
    resolved = materialize_artifact_file(
        replacement,
        repositories=(
            SimpleNamespace(name=PROJECT, aliases=(), checkout_paths=(repo,)),
        ),
    )
    assert resolved is not None
    assert resolved.read_bytes() == b"durable\n"

    again = plan_artifact_file_reclaim(index_path=index, inventory=inventory)
    assert again.verified == ()
    assert again.unresolved_counts == {"already_vcs_backed": 1}


def test_unpushed_content_and_probe_failure_leave_row_untouched(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, _bare = _pushed_repo(tmp_path)
    _commit(repo, "report.txt", b"pushed\n", "pushed")
    _push(repo)
    _sha, digest = _commit(repo, "report.txt", b"local only\n", "local")
    stored = tmp_path / "stored.txt"
    stored.write_bytes(b"local only\n")
    row = _artifact(stored, repo / "report.txt", repo, digest)
    index = _seed_index(tmp_path, row, monkeypatch)
    inventory = RepoInventory((_record(repo),))

    unpushed = plan_artifact_file_reclaim(index_path=index, inventory=inventory)

    assert unpushed.verified == ()
    assert unpushed.unresolved_counts == {"digest_not_found": 1}
    assert stored.exists()
    assert read_artifact_file_index(index) == [row]

    class FailingProbe:
        def durable_candidate_commits(
            self,
            toplevel: str,
            relpath: str,
            *,
            max_history_scan: int,
        ) -> tuple[str, ...] | None:
            return None

        def blob_content_digests(
            self,
            toplevel: str,
            specs: Sequence[str],
        ) -> Mapping[str, str | None] | None:
            raise AssertionError("no blobs should be requested")

        def repo_toplevel(self, path: str) -> str | None:
            raise AssertionError("reclaim resolves repositories from inventory")

        def repo_identity(
            self,
            toplevel: str,
            *,
            project: str,
            workspace_num: int,
        ) -> str | None:
            raise AssertionError("reclaim resolves identities from inventory")

    failed = plan_artifact_file_reclaim(
        index_path=index,
        inventory=inventory,
        probe=FailingProbe(),
    )
    assert failed.unresolved_counts == {"vcs_probe_failed": 1}
    assert read_artifact_file_index(index) == [row]


def test_history_bound_finds_older_exact_content_only_within_bound(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, _bare = _pushed_repo(tmp_path)
    _sha, original_digest = _commit(repo, "report.txt", b"original\n", "original")
    for index in range(15):
        _commit(repo, "report.txt", f"version {index}\n".encode(), f"change {index}")
    _push(repo)
    stored = tmp_path / "stored.txt"
    stored.write_bytes(b"original\n")
    row = _artifact(stored, repo / "report.txt", repo, original_digest)
    index_path = _seed_index(tmp_path, row, monkeypatch)
    inventory = RepoInventory((_record(repo),))

    shallow = plan_artifact_file_reclaim(
        index_path=index_path,
        inventory=inventory,
        max_history_scan=15,
    )
    deep = plan_artifact_file_reclaim(
        index_path=index_path,
        inventory=inventory,
        max_history_scan=16,
    )

    assert shallow.verified == ()
    assert shallow.unresolved_counts == {"digest_not_found": 1}
    assert len(deep.verified) == 1


def test_history_walk_is_shared_by_rows_at_the_same_repo_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, _bare = _pushed_repo(tmp_path)
    _sha, digest = _commit(repo, "report.txt", b"durable\n", "seed")
    _push(repo)
    first_path = tmp_path / "first.txt"
    second_path = tmp_path / "second.txt"
    first_path.write_bytes(b"durable\n")
    second_path.write_bytes(b"durable\n")
    first = _artifact(first_path, repo / "report.txt", repo, digest)
    second = _artifact(
        second_path,
        repo / "report.txt",
        repo,
        digest,
        artifact_id="default:222222222222222222222222",
    )
    index = _seed_index(tmp_path, first, monkeypatch)
    write_artifact_file_index_unlocked(index, [first, second])
    delegate = GitVcsProbe()

    class CountingProbe:
        history_calls = 0

        def durable_candidate_commits(
            self,
            toplevel: str,
            relpath: str,
            *,
            max_history_scan: int,
        ) -> tuple[str, ...] | None:
            self.history_calls += 1
            return delegate.durable_candidate_commits(
                toplevel,
                relpath,
                max_history_scan=max_history_scan,
            )

        def blob_content_digests(
            self,
            toplevel: str,
            specs: Sequence[str],
        ) -> Mapping[str, str | None] | None:
            result = delegate.blob_content_digests(toplevel, specs)
            return None if result is None else dict(result)

        def repo_toplevel(self, path: str) -> str | None:
            raise AssertionError("reclaim resolves repositories from inventory")

        def repo_identity(
            self,
            toplevel: str,
            *,
            project: str,
            workspace_num: int,
        ) -> str | None:
            raise AssertionError("reclaim resolves identities from inventory")

    probe: VcsProbe = CountingProbe()
    plan = plan_artifact_file_reclaim(
        index_path=index,
        inventory=RepoInventory((_record(repo),)),
        probe=probe,
    )

    assert len(plan.verified) == 2
    assert isinstance(probe, CountingProbe)
    assert probe.history_calls == 1


def test_sidecar_nested_source_maps_to_sidecar_repo(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    primary = _record(workspace)
    sidecar = workspace / "sase" / "repos" / "plans"
    bare = tmp_path / "plans.git"
    subprocess.run(["git", "init", "--bare", "-q", str(bare)], check=True)
    _git(bare, "symbolic-ref", "HEAD", "refs/heads/main")
    init_test_git_repo(sidecar)
    _git(sidecar, "branch", "-M", "main")
    _git(sidecar, "remote", "add", "origin", str(bare))
    _sha, digest = _commit(sidecar, "design.md", b"# Design\n", "seed")
    _push(sidecar)
    stored = tmp_path / "stored.md"
    stored.write_bytes(b"# Design\n")
    row = _artifact(stored, sidecar / "design.md", workspace, digest)
    index = _seed_index(tmp_path, row, monkeypatch)
    inventory = RepoInventory(
        (
            primary,
            _record(
                sidecar,
                name="plans",
                kind="sidecar",
                workspace_path=sidecar,
            ),
        )
    )

    plan = plan_artifact_file_reclaim(index_path=index, inventory=inventory)

    assert len(plan.verified) == 1
    assert plan.verified[0].vcs_repo == "plans"
    assert plan.verified[0].vcs_relpath == "design.md"


def test_explicit_consumed_missing_checkout_and_unknown_repo_are_unresolved(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    source = workspace / "sase" / "repos" / "missing" / "file.txt"
    source.parent.mkdir(parents=True)
    source.write_text("value", encoding="utf-8")
    stored = tmp_path / "stored.txt"
    stored.write_text("value", encoding="utf-8")
    digest = hashlib.sha256(b"value").hexdigest()
    automatic = _artifact(stored, source, workspace, digest)
    explicit = _artifact(
        stored,
        source,
        workspace,
        digest,
        artifact_id="explicit:222222222222222222222222",
        explicit=True,
    )
    protected = _artifact(
        stored,
        source,
        workspace,
        digest,
        artifact_id="default:333333333333333333333333",
    )
    index = _seed_index(tmp_path, automatic, monkeypatch)
    write_artifact_file_index_unlocked(index, [automatic, explicit, protected])
    inventory = RepoInventory((_record(workspace),))
    protections = ProtectedArtifactIds(
        referenced_ids=frozenset(),
        consumed_ids=frozenset({protected.id}),
        sources_scanned=(str(tmp_path / "artifacts" / "consumption.jsonl"),),
        sources_unavailable=(),
    )

    plan = plan_artifact_file_reclaim(
        index_path=index,
        inventory=inventory,
        protected_ids=protections.ids,
    )

    assert plan.verified == ()
    assert plan.unresolved_counts == {
        "explicit": 1,
        "referenced": 1,
        "unknown_repo": 1,
    }


def test_missing_checkout_and_unknown_project_fail_safe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    source = workspace / "report.txt"
    source.write_text("value", encoding="utf-8")
    stored = tmp_path / "stored.txt"
    stored.write_text("value", encoding="utf-8")
    row = _artifact(
        stored,
        source,
        workspace,
        hashlib.sha256(b"value").hexdigest(),
    )
    index = _seed_index(tmp_path, row, monkeypatch)
    missing = tmp_path / "deleted-checkout"

    no_checkout = plan_artifact_file_reclaim(
        index_path=index,
        inventory=RepoInventory(
            (_record(missing, workspace_path=missing, exists=False),)
        ),
    )
    unknown_project = plan_artifact_file_reclaim(
        index_path=index,
        inventory=RepoInventory(()),
    )

    assert no_checkout.unresolved_counts == {"missing_checkout": 1}
    assert unknown_project.unresolved_counts == {"unknown_project": 1}
    assert stored.exists()
    assert read_artifact_file_index(index) == [row]
