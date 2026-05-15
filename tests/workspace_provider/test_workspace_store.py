"""Tests for sase.workspace_provider.store (Phase 1 of sase-3p)."""

import os
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.workspace_provider.store import (
    PRIMARY_WORKSPACE_NUM,
    WORKSPACE_ROOT_ENV,
    WorkspacePath,
    WorkspaceStore,
    _default_state_root,
    _derive_project_key,
)
# ── adjacent parity ────────────────────────────────────────────────


class TestAdjacentParity:
    def test_primary_num_returns_primary_path(self) -> None:
        store = WorkspaceStore("/tmp/proj", config={"workspace": {"root": "adjacent"}})
        path = store.resolve(PRIMARY_WORKSPACE_NUM)
        assert path.checkout_dir == "/tmp/proj"
        assert path.materialization == "primary"

    def test_legacy_num_1_maps_to_primary(self) -> None:
        store = WorkspaceStore("/tmp/proj", config={"workspace": {"root": "adjacent"}})
        assert store.resolve(1).checkout_dir == "/tmp/proj"

    def test_secondary_paths_match_legacy(self) -> None:
        primary = "/tmp/proj"
        store = WorkspaceStore(primary, config={"workspace": {"root": "adjacent"}})
        for num in (2, 10, 199):
            assert store.resolve(num).checkout_dir == f"{primary}_{num}/"

    def test_secondary_paths_match_legacy_with_trailing_slash(self) -> None:
        primary = "/tmp/proj/"
        store = WorkspaceStore(primary, config={"workspace": {"root": "adjacent"}})
        assert store.resolve(2).checkout_dir == "/tmp/proj_2/"

    def test_root_dir_is_primary_parent(self) -> None:
        store = WorkspaceStore(
            "/home/u/projects/proj", config={"workspace": {"root": "adjacent"}}
        )
        assert store.root_dir == "/home/u/projects"
        assert store.root_policy == "adjacent"


# ── xdg-state ──────────────────────────────────────────────────────


