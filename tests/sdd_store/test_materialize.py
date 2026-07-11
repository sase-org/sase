from __future__ import annotations

import json
from pathlib import Path
import shutil

import pytest

from sase.sdd.store import (
    SDD_STORAGE_SEPARATE_REPO,
    SddMaterializationError,
    create_and_materialize_sdd_store,
    materialize_sdd_store,
    preflight_sdd_companion,
    read_sdd_store_record,
    write_sdd_store_record,
)
from sase.workspace_provider._hookspec import (
    SddCompanionPreflight,
    WorkflowMetadata,
    hookimpl,
)
from tests.sdd_store._helpers import (
    clone,
    commit_all,
    git,
    init_bare_repo,
    init_git_identity,
    install_workspace_plugin,
)


class _FakeSeparateRepoProvider:
    def __init__(self, remote: Path, *, error: str | None = None) -> None:
        self.remote = remote
        self.error = error
        self.calls = 0

    @hookimpl
    def ws_get_workflow_metadata(self) -> WorkflowMetadata | None:
        return WorkflowMetadata(
            workflow_type="fake",
            ref_pattern="",
            display_name="Fake",
            pre_allocated_env_prefix="SASE_FAKE",
            vcs_provider_name="fake",
            sdd_storage_policy="separate_repo",
        )

    @hookimpl
    def ws_materialize_sdd_store(
        self,
        primary_workspace_dir: str,
        workspace_dir: str,
        options: dict[str, object],
    ) -> dict[str, object] | None:
        del primary_workspace_dir, workspace_dir
        self.calls += 1
        if self.error:
            raise RuntimeError(self.error)
        staging = Path(str(options["staging_dir"]))
        clone(self.remote, staging)
        return {
            "schema_version": 1,
            "storage": "separate_repo",
            "provider": "fake",
            "host": "example.test",
            "repo": "owner/repo--sdd",
            "remote_url": str(self.remote),
            "discovery": "found",
            "created": True,
        }


class _ConcurrentPushProvider:
    """Advance the shared companion remote between the staging clone and push.

    Simulates a second workspace materializing (and pushing to) the same shared
    companion repository first, so this materialization's push is rejected as a
    non-fast-forward and must integrate the remote work before retrying.
    """

    def __init__(self, remote: Path, rival_worktree: Path) -> None:
        self.remote = remote
        self._rival_worktree = rival_worktree
        self.calls = 0

    @hookimpl
    def ws_get_workflow_metadata(self) -> WorkflowMetadata | None:
        return WorkflowMetadata(
            workflow_type="fake",
            ref_pattern="",
            display_name="Fake",
            pre_allocated_env_prefix="SASE_FAKE",
            vcs_provider_name="fake",
            sdd_storage_policy="separate_repo",
        )

    @hookimpl
    def ws_materialize_sdd_store(
        self,
        primary_workspace_dir: str,
        workspace_dir: str,
        options: dict[str, object],
    ) -> dict[str, object] | None:
        del primary_workspace_dir, workspace_dir
        self.calls += 1
        staging = Path(str(options["staging_dir"]))
        clone(self.remote, staging)
        # A concurrent workspace pushes to the shared companion remote after our
        # staging clone is taken but before we push, advancing the remote past
        # our clone so our push is a non-fast-forward rejection.
        clone(self.remote, self._rival_worktree)
        rival = self._rival_worktree / "research" / "rival.md"
        rival.parent.mkdir(parents=True, exist_ok=True)
        rival.write_text("rival\n", encoding="utf-8")
        commit_all(self._rival_worktree, "Concurrent companion import")
        git(["push", "origin", "HEAD"], self._rival_worktree)
        return {
            "schema_version": 1,
            "storage": "separate_repo",
            "provider": "fake",
            "host": "example.test",
            "repo": "owner/repo--sdd",
            "remote_url": str(self.remote),
            "discovery": "found",
            "created": True,
        }


class _MetadataOnlyProvider:
    @hookimpl
    def ws_get_workflow_metadata(self) -> WorkflowMetadata | None:
        return WorkflowMetadata(
            workflow_type="fake",
            ref_pattern="",
            display_name="Fake",
            pre_allocated_env_prefix="SASE_FAKE",
            vcs_provider_name="fake",
            sdd_storage_policy="separate_repo",
        )


