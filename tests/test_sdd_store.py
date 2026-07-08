"""Tests for SDD storage policy resolution."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
from typing import Any

import pluggy
import pytest

from sase.bead.project import BEADS_DIRNAME, BEADS_DIRNAME_NON_VC
from sase.sdd._paths import get_sdd_dir
from sase.sdd.store import (
    SDD_STORAGE_IN_TREE,
    SDD_STORAGE_LOCAL,
    SDD_STORAGE_SEPARATE_REPO,
    SddMaterializationError,
    _record_cache,
    _write_sdd_store_record,
    ensure_workspace_sdd_link,
    get_configured_sdd_storage,
    materialize_sdd_store,
    read_sdd_store_record,
    resolve_sdd_dir,
    resolve_sdd_store,
)
from sase.workspace_provider._hookspec import (
    WorkflowMetadata,
    WorkspaceHookSpec,
    hookimpl,
)
from sase.workspace_provider._plugin_manager import WorkspacePluginManager
import sase.workspace_provider._registry as workspace_registry


@pytest.fixture(autouse=True)
def _clear_store_record_cache() -> None:
    _record_cache.clear()
    workspace_registry.get_all_workflow_metadata.cache_clear()
    yield
    _record_cache.clear()
    workspace_registry.get_all_workflow_metadata.cache_clear()


@pytest.fixture
def config_patch(monkeypatch: pytest.MonkeyPatch):
    def apply(config: dict[str, Any]) -> None:
        monkeypatch.setattr("sase.sdd.store.load_merged_config", lambda: config)

    return apply


@pytest.fixture
def provider_patch(monkeypatch: pytest.MonkeyPatch):
    def apply(detected_vcs: str | None) -> None:
        def policy(vcs_name: str) -> str | None:
            return {
                "bare_git": "in_tree",
                "github": "separate_repo",
            }.get(vcs_name)

        monkeypatch.setattr("sase.vcs_provider.detect_vcs", lambda cwd: detected_vcs)
        monkeypatch.setattr(
            "sase.workspace_provider.get_sdd_storage_policy_by_vcs",
            policy,
        )

    return apply


def install_workspace_plugin(monkeypatch: pytest.MonkeyPatch, plugin: object) -> None:
    pm = pluggy.PluginManager("sase_workspace")
    pm.add_hookspecs(WorkspaceHookSpec)
    pm.register(plugin)
    monkeypatch.setattr(workspace_registry, "_manager", WorkspacePluginManager(pm))
    workspace_registry.get_all_workflow_metadata.cache_clear()


def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )


def _init_git_identity(repo: Path) -> None:
    _git(["config", "user.email", "sase-test@example.com"], repo)
    _git(["config", "user.name", "SASE Test"], repo)
    _git(["config", "commit.gpgsign", "false"], repo)


def _init_bare_repo(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "init", "--bare", "-b", "main", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )


def _clone(source: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "clone", str(source), str(dest)],
        check=True,
        capture_output=True,
        text=True,
    )
    _init_git_identity(dest)


def _commit_all(repo: Path, message: str) -> None:
    _git(["add", "-A"], repo)
    _git(["commit", "-m", message], repo)


def _build_separate_repo_clones(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Build the agent-29 topology: a companion bare repo, a primary clone that
    advances with a tale, and a stale workspace clone that predates the tale.

    Returns ``(companion, primary_sdd, workspace_sdd)``.
    """
    companion = tmp_path / "companion.git"
    primary_sdd = tmp_path / "repo" / ".sase" / "sdd"
    workspace_sdd = tmp_path / "repo_2" / ".sase" / "sdd"

    _init_bare_repo(companion)

    _clone(companion, primary_sdd)
    (primary_sdd / "README.md").write_text("# SDD store\n", encoding="utf-8")
    _commit_all(primary_sdd, "Initialize SDD store")
    _git(["push", "-u", "origin", "main"], primary_sdd)

    # Clone the workspace copy while the companion is still at the initial commit.
    _clone(companion, workspace_sdd)

    # The primary store advances with the just-committed tale and pushes it.
    tale = primary_sdd / "tales" / "202607" / "feature.md"
    tale.parent.mkdir(parents=True)
    tale.write_text("# Plan\n", encoding="utf-8")
    _commit_all(primary_sdd, "Add tale")
    _git(["push"], primary_sdd)

    return companion, primary_sdd, workspace_sdd