class TestXdgStatePolicy:
    def test_returns_stable_paths_under_fake_state_root(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
        monkeypatch.delenv(WORKSPACE_ROOT_ENV, raising=False)
        config = {"workspace": {"root": "xdg-state", "project_key": "my-proj"}}
        store_a = WorkspaceStore("/home/u/work/proj", config=config)
        store_b = WorkspaceStore("/home/u/work/proj", config=config)

        path_a = store_a.resolve(10)
        path_b = store_b.resolve(10)
        assert path_a.checkout_dir == path_b.checkout_dir

        expected_root = tmp_path / "sase" / "workspaces" / "my-proj"
        assert path_a.root_dir == str(expected_root)
        assert path_a.checkout_dir.startswith(str(expected_root))
        assert path_a.checkout_dir.endswith("proj_10/")

    def test_primary_num_under_xdg_state_returns_primary(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
        monkeypatch.delenv(WORKSPACE_ROOT_ENV, raising=False)
        store = WorkspaceStore(
            "/home/u/work/proj",
            config={"workspace": {"root": "xdg-state", "project_key": "k"}},
        )
        assert store.resolve(PRIMARY_WORKSPACE_NUM).checkout_dir == "/home/u/work/proj"


# ── project key derivation ─────────────────────────────────────────


class TestProjectKey:
    def test_same_basename_different_paths_distinct_keys(self) -> None:
        with patch(
            "sase.workspace_provider.store._list_git_remote_urls", return_value=[]
        ):
            key_a = _derive_project_key("/home/u/work/proj")
            key_b = _derive_project_key("/home/u/personal/proj")
        assert key_a != key_b
        assert key_a.startswith("proj-")
        assert key_b.startswith("proj-")

    def test_explicit_project_key_wins(self) -> None:
        with patch(
            "sase.workspace_provider.store._list_git_remote_urls",
            return_value=["git@github.com:other/repo.git"],
        ):
            assert _derive_project_key("/tmp/p", explicit="my-key") == "my-key"

    def test_explicit_project_key_in_config_wins(self) -> None:
        store = WorkspaceStore(
            "/tmp/p",
            config={"workspace": {"root": "adjacent", "project_key": "explicit-key"}},
        )
        assert store.project_key == "explicit-key"

    def test_single_remote_uses_slugified_url(self) -> None:
        with patch(
            "sase.workspace_provider.store._list_git_remote_urls",
            return_value=["git@github.com:sase-org/sase.git"],
        ):
            assert _derive_project_key("/tmp/p") == "github.com_sase-org_sase"

    def test_https_remote_uses_slugified_url(self) -> None:
        with patch(
            "sase.workspace_provider.store._list_git_remote_urls",
            return_value=["https://github.com/sase-org/sase.git"],
        ):
            assert _derive_project_key("/tmp/p") == "github.com_sase-org_sase"

    def test_multiple_remotes_fall_back_to_path(self) -> None:
        with patch(
            "sase.workspace_provider.store._list_git_remote_urls",
            return_value=[
                "git@github.com:a/x.git",
                "git@gitlab.com:b/x.git",
            ],
        ):
            key = _derive_project_key("/tmp/x")
        assert key.startswith("x-")

    def test_unsupported_remote_url_falls_back_to_path(self) -> None:
        with patch(
            "sase.workspace_provider.store._list_git_remote_urls",
            return_value=["something-weird"],
        ):
            key = _derive_project_key("/tmp/x")
        assert key.startswith("x-")


# ── environment override ───────────────────────────────────────────


class TestEnvOverride:
    def test_sase_workspace_root_overrides_config(self, tmp_path: Path) -> None:
        env = {WORKSPACE_ROOT_ENV: str(tmp_path)}
        config = {"workspace": {"root": "adjacent", "project_key": "k"}}
        store = WorkspaceStore("/home/u/proj", config=config, env=env)
        assert store.root_policy == "absolute"
        assert store.root_dir == str(tmp_path / "k")
        assert store.resolve(10).checkout_dir == str(tmp_path / "k" / "proj_10") + "/"

    def test_env_override_with_xdg_state_config(self, tmp_path: Path) -> None:
        env = {WORKSPACE_ROOT_ENV: str(tmp_path / "override")}
        config = {"workspace": {"root": "xdg-state", "project_key": "k"}}
        store = WorkspaceStore("/home/u/proj", config=config, env=env)
        assert store.root_dir == str(tmp_path / "override" / "k")

    def test_empty_env_override_ignored(self) -> None:
        env = {WORKSPACE_ROOT_ENV: ""}
        store = WorkspaceStore(
            "/home/u/proj",
            config={"workspace": {"root": "adjacent"}},
            env=env,
        )
        assert store.root_policy == "adjacent"


# ── absolute root policy ───────────────────────────────────────────


class TestAbsoluteRootPolicy:
    def test_absolute_path_root(self, tmp_path: Path) -> None:
        store = WorkspaceStore(
            "/home/u/proj",
            config={
                "workspace": {
                    "root": str(tmp_path),
                    "project_key": "k",
                }
            },
            env={},
        )
        assert store.root_policy == "absolute"
        assert store.root_dir == str(tmp_path / "k")

    def test_unknown_policy_raises(self) -> None:
        with pytest.raises(ValueError, match="Unsupported workspace.root"):
            WorkspaceStore(
                "/tmp/p",
                config={"workspace": {"root": "weird"}},
                env={},
            )


# ── state root helper ──────────────────────────────────────────────


class TestDefaultStateRoot:
    def test_linux_uses_xdg_state_home(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr("sase.workspace_provider.store.sys.platform", "linux")
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
        assert _default_state_root() == str(tmp_path / "sase" / "workspaces")

    def test_linux_falls_back_to_local_state(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("sase.workspace_provider.store.sys.platform", "linux")
        monkeypatch.delenv("XDG_STATE_HOME", raising=False)
        expected = str(Path.home() / ".local" / "state" / "sase" / "workspaces")
        assert _default_state_root() == expected

    def test_macos_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("sase.workspace_provider.store.sys.platform", "darwin")
        expected = str(
            Path.home() / "Library" / "Application Support" / "sase" / "workspaces"
        )
        assert _default_state_root() == expected

    def test_windows_uses_localappdata(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr("sase.workspace_provider.store.sys.platform", "win32")
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
        assert _default_state_root() == str(tmp_path / "sase" / "workspaces")


# ── empty/default config ───────────────────────────────────────────


class TestDefaults:
    def test_no_config_defaults_to_adjacent(self) -> None:
        store = WorkspaceStore("/tmp/proj")
        assert store.root_policy == "adjacent"
        assert store.cleanup_ttl_days == 14

    def test_workspace_path_fields(self) -> None:
        store = WorkspaceStore(
            "/tmp/proj",
            config={"workspace": {"root": "adjacent", "project_key": "k"}},
        )
        path = store.resolve(10)
        assert isinstance(path, WorkspacePath)
        assert path.project_key == "k"
        assert path.workspace_num == 10
        assert path.display_label == "proj_10"
        assert path.materialization == "git-clone"

    def test_negative_workspace_num_rejected(self) -> None:
        store = WorkspaceStore("/tmp/p")
        with pytest.raises(ValueError, match=">= 0"):
            store.resolve(-1)

    def test_empty_primary_dir_rejected(self) -> None:
        with pytest.raises(ValueError, match="primary_workspace_dir"):
            WorkspaceStore("")


# ── git remote enumeration ─────────────────────────────────────────


class TestGitRemoteEnumeration:
    def test_derive_uses_real_remote(self, tmp_path: Path) -> None:
        repo = tmp_path / "proj"
        repo.mkdir()
        subprocess.run(
            ["git", "init", "-q", str(repo)],
            check=True,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        )
        subprocess.run(
            [
                "git",
                "remote",
                "add",
                "origin",
                "git@github.com:sase-org/sase_102.git",
            ],
            cwd=repo,
            check=True,
        )
        assert _derive_project_key(str(repo)) == "github.com_sase-org_sase_102"

    def test_non_git_path_falls_back(self, tmp_path: Path) -> None:
        target = tmp_path / "plain"
        target.mkdir()
        key = _derive_project_key(str(target))
        assert key.startswith("plain-")

    def test_missing_directory_falls_back(self) -> None:
        key = _derive_project_key("/nonexistent/path/that/does/not/exist")
        assert "-" in key