class _PreflightProvider(_MetadataOnlyProvider):
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, object]]] = []

    @hookimpl
    def ws_preflight_sdd_companion(
        self,
        primary_workspace_dir: str,
        workspace_dir: str,
        options: dict[str, object],
    ) -> SddCompanionPreflight | None:
        self.calls.append((primary_workspace_dir, workspace_dir, options))
        return SddCompanionPreflight(
            status="not_found",
            provider="FakeHub",
            host="example.test",
            repo="owner/repo--sdd",
            visibility="public",
        )


def _install_provider(
    monkeypatch: pytest.MonkeyPatch,
    provider: object,
) -> None:
    install_workspace_plugin(monkeypatch, provider)
    monkeypatch.setattr("sase.vcs_provider.detect_vcs", lambda _cwd: "fake")


def _remote_with_files(tmp_path: Path, files: dict[str, str]) -> Path:
    remote = tmp_path / "companion.git"
    seed = tmp_path / "seed"
    init_bare_repo(remote)
    clone(remote, seed)
    for relpath, content in files.items():
        path = seed / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    commit_all(seed, "Seed companion")
    git(["push", "-u", "origin", "main"], seed)
    shutil.rmtree(seed)
    return remote


def test_preflight_dispatches_read_only_provider_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    primary = tmp_path / "repo"
    primary.mkdir()
    provider = _PreflightProvider()
    _install_provider(monkeypatch, provider)

    result = preflight_sdd_companion(primary, 1)

    assert result.status == "not_found"
    assert result.repo == "owner/repo--sdd"
    assert len(provider.calls) == 1
    called_primary, called_workspace, options = provider.calls[0]
    assert called_primary == str(primary)
    assert called_workspace == str(primary)
    assert options["provider_policy"] == "separate_repo"
    assert "staging_dir" not in options
    assert "create" not in options
    assert not (primary / ".sase").exists()


def test_preflight_fails_closed_when_provider_hook_is_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    primary = tmp_path / "repo"
    primary.mkdir()
    _install_provider(monkeypatch, _MetadataOnlyProvider())

    with pytest.raises(SddMaterializationError, match="Update the provider plugin"):
        preflight_sdd_companion(primary, 1)

    assert not (primary / ".sase").exists()


def test_materialization_bootstraps_primary_and_numbered_workspace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    primary = tmp_path / "repo"
    workspace = tmp_path / "repo_2"
    primary.mkdir()
    workspace.mkdir()
    remote = tmp_path / "companion.git"
    init_bare_repo(remote)
    provider = _FakeSeparateRepoProvider(remote)
    _install_provider(monkeypatch, provider)

    outcome = create_and_materialize_sdd_store(workspace, 2)

    assert outcome.created is True
    assert outcome.store.storage == SDD_STORAGE_SEPARATE_REPO
    assert provider.calls == 1
    assert (primary / ".sase" / "sdd" / ".git").is_dir()
    assert (workspace / ".sase" / "sdd" / ".git").is_dir()
    assert (workspace / ".sase" / "sdd" / "README.md").is_file()
    assert (workspace / ".sase" / "sdd" / "beads").is_dir()
    record = read_sdd_store_record(primary)
    assert record is not None
    assert record.repo == "owner/repo--sdd"


def test_existing_positive_clone_remains_usable_offline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    primary = tmp_path / "repo"
    workspace = tmp_path / "repo_2"
    primary.mkdir()
    workspace.mkdir()
    remote = tmp_path / "companion.git"
    init_bare_repo(remote)
    provider = _FakeSeparateRepoProvider(remote)
    _install_provider(monkeypatch, provider)
    materialize_sdd_store(primary, 1)
    shutil.rmtree(remote)

    class _ExplodingProvider(_FakeSeparateRepoProvider):
        @hookimpl
        def ws_materialize_sdd_store(
            self,
            primary_workspace_dir: str,
            workspace_dir: str,
            options: dict[str, object],
        ) -> dict[str, object] | None:
            raise AssertionError("offline record path must not call the provider")

    _install_provider(monkeypatch, _ExplodingProvider(remote))
    store = materialize_sdd_store(workspace, 2)

    assert store.storage == SDD_STORAGE_SEPARATE_REPO
    assert (store.sdd_dir / ".git").is_dir()
    assert (store.sdd_dir / "README.md").is_file()