@pytest.mark.parametrize(
    ("sdd_config", "detected_vcs", "expected_storage"),
    [
        ({"storage": "in_tree", "version_controlled": False}, "github", "in_tree"),
        ({"storage": "local", "version_controlled": True}, "bare_git", "local"),
        (
            {"storage": "separate_repo", "version_controlled": False},
            None,
            "separate_repo",
        ),
        ({"storage": "auto", "version_controlled": True}, "github", "in_tree"),
        ({"storage": "auto", "version_controlled": False}, "bare_git", "in_tree"),
        ({"storage": "auto", "version_controlled": False}, "github", "local"),
        ({"storage": "auto", "version_controlled": False}, None, "local"),
    ],
)
def test_resolve_sdd_store_equivalence_matrix(
    tmp_path: Path,
    config_patch,
    provider_patch,
    sdd_config: dict[str, Any],
    detected_vcs: str | None,
    expected_storage: str,
) -> None:
    workspace = tmp_path / "repo_2"
    primary = tmp_path / "repo"
    workspace.mkdir()
    primary.mkdir()
    config_patch({"sdd": sdd_config})
    provider_patch(detected_vcs)

    store = resolve_sdd_store(workspace, 2)

    assert store.storage == expected_storage
    expected_sdd_dir = (
        workspace / "sdd"
        if expected_storage == SDD_STORAGE_IN_TREE
        else primary / ".sase" / "sdd"
    )
    assert store.sdd_dir == expected_sdd_dir

    expected_beads_dir = (
        workspace / BEADS_DIRNAME
        if expected_storage == SDD_STORAGE_IN_TREE
        else primary / ".sase" / "sdd" / BEADS_DIRNAME_NON_VC
    )
    assert store.sdd_dir / "beads" == expected_beads_dir


@pytest.mark.parametrize(
    ("sdd_config", "expected"),
    [
        ({"storage": "local", "version_controlled": True}, "local"),
        ({"storage": "in_tree", "version_controlled": False}, "in_tree"),
        ({"storage": "separate_repo", "version_controlled": True}, "separate_repo"),
        ({"storage": "auto", "version_controlled": True}, "in_tree"),
        ({"version_controlled": True}, "in_tree"),
        ({"version_controlled": False}, "auto"),
    ],
)
def test_configured_storage_alias_conflict_behavior(
    config_patch,
    sdd_config: dict[str, Any],
    expected: str,
) -> None:
    config_patch({"sdd": sdd_config})

    assert get_configured_sdd_storage() == expected


def test_record_precedence_under_auto(
    tmp_path: Path,
    config_patch,
    provider_patch,
) -> None:
    workspace = tmp_path / "repo_2"
    primary = tmp_path / "repo"
    workspace.mkdir()
    (primary / ".sase").mkdir(parents=True)
    (primary / ".sase" / "sdd-store.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "storage": "separate_repo",
                "provider": "github",
                "remote_url": "git@github.com:owner/repo-sdd.git",
                "discovery": "found",
            }
        ),
        encoding="utf-8",
    )
    config_patch({"sdd": {"storage": "auto", "version_controlled": False}})
    provider_patch("bare_git")

    store = resolve_sdd_store(workspace, 2)

    assert store.storage == SDD_STORAGE_SEPARATE_REPO
    assert store.sdd_dir == primary / ".sase" / "sdd"
    assert store.provider == "github"
    assert store.remote_url == "git@github.com:owner/repo-sdd.git"


