from __future__ import annotations

from pathlib import Path

import pytest

from sase.sdd.store import (
    SDD_STORAGE_LOCAL,
    SDD_STORAGE_SEPARATE_REPO,
    SddMaterializationError,
    _write_sdd_store_record,
    create_and_materialize_sdd_store,
    materialize_sdd_store,
    read_sdd_store_record,
)
from sase.workspace_provider._hookspec import WorkflowMetadata, hookimpl
from tests.sdd_store._helpers import install_workspace_plugin


def test_materialize_sdd_store_fake_provider_writes_record_and_bootstraps(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    config_patch,
) -> None:
    workspace = tmp_path / "repo_2"
    primary = tmp_path / "repo"
    workspace.mkdir()
    primary.mkdir()
    config_patch({"sdd": {"storage": "auto", "version_controlled": False}})
    monkeypatch.setattr("sase.vcs_provider.detect_vcs", lambda cwd: "fake")

    calls: list[dict[str, object]] = []

    class FakePlugin:
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
            calls.append(options)
            del primary_workspace_dir
            (Path(workspace_dir) / ".sase" / "sdd").mkdir(parents=True)
            return {
                "schema_version": 1,
                "storage": "separate_repo",
                "provider": "fake",
                "repo": "owner/repo-sdd",
                "remote_url": "git@example.com:owner/repo-sdd.git",
                "discovery": "found",
            }

    install_workspace_plugin(monkeypatch, FakePlugin())

    def fake_bead_init(root: Path, *, beads_dirname: str) -> None:
        (root / beads_dirname).mkdir(parents=True)

    committed: list[tuple[str, list[Path]]] = []

    def fake_commit(store, message: str, **kwargs: object) -> bool:
        committed.append((message, list(kwargs.get("paths", ()))))
        return True

    monkeypatch.setattr("sase.bead.project.BeadProject.init", fake_bead_init)
    monkeypatch.setattr("sase.sdd._commit.commit_sdd_store_files", fake_commit)

    store = materialize_sdd_store(workspace, 2)

    assert store.storage == SDD_STORAGE_SEPARATE_REPO
    assert store.sdd_dir == workspace / ".sase" / "sdd"
    assert calls and calls[0]["workspace_num"] == 2
    record = read_sdd_store_record(primary)
    assert record is not None
    assert record.repo == "owner/repo-sdd"
    assert (store.sdd_dir / "README.md").exists()
    assert (store.sdd_dir / "beads").is_dir()
    assert committed and committed[0][0] == "Initialize SDD store"


def test_materialize_sdd_store_existing_record_skips_provider_hook(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    config_patch,
) -> None:
    workspace = tmp_path / "repo_2"
    primary = tmp_path / "repo"
    workspace.mkdir()
    primary.mkdir()
    config_patch({"sdd": {"storage": "auto", "version_controlled": False}})
    monkeypatch.setattr("sase.vcs_provider.detect_vcs", lambda cwd: "fake")
    _write_sdd_store_record(
        primary,
        {
            "storage": "separate_repo",
            "provider": "fake",
            "repo": "owner/repo-sdd",
            "discovery": "found",
        },
    )

    class ExplodingPlugin:
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
            raise AssertionError("provider hook should not run")

    install_workspace_plugin(monkeypatch, ExplodingPlugin())

    store = materialize_sdd_store(workspace, 2)

    assert store.storage == SDD_STORAGE_SEPARATE_REPO
    assert store.provider == "fake"


def test_materialize_sdd_store_no_provider_opt_in_is_noop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    config_patch,
) -> None:
    workspace = tmp_path / "repo"
    workspace.mkdir()
    config_patch({"sdd": {"storage": "auto", "version_controlled": False}})
    monkeypatch.setattr("sase.vcs_provider.detect_vcs", lambda cwd: "fake")

    class NoPolicyPlugin:
        @hookimpl
        def ws_get_workflow_metadata(self) -> WorkflowMetadata | None:
            return WorkflowMetadata(
                workflow_type="fake",
                ref_pattern="",
                display_name="Fake",
                pre_allocated_env_prefix="SASE_FAKE",
                vcs_provider_name="fake",
            )

        @hookimpl
        def ws_materialize_sdd_store(
            self,
            primary_workspace_dir: str,
            workspace_dir: str,
            options: dict[str, object],
        ) -> dict[str, object] | None:
            raise AssertionError("provider hook should not run without opt-in")

    install_workspace_plugin(monkeypatch, NoPolicyPlugin())

    store = materialize_sdd_store(workspace, 1)

    assert store.storage == SDD_STORAGE_LOCAL
    assert read_sdd_store_record(workspace) is None