def test_existing_positive_clone_adopts_new_legacy_artifacts_without_provider(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    primary = tmp_path / "repo"
    primary.mkdir()
    remote = tmp_path / "companion.git"
    init_bare_repo(remote)
    _install_provider(monkeypatch, _FakeSeparateRepoProvider(remote))
    materialize_sdd_store(primary, 1)
    legacy = primary / "sdd" / "research" / "late.md"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("late legacy artifact\n", encoding="utf-8")

    class _ExplodingProvider(_FakeSeparateRepoProvider):
        @hookimpl
        def ws_materialize_sdd_store(
            self,
            primary_workspace_dir: str,
            workspace_dir: str,
            options: dict[str, object],
        ) -> dict[str, object] | None:
            raise AssertionError("positive record adoption must not call the provider")

    _install_provider(monkeypatch, _ExplodingProvider(remote))
    adopted = materialize_sdd_store(primary, 1)
    adopted_head = git(["rev-parse", "HEAD"], adopted.sdd_dir).stdout.strip()
    repeated = materialize_sdd_store(primary, 1)

    assert (adopted.sdd_dir / "research" / "late.md").read_text() == (
        "late legacy artifact\n"
    )
    assert legacy.read_text() == "late legacy artifact\n"
    assert git(["rev-parse", "HEAD"], repeated.sdd_dir).stdout.strip() == adopted_head


def test_old_negative_record_is_retried_and_replaced(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    primary = tmp_path / "repo"
    primary.mkdir()
    record_path = primary / ".sase" / "sdd-store.json"
    record_path.parent.mkdir(parents=True)
    record_path.write_text(
        json.dumps(
            {
                "storage": "separate_repo",
                "provider": "fake",
                "repo": "owner/repo--sdd",
                "discovery": "not_found",
            }
        ),
        encoding="utf-8",
    )
    remote = tmp_path / "companion.git"
    init_bare_repo(remote)
    _install_provider(monkeypatch, _FakeSeparateRepoProvider(remote))

    materialize_sdd_store(primary, 1)

    record = read_sdd_store_record(primary)
    assert record is not None
    assert record.discovery == "found"


@pytest.mark.parametrize("provider_error", [None, "authentication failed"])
def test_first_materialization_fails_closed_without_positive_provider_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    provider_error: str | None,
) -> None:
    primary = tmp_path / "repo"
    primary.mkdir()
    if provider_error is None:
        provider: object = _MetadataOnlyProvider()
    else:
        remote = tmp_path / "unused.git"
        provider = _FakeSeparateRepoProvider(remote, error=provider_error)
    _install_provider(monkeypatch, provider)

    with pytest.raises(SddMaterializationError):
        materialize_sdd_store(primary, 1)

    assert not (primary / ".sase" / "sdd").exists()
    assert read_sdd_store_record(primary) is None


def test_local_and_in_tree_artifacts_are_imported_without_deleting_in_tree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    primary = tmp_path / "repo"
    local_note = primary / ".sase" / "sdd" / "research" / "local.md"
    tree_note = primary / "sdd" / "plans" / "202607" / "tree.md"
    local_note.parent.mkdir(parents=True)
    tree_note.parent.mkdir(parents=True)
    local_note.write_text("local\n", encoding="utf-8")
    tree_note.write_text("tree\n", encoding="utf-8")
    runtime = primary / ".sase" / "sdd" / "beads" / "beads.db-wal"
    runtime.parent.mkdir(parents=True)
    runtime.write_bytes(b"runtime only")
    remote = _remote_with_files(tmp_path, {"research/remote.md": "remote\n"})
    _install_provider(monkeypatch, _FakeSeparateRepoProvider(remote))

    store = materialize_sdd_store(primary, 1)

    assert (store.sdd_dir / "research" / "local.md").read_text() == "local\n"
    assert (store.sdd_dir / "research" / "remote.md").read_text() == "remote\n"
    assert (store.sdd_dir / "plans" / "202607" / "tree.md").read_text() == "tree\n"
    assert tree_note.read_text() == "tree\n"
    assert not (store.sdd_dir / "beads" / "beads.db-wal").exists()


def test_materialization_recovers_from_concurrent_companion_push(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    primary = tmp_path / "repo"
    legacy = primary / ".sase" / "sdd" / "research" / "local.md"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("local\n", encoding="utf-8")
    remote = _remote_with_files(tmp_path, {"research/remote.md": "remote\n"})
    provider = _ConcurrentPushProvider(remote, tmp_path / "rival")
    _install_provider(monkeypatch, provider)

    store = materialize_sdd_store(primary, 1)

    # Our import and the concurrently pushed rival import both survive the rebase.
    assert (store.sdd_dir / "research" / "local.md").read_text() == "local\n"
    assert (store.sdd_dir / "research" / "rival.md").read_text() == "rival\n"
    assert (store.sdd_dir / "research" / "remote.md").read_text() == "remote\n"

    # The staged commit was integrated and pushed, so the shared remote holds it.
    verify = tmp_path / "verify"
    clone(remote, verify)
    assert (verify / "research" / "local.md").read_text() == "local\n"
    assert (verify / "research" / "rival.md").read_text() == "rival\n"


def test_mismatched_local_git_repo_is_imported_via_staging(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    primary = tmp_path / "repo"
    local = primary / ".sase" / "sdd"
    local.mkdir(parents=True)
    git(["init", "-b", "main"], local)
    init_git_identity(local)
    (local / "research").mkdir()
    (local / "research" / "legacy.md").write_text("legacy\n", encoding="utf-8")
    remote = tmp_path / "companion.git"
    init_bare_repo(remote)
    git(["remote", "add", "origin", str(tmp_path / "unrelated.git")], local)
    _install_provider(monkeypatch, _FakeSeparateRepoProvider(remote))

    store = materialize_sdd_store(primary, 1)

    assert (store.sdd_dir / "research" / "legacy.md").read_text() == "legacy\n"
    assert git(["remote", "get-url", "origin"], store.sdd_dir).stdout.strip() == str(
        remote
    )


def test_conflict_aborts_and_preserves_legacy_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    primary = tmp_path / "repo"
    legacy = primary / ".sase" / "sdd" / "research" / "note.md"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("legacy\n", encoding="utf-8")
    remote = _remote_with_files(tmp_path, {"research/note.md": "remote\n"})
    _install_provider(monkeypatch, _FakeSeparateRepoProvider(remote))

    with pytest.raises(SddMaterializationError, match="research/note.md"):
        materialize_sdd_store(primary, 1)

    assert legacy.read_text() == "legacy\n"
    assert read_sdd_store_record(primary) is None


def test_versioned_stale_clone_defers_overlap_and_skips_runtime_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    remote = _remote_with_files(tmp_path, {"plans/202607/shared.md": "companion\n"})
    _install_provider(monkeypatch, _FakeSeparateRepoProvider(remote))

    primary = tmp_path / "repo"
    local = primary / ".sase" / "sdd"
    # A stale companion clone whose origin is the pre-rename URL, so it is not
    # recognized as the companion and is inspected as a legacy source.
    clone(remote, local)
    git(["remote", "set-url", "origin", str(tmp_path / "renamed.git")], local)
    # Its committed copy of the shared tale merely lags the companion, holds a
    # not-yet-pushed unique tale, and carries an accidentally nested companion
    # clone under .sase that must never be imported as a durable artifact.
    (local / "plans" / "202607" / "shared.md").write_text("stale\n", encoding="utf-8")
    (local / "plans" / "202607" / "unique.md").write_text("unique\n", encoding="utf-8")
    nested = local / ".sase" / "sdd" / "plans" / "202607" / "nested.md"
    nested.parent.mkdir(parents=True)
    nested.write_text("nested\n", encoding="utf-8")
    commit_all(local, "Local SDD work")

    store = materialize_sdd_store(primary, 1)

    # The overlapping artifact defers to the authoritative companion; the stale,
    # version-controlled copy no longer aborts the transaction as a conflict.
    assert (store.sdd_dir / "plans" / "202607" / "shared.md").read_text() == (
        "companion\n"
    )
    # The unique, unpushed artifact is still rescued into the companion.
    assert (store.sdd_dir / "plans" / "202607" / "unique.md").read_text() == "unique\n"
    # Nested workspace runtime metadata is excluded from durable-artifact import.
    assert not (store.sdd_dir / ".sase").exists()


def test_materialization_is_idempotent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    primary = tmp_path / "repo"
    primary.mkdir()
    remote = tmp_path / "companion.git"
    init_bare_repo(remote)
    provider = _FakeSeparateRepoProvider(remote)
    _install_provider(monkeypatch, provider)

    first = materialize_sdd_store(primary, 1)
    first_head = git(["rev-parse", "HEAD"], first.sdd_dir).stdout.strip()
    second = materialize_sdd_store(primary, 1)
    second_head = git(["rev-parse", "HEAD"], second.sdd_dir).stdout.strip()

    assert provider.calls == 1
    assert first_head == second_head