def test_negative_record_does_not_activate_separate_repo(
    tmp_path: Path,
    config_patch,
    provider_patch,
) -> None:
    workspace = tmp_path / "repo_2"
    primary = tmp_path / "repo"
    workspace.mkdir()
    (primary / ".sase").mkdir(parents=True)
    (primary / ".sase" / "sdd-store.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "storage": "separate_repo",
                "provider": "github",
                "discovery": "not_found",
            }
        ),
        encoding="utf-8",
    )
    config_patch({"sdd": {"storage": "auto", "version_controlled": False}})
    provider_patch("github")

    store = resolve_sdd_store(workspace, 2)

    assert store.storage == SDD_STORAGE_LOCAL
    assert store.provider is None
    assert store.remote_url is None


def test_explicit_storage_wins_over_record(
    tmp_path: Path,
    config_patch,
    provider_patch,
) -> None:
    workspace = tmp_path / "repo_2"
    primary = tmp_path / "repo"
    workspace.mkdir()
    (primary / ".sase").mkdir(parents=True)
    (primary / ".sase" / "sdd-store.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "storage": "separate_repo",
                "provider": "github",
                "remote_url": "git@github.com:owner/repo-sdd.git",
                "discovery": "found",
            }
        ),
        encoding="utf-8",
    )
    config_patch({"sdd": {"storage": "local", "version_controlled": True}})
    provider_patch("bare_git")

    store = resolve_sdd_store(workspace, 2)

    assert store.storage == SDD_STORAGE_LOCAL
    assert store.sdd_dir == primary / ".sase" / "sdd"
    assert store.provider is None
    assert store.remote_url is None


@pytest.mark.parametrize(
    ("sdd_config", "legacy_in_tree"),
    [
        ({"storage": "in_tree", "version_controlled": False}, True),
        ({"storage": "local", "version_controlled": True}, False),
        ({"storage": "separate_repo", "version_controlled": False}, False),
    ],
)
def test_resolve_sdd_dir_matches_legacy_paths(
    tmp_path: Path,
    config_patch,
    provider_patch,
    sdd_config: dict[str, Any],
    legacy_in_tree: bool,
) -> None:
    workspace = tmp_path / "repo_2"
    (tmp_path / "repo").mkdir()
    workspace.mkdir()
    config_patch({"sdd": sdd_config})
    provider_patch(None)

    assert resolve_sdd_dir(workspace, 2) == get_sdd_dir(
        str(workspace),
        2,
        version_controlled=legacy_in_tree,
    )


def test_write_sdd_store_record_round_trips(
    tmp_path: Path,
) -> None:
    primary = tmp_path / "repo"

    written = _write_sdd_store_record(
        primary,
        {
            "schema_version": 1,
            "storage": "separate_repo",
            "provider": "fake",
            "host": "example.com",
            "repo": "owner/repo-sdd",
            "remote_url": "git@example.com:owner/repo-sdd.git",
            "discovery": "found",
        },
    )

    assert written.probed_at is not None
    reread = read_sdd_store_record(primary)
    assert reread == written
    raw = json.loads((primary / ".sase" / "sdd-store.json").read_text())
    assert raw["storage"] == "separate_repo"
    assert raw["repo"] == "owner/repo-sdd"
    assert raw["probed_at"]


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
            (Path(primary_workspace_dir) / ".sase" / "sdd").mkdir(parents=True)
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
    assert store.sdd_dir == primary / ".sase" / "sdd"
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


def test_ensure_workspace_sdd_link_managed_separate_repo(
    tmp_path: Path,
    config_patch,
    provider_patch,
) -> None:
    primary = tmp_path / "repo"
    workspace = tmp_path / "repo_2"
    store_dir = primary / ".sase" / "sdd"
    plan_path = store_dir / "tales" / "202607" / "feature.md"
    workspace.mkdir()
    plan_path.parent.mkdir(parents=True)
    plan_path.write_text("# Plan\n", encoding="utf-8")
    config_patch({"sdd": {"storage": "separate_repo", "version_controlled": False}})
    provider_patch(None)

    ensure_workspace_sdd_link(workspace, 2)

    workspace_sdd = workspace / ".sase" / "sdd"
    assert workspace_sdd.is_symlink()
    assert workspace_sdd.resolve() == store_dir.resolve()
    assert (workspace_sdd / "tales" / "202607" / "feature.md").read_text(
        encoding="utf-8"
    ) == "# Plan\n"