def test_create_sdd_remote_dispatches_to_workspace_plugin(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Plugin:
        @hookimpl
        def ws_create_sdd_remote(
            self,
            primary_workspace_dir: str,
            workspace_dir: str,
            options: dict[str, object],
        ) -> dict[str, object] | None:
            return {
                "primary": primary_workspace_dir,
                "workspace": workspace_dir,
                "create": options.get("create"),
            }

    install_workspace_plugin(monkeypatch, Plugin())

    from sase.workspace_provider import create_sdd_remote

    result = create_sdd_remote(
        str(tmp_path),
        str(tmp_path / "checkout"),
        {"create": True},
    )

    assert result == {
        "primary": str(tmp_path),
        "workspace": str(tmp_path / "checkout"),
        "create": True,
    }


def test_create_and_materialize_sdd_store_creates_and_bootstraps(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    config_patch,
) -> None:
    workspace = tmp_path / "repo"
    workspace.mkdir()
    config_patch({"sdd": {"storage": "auto", "version_controlled": False}})
    monkeypatch.setattr("sase.vcs_provider.detect_vcs", lambda cwd: "fake")
    calls: list[dict[str, object]] = []

    class FakePlugin:
        @hookimpl
        def ws_create_sdd_remote(
            self,
            primary_workspace_dir: str,
            workspace_dir: str,
            options: dict[str, object],
        ) -> dict[str, object] | None:
            calls.append(options)
            return {
                "schema_version": 1,
                "storage": "separate_repo",
                "provider": "fake",
                "repo": "owner/repo--sdd",
                "remote_url": "git@example.com:owner/repo--sdd.git",
                "discovery": "found",
                "created": True,
            }

    install_workspace_plugin(monkeypatch, FakePlugin())

    def fake_clone(workspace_dir: str | Path, workspace_num: int) -> None:
        del workspace_num
        (Path(workspace_dir) / ".sase" / "sdd").mkdir(parents=True)

    def fake_bead_init(root: Path, *, beads_dirname: str) -> None:
        (root / beads_dirname).mkdir(parents=True)

    committed: list[str] = []

    def fake_commit(store, message: str, **kwargs: object) -> bool:
        del store, kwargs
        committed.append(message)
        return True

    monkeypatch.setattr("sase.sdd.store.ensure_workspace_sdd_clone", fake_clone)
    monkeypatch.setattr("sase.bead.project.BeadProject.init", fake_bead_init)
    monkeypatch.setattr("sase.sdd._commit.commit_sdd_store_files", fake_commit)

    outcome = create_and_materialize_sdd_store(workspace, 1)

    assert outcome.store.storage == SDD_STORAGE_SEPARATE_REPO
    assert outcome.repo == "owner/repo--sdd"
    assert outcome.remote_url == "git@example.com:owner/repo--sdd.git"
    assert outcome.created is True
    assert calls and calls[0]["create"] is True
    record = read_sdd_store_record(workspace)
    assert record is not None
    assert record.repo == "owner/repo--sdd"
    assert (workspace / ".sase" / "sdd" / "README.md").exists()
    assert committed == ["Initialize SDD store"]


def test_create_and_materialize_sdd_store_refreshes_existing_record_with_provider(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    config_patch,
) -> None:
    workspace = tmp_path / "repo"
    workspace.mkdir()
    config_patch({"sdd": {"storage": "auto", "version_controlled": False}})
    _write_sdd_store_record(
        workspace,
        {
            "storage": "separate_repo",
            "provider": "fake",
            "host": "github.com",
            "repo": "owner/repo--sdd",
            "remote_url": "git@example.com:owner/repo--sdd.git",
            "discovery": "found",
        },
    )
    calls: list[dict[str, object]] = []

    class FakePlugin:
        @hookimpl
        def ws_create_sdd_remote(
            self,
            primary_workspace_dir: str,
            workspace_dir: str,
            options: dict[str, object],
        ) -> dict[str, object] | None:
            calls.append(options)
            return {
                "schema_version": 1,
                "storage": "separate_repo",
                "provider": "fake",
                "host": "github.com",
                "repo": "owner/repo--sdd",
                "remote_url": "git@example.com:owner/repo--sdd.git",
                "discovery": "found",
                "created": False,
            }

    install_workspace_plugin(monkeypatch, FakePlugin())

    def fake_clone(workspace_dir: str | Path, workspace_num: int) -> None:
        del workspace_num
        (Path(workspace_dir) / ".sase" / "sdd").mkdir(parents=True)

    monkeypatch.setattr("sase.sdd.store.ensure_workspace_sdd_clone", fake_clone)
    monkeypatch.setattr(
        "sase.sdd.store._ensure_materialized_store_initialized",
        lambda store: None,
    )

    outcome = create_and_materialize_sdd_store(workspace, 1)

    assert outcome.repo == "owner/repo--sdd"
    assert outcome.created is False
    assert calls == [
        {
            "workspace_num": 1,
            "create": True,
            "vcs_name": "",
            "sdd_repo": "owner/repo--sdd",
            "sdd_host": "github.com",
            "sdd_remote_url": "git@example.com:owner/repo--sdd.git",
        }
    ]


def test_create_and_materialize_sdd_store_preserves_existing_record_without_provider(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    config_patch,
) -> None:
    workspace = tmp_path / "repo"
    workspace.mkdir()
    config_patch({"sdd": {"storage": "auto", "version_controlled": False}})
    _write_sdd_store_record(
        workspace,
        {
            "storage": "separate_repo",
            "provider": "fake",
            "repo": "owner/repo--sdd",
            "remote_url": "git@example.com:owner/repo--sdd.git",
            "discovery": "found",
        },
    )

    install_workspace_plugin(monkeypatch, object())

    def fake_clone(workspace_dir: str | Path, workspace_num: int) -> None:
        del workspace_num
        (Path(workspace_dir) / ".sase" / "sdd").mkdir(parents=True)

    monkeypatch.setattr("sase.sdd.store.ensure_workspace_sdd_clone", fake_clone)
    monkeypatch.setattr(
        "sase.sdd.store._ensure_materialized_store_initialized",
        lambda store: None,
    )

    outcome = create_and_materialize_sdd_store(workspace, 1)

    assert outcome.repo == "owner/repo--sdd"
    assert outcome.created is False


def test_create_and_materialize_sdd_store_errors_without_provider(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    config_patch,
) -> None:
    workspace = tmp_path / "repo"
    workspace.mkdir()
    config_patch({"sdd": {"storage": "auto", "version_controlled": False}})
    install_workspace_plugin(monkeypatch, object())

    with pytest.raises(SddMaterializationError) as excinfo:
        create_and_materialize_sdd_store(workspace, 1)

    assert "only GitHub is currently supported" in str(excinfo.value)


def test_create_and_materialize_sdd_store_errors_on_not_found_record(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    config_patch,
) -> None:
    workspace = tmp_path / "repo"
    workspace.mkdir()
    config_patch({"sdd": {"storage": "auto", "version_controlled": False}})

    class FakePlugin:
        @hookimpl
        def ws_create_sdd_remote(
            self,
            primary_workspace_dir: str,
            workspace_dir: str,
            options: dict[str, object],
        ) -> dict[str, object] | None:
            return {
                "schema_version": 1,
                "storage": "separate_repo",
                "provider": "fake",
                "repo": "owner/repo--sdd",
                "remote_url": "git@example.com:owner/repo--sdd.git",
                "discovery": "not_found",
            }

    install_workspace_plugin(monkeypatch, FakePlugin())

    with pytest.raises(SddMaterializationError) as excinfo:
        create_and_materialize_sdd_store(workspace, 1)

    assert "does not exist" in str(excinfo.value)


def test_explicit_separate_repo_without_materialization_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    config_patch,
) -> None:
    workspace = tmp_path / "repo"
    workspace.mkdir()
    config_patch({"sdd": {"storage": "separate_repo", "version_controlled": False}})
    monkeypatch.setattr("sase.vcs_provider.detect_vcs", lambda cwd: None)

    with pytest.raises(SddMaterializationError) as excinfo:
        materialize_sdd_store(workspace, 1)

    message = str(excinfo.value)
    assert "expected SDD companion repository" in message
    assert "sase sdd migrate" in message