def test_ensure_workspace_sdd_link_in_tree_noop(
    tmp_path: Path,
    config_patch,
    provider_patch,
) -> None:
    workspace = tmp_path / "repo_2"
    (tmp_path / "repo").mkdir()
    workspace.mkdir()
    config_patch({"sdd": {"storage": "in_tree", "version_controlled": False}})
    provider_patch(None)

    ensure_workspace_sdd_link(workspace, 2)

    assert not (workspace / ".sase" / "sdd").exists()


def test_ensure_workspace_sdd_link_colocated_store_refreshes_without_symlink(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    config_patch,
    provider_patch,
) -> None:
    workspace = tmp_path / "repo"
    workspace_sdd = workspace / ".sase" / "sdd"
    workspace.mkdir()
    config_patch({"sdd": {"storage": "local", "version_controlled": False}})
    provider_patch(None)
    refreshed: list[Path] = []
    monkeypatch.setattr(
        "sase.sdd.store._refresh_materialized_store",
        lambda path: refreshed.append(path),
    )

    ensure_workspace_sdd_link(workspace, 1)

    assert refreshed == [workspace_sdd]
    assert not workspace_sdd.is_symlink()


def test_ensure_workspace_sdd_link_preserves_non_store_real_dir(
    tmp_path: Path,
    config_patch,
    provider_patch,
) -> None:
    """A real ``.sase/sdd`` that is not a git clone of the store is left alone."""
    primary = tmp_path / "repo"
    workspace = tmp_path / "repo_2"
    store_dir = primary / ".sase" / "sdd"
    workspace_sdd = workspace / ".sase" / "sdd"
    store_dir.mkdir(parents=True)
    workspace_sdd.mkdir(parents=True)
    (workspace_sdd / "keep.md").write_text("# Keep\n", encoding="utf-8")
    config_patch({"sdd": {"storage": "separate_repo", "version_controlled": False}})
    provider_patch(None)

    ensure_workspace_sdd_link(workspace, 2)

    assert workspace_sdd.is_dir()
    assert not workspace_sdd.is_symlink()
    assert (workspace_sdd / "keep.md").read_text(encoding="utf-8") == "# Keep\n"
    assert not workspace_sdd.with_name("sdd.stale-backup").exists()


def test_ensure_workspace_sdd_link_replaces_stale_clean_clone(
    tmp_path: Path,
    config_patch,
    provider_patch,
) -> None:
    """The agent-29 regression: a clean, stale store clone is replaced with a
    symlink to the primary store so a primary-only tale becomes reachable."""
    companion, primary_sdd, workspace_sdd = _build_separate_repo_clones(tmp_path)
    _write_sdd_store_record(
        tmp_path / "repo",
        {
            "storage": "separate_repo",
            "provider": "github",
            "remote_url": str(companion),
            "discovery": "found",
        },
    )
    config_patch({"sdd": {"storage": "separate_repo", "version_controlled": False}})
    provider_patch(None)

    ensure_workspace_sdd_link(tmp_path / "repo_2", 2)

    assert workspace_sdd.is_symlink()
    assert workspace_sdd.resolve() == primary_sdd.resolve()
    assert (workspace_sdd / "tales" / "202607" / "feature.md").read_text(
        encoding="utf-8"
    ) == "# Plan\n"
    backup = workspace_sdd.with_name("sdd.stale-backup")
    assert backup.is_dir()
    assert not backup.is_symlink()
    # The moved-aside clone is the stale content that never carried the tale.
    assert not (backup / "tales" / "202607" / "feature.md").exists()


def test_ensure_workspace_sdd_link_replace_is_idempotent(
    tmp_path: Path,
    config_patch,
    provider_patch,
) -> None:
    """After replacement, a second launch just repoints the symlink; the stale
    backup is not duplicated."""
    companion, primary_sdd, workspace_sdd = _build_separate_repo_clones(tmp_path)
    config_patch({"sdd": {"storage": "separate_repo", "version_controlled": False}})
    provider_patch(None)

    ensure_workspace_sdd_link(tmp_path / "repo_2", 2)
    ensure_workspace_sdd_link(tmp_path / "repo_2", 2)

    assert workspace_sdd.is_symlink()
    assert workspace_sdd.resolve() == primary_sdd.resolve()
    backups = list((tmp_path / "repo_2" / ".sase").glob("sdd.stale-backup*"))
    assert backups == [workspace_sdd.with_name("sdd.stale-backup")]


def test_ensure_workspace_sdd_link_store_clone_with_commits_ahead_is_preserved(
    tmp_path: Path,
    config_patch,
    provider_patch,
) -> None:
    """A store clone with an unpushed local commit is never discarded."""
    companion, primary_sdd, workspace_sdd = _build_separate_repo_clones(tmp_path)
    (workspace_sdd / "local_work.md").write_text("wip\n", encoding="utf-8")
    _commit_all(workspace_sdd, "Local work")
    config_patch({"sdd": {"storage": "separate_repo", "version_controlled": False}})
    provider_patch(None)

    ensure_workspace_sdd_link(tmp_path / "repo_2", 2)

    assert not workspace_sdd.is_symlink()
    assert workspace_sdd.is_dir()
    assert (workspace_sdd / "local_work.md").read_text(encoding="utf-8") == "wip\n"
    assert not workspace_sdd.with_name("sdd.stale-backup").exists()


def test_ensure_workspace_sdd_link_store_clone_with_dirty_tree_is_preserved(
    tmp_path: Path,
    config_patch,
    provider_patch,
) -> None:
    """A dirty store clone is preserved but best-effort fast-forwarded from the
    primary so the tale still becomes reachable without discarding local work."""
    companion, primary_sdd, workspace_sdd = _build_separate_repo_clones(tmp_path)
    (workspace_sdd / "local_notes.md").write_text("draft\n", encoding="utf-8")
    config_patch({"sdd": {"storage": "separate_repo", "version_controlled": False}})
    provider_patch(None)

    ensure_workspace_sdd_link(tmp_path / "repo_2", 2)

    assert not workspace_sdd.is_symlink()
    assert workspace_sdd.is_dir()
    assert (workspace_sdd / "local_notes.md").read_text(encoding="utf-8") == "draft\n"
    assert (workspace_sdd / "tales" / "202607" / "feature.md").read_text(
        encoding="utf-8"
    ) == "# Plan\n"
    assert not workspace_sdd.with_name("sdd.stale-backup").exists()


def test_ensure_workspace_sdd_link_non_matching_remote_clone_is_preserved(
    tmp_path: Path,
    config_patch,
    provider_patch,
) -> None:
    """A git clone whose origin does not match the store remote is unrelated
    content and must be preserved, not discarded."""
    companion, primary_sdd, workspace_sdd = _build_separate_repo_clones(tmp_path)
    shutil.rmtree(workspace_sdd)
    other = tmp_path / "other.git"
    _init_bare_repo(other)
    _clone(other, workspace_sdd)
    (workspace_sdd / "unrelated.md").write_text("unrelated\n", encoding="utf-8")
    _write_sdd_store_record(
        tmp_path / "repo",
        {
            "storage": "separate_repo",
            "provider": "github",
            "remote_url": str(companion),
            "discovery": "found",
        },
    )
    config_patch({"sdd": {"storage": "separate_repo", "version_controlled": False}})
    provider_patch(None)

    ensure_workspace_sdd_link(tmp_path / "repo_2", 2)

    assert not workspace_sdd.is_symlink()
    assert workspace_sdd.is_dir()
    assert (workspace_sdd / "unrelated.md").read_text(encoding="utf-8") == "unrelated\n"
    assert not workspace_sdd.with_name("sdd.stale-backup").exists()


def test_ensure_workspace_sdd_link_stale_clone_makes_relative_prompt_ref_resolve(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    config_patch,
    provider_patch,
) -> None:
    """End-to-end: with a stale real clone in place, the coder hand-off's
    relative ``@.sase/sdd/...`` reference resolves from the workspace CWD, so the
    ``process_file_references`` ``sys.exit(1)`` path cannot re-trigger."""
    from sase.file_references import process_file_references

    _companion, _primary_sdd, _workspace_sdd = _build_separate_repo_clones(tmp_path)
    config_patch({"sdd": {"storage": "separate_repo", "version_controlled": False}})
    provider_patch(None)

    ensure_workspace_sdd_link(tmp_path / "repo_2", 2)
    monkeypatch.chdir(tmp_path / "repo_2")

    prompt = "@.sase/sdd/tales/202607/feature.md\nImplement it now."
    assert process_file_references(prompt) == prompt


def test_ensure_workspace_sdd_link_repoints_stale_symlink_and_is_idempotent(
    tmp_path: Path,
    config_patch,
    provider_patch,
) -> None:
    primary = tmp_path / "repo"
    workspace = tmp_path / "repo_2"
    store_dir = primary / ".sase" / "sdd"
    stale_target = tmp_path / "old-sdd"
    workspace_sdd = workspace / ".sase" / "sdd"
    store_dir.mkdir(parents=True)
    stale_target.mkdir()
    workspace_sdd.parent.mkdir(parents=True)
    workspace_sdd.symlink_to(stale_target, target_is_directory=True)
    config_patch({"sdd": {"storage": "separate_repo", "version_controlled": False}})
    provider_patch(None)

    ensure_workspace_sdd_link(workspace, 2)
    ensure_workspace_sdd_link(workspace, 2)

    assert workspace_sdd.is_symlink()
    assert workspace_sdd.resolve() == store_dir.resolve()


def test_ensure_workspace_sdd_link_refresh_failure_still_links(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    config_patch,
    provider_patch,
) -> None:
    primary = tmp_path / "repo"
    workspace = tmp_path / "repo_2"
    store_dir = primary / ".sase" / "sdd"
    (store_dir / ".git").mkdir(parents=True)
    workspace.mkdir()
    config_patch({"sdd": {"storage": "separate_repo", "version_controlled": False}})
    provider_patch(None)
    monkeypatch.setattr(
        "sase.sdd.store.subprocess.run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0], 1, stdout="", stderr="pull failed"
        ),
    )

    ensure_workspace_sdd_link(workspace, 2)

    assert (workspace / ".sase" / "sdd").resolve() == store_dir.resolve()


def test_ensure_workspace_sdd_link_missing_store_is_best_effort(
    tmp_path: Path,
    config_patch,
    provider_patch,
) -> None:
    workspace = tmp_path / "repo_2"
    workspace.mkdir()
    config_patch({"sdd": {"storage": "separate_repo", "version_controlled": False}})
    provider_patch(None)

    ensure_workspace_sdd_link(workspace, 2)

    assert not (workspace / ".sase" / "sdd").exists()


def test_ensure_workspace_sdd_link_makes_relative_prompt_ref_resolve(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    config_patch,
    provider_patch,
) -> None:
    from sase.file_references import process_file_references

    primary = tmp_path / "repo"
    workspace = tmp_path / "repo_2"
    plan_path = primary / ".sase" / "sdd" / "tales" / "202607" / "approved_plan.md"
    workspace.mkdir()
    plan_path.parent.mkdir(parents=True)
    plan_path.write_text("# Approved\n", encoding="utf-8")
    config_patch({"sdd": {"storage": "separate_repo", "version_controlled": False}})
    provider_patch(None)

    ensure_workspace_sdd_link(workspace, 2)
    monkeypatch.chdir(workspace)

    prompt = "@.sase/sdd/tales/202607/approved_plan.md\nImplement it now."
    assert process_file_references(prompt) == prompt
